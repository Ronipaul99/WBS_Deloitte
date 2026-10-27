"""Synthetic SQL recovery. SQLite does not qualify PostgreSQL locking or RLS."""

from types import SimpleNamespace

import pytest
from agent_evidence_fixtures import QueryProvider, canonical_source
from agent_orchestration_fixtures import delivery
from agent_orchestration_fixtures import execution as execution_fixture  # noqa: F401
from agent_schema_fixtures import uid
from analyst_fixtures import no_facts
from sqlalchemy import select

from app.models.agent_workflows import AgentCheckpoint, AgentStepRun, WorkflowDispatchOutbox
from app.services.agents.analyst_types import AnalystArtifact, AnalystBatch, AnalystPolicy
from app.services.agents.budgeting import ContextBudget, build_reading_plan
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.evidence import repository_for_workflow
from app.services.agents.evidence_storage import EvidenceArtifactStore
from app.services.agents.evidence_types import BatchCompletion, EvidenceError, digest
from app.services.agents.fact_register import normalize_extraction
from app.services.agents.inventory import build_inventory
from app.services.agents.nodes.analyst import TOOL_NAMES
from app.services.agents.nodes.analyst_nodes import build_analyst_nodes
from app.services.agents.nodes.analyst_prompt import INSTRUCTIONS
from app.services.agents.repository import WorkflowRepository
from app.services.agents.state import Node, NodeResult
from app.services.agents.storage import FencedAttempt
from app.services.llm.protocol_support import tool_schemas


async def ready(execution, *, policy=None):
    store, clock = execution
    await canonical_source(store.sessions)
    repository = await repository_for_workflow(store)
    inventory = await build_inventory(repository)
    claim = await store.claim(await delivery(store))
    await EvidenceArtifactStore(store, claim.fence).save_inventory(inventory)
    budget = ContextBudget(
        claim.workflow.profile, INSTRUCTIONS, tuple(tool_schemas(TOOL_NAMES)), 128
    )
    plan = await build_reading_plan(repository, inventory, budget)
    await store.complete(claim, NodeResult(next_node=Node.INVENTORY))
    claim = await store.claim(await delivery(store))
    await store.complete(claim, NodeResult(next_node=Node.ANALYZE))
    claim = await store.claim(await delivery(store))
    nodes = await build_analyst_nodes(
        store,
        claim,
        plan,
        budget,
        QueryProvider(),
        policy=policy or AnalystPolicy(max_gap_rounds=0),
    )
    return store, clock, claim, nodes, budget


def context(store, claim):
    return SimpleNamespace(
        workflow=claim.workflow,
        cursor=claim.cursor,
        checkpoints=ScopedCheckpoints(store),
        provider=None,
    )


async def batch_result(nodes, claim):
    batch = nodes.plan.batches[claim.cursor.batch]
    binding = nodes.analyst.binding(claim.workflow, nodes.plan)
    extraction = await normalize_extraction(
        no_facts(), nodes.analyst.evidence, set(), binding=binding, origin=digest(batch)
    )
    receipt = BatchCompletion(
        inventory_sha256=batch.inventory_sha256,
        batch_sha256=digest(batch),
        primary_chunk_ids=batch.primary_chunk_ids,
        artifact_sha256=digest(extraction),
    )
    return NodeResult(
        next_node=Node.ANALYZE if batch.index + 1 < len(nodes.plan.batches) else Node.CONSOLIDATE,
        artifact=AnalystArtifact(
            kind="analyst_batch.v1",
            payload=AnalystBatch(batch=batch, extraction=extraction, completion=receipt),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_kind", [AgentCheckpoint, WorkflowDispatchOutbox])
async def test_atomic_artifact_receipt_continuation_and_replay(execution, monkeypatch, crash_kind):
    store, _, claim, nodes, budget = await ready(execution)
    result = await batch_result(nodes, claim)
    original = WorkflowRepository.add

    async def crash(self, row):
        if isinstance(row, crash_kind):
            await self.session.flush()
            raise RuntimeError("synthetic commit failure")
        return await original(self, row)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "add", crash)
        with pytest.raises(RuntimeError, match="synthetic commit"):
            await store.complete(claim, result)
    history = await ScopedCheckpoints(store).list()
    assert not any(
        h.result.artifact and h.result.artifact.kind == "analyst_batch.v1" for h in history
    )
    assert (await store.check(claim.fence)).cursor == claim.cursor
    await store.complete(claim, result)
    with pytest.raises(FencedAttempt):
        await store.complete(claim, result)
    claim = await store.claim(await delivery(store))
    rebuilt = await build_analyst_nodes(
        store, claim, nodes.plan, budget, QueryProvider(), policy=AnalystPolicy(max_gap_rounds=0)
    )
    _, artifacts, tracker = await rebuilt.history(context(store, claim))
    assert len(artifacts) == 1
    assert set(nodes.plan.batches[0].primary_chunk_ids) == set(tracker.report().processed_chunk_ids)
    # New node instances continue from SQL, never extract already completed batches.
    assert claim.cursor.batch == 1
    async with store.sessions.begin() as session:
        rows = (
            await session.scalars(
                select(AgentStepRun).where(
                    AgentStepRun.workflow_run_id == uid(80), AgentStepRun.node == "analyze"
                )
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_every_batch_then_register_seal_and_incompatible_replay(execution):
    store, _, claim, nodes, budget = await ready(execution)
    while claim.cursor.node == Node.ANALYZE:
        await store.complete(claim, await batch_result(nodes, claim))
        claim = await store.claim(await delivery(store))
        nodes = await build_analyst_nodes(
            store,
            claim,
            nodes.plan,
            budget,
            QueryProvider(),
            policy=AnalystPolicy(max_gap_rounds=0),
        )
    _, _, tracker = await nodes.history(context(store, claim))
    assert tracker.report().complete
    result = await nodes.consolidate(context(store, claim))
    assert result.artifact.kind == "fact_register.v1"  # explicit no-facts document, no fake claims
    assert result.artifact.payload.reading_complete
    assert all(g.state == "unknown_not_searched" for g in result.artifact.payload.gaps)
    assert result.next_node == Node.WRITE
    changed = await build_analyst_nodes(
        store, claim, nodes.plan, budget, QueryProvider(), policy=AnalystPolicy(max_gap_rounds=1)
    )
    with pytest.raises(EvidenceError, match="replay_incompatible"):
        await changed.history(context(store, claim))
    await store.complete(claim, result)
    history = await ScopedCheckpoints(store).list()
    assert history[0].after.node == Node.WRITE


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "expire"])
async def test_late_analyst_receipt_denied(execution, change):
    store, clock, claim, nodes, _ = await ready(execution)
    result = await batch_result(nodes, claim)
    if change == "cancel":
        await store.cancel()
    else:
        clock.advance(61)
    with pytest.raises(FencedAttempt):
        await store.complete(claim, result)
    assert not any(
        h.result.artifact and h.result.artifact.kind == "analyst_batch.v1"
        for h in await ScopedCheckpoints(store).list()
    )


@pytest.mark.asyncio
async def test_gap_attempt_and_allowance_survive_continuation(execution):
    policy = AnalystPolicy(max_gap_rounds=1)
    store, _, claim, nodes, budget = await ready(execution, policy=policy)
    while claim.cursor.node == Node.ANALYZE:
        await store.complete(claim, await batch_result(nodes, claim))
        claim = await store.claim(await delivery(store))
        nodes = await build_analyst_nodes(
            store, claim, nodes.plan, budget, QueryProvider(), policy=policy
        )
    # SQLite vector search deliberately fails closed. No provider call is attempted.
    outcome = await nodes.consolidate(context(store, claim))
    assert outcome.artifact.kind == "analyst_gap.v1"
    assert outcome.artifact.payload.outcome == "blocked"
    assert (await store.check(claim.fence)).evidence_tools.calls == 1
    await store.complete(claim, outcome)
    claim = await store.claim(await delivery(store))
    resumed = await build_analyst_nodes(
        store, claim, nodes.plan, budget, QueryProvider(), policy=policy
    )
    seal = await resumed.consolidate(context(store, claim))
    assert seal.artifact.kind == "fact_register.v1"
    assert (await store.check(claim.fence)).evidence_tools.calls == 1
    assert sum(g.state == "search_unavailable" for g in seal.artifact.payload.gaps) == 1
