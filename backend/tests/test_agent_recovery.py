"""Step 5 synthetic recovery; run with --noconftest. SQLite is not RLS evidence."""

import asyncio
from dataclasses import replace

import pytest
from agent_orchestration_fixtures import delivery, next_result, provider_factory
from agent_orchestration_fixtures import execution as execution_fixture  # noqa: F401
from agent_schema_fixtures import access, scope, uid
from pydantic import ValidationError
from sqlalchemy import select, update

from app.models.agent_workflows import AgentCheckpoint, AgentStepRun, AgentWorkflowRun
from app.models.domain import Document, DocumentSummary, TenantMembership
from app.models.llm import LlmConnection
from app.services.agents.budgets import DurableCallBudget
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.graph import (
    OrchestrationUnavailable,
    WorkflowGraph,
    orchestration_readiness,
)
from app.services.agents.runner import WorkflowRunner
from app.services.agents.state import Cursor, Node, NodeResult, advance
from app.services.agents.storage import FencedAttempt, InactiveWorkflow, WorkflowStore
from app.services.llm.adapter_types import AttemptRecord, BudgetExhausted


@pytest.mark.parametrize("node", list(Node))
def test_transition_bounds_and_terminal_nodes(node):
    cursor = Cursor(node=node)
    if node in {Node.DONE, Node.BLOCKED}:
        with pytest.raises(ValueError):
            advance(cursor, NodeResult(next_node=Node.PIN))
    else:
        assert advance(cursor, next_result(node)).sequence == 1
        with pytest.raises(ValueError):
            advance(cursor, NodeResult(next_node=Node.PIN))


def test_second_graph_repair_and_versions_rejected():
    with pytest.raises(ValueError):
        advance(Cursor(node=Node.VERIFY, graph_repairs=1), NodeResult(next_node=Node.REPAIR))
    with pytest.raises(ValidationError):
        Cursor(version="unknown")
    with pytest.raises(ValidationError):
        advance(Cursor(sequence=10000), NodeResult(next_node=Node.INVENTORY))
    with pytest.raises(OrchestrationUnavailable):
        WorkflowGraph({})
    settings = type("Settings", (), {"agentic_summary_enabled": False})()
    assert orchestration_readiness(settings)["code"] == "agentic_summary_disabled"


@pytest.mark.asyncio
async def test_fence_duplicate_and_completed_checkpoint_reuse(execution):
    store, clock = execution
    first_delivery = await delivery(store)
    first = await store.claim(first_delivery, lease_seconds=1)
    assert await store.claim(first_delivery) is None
    clock.advance(2)
    newer = await store.claim(first_delivery)
    with pytest.raises(FencedAttempt):
        await store.complete(first, next_result(Node.PIN))
    await store.complete(newer, next_result(Node.PIN))
    assert await store.claim(first_delivery) is None
    resumed = await store.claim(await delivery(store))
    assert resumed.cursor.node == Node.INVENTORY
    history = await ScopedCheckpoints(store).list()
    assert len(history) == 1 and history[0].after == resumed.cursor
    async with store.sessions.begin() as session:
        rows = (
            await session.scalars(
                select(AgentCheckpoint).where(AgentCheckpoint.workflow_run_id == uid(80))
            )
        ).all()
        checkpoint_id = rows[0].id
    assert (await ScopedCheckpoints(store).get(checkpoint_id)).after == resumed.cursor


