from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.observability import record_document_reconciliation, record_document_retention
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.domain import (
    DispatchStatus,
    Document,
    DocumentChunk,
    DocumentDeletionOutbox,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    DocumentSummary,
    ExportFile,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
    Tenant,
    WbsTemplate,
    WbsVersion,
)
from app.services.dispatcher import publish_deletion_dispatch
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.ingestion.workspace import cleanup_stale_workspaces
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
)


class MaintenanceSafetyError(RuntimeError):
    pass


class ReconciliationCategory(StrEnum):
    MISSING_OBJECT = "missing_object"
    ORPHAN_OBJECT = "orphan_object"
    MISSING_DISPATCH = "missing_dispatch"
    STALE_PROCESSING = "stale_processing"
    INVALID_COUNTS = "invalid_counts"
    INVALID_ACTIVE_RUN = "invalid_active_run"
    DELETING_VECTORS = "deleting_vectors"
    DELETING_OBJECT = "deleting_object"
    EXPIRED_RUN = "expired_run"
    STALE_WORKSPACE = "stale_workspace"


@dataclass(frozen=True, slots=True)
class LifecycleMaintenanceResult:
    scanned_count: int
    finding_counts: dict[str, int]
    repaired_count: int
    removed_count: int
    failed_count: int
    dry_run: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ok" if self.failed_count == 0 else "partial",
            "scanned": self.scanned_count,
            "findings": dict(sorted(self.finding_counts.items())),
            "repaired": self.repaired_count,
            "removed": self.removed_count,
            "failed": self.failed_count,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True, slots=True)
class DeletionDispatchRecoveryResult:
    recovered_count: int
    published_count: int
    failed_count: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "status": "ok" if self.failed_count == 0 else "partial",
            "recovered": self.recovered_count,
            "published": self.published_count,
            "failed": self.failed_count,
        }


def _increment(counts: dict[str, int], category: ReconciliationCategory) -> None:
    counts[category.value] = counts.get(category.value, 0) + 1
    record_document_reconciliation(category=category.value, outcome="reported")


def _require_approved(apply_changes: bool, approved: bool) -> None:
    if apply_changes and not approved:
        raise MaintenanceSafetyError("Destructive maintenance requires explicit approval.")


async def _tenant_ids(
    session_factory: async_sessionmaker[AsyncSession],
    requested_tenant_id: UUID | None,
    limit: int,
) -> tuple[UUID, ...]:
    if requested_tenant_id is not None:
        return (requested_tenant_id,)
    async with session_factory() as session:
        return tuple(
            (
                await session.execute(
                    select(Tenant.id)
                    .where(Tenant.is_active.is_(True))
                    .order_by(Tenant.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )


async def _reconcile_database_state(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tenant_id: UUID,
    *,
    apply_changes: bool,
) -> tuple[int, dict[str, int], int, tuple[tuple[UUID, str, str], ...], tuple[UUID, ...]]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=settings.document_deletion_stale_seconds)
    findings: dict[str, int] = {}
    repaired = scanned = 0
    objects: list[tuple[UUID, str, str]] = []
    publish_ids: list[UUID] = []
    async with session_factory() as session:
        async with session.begin():
            await set_local_tenant_context(session, tenant_id)
            documents = list(
                (
                    await session.execute(
                        select(Document)
                        .where(
                            Document.tenant_id == tenant_id,
                            Document.lifecycle_status != DocumentLifecycleStatus.DELETED.value,
                        )
                        .order_by(Document.updated_at, Document.id)
                        .limit(settings.document_lifecycle_batch_size)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for document in documents:
                scanned += 1
                objects.append((document.id, document.project_id, document.storage_key))
                active_run = None
                if document.current_processing_run_id is not None:
                    active_run = await session.scalar(
                        select(DocumentProcessingRun).where(
                            DocumentProcessingRun.id == document.current_processing_run_id,
                            DocumentProcessingRun.tenant_id == tenant_id,
                            DocumentProcessingRun.project_id == document.project_id,
                            DocumentProcessingRun.document_id == document.id,
                            DocumentProcessingRun.status
                            == DocumentProcessingStatus.COMPLETED.value,
                        )
                    )
                    if active_run is None:
                        _increment(findings, ReconciliationCategory.INVALID_ACTIVE_RUN)
                        if apply_changes:
                            document.current_processing_run_id = None
                            document.processing_status = DocumentProcessingStatus.FAILED.value
                            document.processing_error_code = "DOCUMENT_INGESTION_STATE_INCONSISTENT"
                            repaired += 1
                if document.lifecycle_status == DocumentLifecycleStatus.DELETING.value:
                    visible_chunks = int(
                        await session.scalar(
                            select(func.count())
                            .select_from(DocumentChunk)
                            .where(
                                DocumentChunk.tenant_id == tenant_id,
                                DocumentChunk.project_id == document.project_id,
                                DocumentChunk.document_id == document.id,
                            )
                        )
                        or 0
                    )
                    if visible_chunks or document.current_processing_run_id is not None:
                        _increment(findings, ReconciliationCategory.DELETING_VECTORS)
                        if apply_changes:
                            document.current_processing_run_id = None
                            await session.execute(
                                delete(DocumentChunk).where(
                                    DocumentChunk.tenant_id == tenant_id,
                                    DocumentChunk.project_id == document.project_id,
                                    DocumentChunk.document_id == document.id,
                                )
                            )
                            repaired += 1
                    outbox = await session.scalar(
                        select(DocumentDeletionOutbox)
                        .where(
                            DocumentDeletionOutbox.tenant_id == tenant_id,
                            DocumentDeletionOutbox.document_id == document.id,
                        )
                        .with_for_update()
                    )
                    if outbox is None:
                        _increment(findings, ReconciliationCategory.MISSING_DISPATCH)
                    elif outbox.status == DispatchStatus.DEAD.value:
                        _increment(findings, ReconciliationCategory.DELETING_OBJECT)
                    elif (
                        outbox.status == DispatchStatus.PENDING.value
                        or (
                            outbox.status == DispatchStatus.PUBLISHING.value
                            and (outbox.lease_expires_at is None or outbox.lease_expires_at <= now)
                        )
                        or (
                            outbox.status == DispatchStatus.PUBLISHED.value
                            and document.updated_at <= stale_before
                        )
                    ):
                        _increment(findings, ReconciliationCategory.DELETING_OBJECT)
                        if apply_changes:
                            outbox.status = DispatchStatus.PENDING.value
                            outbox.available_at = now
                            outbox.lease_expires_at = None
                            outbox.published_at = None
                            publish_ids.append(outbox.id)
                            repaired += 1

            completed_runs = list(
                (
                    await session.execute(
                        select(DocumentProcessingRun)
                        .where(
                            DocumentProcessingRun.tenant_id == tenant_id,
                            DocumentProcessingRun.status
                            == DocumentProcessingStatus.COMPLETED.value,
                        )
                        .order_by(DocumentProcessingRun.updated_at, DocumentProcessingRun.id)
                        .limit(settings.document_lifecycle_batch_size)
                    )
                )
                .scalars()
                .all()
            )
            scanned += len(completed_runs)
            for run in completed_runs:
                persisted_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(DocumentChunk)
                        .where(
                            DocumentChunk.tenant_id == tenant_id,
                            DocumentChunk.project_id == run.project_id,
                            DocumentChunk.document_id == run.document_id,
                            DocumentChunk.processing_run_id == run.id,
                        )
                    )
                    or 0
                )
                if persisted_count != run.chunk_count or persisted_count < 1:
                    _increment(findings, ReconciliationCategory.INVALID_COUNTS)

            queued_without_dispatch = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.tenant_id == tenant_id,
                        Job.job_type == JobType.DOCUMENT_INGESTION.value,
                        Job.status == ProcessingStatus.QUEUED.value,
                        ~exists().where(JobDispatchOutbox.job_id == Job.id),
                    )
                )
                or 0
            )
            for _ in range(min(queued_without_dispatch, settings.document_lifecycle_batch_size)):
                _increment(findings, ReconciliationCategory.MISSING_DISPATCH)
            stale_runs = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.tenant_id == tenant_id,
                        DocumentProcessingRun.status == DocumentProcessingStatus.IN_PROGRESS.value,
                        or_(
                            DocumentProcessingRun.last_heartbeat_at.is_(None),
                            DocumentProcessingRun.last_heartbeat_at <= stale_before,
                        ),
                    )
                )
                or 0
            )
            for _ in range(min(stale_runs, settings.document_lifecycle_batch_size)):
                _increment(findings, ReconciliationCategory.STALE_PROCESSING)
    return scanned, findings, repaired, tuple(objects), tuple(publish_ids)


