from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
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
    Project,
    Tenant,
    User,
)
from app.services.dispatcher import (
    INGESTION_TASK_NAME,
    DispatchEnvelope,
    DispatchResult,
    publish_ingestion_dispatch,
)
from app.services.ingestion import reconciliation


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.envelopes: list[DispatchEnvelope] = []

    def publish(self, envelope: DispatchEnvelope) -> None:
        self.envelopes.append(envelope)
        if self.fail:
            raise RuntimeError("synthetic broker detail must remain private")


@pytest_asyncio.fixture
async def dispatch_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'dispatch.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    ids = tuple(uuid4() for _ in range(7))
    tenant_id, project_id, document_id, job_id, run_id, outbox_id, user_id = ids
    now = datetime.now(UTC)
    async with sessions.begin() as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    external_subject="dispatch-user",
                    email="dispatch@example.test",
                    display_name="Dispatch",
                ),
                Tenant(id=tenant_id, name="Dispatch", slug=f"dispatch-{tenant_id.hex}"),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                created_by=user_id,
                name="Dispatch",
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
                    size_bytes=32,
                    storage_key=f"synthetic/{document_id}.pdf",
                ),
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    created_by=user_id,
                    job_type=JobType.DOCUMENT_INGESTION.value,
                    status=ProcessingStatus.QUEUED.value,
                    progress=0,
                    current_step=IngestionStage.QUEUED.value,
                ),
            ]
        )
        await session.flush()
        session.add(
            DocumentProcessingRun(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                job_id=job_id,
                status=DocumentProcessingStatus.QUEUED.value,
                current_stage=IngestionStage.QUEUED.value,
            )
        )
        await session.flush()
        session.add(
            JobDispatchOutbox(
                id=outbox_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                job_id=job_id,
                processing_run_id=run_id,
                task_name=INGESTION_TASK_NAME,
                status=DispatchStatus.PENDING.value,
                attempt_count=0,
                available_at=now,
            )
        )
    try:
        yield sessions, ids
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_outbox_publishes_after_commit_and_duplicate_delivery_is_safe(dispatch_context):
    sessions, ids = dispatch_context
    tenant_id, _, _, job_id, run_id, outbox_id, _ = ids
    publisher = RecordingPublisher()

    first = await publish_ingestion_dispatch(
        tenant_id,
        outbox_id,
        publisher=publisher,
        session_factory=sessions,
        policy=get_settings(),
    )
    duplicate = await publish_ingestion_dispatch(
        tenant_id,
        outbox_id,
        publisher=publisher,
        session_factory=sessions,
        policy=get_settings(),
    )

    assert first == DispatchResult(published=True, terminal=True)
    assert duplicate == DispatchResult(published=False, terminal=True)
    assert len(publisher.envelopes) == 1
    envelope = publisher.envelopes[0]
    assert envelope.job_id == job_id
    assert envelope.processing_run_id == run_id
    assert envelope.task_name == INGESTION_TASK_NAME
    assert not hasattr(envelope, "storage_key")
    async with sessions() as session:
        outbox = await session.get(JobDispatchOutbox, outbox_id)
        assert outbox is not None
        assert outbox.status == DispatchStatus.PUBLISHED.value
        assert outbox.published_at is not None


@pytest.mark.asyncio
async def test_broker_failure_is_recoverable_without_exposing_provider_error(dispatch_context):
    sessions, ids = dispatch_context
    tenant_id, _, _, _, _, outbox_id, _ = ids
    failed = await publish_ingestion_dispatch(
        tenant_id,
        outbox_id,
        publisher=RecordingPublisher(fail=True),
        session_factory=sessions,
        policy=get_settings(),
    )
    assert failed == DispatchResult(published=False, terminal=False)
    async with sessions.begin() as session:
        outbox = await session.get(JobDispatchOutbox, outbox_id)
        assert outbox is not None
        assert outbox.status == DispatchStatus.PENDING.value
        assert outbox.last_error_code == "DOCUMENT_DISPATCH_UNAVAILABLE"
        assert "synthetic" not in (outbox.last_error_code or "")
        outbox.available_at = datetime.now(UTC) - timedelta(seconds=1)

    publisher = RecordingPublisher()
    recovered = await publish_ingestion_dispatch(
        tenant_id,
        outbox_id,
        publisher=publisher,
        session_factory=sessions,
        policy=get_settings(),
    )
    assert recovered.published is True
    assert len(publisher.envelopes) == 1


