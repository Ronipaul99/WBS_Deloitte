"""Opt-in Step 6 PG migration/RLS tests. Never reads configured app URLs or .env.

Requires an empty wbs_step06_* database, two roles and the explicit disposable ack.
No schema cleanup against a populated database is performed.
"""

import asyncio
import os

import pytest
import pytest_asyncio
from agent_schema_fixtures import (
    HEAD,
    access,
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

from app.models.agent_workflows import AgentCheckpoint, AgentWorkflowRun
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.storage import WorkflowStore
from migrations.versions.f8c2a6d903b1_add_agent_persistence import PROTECTED_TABLES

NEW_HEAD = "d42a91c7e806"
OWNER = os.getenv("STEP06_POSTGRES_MIGRATION_URL")
RUNTIME = os.getenv("STEP06_POSTGRES_RUNTIME_URL")
ACK = os.getenv("STEP06_POSTGRES_DISPOSABLE_ACK")
pytestmark = pytest.mark.skipif(
    not any((OWNER, RUNTIME, ACK)),
    reason="explicit disposable Step 6 PostgreSQL not provisioned",
)


def checked_urls():
    if not OWNER or not RUNTIME or ACK != "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE":
        raise RuntimeError("complete explicit Step 6 disposable inputs required")
    try:
        owner, runtime = make_url(OWNER), make_url(RUNTIME)
    except Exception:
        raise RuntimeError("invalid disposable database configuration") from None
    if (
        owner.get_backend_name() != "postgresql"
        or runtime.get_backend_name() != "postgresql"
        or not owner.database
        or not owner.database.startswith("wbs_step06_")
        or (owner.host, owner.port, owner.database)
        != (runtime.host, runtime.port, runtime.database)
        or not owner.username
        or not runtime.username
        or owner.username == runtime.username
    ):
        raise RuntimeError("one dedicated wbs_step06_ database and separate roles required")
    return owner.set(drivername="postgresql+asyncpg"), runtime.set(drivername="postgresql+asyncpg")


async def bind(session, *, tenant=1, run=8):
    for key, value in (
        ("app.tenant_id", uid(tenant)),
        ("app.agent_workflow_run_id", uid(run)),
        ("app.agent_user_id", uid(9)),
    ):
        await session.execute(
            text("SELECT set_config(:key,:value,true)"), {"key": key, "value": str(value)}
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres():
    owner_url, runtime_url = checked_urls()
    owner = create_async_engine(owner_url, hide_parameters=True)
    runtime = create_async_engine(runtime_url, hide_parameters=True)
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    try:
        async with owner.begin() as connection:
            assert await connection.scalar(text("SELECT current_database()")) == owner_url.database
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public' "
                        "AND table_type='BASE TABLE'"
                    )
                )
                == 0
            ), "refusing a nonempty database"
            await connection.run_sync(
                lambda conn: migrate(
                    conn, target=HEAD, runtime=runtime_url.username, owner=owner_url.username
                )
            )
            # Historical application fixture privileges only; leave new RLS/grants intact.
            quote = connection.dialect.identifier_preparer.quote
            tables = (
                await connection.scalars(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            ).all()
            for table in tables:
                if table not in PROTECTED_TABLES and table != "alembic_version":
                    await connection.execute(
                        text(
                            f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE "
                            f"{quote(table)} TO {quote(runtime_url.username)}"
                        )
                    )
        async with sessions.begin() as session:
            await bind(session)
            await seed_legacy(session)
            vector = await session.scalar(text("SELECT embedding::text FROM document_chunks"))
        # Step 6 up/down/up with a committed ingestion vector and legacy summary present.
        async with owner.begin() as connection:
            for reverse in (False, True, False):
                await connection.run_sync(
                    lambda conn, reverse=reverse: migrate(
                        conn,
                        target=NEW_HEAD,
                        start=HEAD,
                        runtime=runtime_url.username,
                        owner=owner_url.username,
                        downgrade=reverse,
                    )
                )
        async with sessions.begin() as session:
            await bind(session)
            assert (
                await session.scalar(text("SELECT embedding::text FROM document_chunks")) == vector
            )
            await seed_agents(session)
        yield owner, sessions, runtime_url.username
    finally:
        await runtime.dispose()
        await owner.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_pg_scope_pool_reuse_and_known_checkpoint_identity(postgres):
    _, sessions, _ = postgres
    async with sessions.begin() as session:
        await bind(session)
        assert await session.scalar(select(AgentCheckpoint.id)) == uid(40)
    # Every transaction rebinds scope; known IDs and pooled reuse do not authorize.
    for tenant, run in ((101, 8), (1, 999)):
        async with sessions.begin() as session:
            await bind(session, tenant=tenant, run=run)
            assert await session.scalar(select(AgentCheckpoint.id)) is None
            assert await session.scalar(select(AgentWorkflowRun.id)) is None
    async with sessions.begin() as session:
        # SET LOCAL must not survive transaction/pool reuse.
        assert await session.scalar(select(AgentCheckpoint.id)) is None
    wrong = WorkflowStore(sessions, access(), scope(999))
    with pytest.raises(PermissionError):
        await ScopedCheckpoints(wrong).list()


@pytest.mark.asyncio(loop_scope="module")
async def test_pg_checkpoint_append_only_and_runtime_role(postgres):
    _, sessions, _ = postgres
    async with sessions.begin() as session:
        await bind(session)
        assert not await session.scalar(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
        assert not await session.scalar(text("SELECT has_schema_privilege('public','CREATE')"))
        assert not await session.scalar(
            text("SELECT has_table_privilege('agent_checkpoints','UPDATE')")
        )
        assert not await session.scalar(
            text("SELECT has_table_privilege('agent_checkpoints','DELETE')")
        )
        assert await session.scalar(
            text("SELECT relforcerowsecurity FROM pg_class WHERE oid='agent_checkpoints'::regclass")
        )


@pytest.mark.asyncio(loop_scope="module")
async def test_pg_run_lock_blocks_competing_transaction(postgres):
    _, sessions, _ = postgres
    locked, release = asyncio.Event(), asyncio.Event()

    async def owner():
        async with sessions.begin() as session:
            await bind(session)
            await session.scalar(
                select(AgentWorkflowRun).where(AgentWorkflowRun.id == uid(8)).with_for_update()
            )
            locked.set()
            await release.wait()

    task = asyncio.create_task(owner())
    await asyncio.wait_for(locked.wait(), 5)
    try:
        async with sessions.begin() as session:
            await bind(session)
            await session.execute(text("SET LOCAL lock_timeout='100ms'"))
            with pytest.raises(DBAPIError):
                await session.scalar(
                    select(AgentWorkflowRun).where(AgentWorkflowRun.id == uid(8)).with_for_update()
                )
    finally:
        release.set()
        await task


@pytest.mark.asyncio(loop_scope="module")
async def test_document_free_management_rls_and_runtime_grants(postgres):
    from llm_security_fixtures import endpoint, keys
    from test_llm_management import submitted

    from app.models.llm import LlmConnectionTest
    from app.services.llm.management import ModelManagement

    _, sessions, _ = postgres
    endpoints, _ = endpoint()
    from agent_schema_fixtures import NOW

    manager = ModelManagement(
        sessions, access(), endpoints, keys(), tests_enabled=True, now=lambda: NOW
    )
    c, p, row = await submitted(manager)
    async with sessions.begin() as session:
        await bind(session)
        assert await session.scalar(
            select(LlmConnectionTest.id).where(
                LlmConnectionTest.id == __import__("uuid").UUID(row["id"])
            )
        )
        assert not await session.scalar(
            text("SELECT has_table_privilege('llm_connection_tests','DELETE')")
        )
    async with sessions.begin() as session:
        await bind(session, tenant=101)
        assert await session.scalar(select(LlmConnectionTest.id)) is None
