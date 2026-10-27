"""Opt-in Step 7 PG migration/RLS tests. Never reads configured app URLs or .env.

Requires an empty wbs_step07_* database, two roles and the explicit disposable ack.
No schema cleanup against a populated database is performed.
"""

import os

import pytest
import pytest_asyncio
from agent_schema_fixtures import (
    HEAD,
    access,
    migrate,
    seed_agents,
    seed_legacy,
    uid,
)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from migrations.versions.f8c2a6d903b1_add_agent_persistence import PROTECTED_TABLES

NEW_HEAD = "e53c7a19b402"
OWNER = os.getenv("STEP07_POSTGRES_MIGRATION_URL")
RUNTIME = os.getenv("STEP07_POSTGRES_RUNTIME_URL")
ACK = os.getenv("STEP07_POSTGRES_DISPOSABLE_ACK")
pytestmark = pytest.mark.skipif(
    not any((OWNER, RUNTIME, ACK)),
    reason="explicit disposable Step 7 PostgreSQL not provisioned",
)


def checked_urls():
    if not OWNER or not RUNTIME or ACK != "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE":
        raise RuntimeError("complete explicit Step 7 disposable inputs required")
    try:
        owner, runtime = make_url(OWNER), make_url(RUNTIME)
    except Exception:
        raise RuntimeError("invalid disposable database configuration") from None
    if (
        owner.get_backend_name() != "postgresql"
        or runtime.get_backend_name() != "postgresql"
        or not owner.database
        or not owner.database.startswith("wbs_step07_")
        or (owner.host, owner.port, owner.database)
        != (runtime.host, runtime.port, runtime.database)
        or not owner.username
        or not runtime.username
        or owner.username == runtime.username
    ):
        raise RuntimeError("one dedicated wbs_step07_ database and separate roles required")
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
        # Step 7 up/down/up with a committed ingestion vector and legacy summary present.
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
async def test_pinned_pgvector_scope_lexical_and_pool_reuse(postgres):
    from agent_evidence_fixtures import QueryProvider, canonical_source, source

    from app.models.domain import DocumentChunk
    from app.services.agents.evidence import EvidenceAccess, PinnedRetriever
    from app.services.agents.evidence_types import EvidenceError
    from app.services.agents.inventory import build_inventory
    from app.services.ingestion.pinned import PinnedEvidenceRepository

    _, sessions, _ = postgres
    # Explicit tenant context for modifying only the synthetic fixture's source.
    async with sessions.begin() as session:
        await bind(session)
        # canonical_source owns its transaction; seed under the migration fixture
        # below using a session factory that binds each transaction.
    # The helper uses ordinary sessions; a dedicated scoped factory supplies SET LOCAL.
    from contextlib import asynccontextmanager

    from app.services.agents.scoped_storage import StorageAccess

    class ScopedSessions:
        @asynccontextmanager
        async def begin(self):
            async with sessions.begin() as s:
                await bind(s)
                yield s

    await canonical_source(ScopedSessions())
    repository = PinnedEvidenceRepository(sessions, access(), source())
    inventory = await build_inventory(repository)
    evidence = EvidenceAccess(repository, inventory)
    hits = await PinnedRetriever(evidence, QueryProvider()).search("panels installation", limit=5)
    assert hits and all(h.processing_run_id == uid(4) for h in hits)
    semantic, lexical = await repository.candidates(
        inventory.manifest.pin, QueryProvider().embed_query("x"), ("installation",)
    )
    assert semantic and any("installation" in r["content"] for r in lexical)
    with pytest.raises(EvidenceError):
        await PinnedEvidenceRepository(
            sessions,
            StorageAccess(uid(101), uid(109)),
            source().model_copy(update={"tenant_id": uid(101)}),
        ).pin()
    async with sessions.begin() as session:
        await bind(session, tenant=101)
        assert (
            await session.scalar(select(DocumentChunk.id).where(DocumentChunk.id == uid(14)))
            is None
        )
    assert await repository.pin() == inventory.manifest.pin


@pytest.mark.asyncio(loop_scope="module")
async def test_postgres_evidence_artifact_allowlist_and_immutability(postgres):
    from uuid import uuid4

    from agent_evidence_fixtures import source
    from agent_schema_fixtures import NOW

    from app.models.agent_workflows import AgentStepRun
    from app.services.agents.evidence_types import EvidenceArtifact, InventoryManifest, digest
    from app.services.ingestion.pinned import PinnedEvidenceRepository

    _, sessions, _ = postgres
    pin = await PinnedEvidenceRepository(sessions, access(), source()).pin()
    manifest = InventoryManifest(
        pin=pin, root_sha256=digest([]), page_count=0, chunk_count=pin.chunk_count
    )
    # Constraint/immutability test only. Not a valid sealed inventory for application use.
    identity = uuid4()
    async with sessions.begin() as session:
        await bind(session)
        session.add(
            AgentStepRun(
                id=identity,
                tenant_id=uid(1),
                workflow_run_id=uid(8),
                node="evidence:inventory_manifest.v1",
                batch=0,
                attempt=1,
                input_sha256="a" * 64,
                state="completed",
                artifact=EvidenceArtifact(
                    kind="inventory_manifest.v1", payload=manifest
                ).model_dump(mode="json"),
                usage={"source": "unknown", "input_tokens": None, "output_tokens": None},
                completed_at=NOW,
            )
        )
    from sqlalchemy import update

    with pytest.raises(DBAPIError):
        async with sessions.begin() as session:
            await bind(session)
            await session.execute(
                update(AgentStepRun)
                .where(AgentStepRun.id == identity)
                .values(input_sha256="b" * 64)
            )


@pytest.mark.asyncio(loop_scope="module")
async def test_postgres_tool_allowance_cannot_reset(postgres):
    from agent_schema_fixtures import NOW
    from sqlalchemy import update

    from app.models.agent_workflows import AgentWorkflowRun
    from app.services.agents.evidence_types import ToolPolicy
    from app.services.agents.persistence_types import EndpointPolicyRecord
    from app.services.agents.state import ExecutionLedger
    from app.services.agents.tool_budget import reserve_usage

    _, sessions, _ = postgres
    usage = reserve_usage(None, "a" * 64, ToolPolicy(), "b" * 64)
    execution = ExecutionLedger(
        deadline=NOW,
        endpoint=EndpointPolicyRecord(host="example.invalid", path_prefix="/v1"),
        evidence_tools=usage,
    ).model_dump(mode="json")
    async with sessions.begin() as session:
        await bind(session)
        await session.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == uid(8))
            .values(execution=execution)
        )
    smaller = {**execution, "evidence_tools": None}
    with pytest.raises(DBAPIError):
        async with sessions.begin() as session:
            await bind(session)
            await session.execute(
                update(AgentWorkflowRun)
                .where(AgentWorkflowRun.id == uid(8))
                .values(execution=smaller)
            )
