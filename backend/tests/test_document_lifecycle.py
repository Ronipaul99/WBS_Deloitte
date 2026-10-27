from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models.auth import AuthEvent
from app.models.domain import (
    DispatchStatus,
    Document,
    DocumentChunk,
    DocumentDeletionOutbox,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
    Project,
    Tenant,
    User,
)
from app.services.dispatcher import (
    DeletionDispatchEnvelope,
    DispatchResult,
    publish_deletion_dispatch,
)
from app.services.document_lifecycle import (
    DELETION_STATE_INVALID_CODE,
    DELETION_STORAGE_UNAVAILABLE_CODE,
    DeletionDisposition,
    process_document_deletion,
    request_document_deletion,
)
from app.services.document_maintenance import (
    MaintenanceSafetyError,
    reconcile_document_lifecycle,
    run_document_retention,
)
from app.services.storage import (
    ObjectStorageUnavailableError,
    StoredObjectMetadata,
    validate_document_storage_key,
)


class RecordingStorage:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.deleted: list[str] = []

    async def delete_object(self, storage_key: str) -> None:
        if self.unavailable:
            raise ObjectStorageUnavailableError("private provider diagnostic")
        self.deleted.append(storage_key)

    async def stat_object(self, _storage_key: str) -> StoredObjectMetadata:
        return StoredObjectMetadata(64, "application/pdf", None, None)

    async def list_objects(self, _prefix: str, *, maximum_items: int):
        assert maximum_items > 0
        return ()


class RecordingDeletionPublisher:
    def __init__(self) -> None:
        self.envelopes: list[DeletionDispatchEnvelope] = []

    def publish(self, envelope: DeletionDispatchEnvelope) -> None:
        self.envelopes.append(envelope)


@pytest_asyncio.fixture
async def lifecycle_context(tmp_path):
    database = tmp_path / "document-lifecycle.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid4()
    project_id = uuid4()
    document_id = uuid4()
    ingestion_job_id = uuid4()
    run_id = uuid4()
    user_id = uuid4()
    object_id = uuid4()
    storage_key = f"tenants/{tenant_id}/projects/{project_id}/documents/{object_id}.pdf"
    async with sessions.begin() as session:
        session.add_all(
            [
                Tenant(id=tenant_id, name="Synthetic tenant", slug=f"tenant-{tenant_id.hex}"),
                User(
                    id=user_id,
                    external_subject=f"user-{user_id.hex}",
                    email=f"{user_id.hex}@example.test",
                    display_name="Synthetic user",
                ),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                created_by=user_id,
                name="Synthetic project",
            )
        )
        await session.flush()
        session.add_all(
            [
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    uploaded_by=user_id,
                    kind="PROJECT",
                    file_name="synthetic.pdf",
                    content_type="application/pdf",
                    size_bytes=64,
                    storage_key=storage_key,
                    processing_status=DocumentProcessingStatus.QUEUED.value,
                ),
                Job(
                    id=ingestion_job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    created_by=user_id,
                    job_type=JobType.DOCUMENT_INGESTION.value,
                    status=ProcessingStatus.QUEUED.value,
                    progress=0,
                    request_payload={},
                    result_payload={},
                ),
            ]
        )
        await session.flush()
        run = DocumentProcessingRun(
            id=run_id,
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            job_id=ingestion_job_id,
            status=DocumentProcessingStatus.QUEUED.value,
            current_stage="QUEUED",
        )
        session.add(run)
        await session.flush()
        document = await session.get(Document, document_id)
        assert document is not None
        document.current_processing_run_id = run_id
        session.add_all(
            [
                DocumentChunk(
                    processing_run_id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    ordinal=0,
                    token_count=2,
                    content="Synthetic content",
                    content_sha256="a" * 64,
                    block_type="paragraph",
                    heading_path=[],
                    source_metadata={},
                    embedding=[0.0] * 384,
                ),
                JobDispatchOutbox(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    job_id=ingestion_job_id,
                    processing_run_id=run_id,
                    task_name="wbs.process_document_ingestion",
                    status=DispatchStatus.PENDING.value,
                    available_at=datetime.now(UTC),
                ),
            ]
        )
    try:
        yield (
            sessions,
            tenant_id,
            project_id,
            document_id,
            ingestion_job_id,
            run_id,
            user_id,
            storage_key,
        )
    finally:
        await engine.dispose()


