from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.observability import (
    record_ingestion_reconciliation,
    record_ingestion_reconciliation_backlog,
)
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.domain import (
    DispatchStatus,
    Document,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    IngestionStage,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
    Tenant,
)
from app.services.dispatcher import INGESTION_TASK_NAME, publish_ingestion_dispatch


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    repaired_count: int
    republished_count: int
    failed_count: int


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _complete_job(job: Job, run: DocumentProcessingRun) -> None:
    run.current_stage = IngestionStage.COMPLETED.value
    run.last_heartbeat_at = datetime.now(UTC)
    job.status = ProcessingStatus.COMPLETED.value
    job.progress = 100
    job.current_step = IngestionStage.COMPLETED.value
    job.error_code = None
    job.error_message = None
    job.result_payload = {
        "document_id": str(run.document_id),
        "processing_run_id": str(run.id),
        "chunk_count": run.chunk_count,
    }


def _fail_job(
    job: Job,
    run: DocumentProcessingRun | None,
    *,
    code: str = "DOCUMENT_INGESTION_STATE_INCONSISTENT",
    message: str = "The document ingestion state requires reconciliation.",
) -> None:
    job.status = ProcessingStatus.FAILED.value
    job.current_step = IngestionStage.FAILED.value
    job.error_code = code
    job.error_message = message
    if run is not None and run.status != DocumentProcessingStatus.COMPLETED.value:
        run.status = DocumentProcessingStatus.FAILED.value
        run.current_stage = IngestionStage.FAILED.value
        run.error_code = code
        run.error_message = message
        run.failed_at = datetime.now(UTC)


