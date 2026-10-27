"""Opt-in destructive verification ONLY for a fresh, explicitly disposable PostgreSQL DB.

No .env/settings access. Without all three STEP02_* variables these tests skip
before any socket/engine is created. Never point these at application/Neon data.
"""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from agent_schema_fixtures import (
    NOW,
    OLD_HEAD,
    access,
    checkpoint,
    content,
    migrate,
    scope,
    seed_agents,
    seed_legacy,
    uid,
)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent_workflows import AgentCheckpoint, SummaryApprovalEvent, SummaryRevision
from app.models.domain import DocumentSummary
from app.models.llm import LlmCredentialVersion
from app.services.agents.repository import WorkflowRepository
from migrations.versions import f8c2a6d903b1_add_agent_persistence as migration

OWNER_URL = os.getenv("STEP02_POSTGRES_MIGRATION_URL")
RUNTIME_URL = os.getenv("STEP02_POSTGRES_RUNTIME_URL")
ACK = os.getenv("STEP02_POSTGRES_DISPOSABLE_ACK")
READY = bool(OWNER_URL and RUNTIME_URL and ACK == "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE")
pytestmark = pytest.mark.skipif(
    not READY, reason="fresh disposable Step 2 PostgreSQL URLs/ack required"
)


def checked_urls():
    if not READY:
        raise RuntimeError("explicit disposable PostgreSQL configuration required")
    owner, runtime = make_url(OWNER_URL), make_url(RUNTIME_URL)
    if (
        owner.get_backend_name() != "postgresql"
        or runtime.get_backend_name() != "postgresql"
        or not owner.database
        or not owner.database.startswith("wbs_step02_")
        or (owner.host, owner.port, owner.database)
        != (runtime.host, runtime.port, runtime.database)
        or not owner.username
        or not runtime.username
        or owner.username == runtime.username
    ):
        raise RuntimeError(
            "test URLs must name one dedicated wbs_step02_ database and separate roles"
        )
    return owner.set(drivername="postgresql+asyncpg"), runtime.set(drivername="postgresql+asyncpg")


