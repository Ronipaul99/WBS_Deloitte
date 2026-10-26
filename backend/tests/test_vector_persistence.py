from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vector_persistence_fixtures import (
    embedding_result,
    processing_counts,
    processing_identity,
    synthetic_ids,
)

from app.db.base import Base
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    Job,
    JobType,
    Project,
    ProjectStatus,
    Tenant,
    User,
)
from app.services.ingestion.embeddings.base import EmbeddingBatchResult, EmbeddingMetadata
from app.services.ingestion.errors import PersistenceError, PersistenceErrorCode
from app.services.ingestion.repository import (
    PersistenceScope,
    ProcessingIdentity,
    RunResolution,
    VectorPersistencePolicy,
    VectorPersistenceRepository,
)


@pytest_asyncio.fixture
async def persistence_context(tmp_path):
    database = tmp_path / "persistence.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, project_id, document_id, job_id, user_id = synthetic_ids()
    async with sessions.begin() as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    external_subject="step10-synthetic-user",
                    email="step10@example.test",
                    display_name="Step 10",
                    is_active=True,
                    auth_version=1,
                ),
                Tenant(
                    id=tenant_id,
                    name="Step 10",
                    slug="step10-synthetic",
                    is_active=True,
                ),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                created_by=user_id,
                name="Step 10",
                status=ProjectStatus.ACTIVE.value,
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
                    size_bytes=10,
                    storage_key="synthetic/step10.pdf",
                ),
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    created_by=user_id,
                    job_type=JobType.DOCUMENT_INGESTION.value,
                    status="QUEUED",
                    progress=0,
                    request_payload={},
                    result_payload={},
                ),
            ]
        )
    scope = PersistenceScope(tenant_id, project_id, document_id, job_id)
    repository = VectorPersistenceRepository(
        sessions,
        policy=VectorPersistencePolicy(batch_size=1),
    )
    try:
        yield sessions, repository, scope
    finally:
        await engine.dispose()


def test_scope_identity_and_policy_are_bounded_and_redacted() -> None:
    tenant_id, project_id, document_id, job_id, _ = synthetic_ids()
    scope = PersistenceScope(
        str(tenant_id),
        str(project_id),
        str(document_id),
        str(job_id),
    )
    identity = processing_identity()

    assert scope.tenant_id == tenant_id
    assert "10000000" not in repr(scope)
    assert identity.embedding_dimensions == 384
    assert identity.document_content_sha256 not in repr(identity)
    with pytest.raises(FrozenInstanceError):
        identity.chunker_version = "changed"
    with pytest.raises(PersistenceError) as error:
        ProcessingIdentity(
            document_content_sha256="not-a-hash",
            extractor_name="extractor",
            extractor_version="1",
            chunker_version="1",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_model_revision="revision",
            embedding_dimensions=384,
            embedding_formatting_version="format",
        )
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_INPUT_INVALID


@pytest.mark.asyncio
async def test_staged_batches_activate_atomically_and_duplicate_delivery_is_idempotent(
    persistence_context,
) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(2)
    identity = processing_identity()
    counts = processing_counts(result)

    resolution = await repository.create_or_resolve_run(scope, identity, counts)
    assert resolution.resolution is RunResolution.CREATED
    staged = await repository.stage_embeddings(scope, resolution.run_id, result, identity)
    assert staged.inserted_count == 2
    assert staged.reused_count == 0

    async with sessions() as session:
        document = await session.get(Document, scope.document_id)
        assert document.current_processing_run_id is None

    retried = await repository.stage_embeddings(scope, resolution.run_id, result, identity)
    assert retried.inserted_count == 0
    assert retried.reused_count == 2
    reconciled = await repository.reconcile_run(scope, resolution.run_id, result, identity)
    assert (reconciled.persisted_count, reconciled.first_ordinal, reconciled.last_ordinal) == (
        2,
        0,
        1,
    )

    activated = await repository.activate_run(
        scope,
        resolution.run_id,
        result,
        identity,
        counts,
    )
    assert activated.activated is True
    active = await repository.load_active_ordered_chunks(scope.document_scope)
    assert tuple(chunk.ordinal for chunk in active) == (0, 1)
    assert active[0].source_metadata["source_references"][0]["role"] == "primary"
    assert result.items[0].chunk.content not in repr(active[0])
    assert "1.0" not in repr(active[0])
    with pytest.raises(TypeError):
        active[0].source_metadata["unexpected"] = "mutation"

    repeated = await repository.create_or_resolve_run(scope, identity, counts)
    assert repeated.run_id == resolution.run_id
    assert repeated.resolution is RunResolution.REUSED
    reactivated = await repository.activate_run(
        scope,
        resolution.run_id,
        result,
        identity,
        counts,
    )
    assert reactivated.activated is False


