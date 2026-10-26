from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import randbelow
from typing import Protocol
from uuid import UUID

from celery import Celery
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.observability import record_document_deletion_dispatch, record_ingestion_dispatch
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.domain import DispatchStatus, DocumentDeletionOutbox, JobDispatchOutbox
from app.services.workflows import (
    process_document_summary,
    process_export,
    process_validation,
    process_wbs_generation,
)

INGESTION_TASK_NAME = "wbs.process_document_ingestion"
_SUMMARY_TASK_NAME = "wbs.generate_document_summary"
_GENERATION_TASK_NAME = "wbs.generate_wbs"
_VALIDATION_TASK_NAME = "wbs.validate_wbs"
_EXPORT_TASK_NAME = "wbs.export_wbs"

settings = get_settings()
dispatch_app = Celery("wbs-dispatcher", broker=settings.redis_url, backend=settings.redis_url)
dispatch_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "socket_connect_timeout": settings.document_dispatch_publish_timeout_seconds,
        "socket_timeout": settings.document_dispatch_publish_timeout_seconds,
    },
)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _dispatch(
    background_tasks: BackgroundTasks,
    local_handler: Callable[..., Awaitable[None]],
    task_name: str,
    *args: UUID,
) -> None:
    if settings.tasks_eager:
        background_tasks.add_task(local_handler, *args)
    else:
        dispatch_app.send_task(task_name, args=[str(value) for value in args])


def dispatch_summary(background_tasks: BackgroundTasks, job_id: UUID, document_id: UUID) -> None:
    _dispatch(
        background_tasks,
        process_document_summary,
        _SUMMARY_TASK_NAME,
        job_id,
        document_id,
    )


def dispatch_generation(background_tasks: BackgroundTasks, job_id: UUID) -> None:
    _dispatch(background_tasks, process_wbs_generation, _GENERATION_TASK_NAME, job_id)


def dispatch_validation(background_tasks: BackgroundTasks, validation_id: UUID) -> None:
    _dispatch(background_tasks, process_validation, _VALIDATION_TASK_NAME, validation_id)


def dispatch_export(background_tasks: BackgroundTasks, export_id: UUID) -> None:
    _dispatch(background_tasks, process_export, _EXPORT_TASK_NAME, export_id)


@dataclass(frozen=True, slots=True)
class DispatchEnvelope:
    outbox_id: UUID
    tenant_id: UUID
    job_id: UUID
    processing_run_id: UUID
    task_name: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class DispatchResult:
    published: bool
    terminal: bool


class IngestionTaskPublisher(Protocol):
    def publish(self, envelope: DispatchEnvelope) -> None: ...


class CeleryIngestionTaskPublisher:
    def publish(self, envelope: DispatchEnvelope) -> None:
        dispatch_app.send_task(
            envelope.task_name,
            args=[str(envelope.job_id), str(envelope.processing_run_id)],
            task_id=str(envelope.outbox_id),
            serializer="json",
        )


@dataclass(frozen=True, slots=True)
class DeletionDispatchEnvelope:
    outbox_id: UUID
    tenant_id: UUID
    job_id: UUID
    document_id: UUID
    task_name: str
    attempt_count: int


class DeletionTaskPublisher(Protocol):
    def publish(self, envelope: DeletionDispatchEnvelope) -> None: ...


class CeleryDeletionTaskPublisher:
    def publish(self, envelope: DeletionDispatchEnvelope) -> None:
        dispatch_app.send_task(
            envelope.task_name,
            args=[str(envelope.job_id), str(envelope.document_id)],
            task_id=str(envelope.outbox_id),
            serializer="json",
        )


def _dispatch_backoff(attempt_count: int, policy: Settings) -> int:
    exponent = min(max(attempt_count - 1, 0), 10)
    base = min(
        policy.document_ingestion_retry_base_seconds * (2**exponent),
        policy.document_ingestion_retry_max_seconds,
    )
    return min(
        base + randbelow(policy.document_ingestion_retry_base_seconds + 1),
        policy.document_ingestion_retry_max_seconds,
    )