@pytest.mark.asyncio
async def test_atomic_completion_failure_rolls_back_and_can_recover(execution):
    store, _ = execution
    claim = await store.claim(await delivery(store))
    # Use a final-node cursor only in this synthetic fault fixture.
    async with store.sessions.begin() as session:
        run = await session.get(AgentWorkflowRun, uid(80))
        ledger = dict(run.execution)
        ledger["cursor"] = Cursor(node=Node.PUBLISH).model_dump(mode="json")
        run.execution = ledger
    claim = replace(claim, cursor=Cursor(node=Node.PUBLISH))

    async def crash(session, repo, result):
        summary = await session.get(DocumentSummary, uid(20))
        summary.summary_text = "must roll back"
        await session.flush()
        raise RuntimeError("synthetic commit boundary crash")

    with pytest.raises(RuntimeError):
        await store.complete(claim, next_result(Node.PUBLISH), publisher=crash)
    async with store.sessions.begin() as session:
        assert (await session.get(DocumentSummary, uid(20))).summary_text == "Preserved legacy text"
        assert not (
            await session.scalars(
                select(AgentStepRun).where(AgentStepRun.workflow_run_id == uid(80))
            )
        ).all()
    assert (await store.check(claim.fence)).cursor.node == Node.PUBLISH


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "cancel", "disable", "endpoint", "membership"])
async def test_late_completion_denied_after_lifecycle_change(execution, change):
    store, _ = execution
    claim = await store.claim(await delivery(store))
    if change == "cancel":
        await store.cancel()
    else:
        async with store.sessions.begin() as session:
            if change == "delete":
                await session.execute(
                    update(Document)
                    .where(Document.id == uid(3))
                    .values(
                        lifecycle_status="DELETING",
                        deletion_requested_at=store.now(),
                        vectors_hidden_at=store.now(),
                    )
                )
            elif change == "membership":
                await session.execute(
                    update(TenantMembership)
                    .where(TenantMembership.user_id == uid(9))
                    .values(role="VIEWER")
                )
            elif change == "endpoint":
                await session.execute(
                    update(LlmConnection)
                    .where(LlmConnection.id == uid(5))
                    .values(endpoint_policy={"host": "other.invalid", "path_prefix": "/v1"})
                )
            else:
                await session.execute(
                    update(LlmConnection).where(LlmConnection.id == uid(5)).values(enabled=False)
                )
    with pytest.raises((FencedAttempt, InactiveWorkflow, ValueError, PermissionError)):
        await store.complete(claim, next_result(Node.PIN))


@pytest.mark.asyncio
async def test_checkpoint_scope_history_and_unsupported_operations(execution):
    store, _ = execution
    await store.complete(await store.claim(await delivery(store)), next_result(Node.PIN))
    for wrong_access, wrong_scope in ((access(109, 101), scope(80)), (access(), scope(81))):
        wrong = WorkflowStore(store.sessions, wrong_access, wrong_scope)
        with pytest.raises(PermissionError):
            await ScopedCheckpoints(wrong).list()
    checkpoint = ScopedCheckpoints(store)
    for method in (
        "put",
        "put_writes",
        "get_tuple",
        "delete_thread",
        "aprune",
        "acopy_thread",
        "aget_delta_channel_history",
        "adelete_for_runs",
    ):
        with pytest.raises(NotImplementedError):
            getattr(checkpoint, method)({"thread_id": str(uid(80))})
    assert await checkpoint.list(before=1) == ()


@pytest.mark.asyncio
async def test_durable_budget_reservations_repair_and_ambiguous_restart(execution):
    store, clock = execution
    original = await store.claim(await delivery(store), lease_seconds=1)
    budget = DurableCallBudget(store, original)
    budget.bind("a" * 64)
    assert await budget.before_attempt(100, 50) == 1
    await budget.before_repair(uid(90))
    with pytest.raises(BudgetExhausted):
        await DurableCallBudget(store, original).before_repair(uid(91))
    restarted = DurableCallBudget(store, original)
    restarted.bind("a" * 64)
    assert await restarted.before_attempt(100, 50) == 2
    ledger = await store.check(original.fence)
    assert ledger.calls == 2 and ledger.reserved_tokens == 300 and not ledger.records
    clock.advance(2)
    assert await store.claim(await delivery(store)) is None
    async with store.sessions.begin() as session:
        run = await session.get(AgentWorkflowRun, uid(80))
        assert run.state == "failed" and run.error_code == "agent_ambiguous_attempt"