async def bind(session, tenant=1, run=8, user=9):
    for key, value in (
        ("app.tenant_id", uid(tenant)),
        ("app.agent_workflow_run_id", uid(run)),
        ("app.agent_user_id", uid(user)),
    ):
        await session.execute(
            text("SELECT set_config(:key,:value,true)"), {"key": key, "value": str(value)}
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres():
    owner_url, runtime_url = checked_urls()
    owner = create_async_engine(owner_url, hide_parameters=True)
    runtime = create_async_engine(runtime_url, hide_parameters=True)
    factory = async_sessionmaker(runtime, expire_on_commit=False)
    try:
        async with owner.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == owner_url.database
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                    )
                )
                == 0
            ), "refusing to mutate a nonempty test database"
            await connection.run_sync(
                lambda conn: migrate(
                    conn, target=OLD_HEAD, runtime=runtime_url.username, owner=owner_url.username
                )
            )
            # Only historical tables receive baseline fixture grants. New append-only
            # privileges are installed separately by the new migration.
            quoted = connection.dialect.identifier_preparer.quote(runtime_url.username)
            await connection.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                    f"IN SCHEMA public TO {quoted}"
                )
            )
        async with factory.begin() as session:
            await bind(session)
            await seed_legacy(session, with_summary=False)
            await session.execute(
                text(
                    "INSERT INTO document_summaries "
                    "(id,tenant_id,document_id,summary_text,key_points,requirements,is_approved) "
                    "VALUES (:id,:tenant,:doc,'Preserved legacy text','[]','[]',false)"
                ),
                {"id": uid(20), "tenant": uid(1), "doc": uid(3)},
            )
            vector_before = await session.scalar(
                text("SELECT embedding::text FROM document_chunks")
            )
        # Check up/down/up while new tables are empty, retaining historical data.
        async with owner.begin() as connection:
            for reverse in (False, True, False):
                await connection.run_sync(
                    lambda conn, reverse=reverse: migrate(
                        conn,
                        start=OLD_HEAD,
                        runtime=runtime_url.username,
                        owner=owner_url.username,
                        downgrade=reverse,
                    )
                )
        async with factory.begin() as session:
            await bind(session)
            assert (
                await session.scalar(text("SELECT embedding::text FROM document_chunks"))
                == vector_before
            )
            legacy = await session.get(DocumentSummary, uid(20))
            assert legacy.summary_text == "Preserved legacy text"
            assert (
                legacy.active_revision_id is None and legacy.content_origin == "legacy_unverified"
            )
            assert await session.scalar(text("SELECT count(*) FROM summary_revisions")) == 0
            await seed_agents(session)
        yield owner, factory, runtime_url.username, owner_url.username
    finally:
        await runtime.dispose()
        await owner.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_runtime_role_forced_rls_grants_and_no_scope_defaults(postgres):
    owner, factory, runtime_name, _ = postgres
    async with owner.connect() as connection:
        assert tuple(
            (
                await connection.execute(
                    text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:role"),
                    {"role": runtime_name},
                )
            ).one()
        ) == (False, False)
        for table in migration.PROTECTED_TABLES:
            assert tuple(
                (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                            "WHERE oid=CAST(:table AS regclass)"
                        ),
                        {"table": table},
                    )
                ).one()
            ) == (True, True)
        assert not await connection.scalar(
            text("SELECT has_schema_privilege(:role,'public','CREATE')"), {"role": runtime_name}
        )
    async with factory() as session, session.begin():
        assert await session.scalar(select(AgentCheckpoint.id)) is None
        await bind(session, tenant=101, user=109)
        assert await session.scalar(select(AgentCheckpoint.id)) is None
        assert await session.scalar(select(LlmCredentialVersion.id)) is None
        await bind(session, run=88)
        assert await session.scalar(select(AgentCheckpoint.id)) is None
        await bind(session)
        assert await session.scalar(select(AgentCheckpoint.id)) == uid(40)
        await session.rollback()


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "operation",
    [
        "credential_fk",
        "checkpoint_scope",
        "checkpoint_duplicate",
        "revision_update",
        "forbidden_json",
        "cross_pointer",
        "outbox_job",
        "cross_evidence",
    ],
)
async def test_runtime_rejects_invalid_relationships_and_mutations(postgres, operation):
    _, factory, _, _ = postgres
    async with factory() as session, session.begin():
        await bind(session)
        with pytest.raises(DBAPIError):
            if operation == "credential_fk":
                await bind(session, tenant=101, user=109)
                await session.execute(
                    LlmCredentialVersion.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=uid(101),
                        connection_id=uid(5),
                        version=1,
                        ciphertext=b"x" * 32,
                        nonce=b"n" * 12,
                        key_version="synthetic",
                    )
                )
            elif operation == "checkpoint_scope":
                await session.execute(
                    AgentCheckpoint.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=uid(101),
                        workflow_run_id=uid(8),
                        sequence=2,
                        node="synthetic",
                        input_sha256="a" * 64,
                        artifact={"kind": "facts.v1", "payload": {}},
                    )
                )
            elif operation == "checkpoint_duplicate":
                session.add(checkpoint(44))
                await session.flush()
            elif operation == "revision_update":
                await session.execute(
                    text("UPDATE summary_revisions SET quality='stale' WHERE id=:id"),
                    {"id": uid(10)},
                )
            elif operation == "forbidden_json":
                await session.execute(
                    AgentCheckpoint.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=uid(1),
                        workflow_run_id=uid(8),
                        sequence=2,
                        node="synthetic",
                        input_sha256="a" * 64,
                        artifact={"kind": "facts.v1", "payload": {"api_key": "SYNTHETIC"}},
                    )
                )
            elif operation == "outbox_job":
                from app.models.agent_workflows import WorkflowDispatchOutbox

                await session.execute(
                    WorkflowDispatchOutbox.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=uid(1),
                        workflow_run_id=uid(8),
                        job_id=uid(30),
                        task_name="synthetic",
                        continuation=0,
                        available_at=NOW,
                    )
                )
            elif operation == "cross_evidence":
                from app.models.agent_workflows import SummaryEvidence

                locator = content()["evidence"][0]
                await session.execute(
                    SummaryEvidence.__table__.insert().values(
                        id=uuid4(),
                        tenant_id=uid(101),
                        workflow_run_id=uid(8),
                        revision_id=uid(10),
                        project_id=uid(2),
                        document_id=uid(3),
                        processing_run_id=uid(4),
                        chunk_id=uid(14),
                        evidence_id=uid(13),
                        claim_id=uid(11),
                        chunk_sha256=locator["chunk_sha256"],
                        locator=locator,
                    )
                )
            else:
                await bind(session, tenant=101, user=109)
                await session.execute(
                    text(
                        "UPDATE document_summaries SET active_revision_id=:revision, "
                        "revision_version=1,content_origin='agent_draft' WHERE id=:summary"
                    ),
                    {"revision": uid(10), "summary": uid(20)},
                )
        await session.rollback()