@pytest.mark.asyncio
async def test_reconciler_recovers_stale_processing_and_repairs_completed_job(
    dispatch_context, monkeypatch
):
    sessions, ids = dispatch_context
    tenant_id, _, document_id, job_id, run_id, _, _ = ids
    policy = get_settings().model_copy(
        update={
            "document_ingestion_enabled": True,
            "tasks_eager": False,
            "document_reconciliation_stale_seconds": 60,
            "document_reconciliation_batch_size": 20,
        }
    )
    async with sessions.begin() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        job = await session.get(Job, job_id)
        outbox = await session.get(JobDispatchOutbox, ids[5])
        assert run is not None and job is not None and outbox is not None
        run.status = DocumentProcessingStatus.IN_PROGRESS.value
        run.current_stage = IngestionStage.EXTRACTING.value
        run.attempt_count = 1
        run.last_heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        job.status = ProcessingStatus.IN_PROGRESS.value
        job.current_step = IngestionStage.EXTRACTING.value
        outbox.status = DispatchStatus.PUBLISHED.value

    published: list[UUID] = []

    async def fake_publish(_tenant_id, outbox_id, **_kwargs):
        published.append(outbox_id)
        return DispatchResult(True, True)

    monkeypatch.setattr(reconciliation, "publish_ingestion_dispatch", fake_publish)
    result = await reconciliation.reconcile_ingestion_dispatches(
        session_factory=sessions,
        settings=policy,
    )
    assert result.repaired_count == 1
    assert result.republished_count == 1
    assert published == [ids[5]]

    async with sessions.begin() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        job = await session.get(Job, job_id)
        document = await session.get(Document, document_id)
        assert run is not None and job is not None and document is not None
        run.status = DocumentProcessingStatus.COMPLETED.value
        run.current_stage = IngestionStage.COMPLETED.value
        run.document_content_sha256 = "a" * 64
        run.extractor_name = "secure-pdf-extractor"
        run.extractor_version = "1.0.0"
        run.chunker_version = "1.0.0"
        run.embedding_provider = "fastembed"
        run.embedding_model = "BAAI/bge-small-en-v1.5"
        run.embedding_model_revision = "a" * 40
        run.embedding_dimensions = 384
        run.embedding_formatting_version = "format-v1"
        run.chunk_count = 1
        document.current_processing_run_id = run.id
        job.status = ProcessingStatus.IN_PROGRESS.value

    completed = await reconciliation.reconcile_ingestion_dispatches(
        session_factory=sessions,
        settings=policy,
    )
    assert completed.repaired_count == 1
    async with sessions() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.status == ProcessingStatus.COMPLETED.value
        assert job.progress == 100


@pytest.mark.asyncio
async def test_reconciler_fails_queued_ingestion_job_with_missing_run(
    dispatch_context, monkeypatch
):
    sessions, ids = dispatch_context
    tenant_id, project_id, _, existing_job_id, _, _, _ = ids
    missing_run_job_id = uuid4()
    async with sessions.begin() as session:
        existing_job = await session.get(Job, existing_job_id)
        assert existing_job is not None
        session.add(
            Job(
                id=missing_run_job_id,
                tenant_id=tenant_id,
                project_id=project_id,
                created_by=existing_job.created_by,
                job_type=JobType.DOCUMENT_INGESTION.value,
                status=ProcessingStatus.QUEUED.value,
                progress=0,
                current_step=IngestionStage.QUEUED.value,
            )
        )

    async def no_publish(*_args, **_kwargs):
        return DispatchResult(False, False)

    monkeypatch.setattr(reconciliation, "publish_ingestion_dispatch", no_publish)
    policy = get_settings().model_copy(
        update={
            "document_ingestion_enabled": True,
            "tasks_eager": False,
            "document_reconciliation_batch_size": 20,
        }
    )
    result = await reconciliation.reconcile_ingestion_dispatches(
        session_factory=sessions,
        settings=policy,
    )

    assert result.failed_count == 1
    async with sessions() as session:
        job = await session.get(Job, missing_run_job_id)
        assert job is not None
        assert job.status == ProcessingStatus.FAILED.value
        assert job.error_code == "DOCUMENT_INGESTION_STATE_INCONSISTENT"