@pytest.mark.asyncio
async def test_failed_reprocessing_preserves_previous_active_run(persistence_context) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(1)
    counts = processing_counts(result)
    first_identity = processing_identity(chunker_version="1.0.0")
    first = await repository.create_or_resolve_run(scope, first_identity, counts)
    await repository.stage_embeddings(scope, first.run_id, result, first_identity)
    await repository.activate_run(scope, first.run_id, result, first_identity, counts)

    second_identity = processing_identity(chunker_version="2.0.0")
    second = await repository.create_or_resolve_run(scope, second_identity, counts)
    await repository.stage_embeddings(scope, second.run_id, result, second_identity)
    failure = PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_UNAVAILABLE)
    await repository.mark_run_failed(scope, second.run_id, failure)

    async with sessions() as session:
        document = await session.get(Document, scope.document_id)
        failed_run = await session.get(DocumentProcessingRun, second.run_id)
        assert document.current_processing_run_id == first.run_id
        assert document.processing_status == DocumentProcessingStatus.FAILED.value
        assert failed_run.status == DocumentProcessingStatus.FAILED.value
        assert failed_run.error_message == str(failure)

    active = await repository.load_active_ordered_chunks(scope.document_scope)
    assert len(active) == 1
    assert active[0].processing_run_id == first.run_id
    superseded = await repository.list_superseded_runs(scope.document_scope)
    assert tuple(run.run_id for run in superseded) == (second.run_id,)
    assert await repository.delete_superseded_run(scope.document_scope, second.run_id) is True
    async with sessions() as session:
        chunk_count = await session.scalar(
            select(DocumentChunk).where(DocumentChunk.processing_run_id == second.run_id)
        )
        assert chunk_count is None


@pytest.mark.asyncio
async def test_reconciliation_failure_never_changes_active_pointer(persistence_context) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(2)
    identity = processing_identity()
    counts = processing_counts(result)
    run = await repository.create_or_resolve_run(scope, identity, counts)

    with pytest.raises(PersistenceError) as error:
        await repository.activate_run(scope, run.run_id, result, identity, counts)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED
    async with sessions() as session:
        document = await session.get(Document, scope.document_id)
        stored_run = await session.get(DocumentProcessingRun, run.run_id)
        assert document.current_processing_run_id is None
        assert stored_run.status == DocumentProcessingStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_conflicting_existing_ordinal_fails_closed(persistence_context) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(1)
    identity = processing_identity()
    counts = processing_counts(result)
    run = await repository.create_or_resolve_run(scope, identity, counts)
    await repository.stage_embeddings(scope, run.run_id, result, identity)
    async with sessions.begin() as session:
        row = await session.scalar(
            select(DocumentChunk).where(DocumentChunk.processing_run_id == run.run_id)
        )
        row.content_sha256 = "f" * 64

    with pytest.raises(PersistenceError) as error:
        await repository.stage_embeddings(scope, run.run_id, result, identity)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT


@pytest.mark.asyncio
async def test_middle_batch_conflict_leaves_partial_stage_inactive(persistence_context) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(2)
    identity = processing_identity()
    counts = processing_counts(result)
    run = await repository.create_or_resolve_run(scope, identity, counts)
    async with sessions.begin() as session:
        session.add(
            DocumentChunk(
                processing_run_id=run.run_id,
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                document_id=scope.document_id,
                ordinal=1,
                token_count=1,
                content="Conflicting synthetic row",
                content_sha256="f" * 64,
                block_type="canonical_chunk",
                page_number=2,
                worksheet_name=None,
                row_start=None,
                row_end=None,
                heading_path=[],
                source_metadata={},
                embedding=[0.0] * 384,
            )
        )

    with pytest.raises(PersistenceError) as error:
        await repository.stage_embeddings(scope, run.run_id, result, identity)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT
    async with sessions() as session:
        document = await session.get(Document, scope.document_id)
        persisted = (
            await session.execute(
                select(DocumentChunk).where(DocumentChunk.processing_run_id == run.run_id)
            )
        ).scalars()
        assert document.current_processing_run_id is None
        assert len(persisted.all()) == 2
    assert await repository.load_active_ordered_chunks(scope.document_scope) == ()


@pytest.mark.asyncio
async def test_cross_scope_operations_fail_closed(persistence_context) -> None:
    _sessions, repository, scope = persistence_context
    result = embedding_result(1)
    identity = processing_identity()
    counts = processing_counts(result)
    run = await repository.create_or_resolve_run(scope, identity, counts)
    wrong_scope = PersistenceScope(
        UUID("10000000-0000-0000-0000-000000000099"),
        scope.project_id,
        scope.document_id,
        scope.job_id,
    )

    with pytest.raises(PersistenceError) as error:
        await repository.stage_embeddings(wrong_scope, run.run_id, result, identity)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH


@pytest.mark.asyncio
async def test_embedding_metadata_mismatch_is_rejected_before_write(persistence_context) -> None:
    sessions, repository, scope = persistence_context
    result = embedding_result(1)
    identity = processing_identity()
    run = await repository.create_or_resolve_run(scope, identity, processing_counts(result))
    mismatched = EmbeddingBatchResult(
        items=result.items,
        metadata=EmbeddingMetadata(
            provider_name=result.metadata.provider_name,
            model_name=result.metadata.model_name,
            model_revision=result.metadata.model_revision,
            dimensions=result.metadata.dimensions,
            formatting_version="incompatible-format-v2",
        ),
    )

    with pytest.raises(PersistenceError) as error:
        await repository.stage_embeddings(scope, run.run_id, mismatched, identity)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_INPUT_INVALID
    async with sessions() as session:
        assert (
            await session.scalar(
                select(DocumentChunk).where(DocumentChunk.processing_run_id == run.run_id)
            )
            is None
        )


@pytest.mark.asyncio
async def test_current_or_in_progress_run_cannot_be_deleted(persistence_context) -> None:
    _sessions, repository, scope = persistence_context
    result = embedding_result(1)
    identity = processing_identity()
    run = await repository.create_or_resolve_run(scope, identity, processing_counts(result))

    with pytest.raises(PersistenceError) as error:
        await repository.delete_superseded_run(scope.document_scope, run.run_id)
    assert error.value.code is PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT
