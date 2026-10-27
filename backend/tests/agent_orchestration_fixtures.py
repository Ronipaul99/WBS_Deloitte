"""Disposable synthetic Step 5 data. Never imports application settings or .env."""

from datetime import timedelta

import pytest_asyncio
from agent_schema_fixtures import (
    NOW,
    access,
    content,
    scope,
    seed_agents,
    seed_legacy,
    uid,
)
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.agent_workflows import WorkflowDispatchOutbox
from app.models.llm import LlmConnection, LlmCredentialVersion, LlmModelProfile
from app.services.agents.contracts import WorkflowInput
from app.services.agents.persistence_types import EndpointPolicyRecord, RunBudget
from app.services.agents.state import Node, NodeResult
from app.services.agents.storage import WorkflowStore


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest_asyncio.fixture(name="execution")
async def execution(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'step05.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await seed_legacy(session)
        await seed_agents(session)
        session.add(
            LlmCredentialVersion(
                id=uid(50),
                tenant_id=uid(1),
                connection_id=uid(5),
                version=1,
                ciphertext=b"synthetic-encrypted-bytes-only",
                nonce=b"n" * 12,
                key_version="test",
            )
        )
        await session.flush()
        await session.execute(
            update(LlmConnection)
            .where(LlmConnection.id == uid(5))
            .values(
                enabled=True,
                active_credential_id=uid(50),
                endpoint_policy=EndpointPolicyRecord(
                    host="gateway.example.invalid", path_prefix="/v1", approval_id=uid(70)
                ).model_dump(mode="json"),
            )
        )
        # SQLite-only availability fixture. Deliberately DOES NOT promote synthetic
        # capabilities to live_worker or establish runtime/provider qualification.
        await session.execute(
            update(LlmModelProfile).where(LlmModelProfile.id == uid(6)).values(enabled=True)
        )
    clock = Clock()
    store = WorkflowStore(sessions, access(), scope(80), now=clock)
    data = content()["workflow"]
    data["workflow_run_id"] = str(uid(80))
    workflow = WorkflowInput.model_validate(data)
    await store.create(
        workflow, uid(21), RunBudget(max_calls=10, max_total_tokens=10000, timeout_seconds=60)
    )
    yield store, clock
    await engine.dispose()


async def delivery(store):
    async with store.sessions.begin() as session:
        return await session.scalar(
            select(WorkflowDispatchOutbox.id)
            .where(
                WorkflowDispatchOutbox.workflow_run_id == store.scope.workflow_run_id,
            )
            .order_by(WorkflowDispatchOutbox.continuation.desc())
            .limit(1)
        )


def next_result(node):
    return NodeResult(
        next_node={
            Node.PIN: Node.INVENTORY,
            Node.INVENTORY: Node.ANALYZE,
            Node.ANALYZE: Node.CONSOLIDATE,
            Node.CONSOLIDATE: Node.WRITE,
            Node.WRITE: Node.VERIFY,
            Node.VERIFY: Node.PUBLISH,
            Node.REPAIR: Node.VERIFY,
            Node.PUBLISH: Node.DONE,
        }[node]
    )


def provider_factory(workflow, budget):
    from llm_adapter_fixtures import adapter, request

    req = request(
        "openai_compatible",
        profile=workflow.profile,
        input_token_budget=4096,
        max_output_tokens=128,
    )
    return adapter(req, budget=budget)[0]