async def _request(context):
    sessions, tenant_id, _, document_id, _, _, user_id, _ = context
    async with sessions() as session:
        return await request_document_deletion(
            session,
            tenant_id=tenant_id,
            document_id=document_id,
            requested_by=user_id,
        )


@pytest.mark.asyncio
async def test_deletion_request_hides_vectors_and_is_idempotent(lifecycle_context) -> None:
    sessions, _, _, document_id, ingestion_job_id, run_id, _, _ = lifecycle_context
    job, outbox = await _request(lifecycle_context)

    assert outbox is not None
    assert job.job_type == JobType.DOCUMENT_DELETION.value
    async with sessions() as session:
        document = await session.get(Document, document_id)
        run = await session.get(DocumentProcessingRun, run_id)
        ingestion_job = await session.get(Job, ingestion_job_id)
        ingestion_outbox = await session.scalar(
            select(JobDispatchOutbox).where(JobDispatchOutbox.processing_run_id == run_id)
        )
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        assert document is not None
        assert document.lifecycle_status == DocumentLifecycleStatus.DELETING.value
        assert document.current_processing_run_id is None
        assert document.vectors_hidden_at is not None
        assert run is not None and run.status == DocumentProcessingStatus.CANCELLED.value
        assert (
            ingestion_job is not None and ingestion_job.status == ProcessingStatus.CANCELLED.value
        )
        assert ingestion_outbox is not None
        assert ingestion_outbox.status == DispatchStatus.DEAD.value
        assert chunk_count == 0

    duplicate_job, duplicate_outbox = await _request(lifecycle_context)
    assert duplicate_job.id == job.id
    assert duplicate_outbox is None


@pytest.mark.asyncio
async def test_cleanup_completes_tombstone_and_duplicate_delivery_is_safe(
    lifecycle_context,
) -> None:
    sessions, _, _, document_id, _, _, _, storage_key = lifecycle_context
    job, _ = await _request(lifecycle_context)
    storage = RecordingStorage()

    result = await process_document_deletion(
        job.id,
        document_id,
        session_factory=sessions,
        storage=storage,
        settings=Settings(_env_file=None),
    )
    duplicate = await process_document_deletion(
        job.id,
        document_id,
        session_factory=sessions,
        storage=storage,
        settings=Settings(_env_file=None),
    )

    assert result.disposition == DeletionDisposition.COMPLETED
    assert duplicate.disposition == DeletionDisposition.COMPLETED
    assert storage.deleted == [storage_key]
    async with sessions() as session:
        document = await session.get(Document, document_id)
        deletion_job = await session.get(Job, job.id)
        assert document is not None
        assert document.lifecycle_status == DocumentLifecycleStatus.DELETED.value
        assert document.deletion_completed_at is not None
        assert document.file_name == "deleted"
        assert document.size_bytes == 0
        assert deletion_job is not None
        assert deletion_job.status == ProcessingStatus.COMPLETED.value
        assert deletion_job.progress == 100
        audit_events = list(
            (
                await session.scalars(
                    select(AuthEvent).where(
                        AuthEvent.event_type.in_(
                            {
                                "document_deletion_requested",
                                "document_deletion_completed",
                            }
                        )
                    )
                )
            ).all()
        )
        assert len(audit_events) == 2
        assert all(
            set(event.details) == {"tenant_id", "document_id", "job_id"} for event in audit_events
        )
        assert all(
            "synthetic.pdf" not in str(event.details) and storage_key not in str(event.details)
            for event in audit_events
        )