@pytest.mark.asyncio
async def test_budget_endpoint_binding_deadline_and_overrun(execution):
    store, clock = execution
    claim = await store.claim(await delivery(store))
    budget = DurableCallBudget(store, claim)
    budget.bind("a" * 64)
    await budget.before_attempt(10, 10)
    await budget.after_attempt(
        AttemptRecord(
            request_id=uid(88),
            sequence=1,
            purpose="inference",
            outcome="completed",
            submitted=True,
            stop_reason="stop",
        )
    )
    other = DurableCallBudget(store, claim)
    other.bind("b" * 64)
    with pytest.raises(BudgetExhausted):
        await other.before_attempt(1, 1)
    await budget.after_overrun(10)
    with pytest.raises(BudgetExhausted):
        await budget.before_attempt(1, 1)
    clock.advance(61)
    with pytest.raises(FencedAttempt):
        await store.heartbeat(claim.fence)


@pytest.mark.asyncio
async def test_graph_runs_one_node_and_cancellation_stops_inflight_work(execution):
    store, _ = execution
    started, cancelled = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(context):
        calls.append(context.cursor.node)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    graph = WorkflowGraph({node: handler for node in Node if node not in {Node.DONE, Node.BLOCKED}})
    runner = WorkflowRunner(store, graph, provider_factory, heartbeat_seconds=0.02, enabled=True)
    task = asyncio.create_task(runner.run(await delivery(store)))
    await asyncio.wait_for(started.wait(), 2)
    await store.cancel()
    await asyncio.wait_for(task, 2)
    assert cancelled.is_set() and calls == [Node.PIN]
    async with store.sessions.begin() as session:
        assert (await session.get(AgentWorkflowRun, uid(80))).state == "cancelled"


@pytest.mark.asyncio
async def test_continuations_do_not_replay_completed_nodes(execution):
    store, _ = execution
    calls = []

    async def handler(context):
        calls.append(context.cursor.node)
        return next_result(context.cursor.node)

    graph = WorkflowGraph({node: handler for node in Node if node not in {Node.DONE, Node.BLOCKED}})
    runner = WorkflowRunner(store, graph, provider_factory, enabled=True)
    for _ in range(3):
        item = await delivery(store)
        await runner.run(item)
        await runner.run(item)
    assert calls == [Node.PIN, Node.INVENTORY, Node.ANALYZE]
    assert len(await ScopedCheckpoints(store).list()) == 3


@pytest.mark.asyncio
async def test_synthetic_publication_is_atomic_single_active_and_never_approved(execution):
    from agent_schema_fixtures import content

    from app.models.agent_workflows import SummaryRevision
    from app.services.agents.contracts import WorkflowInput

    store, _ = execution

    async def handler(context):
        return next_result(context.cursor.node)

    async def publish(session, repo, result):
        run = await repo._run()
        data = content()
        data.update(revision_id=str(uid(95)), workflow=run.input_snapshot)
        data["verification"]["revision_id"] = str(uid(95))
        assert WorkflowInput.model_validate(data["workflow"]).workflow_run_id == uid(80)
        await repo.add(
            SummaryRevision(
                id=uid(95),
                tenant_id=uid(1),
                workflow_run_id=uid(80),
                summary_id=uid(20),
                project_id=uid(2),
                document_id=uid(3),
                processing_run_id=uid(4),
                version=2,
                content=data,
                quality="review_required",
            )
        )
        await repo.set_active_revision(uid(20), uid(95), expected_version=0)

    graph = WorkflowGraph({node: handler for node in Node if node not in {Node.DONE, Node.BLOCKED}})
    runner = WorkflowRunner(store, graph, provider_factory, publisher=publish, enabled=True)
    for _ in range(8):
        item = await delivery(store)
        await runner.run(item)
        await runner.run(item)
    async with store.sessions.begin() as session:
        summary = await session.get(DocumentSummary, uid(20))
        assert summary.active_revision_id == uid(95) and summary.revision_version == 1
        assert not summary.is_approved and summary.approved_at is None
        run = await session.get(AgentWorkflowRun, uid(80))
        assert run.state == "review_required"
        assert (
            len(
                (
                    await session.scalars(
                        select(SummaryRevision).where(SummaryRevision.workflow_run_id == uid(80))
                    )
                ).all()
            )
            == 1
        )


