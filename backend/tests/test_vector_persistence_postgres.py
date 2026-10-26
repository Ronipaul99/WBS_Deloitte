from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from vector_persistence_fixtures import embedding_result, processing_counts, processing_identity

from app.core.config import Settings
from app.services.ingestion.embeddings.base import EmbeddingVector
from app.services.ingestion.errors import PersistenceError, PersistenceErrorCode
from app.services.ingestion.repository import PersistenceScope, VectorPersistenceRepository

MIGRATION_URL = os.getenv("STEP10_POSTGRES_MIGRATION_URL")
RUNTIME_URL = os.getenv("STEP10_POSTGRES_RUNTIME_URL")
DISPOSABLE_ACK = os.getenv("STEP10_POSTGRES_DISPOSABLE_ACK")
POSTGRES_READY = bool(
    MIGRATION_URL and RUNTIME_URL and DISPOSABLE_ACK == "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE"
)

pytestmark = pytest.mark.skipif(
    not POSTGRES_READY,
    reason="isolated Step 10 PostgreSQL URLs and disposable-database acknowledgement are required",
)


def _async_url(value: str) -> str:
    return Settings._as_async_sqlalchemy_url(value)


@pytest.mark.asyncio
async def test_postgresql_transactional_persistence_rls_concurrency_and_exact_query() -> None:
    admin_engine = create_async_engine(_async_url(MIGRATION_URL))
    runtime_engine = create_async_engine(_async_url(RUNTIME_URL), pool_size=2, max_overflow=0)
    RuntimeSession = async_sessionmaker(runtime_engine, expire_on_commit=False)
    repository = VectorPersistenceRepository(RuntimeSession)

    user_id = uuid4()
    tenant_id, other_tenant_id = uuid4(), uuid4()
    project_id, other_project_id = uuid4(), uuid4()
    document_id, other_document_id = uuid4(), uuid4()
    job_id, other_job_id = uuid4(), uuid4()
    scope = PersistenceScope(tenant_id, project_id, document_id, job_id)
    result = embedding_result(2)
    counts = processing_counts(result)
    identity = processing_identity()

    try:
        async with admin_engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "e71c4a9b203d"
            )
            runtime_role = make_url(_async_url(RUNTIME_URL)).username
            # Legacy application grants are normally provisioned separately;
            # vector migrations deliberately grant only their protected tables.
            quoted_runtime = admin_engine.dialect.identifier_preparer.quote(runtime_role)
            await connection.execute(
                text(f"GRANT SELECT, UPDATE ON documents, jobs TO {quoted_runtime}")
            )
            role = (
                await connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                    {"role": runtime_role},
                )
            ).one()
            assert role == (False, False)
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, external_subject, email, display_name, is_active, auth_version) "
                    "VALUES (:id, :subject, :email, 'Step 10', true, 1)"
                ),
                {
                    "id": user_id,
                    "subject": f"step10-{user_id}",
                    "email": f"step10-{user_id}@example.test",
                },
            )
            for current_tenant in (tenant_id, other_tenant_id):
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, is_active) "
                        "VALUES (:id, 'Step 10', :slug, true)"
                    ),
                    {"id": current_tenant, "slug": f"step10-{current_tenant}"},
                )
            for current_tenant, current_project, current_document, current_job in (
                (tenant_id, project_id, document_id, job_id),
                (other_tenant_id, other_project_id, other_document_id, other_job_id),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO projects (id, tenant_id, created_by, name, status) "
                        "VALUES (:id, :tenant_id, :user_id, 'Step 10', 'ACTIVE')"
                    ),
                    {
                        "id": current_project,
                        "tenant_id": current_tenant,
                        "user_id": user_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO jobs "
                        "(id, tenant_id, project_id, created_by, job_type, status, progress, "
                        "request_payload, result_payload) VALUES "
                        "(:id, :tenant_id, :project_id, :user_id, "
                        "'DOCUMENT_INGESTION', 'QUEUED', 0, '{}', '{}')"
                    ),
                    {
                        "id": current_job,
                        "tenant_id": current_tenant,
                        "project_id": current_project,
                        "user_id": user_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(id, tenant_id, project_id, uploaded_by, kind, file_name, content_type, "
                        "size_bytes, storage_key) VALUES "
                        "(:id, :tenant_id, :project_id, :user_id, 'PROJECT', "
                        "'synthetic.pdf', 'application/pdf', 1, :storage_key)"
                    ),
                    {
                        "id": current_document,
                        "tenant_id": current_tenant,
                        "project_id": current_project,
                        "user_id": user_id,
                        "storage_key": f"step10/{current_document}.pdf",
                    },
                )

        run = await repository.create_or_resolve_run(scope, identity, counts)
        await repository.stage_embeddings(scope, run.run_id, result, identity)
        activation_results = await asyncio.gather(
            repository.activate_run(scope, run.run_id, result, identity, counts),
            repository.activate_run(scope, run.run_id, result, identity, counts),
        )
        assert sorted(item.activated for item in activation_results) == [False, True]

        query = [0.0] * 384
        query[0] = 1.0
        matches = await repository.exact_active_similarity(
            scope.document_scope,
            EmbeddingVector(query, dimensions=384),
            limit=2,
        )
        assert tuple(match.ordinal for match in matches) == (0, 1)
        semantic, lexical = await repository.active_search_candidates(
            scope.document_scope,
            EmbeddingVector(query, dimensions=384),
            terms=("synthetic", "persistence"),
            candidate_limit=2,
        )
        assert [row["ordinal"] for row in semantic] == [0, 1]
        assert {row["ordinal"] for row in lexical} == {0, 1}
        assert all(row["processing_run_id"] == run.run_id for row in semantic + lexical)

        failed_identity = processing_identity(chunker_version="2.0.0")
        failed_run = await repository.create_or_resolve_run(scope, failed_identity, counts)
        await repository.mark_run_failed(
            scope,
            failed_run.run_id,
            PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_UNAVAILABLE),
        )
        active = await repository.load_active_ordered_chunks(scope.document_scope)
        assert {chunk.processing_run_id for chunk in active} == {run.run_id}
        semantic, lexical = await repository.active_search_candidates(
            scope.document_scope,
            EmbeddingVector(query, dimensions=384),
            terms=("synthetic",),
            candidate_limit=2,
        )
        assert all(row["processing_run_id"] == run.run_id for row in semantic + lexical)

        wrong_scope = PersistenceScope(
            tenant_id,
            other_project_id,
            other_document_id,
            other_job_id,
        )
        with pytest.raises(PersistenceError) as error:
            await repository.create_or_resolve_run(wrong_scope, identity, counts)
        assert error.value.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH

        with pytest.raises(PersistenceError):
            await repository.active_search_candidates(
                wrong_scope.document_scope,
                EmbeddingVector(query, dimensions=384),
                terms=("synthetic",),
            )
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE documents SET lifecycle_status='DELETING', "
                    "deletion_requested_at=now(), vectors_hidden_at=now() WHERE id=:id"
                ),
                {"id": document_id},
            )
        with pytest.raises(PersistenceError):
            await repository.active_search_candidates(
                scope.document_scope,
                EmbeddingVector(query, dimensions=384),
                terms=("synthetic",),
            )

        async with RuntimeSession.begin() as session:
            assert await session.scalar(text("SELECT COUNT(*) FROM document_chunks")) == 0
    finally:
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE documents SET current_processing_run_id = NULL "
                        "WHERE id = ANY(:document_ids)"
                    ),
                    {"document_ids": [document_id, other_document_id]},
                )
                await connection.execute(
                    text("DELETE FROM document_processing_runs WHERE document_id = ANY(:ids)"),
                    {"ids": [document_id, other_document_id]},
                )
                await connection.execute(
                    text("DELETE FROM documents WHERE id = ANY(:ids)"),
                    {"ids": [document_id, other_document_id]},
                )
                await connection.execute(
                    text("DELETE FROM jobs WHERE id = ANY(:ids)"),
                    {"ids": [job_id, other_job_id]},
                )
                await connection.execute(
                    text("DELETE FROM projects WHERE id = ANY(:ids)"),
                    {"ids": [project_id, other_project_id]},
                )
                await connection.execute(
                    text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                    {"ids": [tenant_id, other_tenant_id]},
                )
                await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        finally:
            await runtime_engine.dispose()
            await admin_engine.dispose()