@pytest.mark.asyncio
async def test_deletion_outbox_publishes_only_opaque_identifiers(lifecycle_context) -> None:
    sessions, tenant_id, _, document_id, _, _, _, _ = lifecycle_context
    job, outbox = await _request(lifecycle_context)
    assert outbox is not None
    publisher = RecordingDeletionPublisher()

    result = await publish_deletion_dispatch(
        tenant_id,
        outbox.id,
        publisher=publisher,
        session_factory=sessions,
        policy=Settings(_env_file=None),
    )
    duplicate = await publish_deletion_dispatch(
        tenant_id,
        outbox.id,
        publisher=publisher,
        session_factory=sessions,
        policy=Settings(_env_file=None),
    )

    assert result == DispatchResult(True, True)
    assert duplicate == DispatchResult(False, True)
    assert len(publisher.envelopes) == 1
    envelope = publisher.envelopes[0]
    assert envelope.job_id == job.id
    assert envelope.document_id == document_id
    assert not hasattr(envelope, "storage_key")
    assert not hasattr(envelope, "file_name")


@pytest.mark.asyncio
async def test_storage_failure_retries_without_restoring_visibility(lifecycle_context) -> None:
    sessions, _, _, document_id, _, _, _, _ = lifecycle_context
    job, _ = await _request(lifecycle_context)
    result = await process_document_deletion(
        job.id,
        document_id,
        session_factory=sessions,
        storage=RecordingStorage(unavailable=True),
        settings=Settings(_env_file=None),
    )

    assert result.disposition == DeletionDisposition.RETRY
    assert result.error_code == DELETION_STORAGE_UNAVAILABLE_CODE
    async with sessions() as session:
        document = await session.get(Document, document_id)
        deletion_job = await session.get(Job, job.id)
        assert document is not None
        assert document.lifecycle_status == DocumentLifecycleStatus.DELETING.value
        assert document.vectors_hidden_at is not None
        assert deletion_job is not None
        assert deletion_job.status == ProcessingStatus.QUEUED.value
        assert deletion_job.error_message == "Document cleanup is temporarily unavailable."


@pytest.mark.asyncio
async def test_invalid_persisted_key_fails_permanently(lifecycle_context) -> None:
    sessions, _, _, document_id, _, _, _, _ = lifecycle_context
    job, _ = await _request(lifecycle_context)
    async with sessions.begin() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        document.storage_key = "../outside.pdf"

    result = await process_document_deletion(
        job.id,
        document_id,
        session_factory=sessions,
        storage=RecordingStorage(),
        settings=Settings(_env_file=None),
    )

    assert result.disposition == DeletionDisposition.FAILED
    assert result.error_code == DELETION_STATE_INVALID_CODE
    async with sessions() as session:
        outbox = await session.scalar(
            select(DocumentDeletionOutbox).where(DocumentDeletionOutbox.job_id == job.id)
        )
        assert outbox is not None and outbox.status == DispatchStatus.DEAD.value


def test_generated_storage_key_validation_is_scope_bound() -> None:
    tenant_id = uuid4()
    project_id = uuid4()
    valid = f"tenants/{tenant_id}/projects/{project_id}/documents/{uuid4()}.csv"
    assert (
        validate_document_storage_key(
            valid,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        == valid
    )
    with pytest.raises(ValueError):
        validate_document_storage_key(
            "../outside.csv",
            tenant_id=tenant_id,
            project_id=project_id,
        )
    with pytest.raises(ValueError):
        validate_document_storage_key(
            f"tenants/{UUID(int=0)}/projects/{project_id}/documents/{uuid4()}.csv",
            tenant_id=tenant_id,
            project_id=project_id,
        )


@pytest.mark.asyncio
async def test_retention_is_disabled_without_approved_policy(lifecycle_context) -> None:
    sessions, tenant_id, *_ = lifecycle_context
    with pytest.raises(MaintenanceSafetyError, match="not enabled and approved"):
        await run_document_retention(
            tenant_id=tenant_id,
            session_factory=sessions,
            settings=Settings(_env_file=None, document_retention_enabled=False),
        )


@pytest.mark.asyncio
async def test_retention_never_removes_current_run_and_is_idempotent(
    lifecycle_context,
) -> None:
    sessions, tenant_id, _, document_id, _, run_id, _, _ = lifecycle_context
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        assert run is not None
        run.status = DocumentProcessingStatus.CANCELLED.value
        run.updated_at = now - timedelta(days=10)
    policy = Settings(_env_file=None).model_copy(
        update={
            "document_retention_enabled": True,
            "document_retention_failed_run_days": 1,
            "document_retention_cancelled_run_days": 1,
            "document_retention_superseded_run_days": 1,
            "document_retention_job_days": 1,
            "document_retention_malware_event_days": 1,
            "document_retention_tombstone_days": 1,
            "document_retention_stale_workspace_hours": 1,
            "document_lifecycle_batch_size": 20,
        }
    )

    protected = await run_document_retention(
        tenant_id=tenant_id,
        apply_changes=True,
        approved=True,
        session_factory=sessions,
        settings=policy,
        now=now,
    )
    async with sessions() as session:
        assert await session.get(DocumentProcessingRun, run_id) is not None
    assert protected.removed_count == 0

    await _request(lifecycle_context)
    async with sessions.begin() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        assert run is not None
        run.updated_at = now - timedelta(days=10)
    dry_run = await run_document_retention(
        tenant_id=tenant_id,
        session_factory=sessions,
        settings=policy,
        now=now,
    )
    applied = await run_document_retention(
        tenant_id=tenant_id,
        apply_changes=True,
        approved=True,
        session_factory=sessions,
        settings=policy,
        now=now,
    )
    repeated = await run_document_retention(
        tenant_id=tenant_id,
        apply_changes=True,
        approved=True,
        session_factory=sessions,
        settings=policy,
        now=now,
    )

    assert dry_run.dry_run is True
    assert dry_run.finding_counts["cancelled_run"] == 1
    assert applied.removed_count == 1
    assert repeated.removed_count == 0
    async with sessions() as session:
        assert await session.get(DocumentProcessingRun, run_id) is None
        document = await session.get(Document, document_id)
        assert document is not None
        assert document.lifecycle_status == DocumentLifecycleStatus.DELETING.value


@pytest.mark.asyncio
async def test_reconciliation_reports_then_repairs_visible_deleting_chunks(
    lifecycle_context,
    monkeypatch,
) -> None:
    sessions, tenant_id, project_id, document_id, _, run_id, _, _ = lifecycle_context
    _, _ = await _request(lifecycle_context)
    async with sessions.begin() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        document.current_processing_run_id = run_id
        session.add(
            DocumentChunk(
                processing_run_id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                ordinal=1,
                token_count=2,
                content="Synthetic residual",
                content_sha256="b" * 64,
                block_type="paragraph",
                heading_path=[],
                source_metadata={},
                embedding=[0.0] * 384,
            )
        )

    async def fake_publish(*_args, **_kwargs):
        return DispatchResult(True, True)

    monkeypatch.setattr(
        "app.services.document_maintenance.publish_deletion_dispatch",
        fake_publish,
    )
    policy = Settings(_env_file=None).model_copy(update={"document_lifecycle_batch_size": 20})
    report = await reconcile_document_lifecycle(
        tenant_id=tenant_id,
        session_factory=sessions,
        storage=RecordingStorage(),
        settings=policy,
    )
    repaired = await reconcile_document_lifecycle(
        tenant_id=tenant_id,
        apply_changes=True,
        approved=True,
        session_factory=sessions,
        storage=RecordingStorage(),
        settings=policy,
    )

    assert report.dry_run is True
    assert report.finding_counts["deleting_vectors"] == 1
    assert repaired.repaired_count >= 1
    async with sessions() as session:
        document = await session.get(Document, document_id)
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        assert document is not None and document.current_processing_run_id is None
        assert chunk_count == 0