@pytest.mark.asyncio
async def test_real_adapter_retry_uses_durable_admission_and_fresh_credentials(execution):
    from llm_adapter_fixtures import adapter, reply, request, wire
    from llm_security_fixtures import SENTINEL

    from app.services.llm.adapter_types import AttemptPolicy

    store, _ = execution
    claim = await store.claim(await delivery(store))
    req = request(
        "openai_compatible",
        profile=claim.workflow.profile,
        response_schema="verification.v1",
        input_token_budget=4096,
        max_output_tokens=128,
    )
    budget = DurableCallBudget(store, claim)
    provider, backend, auth = adapter(
        req,
        wire({}, status=b"429 Too Many Requests"),
        wire(reply("openai_compatible", {"checked_claim_ids": []})),
        budget=budget,
        policy=AttemptPolicy(base_delay_seconds=0, max_delay_seconds=0),
    )
    result = await provider.generate(req)
    assert result.status == "completed", result.model_dump_json()
    ledger = await store.check(claim.fence)
    assert ledger.calls == 2 and len(ledger.records) == 2 and auth.prepares == 2
    assert ledger.binding and ledger.reserved_tokens == 8448
    assert SENTINEL not in ledger.model_dump_json()
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_real_adapter_repair_is_shared_and_survives_new_budget_instance(execution):
    from llm_adapter_fixtures import adapter, reply, request, wire

    store, _ = execution
    claim = await store.claim(await delivery(store))
    req = request(
        "openai_compatible",
        profile=claim.workflow.profile,
        response_schema="verification.v1",
        input_token_budget=4096,
        max_output_tokens=128,
    )
    provider, _, _ = adapter(
        req,
        wire(reply("openai_compatible", "malformed")),
        wire(reply("openai_compatible", {"checked_claim_ids": []})),
        budget=DurableCallBudget(store, claim),
    )
    result = await provider.generate(req)
    assert result.status == "completed", result.model_dump_json()
    assert (await store.check(claim.fence)).format_repairs == 1
    with pytest.raises(BudgetExhausted):
        await DurableCallBudget(store, claim).before_repair(uid(92))


@pytest.mark.asyncio
async def test_worker_probe_uses_synthetic_transport_and_admin_permission(execution):
    from llm_adapter_fixtures import adapter, request

    from app.services.agents.connection_tests import WorkerConnectionTest
    from app.services.llm.capabilities import ProbePlan

    store, _ = execution
    provider, backend, _ = adapter(request("openai_compatible"))
    test = WorkerConnectionTest(store.sessions, access(19), provider, ProbePlan())
    with pytest.raises(PermissionError):
        await test.execute()
    assert not backend.calls


@pytest.mark.asyncio
async def test_synthetic_worker_probe_result_and_runtime_gate(execution):
    from types import SimpleNamespace

    from llm_adapter_fixtures import adapter, reply, request, wire

    from app.services.agents.connection_tests import WorkerConnectionTest
    from app.services.agents.worker_runtime import AgentWorkerUnavailable
    from app.services.agents.worker_runtime import advance as worker_advance
    from app.services.llm.capabilities import ProbePlan

    store, _ = execution
    provider, backend, auth = adapter(
        request("openai_compatible"),
        wire(reply("openai_compatible", {"schema_version": "1.0", "answer": "synthetic-ok"})),
    )
    report = await WorkerConnectionTest(
        store.sessions, access(), provider, ProbePlan(cases=("authentication",))
    ).execute()
    assert report.observations[0].origin == "synthetic_fixture" and auth.prepares == 1
    assert len(backend.calls) == 1
    with pytest.raises(AgentWorkerUnavailable, match="disabled"):
        await worker_advance(SimpleNamespace(agentic_summary_enabled=False), uid(80), uid(81))
    with pytest.raises(AgentWorkerUnavailable, match="runtime_unavailable"):
        await worker_advance(SimpleNamespace(agentic_summary_enabled=True), uid(80), uid(81))


