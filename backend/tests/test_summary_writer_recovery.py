"""Step 9 SQL recovery over disposable SQLite. Not PostgreSQL qualification."""

from types import SimpleNamespace

import pytest
from agent_evidence_fixtures import QueryProvider
from agent_orchestration_fixtures import delivery
from agent_orchestration_fixtures import execution as execution_fixture  # noqa: F401
from agent_schema_fixtures import access, scope, uid
from analyst_fixtures import extraction
from llm_adapter_fixtures import adapter, reply, request, wire
from sqlalchemy import select, update
from test_evidence_analyst_recovery import batch_result, context, ready
from writer_fixtures import output

from app.models.agent_workflows import (
    AgentCheckpoint,
    AgentWorkflowRun,
    SummaryRevision,
    WorkflowDispatchOutbox,
)
from app.models.domain import Document, DocumentSummary, TenantMembership
from app.models.llm import LlmConnection
from app.services.agents.analyst_types import AnalystArtifact, AnalystBatch, AnalystPolicy
from app.services.agents.budgeting import ContextBudget
from app.services.agents.budgets import DurableCallBudget
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.evidence_types import BatchCompletion, EvidenceError, digest
from app.services.agents.fact_register import normalize_extraction
from app.services.agents.graph import OrchestrationUnavailable, WorkflowGraph
from app.services.agents.nodes.analyst_nodes import build_analyst_nodes
from app.services.agents.nodes.writer_nodes import build_writer_node
from app.services.agents.nodes.writer_prompt import INSTRUCTIONS
from app.services.agents.repository import WorkflowRepository
from app.services.agents.state import Node, NodeResult
from app.services.agents.storage import FencedAttempt, InactiveWorkflow, WorkflowStore
from app.services.agents.writer_register import restore_writer_register
from app.services.agents.writer_types import WriterPolicy


async def writer_ready(execution):
    store, clock, claim, analyst, analyst_budget = await ready(execution)
    while claim.cursor.node == Node.ANALYZE:
        result = await batch_result(analyst, claim)
        if claim.cursor.batch == 0:
            batch = result.artifact.payload.batch
            (chunk,) = await analyst.analyst.evidence.chunks((uid(14),))
            record = await normalize_extraction(
                extraction(chunk),
                analyst.analyst.evidence,
                set(batch.primary_chunk_ids),
                binding=analyst.analyst.binding(claim.workflow, analyst.plan),
                origin=digest(batch),
            )
            result = NodeResult(
                next_node=result.next_node,
                artifact=AnalystArtifact(
                    kind="analyst_batch.v1",
                    payload=AnalystBatch(
                        batch=batch,
                        extraction=record,
                        completion=BatchCompletion(
                            inventory_sha256=batch.inventory_sha256,
                            batch_sha256=digest(batch),
                            primary_chunk_ids=batch.primary_chunk_ids,
                            artifact_sha256=digest(record),
                        ),
                    ),
                ),
            )
        await store.complete(claim, result)
        claim = await store.claim(await delivery(store))
        analyst = await build_analyst_nodes(
            store,
            claim,
            analyst.plan,
            analyst_budget,
            QueryProvider(),
            policy=AnalystPolicy(max_gap_rounds=0),
        )
    while claim.cursor.node == Node.CONSOLIDATE:
        await store.complete(claim, await analyst.consolidate(context(store, claim)))
        claim = await store.claim(await delivery(store))
        analyst = await build_analyst_nodes(
            store,
            claim,
            analyst.plan,
            analyst_budget,
            QueryProvider(),
            policy=AnalystPolicy(max_gap_rounds=0),
        )
    budget = ContextBudget(claim.workflow.profile, INSTRUCTIONS, (), 128)
    node = await build_writer_node(store, claim, analyst.plan, budget)
    req = request(
        "openai_compatible",
        schema="writer_fragment.v1",
        profile=claim.workflow.profile,
        input_token_budget=4096,
        max_output_tokens=128,
    )
    client, backend, _ = adapter(req, budget=DurableCallBudget(store, claim))
    ctx = context(store, claim)
    ctx.provider = client
    snapshot, _ = await restore_writer_register(
        ctx, node.evidence, node.plan, node.writer.guard, node.writer.policy
    )
    partitions = node.writer.partitions(snapshot, client)
    backend.attempts = tuple(
        wire(reply("openai_compatible", output(snapshot, p).model_dump(mode="json")))
        for p in partitions
    )
    return SimpleNamespace(
        store=store,
        clock=clock,
        claim=claim,
        node=node,
        budget=budget,
        context=ctx,
        provider=client,
        backend=backend,
        snapshot=snapshot,
    )


async def reserved_calls(store):
    async with store.sessions.begin() as session:
        run = await session.get(AgentWorkflowRun, store.scope.workflow_run_id)
        return run.execution["calls"]