async def _reconcile_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tenant_id: UUID,
    remaining: int,
) -> tuple[list[UUID], int, int]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=settings.document_reconciliation_stale_seconds)
    publish_ids: list[UUID] = []
    repaired = failed = 0
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, tenant_id)
            missing_run_jobs = list(
                (
                    await session.execute(
                        select(Job)
                        .where(
                            Job.tenant_id == tenant_id,
                            Job.job_type == JobType.DOCUMENT_INGESTION.value,
                            Job.status.in_(
                                (ProcessingStatus.QUEUED.value, ProcessingStatus.IN_PROGRESS.value)
                            ),
                            ~exists().where(DocumentProcessingRun.job_id == Job.id),
                        )
                        .order_by(Job.updated_at, Job.id)
                        .limit(remaining)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for job in missing_run_jobs:
                _fail_job(job, None)
                failed += 1
            run_limit = max(remaining - failed, 0)
            if run_limit == 0:
                return publish_ids, repaired, failed
            runs = list(
                (
                    await session.execute(
                        select(DocumentProcessingRun)
                        .where(DocumentProcessingRun.tenant_id == tenant_id)
                        .order_by(DocumentProcessingRun.updated_at, DocumentProcessingRun.id)
                        .limit(run_limit)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for run in runs:
                job = await session.scalar(
                    select(Job)
                    .where(
                        Job.id == run.job_id,
                        Job.tenant_id == tenant_id,
                        Job.project_id == run.project_id,
                        Job.job_type == JobType.DOCUMENT_INGESTION.value,
                    )
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document)
                    .where(
                        Document.id == run.document_id,
                        Document.tenant_id == tenant_id,
                        Document.project_id == run.project_id,
                    )
                    .with_for_update()
                )
                if job is None or document is None:
                    continue
                if run.status == DocumentProcessingStatus.COMPLETED.value:
                    if document.current_processing_run_id == run.id:
                        if job.status != ProcessingStatus.COMPLETED.value:
                            _complete_job(job, run)
                            repaired += 1
                    elif job.status in {
                        ProcessingStatus.QUEUED.value,
                        ProcessingStatus.IN_PROGRESS.value,
                    }:
                        _fail_job(job, None)
                        failed += 1
                    continue
                if job.status == ProcessingStatus.COMPLETED.value:
                    _fail_job(job, run)
                    failed += 1
                    continue
                is_stale = run.status == DocumentProcessingStatus.IN_PROGRESS.value and (
                    run.last_heartbeat_at is None or _as_utc(run.last_heartbeat_at) < stale_before
                )
                if is_stale:
                    if run.attempt_count >= settings.document_ingestion_max_attempts:
                        _fail_job(
                            job,
                            run,
                            code="DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED",
                            message="Document ingestion exhausted its retry attempts.",
                        )
                        failed += 1
                        continue
                    run.status = DocumentProcessingStatus.QUEUED.value
                    run.current_stage = IngestionStage.RETRY_WAIT.value
                    job.status = ProcessingStatus.QUEUED.value
                    job.current_step = IngestionStage.RETRY_WAIT.value
                    repaired += 1
                if run.status != DocumentProcessingStatus.QUEUED.value:
                    continue
                outbox = await session.scalar(
                    select(JobDispatchOutbox)
                    .where(
                        JobDispatchOutbox.tenant_id == tenant_id,
                        JobDispatchOutbox.job_id == job.id,
                        JobDispatchOutbox.processing_run_id == run.id,
                        JobDispatchOutbox.task_name == INGESTION_TASK_NAME,
                    )
                    .with_for_update()
                )
                if outbox is None:
                    outbox = JobDispatchOutbox(
                        tenant_id=tenant_id,
                        project_id=run.project_id,
                        document_id=run.document_id,
                        job_id=job.id,
                        processing_run_id=run.id,
                        task_name=INGESTION_TASK_NAME,
                        status=DispatchStatus.PENDING.value,
                        attempt_count=0,
                        available_at=now,
                    )
                    session.add(outbox)
                    await session.flush()
                    publish_ids.append(outbox.id)
                    repaired += 1
                elif is_stale:
                    outbox.status = DispatchStatus.PENDING.value
                    outbox.available_at = now
                    outbox.lease_expires_at = None
                    if outbox.attempt_count < settings.document_ingestion_max_attempts:
                        publish_ids.append(outbox.id)
                elif outbox.status == DispatchStatus.PENDING.value:
                    if outbox.attempt_count < settings.document_ingestion_max_attempts:
                        publish_ids.append(outbox.id)
                elif outbox.status == DispatchStatus.PUBLISHING.value and (
                    outbox.lease_expires_at is None or _as_utc(outbox.lease_expires_at) <= now
                ):
                    outbox.status = DispatchStatus.PENDING.value
                    outbox.available_at = now
                    outbox.lease_expires_at = None
                    if outbox.attempt_count < settings.document_ingestion_max_attempts:
                        publish_ids.append(outbox.id)
                elif outbox.status == DispatchStatus.DEAD.value:
                    job.status = ProcessingStatus.FAILED.value
                    job.current_step = IngestionStage.FAILED.value
                    job.error_code = "DOCUMENT_DISPATCH_UNAVAILABLE"
                    job.error_message = "Document ingestion dispatch is temporarily unavailable."
                    run.status = DocumentProcessingStatus.FAILED.value
                    run.current_stage = IngestionStage.FAILED.value
                    run.error_code = job.error_code
                    run.error_message = job.error_message
                    run.failed_at = now
                    failed += 1
    return publish_ids, repaired, failed


async def reconcile_ingestion_dispatches(
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    settings: Settings | None = None,
) -> ReconciliationResult:
    policy = settings or get_settings()
    if not policy.document_ingestion_enabled or policy.tasks_eager:
        record_ingestion_reconciliation_backlog(count=0)
        return ReconciliationResult(0, 0, 0)
    async with session_factory() as session:
        tenant_ids = tuple(
            (
                await session.execute(
                    select(Tenant.id)
                    .where(Tenant.is_active.is_(True))
                    .order_by(Tenant.id)
                    .limit(policy.document_reconciliation_batch_size)
                )
            )
            .scalars()
            .all()
        )
    repaired = republished = failed = 0
    backlog = 0
    remaining = policy.document_reconciliation_batch_size
    for tenant_id in tenant_ids:
        if remaining <= 0:
            break
        outbox_ids, tenant_repaired, tenant_failed = await _reconcile_tenant(
            session_factory,
            policy,
            tenant_id,
            remaining,
        )
        repaired += tenant_repaired
        failed += tenant_failed
        backlog += len(outbox_ids)
        remaining -= tenant_repaired + tenant_failed
        for outbox_id in outbox_ids:
            outcome = await publish_ingestion_dispatch(
                tenant_id,
                outbox_id,
                session_factory=session_factory,
                policy=policy,
            )
            if outcome.published:
                republished += 1
    record_ingestion_reconciliation_backlog(count=backlog)
    record_ingestion_reconciliation(
        outcome="failed" if failed else ("repaired" if repaired or republished else "success")
    )
    return ReconciliationResult(repaired, republished, failed)
