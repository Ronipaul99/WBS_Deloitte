from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from secrets import randbelow
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.observability import record_document_deletion
from app.db.session import SessionLocal, ensure_tenant_transaction, set_local_tenant_context
from app.models.domain import (
    ACTIVE_DOCUMENT_PROCESSING_STATUSES,
    DeletionStage,
    DispatchStatus,
    Document,
    DocumentChunk,
    DocumentDeletionOutbox,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    IngestionStage,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
)
from app.services.auth import add_auth_event
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
    validate_document_storage_key,
)

DELETION_TASK_NAME = "wbs.cleanup_document_deletion"
DELETION_REQUESTED_CODE = "DOCUMENT_DELETION_REQUESTED"
DELETION_STORAGE_UNAVAILABLE_CODE = "DOCUMENT_DELETION_STORAGE_UNAVAILABLE"
DELETION_STATE_INVALID_CODE = "DOCUMENT_DELETION_STATE_INVALID"


class DeletionDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    RETRY = "RETRY"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class DeletionResult:
    disposition: DeletionDisposition
    attempt_count: int
    retry_after_seconds: int | None = None
    error_code: str | None = None
    job_id: UUID = field(repr=False, default=UUID(int=0))
    document_id: UUID = field(repr=False, default=UUID(int=0))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _retry_delay(attempt_count: int, settings: Settings) -> int:
    exponent = min(max(attempt_count - 1, 0), 10)
    base = min(
        settings.document_deletion_retry_base_seconds * (2**exponent),
        settings.document_deletion_retry_max_seconds,
    )
    return min(
        base + randbelow(settings.document_deletion_retry_base_seconds + 1),
        settings.document_deletion_retry_max_seconds,
    )