@pytest.mark.asyncio
async def test_missing_endpoint_or_budget_binding_fails_without_network(execution):
    from llm_adapter_fixtures import adapter, request

    store, _ = execution
    calls = []

    async def handler(context):
        calls.append(context.cursor.node)
        return next_result(context.cursor.node)

    graph = WorkflowGraph({node: handler for node in Node if node not in {Node.DONE, Node.BLOCKED}})
    # An in-process budget cannot replace the committed workflow admission ledger.
    runner = WorkflowRunner(
        store, graph, lambda workflow, budget: adapter(request())[0], enabled=True
    )
    await runner.run(await delivery(store))
    assert calls == []
    async with store.sessions.begin() as session:
        assert (await session.get(AgentWorkflowRun, uid(80))).state == "stale"


@pytest.mark.asyncio
async def test_continuation_insert_fault_rolls_back_checkpoint_and_cursor(execution, monkeypatch):
    store, _ = execution
    claim = await store.claim(await delivery(store))

    def crash(*args):
        raise RuntimeError("synthetic continuation insert crash")

    monkeypatch.setattr(store, "_delivery", crash)
    with pytest.raises(RuntimeError):
        await store.complete(claim, next_result(Node.PIN))
    assert (await store.check(claim.fence)).cursor == claim.cursor
    assert await ScopedCheckpoints(store).list() == ()


@pytest.mark.asyncio
async def test_create_failure_rolls_back_job_run_and_request_sequence(execution):
    from agent_schema_fixtures import content

    from app.models.domain import Job
    from app.services.agents.contracts import WorkflowInput
    from app.services.agents.persistence_types import RunBudget

    store, _ = execution
    async with store.sessions.begin() as session:
        before = (await session.get(DocumentSummary, uid(20))).latest_request_sequence
        count = len((await session.scalars(select(Job.id))).all())
        await session.execute(
            update(LlmConnection).where(LlmConnection.id == uid(5)).values(enabled=False)
        )
    other = WorkflowStore(store.sessions, access(), scope(81), now=store.now)
    data = content()["workflow"]
    data["workflow_run_id"] = str(uid(81))
    with pytest.raises(InactiveWorkflow):
        await other.create(
            WorkflowInput.model_validate(data),
            uid(21),
            RunBudget(max_calls=2, max_total_tokens=10000, timeout_seconds=60),
        )
    async with store.sessions.begin() as session:
        assert (await session.get(DocumentSummary, uid(20))).latest_request_sequence == before
        assert len((await session.scalars(select(Job.id))).all()) == count
        assert await session.get(AgentWorkflowRun, uid(81)) is None


@pytest.mark.asyncio
async def test_completed_ledger_cannot_reset_or_change_version(execution):
    store, _ = execution
    claim = await store.claim(await delivery(store))
    budget = DurableCallBudget(store, claim)
    budget.bind("a" * 64)
    await budget.before_attempt(10, 10)
    async with store.sessions() as session:
        with pytest.raises(ValueError, match="cannot reset"):
            async with session.begin():
                run = await session.get(AgentWorkflowRun, uid(80))
                run.execution = {**run.execution, "calls": 0}
    with pytest.raises(ValidationError):
        from app.services.agents.state import ExecutionLedger

        ExecutionLedger.model_validate(
            {**(await store.check(claim.fence)).model_dump(), "version": "unsupported"}
        )