@pytest.mark.asyncio
async def test_sql_fragments_manifests_and_draft_resume_without_repeating_calls(execution):
    p = await writer_ready(execution)
    result = await p.node.step(p.context)
    assert result.artifact.kind == "writer_fragment.v1" and len(p.backend.calls) == 1
    await p.store.complete(p.claim, result)
    with pytest.raises(FencedAttempt):
        await p.store.complete(p.claim, result)
    call_count = await reserved_calls(p.store)
    while True:
        claim = await p.store.claim(await delivery(p.store))
        node = await build_writer_node(p.store, claim, p.node.plan, p.budget)
        ctx = context(p.store, claim)
        ctx.provider = p.provider  # same synthetic adapter; no further outbound call is permitted
        result = await node.step(ctx)
        await p.store.complete(claim, result)
        if result.next_node == Node.VERIFY:
            break
    assert len(p.backend.calls) == call_count == 1
    assert result.artifact.kind == "writer_draft.v1"
    assert result.artifact.payload.state == "intermediate_unverified"
    async with p.store.sessions.begin() as session:
        assert (await session.get(DocumentSummary, uid(20))).summary_text == "Preserved legacy text"
        assert (
            await session.scalar(
                select(SummaryRevision.id).where(SummaryRevision.workflow_run_id == uid(80))
            )
            is None
        )
    with pytest.raises(OrchestrationUnavailable):
        WorkflowGraph(node.handlers())


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_kind", [AgentCheckpoint, WorkflowDispatchOutbox])
async def test_atomic_writer_checkpoint_and_continuation_rollback(
    execution, monkeypatch, crash_kind
):
    p = await writer_ready(execution)
    result = await p.node.step(p.context)
    original = WorkflowRepository.add

    async def crash(self, row):
        if isinstance(row, crash_kind):
            await self.session.flush()
            raise RuntimeError("synthetic writer commit failure")
        return await original(self, row)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "add", crash)
        with pytest.raises(RuntimeError, match="synthetic writer"):
            await p.store.complete(p.claim, result)
    assert not any(
        c.result.artifact and c.result.artifact.kind == "writer_fragment.v1"
        for c in await ScopedCheckpoints(p.store).list()
    )
    # Safely retry only the failed SQL commit while its validated result is still available.
    await p.store.complete(p.claim, result)
    assert len(p.backend.calls) == 1
    assert await reserved_calls(p.store) == 1


@pytest.mark.asyncio
async def test_worker_loss_after_submission_keeps_paid_allowance_and_blocks_replay(execution):
    p = await writer_ready(execution)
    await p.node.step(p.context)  # provider returned, worker dies before completion
    before = await p.store.check(p.claim.fence)
    p.clock.advance(61)
    assert await p.store.claim(await delivery(p.store)) is None
    async with p.store.sessions.begin() as session:
        run = await session.get(AgentWorkflowRun, uid(80))
        assert run.error_code == "agent_ambiguous_attempt"
        assert run.execution["calls"] == before.calls == 1
        assert run.execution["reserved_tokens"] == before.reserved_tokens > 0
    assert len(p.backend.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "expire", "delete", "disable", "membership"])
async def test_late_writer_results_cannot_commit(execution, change):
    p = await writer_ready(execution)
    result = await p.node.step(p.context)
    if change == "cancel":
        await p.store.cancel()
    elif change == "expire":
        p.clock.advance(61)
    else:
        async with p.store.sessions.begin() as session:
            if change == "delete":
                await session.execute(
                    update(Document)
                    .where(Document.id == uid(3))
                    .values(
                        lifecycle_status="DELETING",
                        deletion_requested_at=p.clock(),
                        vectors_hidden_at=p.clock(),
                    )
                )
            elif change == "disable":
                await session.execute(
                    update(LlmConnection).where(LlmConnection.id == uid(5)).values(enabled=False)
                )
            else:
                await session.execute(
                    update(TenantMembership)
                    .where(TenantMembership.user_id == uid(9))
                    .values(role="VIEWER")
                )
    with pytest.raises((FencedAttempt, InactiveWorkflow, PermissionError, ValueError)):
        await p.store.complete(p.claim, result)


@pytest.mark.asyncio
async def test_changed_writer_policy_and_foreign_checkpoint_access_are_rejected(execution):
    p = await writer_ready(execution)
    await p.store.complete(p.claim, await p.node.step(p.context))
    claim = await p.store.claim(await delivery(p.store))
    node = await build_writer_node(
        p.store, claim, p.node.plan, p.budget, policy=WriterPolicy(fragment_entries=1)
    )
    ctx = context(p.store, claim)
    ctx.provider = p.provider
    with pytest.raises(EvidenceError, match="replay_incompatible"):
        await node.step(ctx)
    foreign = WorkflowStore(p.store.sessions, access(109, 101), scope(80), now=p.clock)
    with pytest.raises(PermissionError):
        await ScopedCheckpoints(foreign).list()
    assert len(p.backend.calls) == 1
