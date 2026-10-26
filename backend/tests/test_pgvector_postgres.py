import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import set_local_tenant_context

MIGRATION_URL = os.getenv("STEP3_POSTGRES_MIGRATION_URL")
RUNTIME_URL = os.getenv("STEP3_POSTGRES_RUNTIME_URL")
DISPOSABLE_ACK = os.getenv("STEP3_POSTGRES_DISPOSABLE_ACK")
POSTGRES_READY = bool(
    MIGRATION_URL and RUNTIME_URL and DISPOSABLE_ACK == "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE"
)

pytestmark = pytest.mark.skipif(
    not POSTGRES_READY,
    reason="isolated Step 3 PostgreSQL URLs and disposable-database acknowledgement are required",
)


def _async_url(value: str) -> str:
    return Settings._as_async_sqlalchemy_url(value)


def _vector(position: int) -> str:
    values = [0.0] * 384
    values[position] = 1.0
    return "[" + ",".join(str(value) for value in values) + "]"


async def _set_tenant(session, tenant_id: UUID) -> None:
    await set_local_tenant_context(session, tenant_id)


async def _insert_run(
    session,
    *,
    run_id: UUID,
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    job_id: UUID,
    status: str,
    extractor_version: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO document_processing_runs (
                id, tenant_id, project_id, document_id, job_id, status,
                document_content_sha256, extractor_name, extractor_version,
                embedding_provider, embedding_model, embedding_dimensions,
                chunker_version, embedding_model_revision, embedding_formatting_version,
                page_count, worksheet_count, block_count, chunk_count
            ) VALUES (
                :id, :tenant_id, :project_id, :document_id, :job_id, :status,
                :content_hash, 'step3-test', :extractor_version,
                'fastembed', 'BAAI/bge-small-en-v1.5', 384,
                '1.0.0', :revision, 'format-v1', 1, 0, 1, 1
            )
            """
        ),
        {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "document_id": document_id,
            "job_id": job_id,
            "status": status,
            "content_hash": "a" * 64,
            "extractor_version": extractor_version,
            "revision": "a" * 40,
        },
    )


async def _insert_chunk(
    session,
    *,
    chunk_id: UUID,
    run_id: UUID,
    tenant_id: UUID,
    project_id: UUID,
    document_id: UUID,
    ordinal: int,
    embedding: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO document_chunks (
                id, processing_run_id, tenant_id, project_id, document_id,
                ordinal, token_count, content, content_sha256, block_type,
                heading_path, source_metadata, embedding
            ) VALUES (
                :id, :run_id, :tenant_id, :project_id, :document_id,
                :ordinal, 4, 'synthetic chunk', :content_hash, 'paragraph',
                '[]'::jsonb, '{}'::jsonb, CAST(:embedding AS vector)
            )
            """
        ),
        {
            "id": chunk_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "document_id": document_id,
            "ordinal": ordinal,
            "content_hash": "b" * 64,
            "embedding": embedding,
        },
    )