@pytest.mark.asyncio(loop_scope="module")
async def test_runtime_pointer_approval_history_and_stale_updates(postgres):
    _, factory, _, _ = postgres
    async with factory() as session, session.begin():
        repo = WorkflowRepository(session, access(), scope())
        await repo.set_active_revision(uid(20), uid(10), 0)
        await repo.append_approval_event(
            SummaryApprovalEvent(
                id=uid(60),
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                summary_id=uid(20),
                document_id=uid(3),
                revision_id=uid(10),
                reviewer_id=uid(9),
                expected_version=1,
                decision="approved",
                decided_at=NOW,
            )
        )
        summary = (
            await session.execute(select(DocumentSummary).execution_options(populate_existing=True))
        ).scalar_one()
        assert summary.revision_version == 2 and summary.is_approved
        assert (await session.get(SummaryRevision, uid(10))).content == content()
        with pytest.raises(DBAPIError):
            await session.execute(
                text("DELETE FROM summary_approval_events WHERE id=:id"), {"id": uid(60)}
            )
        await session.rollback()


@pytest.mark.asyncio(loop_scope="module")
async def test_populated_agent_schema_refuses_downgrade(postgres):
    owner, _, runtime_name, owner_name = postgres
    async with owner.connect() as connection:
        async with connection.begin():
            with pytest.raises(RuntimeError, match="forward fix"):
                await connection.run_sync(
                    lambda conn: migrate(
                        conn, start=OLD_HEAD, downgrade=True, runtime=runtime_name, owner=owner_name
                    )
                )
            await connection.rollback()


@pytest.mark.asyncio(loop_scope="module")
async def test_transaction_scope_does_not_leak_on_reused_connection(postgres):
    _, factory, _, _ = postgres
    async with factory.kw["bind"].connect() as connection:
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config('app.tenant_id',:value,true)"), {"value": str(uid(1))}
            )
            await connection.execute(
                text("SELECT set_config('app.agent_workflow_run_id',:value,true)"),
                {"value": str(uid(8))},
            )
            assert await connection.scalar(text("SELECT count(*) FROM agent_checkpoints")) == 1
        async with connection.begin():
            assert await connection.scalar(text("SELECT count(*) FROM agent_checkpoints")) == 0


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("kind", ["step", "outbox"])
async def test_postgres_duplicate_step_and_outbox_identities(postgres, kind):
    from app.models.agent_workflows import AgentStepRun, WorkflowDispatchOutbox

    def row():
        if kind == "step":
            return AgentStepRun(
                id=uuid4(),
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                node="synthetic",
                batch=0,
                attempt=1,
                state="pending",
                input_sha256="a" * 64,
                artifact={"kind": "facts.v1", "payload": {}},
                usage={"source": "unknown"},
            )
        return WorkflowDispatchOutbox(
            id=uuid4(),
            tenant_id=uid(1),
            workflow_run_id=uid(8),
            job_id=uid(31),
            task_name="synthetic",
            continuation=0,
            available_at=NOW,
        )

    _, factory, _, _ = postgres
    async with factory() as session, session.begin():
        await bind(session)
        session.add(row())
        await session.flush()
        session.add(row())
        with pytest.raises(DBAPIError):
            await session.flush()
        await session.rollback()