@pytest.mark.asyncio
async def test_safe_resume_keeps_completed_work_deadline_and_allowances(execution):
    store, _ = execution
    first = await store.claim(await delivery(store))
    await store.complete(first, next_result(Node.PIN))
    second = await store.claim(await delivery(store))
    deadline = (await store.check(second.fence)).deadline
    await store.stop(second.fence)
    await store.resume()
    resumed = await store.claim(await delivery(store))
    assert resumed.cursor.node == Node.INVENTORY and resumed.deadline == deadline
    assert len(await ScopedCheckpoints(store).list()) == 1
    ledger = await store.check(resumed.fence)
    assert ledger.resumes == 1 and ledger.calls == 0
    await store.cancel()
    with pytest.raises(InactiveWorkflow):
        await store.resume()


@pytest.mark.asyncio
async def test_live_worker_probe_requires_durable_document_free_request(execution, monkeypatch):
    from llm_adapter_fixtures import adapter, request

    from app.services.agents.connection_tests import WorkerConnectionTest
    from app.services.llm.capabilities import ProbePlan

    store, _ = execution
    provider, backend, _ = adapter(request("openai_compatible"))
    monkeypatch.setattr(
        type(provider.transport), "execution_origin", property(lambda self: "live_network")
    )
    with pytest.raises(OrchestrationUnavailable, match="persistence_unqualified"):
        await WorkerConnectionTest(store.sessions, access(), provider, ProbePlan()).execute()
    assert backend.calls == []


@pytest.mark.asyncio
async def test_durable_attempt_receipt_cannot_cross_connection_scope(execution):
    from llm_security_fixtures import FakeAuthorizer, endpoint

    store, _ = execution
    claim = await store.claim(await delivery(store))
    budget = DurableCallBudget(store, claim)
    budget.bind("a" * 64)
    await budget.before_attempt(10, 10)
    _, pinned = endpoint()
    authorized = await FakeAuthorizer().prepare(uid(99), pinned, "inference")
    with pytest.raises(PermissionError):
        await budget.after_attempt(
            AttemptRecord(
                request_id=uid(88),
                sequence=1,
                purpose="inference",
                outcome="completed",
                stop_reason="stop",
                receipt=authorized.receipt,
            )
        )
    assert not (await store.check(claim.fence)).records


@pytest.mark.asyncio
async def test_trusted_sql_routing_cross_checks_job_identity_and_delivery(execution):
    from app.models.domain import Job
    from app.services.agents.runtime import SqlWorkerRuntime

    store, _ = execution

    async def handler(context):
        return next_result(context.cursor.node)

    async def broker(*args):
        return None

    graph = WorkflowGraph({node: handler for node in Node if node not in {Node.DONE, Node.BLOCKED}})
    runtime = SqlWorkerRuntime(store.sessions, graph, provider_factory, broker, now=store.now)
    runner = await runtime.resolve_runner(uid(80), await delivery(store))
    assert runner.store.access == store.access
    assert runner.store.scope == store.scope
    with pytest.raises(PermissionError):
        await runtime.resolve_runner(uid(80), uid(999))
    async with store.sessions.begin() as session:
        run = await session.get(AgentWorkflowRun, uid(80))
        job = await session.get(Job, run.job_id)
        job.created_by = uid(19)  # Simulate tampered routing metadata.
    with pytest.raises(PermissionError):
        await runtime.resolve_runner(uid(80), await delivery(store))


def test_step05_frozen_migration_round_trip_on_empty_disposable_sqlite(tmp_path):
    from agent_schema_fixtures import HEAD, migrate
    from sqlalchemy import create_engine, inspect

    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    try:
        with engine.begin() as conn:
            migrate(conn, target="b7e31d95a204")
            assert "execution" in {
                c["name"] for c in inspect(conn).get_columns("agent_workflow_runs")
            }
            migrate(conn, target="b7e31d95a204", start=HEAD, downgrade=True)
            assert "execution" not in {
                c["name"] for c in inspect(conn).get_columns("agent_workflow_runs")
            }
            migrate(conn, target="b7e31d95a204", start=HEAD)
    finally:
        engine.dispose()