@pytest.mark.asyncio
async def test_postgresql_extension_rls_grants_and_runtime_role() -> None:
    admin_engine = create_async_engine(_async_url(MIGRATION_URL))
    try:
        async with admin_engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            )
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "e71c4a9b203d"
            )
            vector_type = await connection.scalar(
                text(
                    """
                    SELECT format_type(attribute.atttypid, attribute.atttypmod)
                    FROM pg_attribute AS attribute
                    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                    WHERE relation.relname = 'document_chunks'
                      AND attribute.attname = 'embedding'
                    """
                )
            )
            assert vector_type == "vector(384)"

            runtime_role = make_url(_async_url(RUNTIME_URL)).username
            role = (
                await connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                    {"role": runtime_role},
                )
            ).one()
            assert role == (False, False)
            for table in (
                "document_processing_runs",
                "document_chunks",
                "job_dispatch_outbox",
            ):
                security = (
                    await connection.execute(
                        text(
                            """
                            SELECT relrowsecurity, relforcerowsecurity,
                                   pg_get_userbyid(relowner) = :runtime_role
                            FROM pg_class
                            WHERE relname = :table
                            """
                        ),
                        {"runtime_role": runtime_role, "table": table},
                    )
                ).one()
                assert security == (True, True, False)
                policy = await connection.scalar(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM pg_policies
                        WHERE tablename = :table
                          AND cmd = 'ALL'
                          AND :runtime_role = ANY(roles)
                          AND qual LIKE '%app.tenant_id%'
                          AND with_check LIKE '%app.tenant_id%'
                        """
                    ),
                    {"runtime_role": runtime_role, "table": table},
                )
                assert policy == 1
    finally:
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_ownership_rls_dimensions_and_exact_query() -> None:
    admin_engine = create_async_engine(_async_url(MIGRATION_URL))
    runtime_engine = create_async_engine(_async_url(RUNTIME_URL), pool_size=1, max_overflow=0)
    RuntimeSession = async_sessionmaker(runtime_engine, expire_on_commit=False)

    user_id = uuid4()
    tenant_a, tenant_b = uuid4(), uuid4()
    project_a, project_a2, project_b = uuid4(), uuid4(), uuid4()
    document_a, document_a2, document_b = uuid4(), uuid4(), uuid4()
    job_a, job_a2, job_b = uuid4(), uuid4(), uuid4()
    run_a, run_a2, run_b = uuid4(), uuid4(), uuid4()
    chunk_a, chunk_a2, chunk_b = uuid4(), uuid4(), uuid4()

    projects = (
        (tenant_a, project_a, document_a, job_a),
        (tenant_a, project_a2, document_a2, job_a2),
        (tenant_b, project_b, document_b, job_b),
    )
    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, external_subject, email, display_name, is_active, auth_version
                    ) VALUES (:id, :subject, :email, 'Step 3 Test', true, 1)
                    """
                ),
                {
                    "id": user_id,
                    "subject": f"step3-{user_id}",
                    "email": f"step3-{user_id}@example.test",
                },
            )
            for tenant_id in (tenant_a, tenant_b):
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, name, slug, is_active) "
                        "VALUES (:id, 'Step 3', :slug, true)"
                    ),
                    {"id": tenant_id, "slug": f"step3-{tenant_id}"},
                )
            for tenant_id, project_id, document_id, job_id in projects:
                await connection.execute(
                    text(
                        """
                        INSERT INTO projects (id, tenant_id, created_by, name, status)
                        VALUES (:id, :tenant_id, :user_id, 'Step 3', 'ACTIVE')
                        """
                    ),
                    {"id": project_id, "tenant_id": tenant_id, "user_id": user_id},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO jobs (
                            id, tenant_id, project_id, created_by, job_type, status,
                            progress, request_payload, result_payload
                        ) VALUES (
                            :id, :tenant_id, :project_id, :user_id,
                            'DOCUMENT_INGESTION', 'QUEUED', 0, '{}', '{}'
                        )
                        """
                    ),
                    {
                        "id": job_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": user_id,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id, tenant_id, project_id, uploaded_by, kind, file_name,
                            content_type, size_bytes, storage_key, content_sha256
                        ) VALUES (
                            :id, :tenant_id, :project_id, :user_id, 'PROJECT',
                            'synthetic.pdf', 'application/pdf', 1, :storage_key, :content_hash
                        )
                        """
                    ),
                    {
                        "id": document_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "storage_key": f"step3/{document_id}.pdf",
                        "content_hash": "a" * 64,
                    },
                )

        for tenant_id, project_id, document_id, job_id, run_id, chunk_id, position in (
            (tenant_a, project_a, document_a, job_a, run_a, chunk_a, 0),
            (tenant_a, project_a2, document_a2, job_a2, run_a2, chunk_a2, 1),
            (tenant_b, project_b, document_b, job_b, run_b, chunk_b, 2),
        ):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_id)
                await _insert_run(
                    session,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    job_id=job_id,
                    status="COMPLETED",
                    extractor_version=f"1.{position}",
                )
                await _insert_chunk(
                    session,
                    chunk_id=chunk_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    document_id=document_id,
                    ordinal=0,
                    embedding=_vector(position),
                )

        async with RuntimeSession.begin() as session:
            await _set_tenant(session, tenant_a)
            tenant_rows = (
                (await session.execute(text("SELECT id FROM document_chunks ORDER BY id")))
                .scalars()
                .all()
            )
            assert set(tenant_rows) == {chunk_a, chunk_a2}

            scoped_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id FROM document_chunks "
                            "WHERE tenant_id = :tenant_id AND project_id = :project_id"
                        ),
                        {"tenant_id": tenant_a, "project_id": project_a},
                    )
                )
                .scalars()
                .all()
            )
            assert scoped_rows == [chunk_a]

            nearest = await session.scalar(
                text(
                    """
                    SELECT id FROM document_chunks
                    WHERE tenant_id = :tenant_id AND project_id = :project_id
                    ORDER BY embedding <=> CAST(:query AS vector)
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_a,
                    "project_id": project_a,
                    "query": _vector(0),
                },
            )
            assert nearest == chunk_a

            cross_tenant_update = await session.execute(
                text("UPDATE document_chunks SET block_type = 'blocked' WHERE id = :chunk_id"),
                {"chunk_id": chunk_b},
            )
            cross_tenant_delete = await session.execute(
                text("DELETE FROM document_chunks WHERE id = :chunk_id"),
                {"chunk_id": chunk_b},
            )
            assert cross_tenant_update.rowcount == 0
            assert cross_tenant_delete.rowcount == 0

        async with RuntimeSession.begin() as session:
            assert (await session.scalar(text("SELECT COUNT(*) FROM document_chunks"))) == 0

        with pytest.raises(DBAPIError):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_a)
                await _insert_chunk(
                    session,
                    chunk_id=uuid4(),
                    run_id=run_a,
                    tenant_id=tenant_a,
                    project_id=project_a,
                    document_id=document_a,
                    ordinal=1,
                    embedding="[1,0]",
                )

        with pytest.raises(DBAPIError):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_a)
                await _insert_chunk(
                    session,
                    chunk_id=uuid4(),
                    run_id=run_a,
                    tenant_id=tenant_a,
                    project_id=project_a,
                    document_id=document_a,
                    ordinal=0,
                    embedding=_vector(0),
                )

        with pytest.raises(DBAPIError):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_a)
                await _insert_run(
                    session,
                    run_id=uuid4(),
                    tenant_id=tenant_b,
                    project_id=project_b,
                    document_id=document_b,
                    job_id=job_b,
                    status="FAILED",
                    extractor_version="denied",
                )

        failed_run = uuid4()
        async with RuntimeSession.begin() as session:
            await _set_tenant(session, tenant_a)
            await _insert_run(
                session,
                run_id=failed_run,
                tenant_id=tenant_a,
                project_id=project_a,
                document_id=document_a,
                job_id=job_a,
                status="FAILED",
                extractor_version="failed-retry",
            )

        with pytest.raises(DBAPIError):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_a)
                await _insert_run(
                    session,
                    run_id=uuid4(),
                    tenant_id=tenant_a,
                    project_id=project_a,
                    document_id=document_a,
                    job_id=job_a,
                    status="FAILED",
                    extractor_version="1.0",
                )

        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE documents SET current_processing_run_id = :run_id, "
                    "processing_status = 'COMPLETED' WHERE id = :document_id"
                ),
                {"run_id": run_a, "document_id": document_a},
            )
        with pytest.raises(DBAPIError):
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE documents SET current_processing_run_id = :run_id "
                        "WHERE id = :document_id"
                    ),
                    {"run_id": run_a, "document_id": document_a2},
                )

        active_run = uuid4()
        async with RuntimeSession.begin() as session:
            await _set_tenant(session, tenant_a)
            await _insert_run(
                session,
                run_id=active_run,
                tenant_id=tenant_a,
                project_id=project_a2,
                document_id=document_a2,
                job_id=job_a2,
                status="QUEUED",
                extractor_version="active-1",
            )
        with pytest.raises(DBAPIError):
            async with RuntimeSession.begin() as session:
                await _set_tenant(session, tenant_a)
                await _insert_run(
                    session,
                    run_id=uuid4(),
                    tenant_id=tenant_a,
                    project_id=project_a2,
                    document_id=document_a2,
                    job_id=job_a2,
                    status="IN_PROGRESS",
                    extractor_version="active-2",
                )

        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE documents SET current_processing_run_id = NULL WHERE id = :document_id"
                ),
                {"document_id": document_a},
            )
        async with RuntimeSession.begin() as session:
            await _set_tenant(session, tenant_a)
            await session.execute(
                text("DELETE FROM document_processing_runs WHERE id = :run_id"),
                {"run_id": run_a},
            )
            assert (
                await session.scalar(
                    text("SELECT COUNT(*) FROM document_chunks WHERE id = :chunk_id"),
                    {"chunk_id": chunk_a},
                )
                == 0
            )
    finally:
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE documents SET current_processing_run_id = NULL "
                        "WHERE id = ANY(:document_ids)"
                    ),
                    {"document_ids": [document_a, document_a2, document_b]},
                )
            for tenant_id in (tenant_a, tenant_b):
                async with RuntimeSession.begin() as session:
                    await _set_tenant(session, tenant_id)
                    await session.execute(
                        text("DELETE FROM document_processing_runs WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
                    )
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM documents WHERE id = ANY(:ids)"),
                    {"ids": [document_a, document_a2, document_b]},
                )
                await connection.execute(
                    text("DELETE FROM jobs WHERE id = ANY(:ids)"),
                    {"ids": [job_a, job_a2, job_b]},
                )
                await connection.execute(
                    text("DELETE FROM projects WHERE id = ANY(:ids)"),
                    {"ids": [project_a, project_a2, project_b]},
                )
                await connection.execute(
                    text("DELETE FROM tenants WHERE id = ANY(:ids)"),
                    {"ids": [tenant_a, tenant_b]},
                )
                await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        finally:
            await runtime_engine.dispose()
            await admin_engine.dispose()