def _deletion_dispatch_backoff(attempt_count: int, policy: Settings) -> int:
    exponent = min(max(attempt_count - 1, 0), 10)
    base = min(
        policy.document_deletion_retry_base_seconds * (2**exponent),
        policy.document_deletion_retry_max_seconds,
    )
    return min(
        base + randbelow(policy.document_deletion_retry_base_seconds + 1),
        policy.document_deletion_retry_max_seconds,
    )


async def _claim_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    policy: Settings,
    tenant_id: UUID,
    outbox_id: UUID,
) -> DispatchEnvelope | None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, tenant_id)
            record = await session.scalar(
                select(JobDispatchOutbox)
                .where(
                    JobDispatchOutbox.id == outbox_id,
                    JobDispatchOutbox.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if record is None or record.status in {
                DispatchStatus.PUBLISHED.value,
                DispatchStatus.DEAD.value,
            }:
                return None
            if _as_utc(record.available_at) > now:
                return None
            if (
                record.status == DispatchStatus.PUBLISHING.value
                and record.lease_expires_at is not None
                and _as_utc(record.lease_expires_at) > now
            ):
                return None
            if record.attempt_count >= policy.document_ingestion_max_attempts:
                record.status = DispatchStatus.DEAD.value
                record.lease_expires_at = None
                record.last_error_code = "DOCUMENT_DISPATCH_UNAVAILABLE"
                return None
            record.status = DispatchStatus.PUBLISHING.value
            record.attempt_count += 1
            record.lease_expires_at = now + timedelta(
                seconds=policy.document_dispatch_lease_seconds
            )
            record.last_error_code = None
            return DispatchEnvelope(
                outbox_id=record.id,
                tenant_id=record.tenant_id,
                job_id=record.job_id,
                processing_run_id=record.processing_run_id,
                task_name=record.task_name,
                attempt_count=record.attempt_count,
            )


async def _finish_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    policy: Settings,
    envelope: DispatchEnvelope,
    *,
    published: bool,
) -> DispatchResult:
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, envelope.tenant_id)
            record = await session.scalar(
                select(JobDispatchOutbox)
                .where(
                    JobDispatchOutbox.id == envelope.outbox_id,
                    JobDispatchOutbox.tenant_id == envelope.tenant_id,
                )
                .with_for_update()
            )
            if record is None:
                return DispatchResult(False, True)
            record.lease_expires_at = None
            if published:
                record.status = DispatchStatus.PUBLISHED.value
                record.published_at = now
                record.last_error_code = None
                return DispatchResult(True, True)
            record.last_error_code = "DOCUMENT_DISPATCH_UNAVAILABLE"
            terminal = record.attempt_count >= policy.document_ingestion_max_attempts
            record.status = DispatchStatus.DEAD.value if terminal else DispatchStatus.PENDING.value
            if not terminal:
                record.available_at = now + timedelta(
                    seconds=_dispatch_backoff(record.attempt_count, policy)
                )
            return DispatchResult(False, terminal)


async def publish_ingestion_dispatch(
    tenant_id: UUID,
    outbox_id: UUID,
    *,
    publisher: IngestionTaskPublisher | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    policy: Settings | None = None,
) -> DispatchResult:
    effective_policy = policy or get_settings()
    envelope = await _claim_dispatch(session_factory, effective_policy, tenant_id, outbox_id)
    if envelope is None:
        record_ingestion_dispatch(outcome="duplicate")
        return DispatchResult(False, True)
    effective_publisher = publisher or CeleryIngestionTaskPublisher()
    try:
        await asyncio.to_thread(effective_publisher.publish, envelope)
    except Exception:
        result = await _finish_dispatch(
            session_factory,
            effective_policy,
            envelope,
            published=False,
        )
        record_ingestion_dispatch(outcome="failed" if result.terminal else "pending")
        return result
    result = await _finish_dispatch(
        session_factory,
        effective_policy,
        envelope,
        published=True,
    )
    record_ingestion_dispatch(outcome="published")
    return result


