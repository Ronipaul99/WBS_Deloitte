"""Opt-in Step 9 serialization/RLS checks. Never imports settings or application URLs."""

import os

import pytest
import pytest_asyncio
from agent_schema_fixtures import (
    NOW,
    access,
    content,
    migrate,
    scope,
    seed_agents,
    seed_legacy,
    uid,
)
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.agent_workflows import AgentCheckpoint, AgentStepRun
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.state import (
    CompletedNode,
    Cursor,
    Node,
    NodeResult,
    OrchestrationArtifact,
    advance,
    node_input_hash,
)
from app.services.agents.storage import WorkflowStore
from migrations.versions.f8c2a6d903b1_add_agent_persistence import PROTECTED_TABLES

NAMES = (
    "STEP09_POSTGRES_MIGRATION_URL",
    "STEP09_POSTGRES_RUNTIME_URL",
    "STEP09_POSTGRES_DISPOSABLE_ACK",
)
pytestmark = pytest.mark.skipif(
    not any(os.getenv(n) for n in NAMES),
    reason="explicit disposable Step 9 PostgreSQL not provisioned",
)


def checked_urls():
    owner, runtime, ack = (os.getenv(n) for n in NAMES)
    if not owner or not runtime or ack != "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE":
        raise RuntimeError("complete explicit Step 9 disposable inputs required")
    try:
        owner, runtime = make_url(owner), make_url(runtime)
    except Exception:
        raise RuntimeError("invalid disposable configuration") from None
    if (
        owner.get_backend_name() != "postgresql"
        or runtime.get_backend_name() != "postgresql"
        or not owner.database
        or not owner.database.startswith("wbs_step09_")
        or (owner.host, owner.port, owner.database)
        != (runtime.host, runtime.port, runtime.database)
        or not owner.username
        or not runtime.username
        or owner.username == runtime.username
    ):
        raise RuntimeError("dedicated wbs_step09_ database and separate roles required")
    return owner.set(drivername="postgresql+asyncpg"), runtime.set(drivername="postgresql+asyncpg")


async def bind(session, tenant=1):
    for key, value in (
        ("app.tenant_id", uid(tenant)),
        ("app.agent_user_id", uid(9)),
        ("app.agent_workflow_run_id", uid(8)),
    ):
        await session.execute(
            text("SELECT set_config(:key,:value,true)"), {"key": key, "value": str(value)}
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres():
    owner_url, runtime_url = checked_urls()
    owner = create_async_engine(owner_url, hide_parameters=True)
    runtime = create_async_engine(runtime_url, hide_parameters=True, pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    try:
        async with owner.begin() as c:
            assert await c.scalar(text("SELECT current_database()")) == owner_url.database
            assert (
                await c.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_type='BASE TABLE'"
                    )
                )
                == 0
            ), "refusing nonempty disposable database"
            role = (
                await c.execute(
                    text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=:r"),
                    {"r": runtime_url.username},
                )
            ).one()
            assert not any(role)
            assert not await c.scalar(
                text("SELECT pg_has_role(:runtime,:owner,'MEMBER')"),
                {"runtime": runtime_url.username, "owner": owner_url.username},
            )
            await c.run_sync(
                lambda conn: migrate(
                    conn,
                    target="e53c7a19b402",
                    runtime=runtime_url.username,
                    owner=owner_url.username,
                )
            )
            quote = c.dialect.identifier_preparer.quote
            for table in await c.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ):
                if table not in PROTECTED_TABLES and table != "alembic_version":
                    await c.execute(
                        text(
                            f"GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE {quote(table)} "
                            f"TO {quote(runtime_url.username)}"
                        )
                    )
        async with sessions.begin() as s:
            assert not await s.scalar(
                text("SELECT has_schema_privilege(current_user,'public','CREATE')")
            )
            await bind(s)
            await seed_legacy(s)
            await seed_agents(s)
        yield sessions
    finally:
        await runtime.dispose()
        await owner.dispose()


def writer_artifact():
    # Storage contract fixture, not an executed/qualified worker or provider result.
    from dataclasses import replace

    from writer_fixtures import Guard, prepared

    from app.services.agents.budgeting import ContextBudget
    from app.services.agents.contracts import WorkflowInput
    from app.services.agents.nodes.writer import SummaryWriter
    from app.services.agents.nodes.writer_prompt import INSTRUCTIONS
    from app.services.agents.writer_assembly import assemble_draft
    from app.services.agents.writer_types import WriterArtifact

    fixture = prepared(count=0)
    snapshot = replace(
        fixture.snapshot, workflow=WorkflowInput.model_validate(content()["workflow"])
    )
    writer = SummaryWriter(ContextBudget(snapshot.workflow.profile, INSTRUCTIONS, (), 128), Guard())
    binding = writer.binding(snapshot, ())
    _, draft = assemble_draft(snapshot, (), binding, writer.policy)
    result = NodeResult(
        next_node=Node.VERIFY, artifact=WriterArtifact(kind="writer_draft.v1", payload=draft)
    )
    before = Cursor(node=Node.WRITE, sequence=1)
    completed = CompletedNode(
        workflow_run_id=uid(8),
        before=before,
        after=advance(before, result),
        input_sha256=node_input_hash(content()["workflow"], before),
        result=result,
    )
    return OrchestrationArtifact(payload=completed).model_dump(mode="json")


@pytest.mark.asyncio(loop_scope="module")
async def test_writer_checkpoint_transaction_rls_and_pool_reuse(postgres):
    data = writer_artifact()

    def rows():
        common = dict(
            tenant_id=uid(1),
            workflow_run_id=uid(8),
            node="write",
            input_sha256=data["payload"]["input_sha256"],
            artifact=data,
        )
        return (
            AgentStepRun(
                id=uid(900),
                batch=1,
                attempt=1,
                state="completed",
                completed_at=NOW,
                usage={"source": "unknown"},
                **common,
            ),
            AgentCheckpoint(id=uid(901), sequence=2, **common),
        )

    with pytest.raises(RuntimeError, match="synthetic writer rollback"):
        async with postgres.begin() as session:
            await bind(session)
            session.add_all(rows())
            await session.flush()
            raise RuntimeError("synthetic writer rollback")
    async with postgres.begin() as session:
        await bind(session)
        assert await session.get(AgentCheckpoint, uid(901)) is None
        session.add_all(rows())
    checkpoints = ScopedCheckpoints(WorkflowStore(postgres, access(), scope()))
    restored = await checkpoints.get(uid(901))
    assert restored.result.artifact.payload.state == "intermediate_unverified"
    async with postgres.begin() as session:
        await bind(session, tenant=101)
        assert await session.get(AgentCheckpoint, uid(901)) is None
    async with postgres.begin() as session:
        assert await session.scalar(select(AgentCheckpoint.id)) is None
    assert len(await checkpoints.list(limit=1)) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_writer_checkpoint_cannot_be_mutated(postgres):
    with pytest.raises(DBAPIError):
        async with postgres.begin() as session:
            await bind(session)
            await session.execute(
                update(AgentCheckpoint)
                .where(AgentCheckpoint.id == uid(901))
                .values(input_sha256="f" * 64)
            )