async def request_document_deletion(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: UUID,
) -> tuple[Job, DocumentDeletionOutbox | None]:
    now = datetime.now(UTC)
    await ensure_tenant_transaction(db, tenant_id)
    document = await db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == tenant_id)
        .with_for_update()
    )
    if document is None:
        raise LookupError("DOCUMENT_NOT_FOUND")
    if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value:
        job = None
        if document.deletion_job_id is not None:
            job = await db.scalar(
                select(Job).where(
                    Job.id == document.deletion_job_id,
                    Job.tenant_id == tenant_id,
                    Job.project_id == document.project_id,
                    Job.job_type == JobType.DOCUMENT_DELETION.value,
                )
            )
        if job is None:
            raise RuntimeError(DELETION_STATE_INVALID_CODE)
        return job, None

    active_runs = list(
        (
            await db.execute(
                select(DocumentProcessingRun)
                .where(
                    DocumentProcessingRun.tenant_id == tenant_id,
                    DocumentProcessingRun.project_id == document.project_id,
                    DocumentProcessingRun.document_id == document.id,
                    DocumentProcessingRun.status.in_(ACTIVE_DOCUMENT_PROCESSING_STATUSES),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for run in active_runs:
        run.status = DocumentProcessingStatus.CANCELLED.value
        run.current_stage = IngestionStage.FAILED.value
        run.failed_at = now
        run.last_heartbeat_at = now
        run.error_code = DELETION_REQUESTED_CODE
        run.error_message = "Document ingestion stopped because deletion was requested."
        ingestion_job = await db.scalar(
            select(Job)
            .where(
                Job.id == run.job_id,
                Job.tenant_id == tenant_id,
                Job.project_id == document.project_id,
                Job.job_type == JobType.DOCUMENT_INGESTION.value,
            )
            .with_for_update()
        )
        if ingestion_job is not None:
            ingestion_job.status = ProcessingStatus.CANCELLED.value
            ingestion_job.current_step = IngestionStage.FAILED.value
            ingestion_job.error_code = DELETION_REQUESTED_CODE
            ingestion_job.error_message = (
                "Document ingestion stopped because deletion was requested."
            )
        ingestion_outbox = await db.scalar(
            select(JobDispatchOutbox)
            .where(
                JobDispatchOutbox.tenant_id == tenant_id,
                JobDispatchOutbox.project_id == document.project_id,
                JobDispatchOutbox.document_id == document.id,
                JobDispatchOutbox.processing_run_id == run.id,
            )
            .with_for_update()
        )
        if ingestion_outbox is not None:
            ingestion_outbox.status = DispatchStatus.DEAD.value
            ingestion_outbox.lease_expires_at = None
            ingestion_outbox.last_error_code = DELETION_REQUESTED_CODE

    document.current_processing_run_id = None
    document.processing_status = DocumentProcessingStatus.CANCELLED.value
    document.processing_error_code = DELETION_REQUESTED_CODE
    document.lifecycle_status = DocumentLifecycleStatus.DELETING.value
    from app.services.document_content import mark_content_deleting

    document.deletion_requested_at = now
    document.vectors_hidden_at = now
    document.deletion_completed_at = None
    document.deletion_error_code = None
    await mark_content_deleting(db, document)
    await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.project_id == document.project_id,
            DocumentChunk.document_id == document.id,
        )
    )

    job = Job(
        tenant_id=tenant_id,
        project_id=document.project_id,
        created_by=requested_by,
        job_type=JobType.DOCUMENT_DELETION.value,
        status=ProcessingStatus.QUEUED.value,
        progress=25,
        current_step=DeletionStage.QUEUED.value,
        request_payload={"document_id": str(document.id)},
        result_payload={},
    )
    db.add(job)
    await db.flush()
    document.deletion_job_id = job.id
    outbox = DocumentDeletionOutbox(
        tenant_id=tenant_id,
        project_id=document.project_id,
        document_id=document.id,
        job_id=job.id,
        task_name=DELETION_TASK_NAME,
        status=DispatchStatus.PENDING.value,
        attempt_count=0,
        available_at=now,
    )
    db.add(outbox)
    add_auth_event(
        db,
        event_type="document_deletion_requested",
        success=True,
        user_id=requested_by,
        subject_hash=None,
        ip_hash=None,
        user_agent_hash=None,
        details={
            "tenant_id": str(tenant_id),
            "document_id": str(document.id),
            "job_id": str(job.id),
        },
    )
    await db.commit()
    await db.refresh(job)
    record_document_deletion(outcome="requested")
    return job, outbox


async def process_document_deletion(
    job_id: UUID,
    document_id: UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    storage: UploadObjectStorage | None = None,
    settings: Settings | None = None,
) -> DeletionResult:
    policy = settings or get_settings()
    now = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job is None or job.job_type != JobType.DOCUMENT_DELETION.value:
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    0,
                    error_code=DELETION_STATE_INVALID_CODE,
                    job_id=job_id,
                    document_id=document_id,
                )
            if job.project_id is None:
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    job.attempt_count,
                    error_code=DELETION_STATE_INVALID_CODE,
                    job_id=job_id,
                    document_id=document_id,
                )
            await set_local_tenant_context(session, job.tenant_id)
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == job.tenant_id,
                    Document.project_id == job.project_id,
                    Document.deletion_job_id == job.id,
                )
                .with_for_update()
            )
            outbox = await session.scalar(
                select(DocumentDeletionOutbox)
                .where(
                    DocumentDeletionOutbox.job_id == job.id,
                    DocumentDeletionOutbox.document_id == document_id,
                    DocumentDeletionOutbox.tenant_id == job.tenant_id,
                    DocumentDeletionOutbox.project_id == job.project_id,
                )
                .with_for_update()
            )
            if document is None or outbox is None:
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    job.attempt_count,
                    error_code=DELETION_STATE_INVALID_CODE,
                    job_id=job_id,
                    document_id=document_id,
                )
            if document.lifecycle_status == DocumentLifecycleStatus.DELETED.value:
                return DeletionResult(
                    DeletionDisposition.COMPLETED,
                    job.attempt_count,
                    job_id=job.id,
                    document_id=document.id,
                )
            if document.lifecycle_status != DocumentLifecycleStatus.DELETING.value:
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    job.attempt_count,
                    error_code=DELETION_STATE_INVALID_CODE,
                    job_id=job.id,
                    document_id=document.id,
                )
            if (
                outbox.lease_expires_at is not None
                and _as_utc(outbox.lease_expires_at) > now
                and job.status == ProcessingStatus.IN_PROGRESS.value
            ):
                return DeletionResult(
                    DeletionDisposition.DUPLICATE,
                    job.attempt_count,
                    job_id=job.id,
                    document_id=document.id,
                )
            if job.attempt_count >= policy.document_deletion_max_attempts:
                outbox.status = DispatchStatus.DEAD.value
                job.status = ProcessingStatus.FAILED.value
                job.current_step = DeletionStage.FAILED.value
                job.error_code = DELETION_STORAGE_UNAVAILABLE_CODE
                document.deletion_error_code = DELETION_STORAGE_UNAVAILABLE_CODE
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    job.attempt_count,
                    error_code=DELETION_STORAGE_UNAVAILABLE_CODE,
                    job_id=job.id,
                    document_id=document.id,
                )
            outbox.lease_expires_at = now + timedelta(
                seconds=policy.document_deletion_lease_seconds
            )
            job.attempt_count += 1
            job.status = ProcessingStatus.IN_PROGRESS.value
            job.current_step = DeletionStage.DELETING_OBJECTS.value
            job.progress = max(job.progress, 60)
            job.error_code = None
            job.error_message = None
            document.deletion_error_code = None
            tenant_id = job.tenant_id
            project_id = job.project_id
            storage_key = document.storage_key
            attempt_count = job.attempt_count

    try:
        trusted_key = validate_document_storage_key(
            storage_key,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except ValueError:
        async with session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, tenant_id)
                job = await session.scalar(
                    select(Job)
                    .where(Job.id == job_id, Job.tenant_id == tenant_id)
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document)
                    .where(Document.id == document_id, Document.tenant_id == tenant_id)
                    .with_for_update()
                )
                outbox = await session.scalar(
                    select(DocumentDeletionOutbox)
                    .where(
                        DocumentDeletionOutbox.job_id == job_id,
                        DocumentDeletionOutbox.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
                if job is not None and document is not None and outbox is not None:
                    outbox.status = DispatchStatus.DEAD.value
                    outbox.lease_expires_at = None
                    outbox.last_error_code = DELETION_STATE_INVALID_CODE
                    job.status = ProcessingStatus.FAILED.value
                    job.current_step = DeletionStage.FAILED.value
                    job.error_code = DELETION_STATE_INVALID_CODE
                    job.error_message = "The document deletion state is invalid."
                    document.deletion_error_code = DELETION_STATE_INVALID_CODE
        record_document_deletion(outcome="failed")
        return DeletionResult(
            DeletionDisposition.FAILED,
            attempt_count,
            error_code=DELETION_STATE_INVALID_CODE,
            job_id=job_id,
            document_id=document_id,
        )

    try:
        await (storage or get_upload_storage()).delete_object(trusted_key)
    except ObjectStorageUnavailableError:
        retry_after = _retry_delay(attempt_count, policy)
        exhausted = attempt_count >= policy.document_deletion_max_attempts
        async with session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, tenant_id)
                job = await session.scalar(
                    select(Job)
                    .where(Job.id == job_id, Job.tenant_id == tenant_id)
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document)
                    .where(Document.id == document_id, Document.tenant_id == tenant_id)
                    .with_for_update()
                )
                outbox = await session.scalar(
                    select(DocumentDeletionOutbox)
                    .where(
                        DocumentDeletionOutbox.job_id == job_id,
                        DocumentDeletionOutbox.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
                if job is not None and document is not None and outbox is not None:
                    outbox.lease_expires_at = None
                    outbox.last_error_code = DELETION_STORAGE_UNAVAILABLE_CODE
                    outbox.status = (
                        DispatchStatus.DEAD.value if exhausted else DispatchStatus.PENDING.value
                    )
                    if not exhausted:
                        outbox.available_at = datetime.now(UTC) + timedelta(seconds=retry_after)
                        outbox.published_at = None
                    job.status = (
                        ProcessingStatus.FAILED.value
                        if exhausted
                        else ProcessingStatus.QUEUED.value
                    )
                    job.current_step = (
                        DeletionStage.FAILED.value if exhausted else DeletionStage.RETRY_WAIT.value
                    )
                    job.error_code = DELETION_STORAGE_UNAVAILABLE_CODE
                    job.error_message = "Document cleanup is temporarily unavailable."
                    document.deletion_error_code = DELETION_STORAGE_UNAVAILABLE_CODE
        record_document_deletion(outcome="failed" if exhausted else "retrying")
        return DeletionResult(
            DeletionDisposition.FAILED if exhausted else DeletionDisposition.RETRY,
            attempt_count,
            None if exhausted else retry_after,
            DELETION_STORAGE_UNAVAILABLE_CODE,
            job_id,
            document_id,
        )

    completed_at = datetime.now(UTC)
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, tenant_id)
            job = await session.scalar(
                select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id).with_for_update()
            )
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                    Document.project_id == project_id,
                    Document.deletion_job_id == job_id,
                )
                .with_for_update()
            )
            outbox = await session.scalar(
                select(DocumentDeletionOutbox)
                .where(
                    DocumentDeletionOutbox.job_id == job_id,
                    DocumentDeletionOutbox.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if job is None or document is None or outbox is None:
                return DeletionResult(
                    DeletionDisposition.FAILED,
                    attempt_count,
                    error_code=DELETION_STATE_INVALID_CODE,
                    job_id=job_id,
                    document_id=document_id,
                )
            await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.project_id == project_id,
                    DocumentChunk.document_id == document_id,
                )
            )
            document.current_processing_run_id = None
            document.lifecycle_status = DocumentLifecycleStatus.DELETED.value
            from app.services.document_content import release_deleted_content

            document.deletion_completed_at = completed_at
            await release_deleted_content(session, document)
            document.deletion_error_code = None
            document.file_name = "deleted"
            document.content_type = "application/octet-stream"
            document.size_bytes = 0
            document.storage_key = f"deleted/{document.id}"
            document.content_sha256 = None
            job.status = ProcessingStatus.COMPLETED.value
            job.current_step = DeletionStage.COMPLETED.value
            job.progress = 100
            job.error_code = None
            job.error_message = None
            job.result_payload = {"document_id": str(document.id)}
            outbox.status = DispatchStatus.PUBLISHED.value
            outbox.lease_expires_at = None
            outbox.last_error_code = None
            add_auth_event(
                session,
                event_type="document_deletion_completed",
                success=True,
                user_id=job.created_by,
                subject_hash=None,
                ip_hash=None,
                user_agent_hash=None,
                details={
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "job_id": str(job_id),
                },
            )
    record_document_deletion(outcome="completed")
    return DeletionResult(
        DeletionDisposition.COMPLETED,
        attempt_count,
        job_id=job_id,
        document_id=document_id,
    )