async def _claim_deletion_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    policy: Settings,
    tenant_id: UUID,
    outbox_id: UUID,
) -> DeletionDispatchEnvelope | None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, tenant_id)
            record = await session.scalar(
                select(DocumentDeletionOutbox)
                .where(
                    DocumentDeletionOutbox.id == outbox_id,
                    DocumentDeletionOutbox.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if record is None or record.status in {
                DispatchStatus.PUBLISHED.value,
                DispatchStatus.DEAD.value,
            }:
                return None
            if _as_utc(record.available_at) > now:
                return None
            if (
                record.status == DispatchStatus.PUBLISHING.value
                and record.lease_expires_at is not None
                and _as_utc(record.lease_expires_at) > now
            ):
                return None
            if record.attempt_count >= policy.document_deletion_max_attempts:
                record.status = DispatchStatus.DEAD.value
                record.lease_expires_at = None
                record.last_error_code = "DOCUMENT_DELETION_DISPATCH_UNAVAILABLE"
                return None
            record.status = DispatchStatus.PUBLISHING.value
            record.attempt_count += 1
            record.lease_expires_at = now + timedelta(
                seconds=policy.document_deletion_lease_seconds
            )
            record.last_error_code = None
            return DeletionDispatchEnvelope(
                outbox_id=record.id,
                tenant_id=record.tenant_id,
                job_id=record.job_id,
                document_id=record.document_id,
                task_name=record.task_name,
                attempt_count=record.attempt_count,
            )


async def _finish_deletion_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    policy: Settings,
    envelope: DeletionDispatchEnvelope,
    *,
    published: bool,
) -> DispatchResult:
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, envelope.tenant_id)
            record = await session.scalar(
                select(DocumentDeletionOutbox)
                .where(
                    DocumentDeletionOutbox.id == envelope.outbox_id,
                    DocumentDeletionOutbox.tenant_id == envelope.tenant_id,
                )
                .with_for_update()
            )
            if record is None:
                return DispatchResult(False, True)
            record.lease_expires_at = None
            if published:
                record.status = DispatchStatus.PUBLISHED.value
                record.published_at = now
                record.last_error_code = None
                return DispatchResult(True, True)
            record.last_error_code = "DOCUMENT_DELETION_DISPATCH_UNAVAILABLE"
            terminal = record.attempt_count >= policy.document_deletion_max_attempts
            record.status = DispatchStatus.DEAD.value if terminal else DispatchStatus.PENDING.value
            if not terminal:
                record.available_at = now + timedelta(
                    seconds=_deletion_dispatch_backoff(record.attempt_count, policy)
                )
            return DispatchResult(False, terminal)


async def publish_deletion_dispatch(
    tenant_id: UUID,
    outbox_id: UUID,
    *,
    publisher: DeletionTaskPublisher | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    policy: Settings | None = None,
) -> DispatchResult:
    effective_policy = policy or get_settings()
    envelope = await _claim_deletion_dispatch(
        session_factory, effective_policy, tenant_id, outbox_id
    )
    if envelope is None:
        record_document_deletion_dispatch(outcome="duplicate")
        return DispatchResult(False, True)
    effective_publisher = publisher or CeleryDeletionTaskPublisher()
    try:
        await asyncio.to_thread(effective_publisher.publish, envelope)
    except Exception:
        result = await _finish_deletion_dispatch(
            session_factory,
            effective_policy,
            envelope,
            published=False,
        )
        record_document_deletion_dispatch(outcome="failed" if result.terminal else "pending")
        return result
    result = await _finish_deletion_dispatch(
        session_factory,
        effective_policy,
        envelope,
        published=True,
    )
    record_document_deletion_dispatch(outcome="published")
    return result