async def reconcile_document_lifecycle(
    *,
    tenant_id: UUID | None,
    apply_changes: bool = False,
    approved: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    storage: UploadObjectStorage | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> LifecycleMaintenanceResult:
    _require_approved(apply_changes, approved)
    policy = settings or get_settings()
    object_storage = storage or get_upload_storage()
    current_time = now or datetime.now(UTC)
    tenant_ids = await _tenant_ids(
        session_factory,
        tenant_id,
        policy.document_lifecycle_batch_size,
    )
    total_scanned = repaired = removed = failed = 0
    totals: dict[str, int] = {}
    for scoped_tenant_id in tenant_ids:
        scanned, findings, db_repaired, objects, publish_ids = await _reconcile_database_state(
            session_factory,
            policy,
            scoped_tenant_id,
            apply_changes=apply_changes,
        )
        total_scanned += scanned
        repaired += db_repaired
        for category, count in findings.items():
            totals[category] = totals.get(category, 0) + count
        persisted_keys = {key for _, _, key in objects}
        async with session_factory() as session:
            persisted_keys.update(
                await session.scalars(
                    select(WbsTemplate.storage_key).where(WbsTemplate.tenant_id == scoped_tenant_id)
                )
            )
            persisted_keys.update(
                key
                for key in await session.scalars(
                    select(ExportFile.storage_key).where(
                        ExportFile.tenant_id == scoped_tenant_id,
                        ExportFile.storage_key.is_not(None),
                    )
                )
                if key
            )
        for _, _, storage_key in objects:
            try:
                await object_storage.stat_object(storage_key)
            except DocumentInputError as exc:
                if exc.code is DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING:
                    _increment(totals, ReconciliationCategory.MISSING_OBJECT)
                else:
                    failed += 1
            except Exception:
                failed += 1
        try:
            listed = await object_storage.list_objects(
                f"tenants/{scoped_tenant_id}",
                maximum_items=policy.document_lifecycle_batch_size,
            )
        except (ObjectStorageUnavailableError, DocumentInputError, ValueError):
            failed += 1
            listed = ()
        orphan_cutoff = None
        if policy.document_orphan_minimum_age_hours is not None:
            orphan_cutoff = current_time - timedelta(hours=policy.document_orphan_minimum_age_hours)
        for entry in listed:
            if entry.storage_key in persisted_keys:
                continue
            if orphan_cutoff is None or entry.updated_at > orphan_cutoff:
                continue
            _increment(totals, ReconciliationCategory.ORPHAN_OBJECT)
            if apply_changes and policy.document_orphan_cleanup_enabled:
                try:
                    await object_storage.delete_object(entry.storage_key)
                    removed += 1
                    record_document_reconciliation(
                        category=ReconciliationCategory.ORPHAN_OBJECT.value,
                        outcome="repaired",
                    )
                except ObjectStorageUnavailableError:
                    failed += 1
        if apply_changes:
            for outbox_id in publish_ids:
                outcome = await publish_deletion_dispatch(
                    scoped_tenant_id,
                    outbox_id,
                    session_factory=session_factory,
                    policy=policy,
                )
                if outcome.published:
                    repaired += 1
                elif outcome.terminal:
                    failed += 1
    return LifecycleMaintenanceResult(
        total_scanned,
        totals,
        repaired,
        removed,
        failed,
        not apply_changes,
    )


async def recover_document_deletion_dispatches(
    *,
    tenant_id: UUID | None = None,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    settings: Settings | None = None,
) -> DeletionDispatchRecoveryResult:
    policy = settings or get_settings()
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=policy.document_deletion_stale_seconds)
    tenant_ids = await _tenant_ids(
        session_factory,
        tenant_id,
        policy.document_lifecycle_batch_size,
    )
    recovered = published = failed = 0
    for scoped_tenant_id in tenant_ids:
        async with session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, scoped_tenant_id)
                records = list(
                    (
                        await session.execute(
                            select(DocumentDeletionOutbox)
                            .join(
                                Document,
                                (Document.id == DocumentDeletionOutbox.document_id)
                                & (Document.tenant_id == DocumentDeletionOutbox.tenant_id)
                                & (Document.project_id == DocumentDeletionOutbox.project_id),
                            )
                            .join(Job, Job.id == DocumentDeletionOutbox.job_id)
                            .where(
                                DocumentDeletionOutbox.tenant_id == scoped_tenant_id,
                                Document.lifecycle_status == DocumentLifecycleStatus.DELETING.value,
                                DocumentDeletionOutbox.status != DispatchStatus.DEAD.value,
                                or_(
                                    (DocumentDeletionOutbox.status == DispatchStatus.PENDING.value)
                                    & (DocumentDeletionOutbox.available_at <= now),
                                    (
                                        DocumentDeletionOutbox.status
                                        == DispatchStatus.PUBLISHING.value
                                    )
                                    & or_(
                                        DocumentDeletionOutbox.lease_expires_at.is_(None),
                                        DocumentDeletionOutbox.lease_expires_at <= now,
                                    ),
                                    (
                                        DocumentDeletionOutbox.status
                                        == DispatchStatus.PUBLISHED.value
                                    )
                                    & (Job.status == ProcessingStatus.QUEUED.value)
                                    & (Job.updated_at <= stale_before),
                                ),
                            )
                            .order_by(
                                DocumentDeletionOutbox.available_at,
                                DocumentDeletionOutbox.id,
                            )
                            .limit(policy.document_lifecycle_batch_size)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                publish_ids = []
                for record in records:
                    record.status = DispatchStatus.PENDING.value
                    record.available_at = now
                    record.lease_expires_at = None
                    record.published_at = None
                    publish_ids.append(record.id)
                    recovered += 1
        for outbox_id in publish_ids:
            result = await publish_deletion_dispatch(
                scoped_tenant_id,
                outbox_id,
                session_factory=session_factory,
                policy=policy,
            )
            if result.published:
                published += 1
            elif result.terminal:
                failed += 1
    return DeletionDispatchRecoveryResult(recovered, published, failed)


async def run_document_retention(
    *,
    tenant_id: UUID | None,
    apply_changes: bool = False,
    approved: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> LifecycleMaintenanceResult:
    _require_approved(apply_changes, approved)
    policy = settings or get_settings()
    if not policy.document_retention_enabled:
        raise MaintenanceSafetyError("Document retention policy is not enabled and approved.")
    required = (
        policy.document_retention_failed_run_days,
        policy.document_retention_cancelled_run_days,
        policy.document_retention_superseded_run_days,
        policy.document_retention_job_days,
        policy.document_retention_malware_event_days,
        policy.document_retention_tombstone_days,
        policy.document_retention_stale_workspace_hours,
    )
    if any(value is None for value in required):
        raise MaintenanceSafetyError("Document retention policy is incomplete.")
    current_time = now or datetime.now(UTC)
    tenant_ids = await _tenant_ids(
        session_factory,
        tenant_id,
        policy.document_lifecycle_batch_size,
    )
    findings: dict[str, int] = {}
    scanned = removed = 0
    for scoped_tenant_id in tenant_ids:
        async with session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, scoped_tenant_id)
                malware_cutoff = current_time - timedelta(
                    days=policy.document_retention_malware_event_days or 1
                )
                candidates = list(
                    (
                        await session.execute(
                            select(DocumentProcessingRun)
                            .join(
                                Document,
                                (Document.id == DocumentProcessingRun.document_id)
                                & (Document.tenant_id == DocumentProcessingRun.tenant_id)
                                & (Document.project_id == DocumentProcessingRun.project_id),
                            )
                            .where(
                                DocumentProcessingRun.tenant_id == scoped_tenant_id,
                                DocumentProcessingRun.id
                                != func.coalesce(Document.current_processing_run_id, UUID(int=0)),
                                or_(
                                    (
                                        DocumentProcessingRun.status
                                        == DocumentProcessingStatus.FAILED.value
                                    )
                                    & or_(
                                        DocumentProcessingRun.error_code.is_(None),
                                        DocumentProcessingRun.error_code
                                        != "DOCUMENT_REJECTED_MALWARE",
                                    )
                                    & (
                                        DocumentProcessingRun.updated_at
                                        <= current_time
                                        - timedelta(
                                            days=policy.document_retention_failed_run_days or 1
                                        )
                                    ),
                                    (
                                        DocumentProcessingRun.status
                                        == DocumentProcessingStatus.FAILED.value
                                    )
                                    & (
                                        DocumentProcessingRun.error_code
                                        == "DOCUMENT_REJECTED_MALWARE"
                                    )
                                    & (DocumentProcessingRun.updated_at <= malware_cutoff),
                                    (
                                        DocumentProcessingRun.status
                                        == DocumentProcessingStatus.CANCELLED.value
                                    )
                                    & (
                                        DocumentProcessingRun.updated_at
                                        <= current_time
                                        - timedelta(
                                            days=policy.document_retention_cancelled_run_days or 1
                                        )
                                    ),
                                    (
                                        DocumentProcessingRun.status
                                        == DocumentProcessingStatus.COMPLETED.value
                                    )
                                    & (
                                        DocumentProcessingRun.updated_at
                                        <= current_time
                                        - timedelta(
                                            days=policy.document_retention_superseded_run_days or 1
                                        )
                                    ),
                                ),
                            )
                            .order_by(
                                DocumentProcessingRun.updated_at,
                                DocumentProcessingRun.id,
                            )
                            .limit(policy.document_lifecycle_batch_size)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                scanned += len(candidates)
                for run in candidates:
                    category = (
                        "malware_event"
                        if run.error_code == "DOCUMENT_REJECTED_MALWARE"
                        else {
                            DocumentProcessingStatus.FAILED.value: "failed_run",
                            DocumentProcessingStatus.CANCELLED.value: "cancelled_run",
                            DocumentProcessingStatus.COMPLETED.value: "superseded_run",
                        }[run.status]
                    )
                    findings[category] = findings.get(category, 0) + 1
                    record_document_retention(category=category, outcome="candidate")
                    if apply_changes:
                        await session.delete(run)
                        removed += 1
                        record_document_retention(category=category, outcome="removed")

                job_cutoff = current_time - timedelta(days=policy.document_retention_job_days or 1)
                job_candidates = list(
                    (
                        await session.execute(
                            select(Job)
                            .where(
                                Job.tenant_id == scoped_tenant_id,
                                Job.status.in_(
                                    {
                                        ProcessingStatus.COMPLETED.value,
                                        ProcessingStatus.FAILED.value,
                                        ProcessingStatus.CANCELLED.value,
                                    }
                                ),
                                or_(
                                    (Job.error_code == "DOCUMENT_REJECTED_MALWARE")
                                    & (Job.updated_at <= malware_cutoff),
                                    or_(
                                        Job.error_code.is_(None),
                                        Job.error_code != "DOCUMENT_REJECTED_MALWARE",
                                    )
                                    & (Job.updated_at <= job_cutoff),
                                ),
                                ~exists().where(DocumentProcessingRun.job_id == Job.id),
                                ~exists().where(JobDispatchOutbox.job_id == Job.id),
                                ~exists().where(DocumentDeletionOutbox.job_id == Job.id),
                                ~exists().where(Document.deletion_job_id == Job.id),
                                ~exists().where(WbsVersion.generation_job_id == Job.id),
                            )
                            .order_by(Job.updated_at, Job.id)
                            .limit(policy.document_lifecycle_batch_size)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                scanned += len(job_candidates)
                for job in job_candidates:
                    category = (
                        "malware_event" if job.error_code == "DOCUMENT_REJECTED_MALWARE" else "job"
                    )
                    findings[category] = findings.get(category, 0) + 1
                    record_document_retention(category=category, outcome="candidate")
                    if apply_changes:
                        await session.delete(job)
                        removed += 1
                        record_document_retention(category=category, outcome="removed")

                tombstone_cutoff = current_time - timedelta(
                    days=policy.document_retention_tombstone_days or 1
                )
                tombstones = list(
                    (
                        await session.execute(
                            select(Document)
                            .where(
                                Document.tenant_id == scoped_tenant_id,
                                Document.lifecycle_status == DocumentLifecycleStatus.DELETED.value,
                                Document.deletion_completed_at <= tombstone_cutoff,
                                ~exists().where(DocumentProcessingRun.document_id == Document.id),
                            )
                            .order_by(Document.deletion_completed_at, Document.id)
                            .limit(policy.document_lifecycle_batch_size)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                scanned += len(tombstones)
                for document in tombstones:
                    findings["tombstone"] = findings.get("tombstone", 0) + 1
                    record_document_retention(category="tombstone", outcome="candidate")
                    if not apply_changes:
                        continue
                    deletion_job_id = document.deletion_job_id
                    await session.execute(
                        delete(DocumentSummary).where(
                            DocumentSummary.tenant_id == scoped_tenant_id,
                            DocumentSummary.document_id == document.id,
                        )
                    )
                    await session.execute(
                        delete(DocumentDeletionOutbox).where(
                            DocumentDeletionOutbox.tenant_id == scoped_tenant_id,
                            DocumentDeletionOutbox.document_id == document.id,
                        )
                    )
                    document.deletion_job_id = None
                    await session.flush()
                    await session.delete(document)
                    if deletion_job_id is not None:
                        deletion_job = await session.scalar(
                            select(Job).where(
                                Job.id == deletion_job_id,
                                Job.tenant_id == scoped_tenant_id,
                            )
                        )
                        if deletion_job is not None:
                            await session.delete(deletion_job)
                    removed += 1
                    record_document_retention(category="tombstone", outcome="removed")
    workspace_hours = policy.document_retention_stale_workspace_hours
    if workspace_hours is not None:
        try:
            workspace_result = cleanup_stale_workspaces(
                policy.document_processing_temp_root,
                cutoff=current_time - timedelta(hours=workspace_hours),
                maximum_items=policy.document_lifecycle_batch_size,
                apply_changes=apply_changes,
            )
            if workspace_result.candidates:
                findings["workspace"] = workspace_result.candidates
                scanned += workspace_result.candidates
                removed += workspace_result.removed
                for _ in range(workspace_result.candidates):
                    record_document_retention(category="workspace", outcome="candidate")
                for _ in range(workspace_result.removed):
                    record_document_retention(category="workspace", outcome="removed")
        except Exception:
            return LifecycleMaintenanceResult(
                scanned,
                findings,
                removed,
                removed,
                1,
                not apply_changes,
            )
    return LifecycleMaintenanceResult(
        scanned,
        findings,
        removed,
        removed,
        0,
        not apply_changes,
    )
