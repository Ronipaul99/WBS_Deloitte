"""Synthetic broker faults and transactional delivery; no Redis or real sockets."""

import pytest
from agent_orchestration_fixtures import delivery, next_result
from agent_orchestration_fixtures import execution as execution_fixture  # noqa: F401
from agent_schema_fixtures import uid
from sqlalchemy import select

from app.models.agent_workflows import AgentWorkflowRun, WorkflowDispatchOutbox
from app.models.domain import Job
from app.services.agents.outbox import WorkflowOutbox
from app.services.agents.state import Node
from app.services.agents.storage import FencedAttempt


@pytest.mark.asyncio
async def test_job_run_outbox_creation_has_only_identifiers_in_broker(execution):
    store, _ = execution
    emitted = []

    async def broker(task, args, identity):
        emitted.append((task, args, identity))
        async with store.sessions.begin() as session:
            # Publication observes a committed run and job, not an open transaction.
            run = await session.get(AgentWorkflowRun, uid(80))
            assert await session.get(Job, run.job_id)

    outbox = WorkflowOutbox(store)
    assert await outbox.publish(broker)
    assert not await outbox.publish(broker)
    assert emitted == [
        (
            "wbs.advance_agent_workflow",
            (str(uid(80)), str(await delivery(store))),
            str(await delivery(store)),
        )
    ]


@pytest.mark.asyncio
async def test_publish_then_crash_before_ack_reconciles_duplicate_safely(execution):
    store, clock = execution
    outbox = WorkflowOutbox(store, lease_seconds=5)
    first = await outbox.claim()
    await outbox._finish(first, publishing=True)
    # Broker accepted delivery; publisher process dies before recording success.
    clock.advance(6)
    assert await outbox.reconcile()
    replacement = await outbox.claim()
    with pytest.raises(FencedAttempt):
        await outbox._finish(first, published=True)
    await outbox._finish(replacement, published=True)
    # Stable delivery identity can execute once despite uncertain broker acknowledgment.
    assert await store.claim(first.delivery_id) is not None
    assert await store.claim(first.delivery_id) is None


@pytest.mark.asyncio
async def test_broker_failures_backoff_and_die_with_bounded_attempts(execution):
    store, clock = execution
    outbox = WorkflowOutbox(store, max_attempts=2)

    async def failed(*args):
        raise RuntimeError("synthetic secret must never become an error body")

    assert not await outbox.publish(failed)
    assert await outbox.claim() is None
    clock.advance(5)
    assert not await outbox.publish(failed)
    async with store.sessions.begin() as session:
        row = await session.get(WorkflowDispatchOutbox, await delivery(store))
        assert row.status == "dead" and row.attempt_count == 2
        assert row.last_error_code == "agent_broker_publish_failed"
        assert (await session.get(AgentWorkflowRun, uid(80))).state == "failed"


@pytest.mark.asyncio
async def test_next_outbox_commits_with_checkpoint_and_cannot_replay_old_delivery(execution):
    store, _ = execution
    first = await delivery(store)
    claim = await store.claim(first)
    await store.complete(claim, next_result(Node.PIN))
    async with store.sessions.begin() as session:
        rows = (
            await session.scalars(
                select(WorkflowDispatchOutbox).where(
                    WorkflowDispatchOutbox.workflow_run_id == uid(80)
                )
            )
        ).all()
        assert sorted(row.continuation for row in rows) == [0, 1]
    assert await store.claim(first) is None
    assert (await store.claim(await delivery(store))).cursor.node == Node.INVENTORY


@pytest.mark.asyncio
async def test_cancel_between_claim_and_publish_prevents_broker_send(execution):
    store, _ = execution
    outbox = WorkflowOutbox(store)
    claim = await outbox.claim()
    await store.cancel()
    assert not await outbox._finish(claim, publishing=True)


@pytest.mark.asyncio
async def test_celery_adapter_sends_only_ids_without_implicit_retries():
    from types import SimpleNamespace

    from app.services.agents.dispatch import celery_publisher

    sent = []
    app = SimpleNamespace(send_task=lambda *args, **kwargs: sent.append((args, kwargs)))
    publish = celery_publisher(app)
    await publish("wbs.advance_agent_workflow", (str(uid(80)), str(uid(81))), str(uid(81)))
    assert sent[0][1] == {
        "args": [str(uid(80)), str(uid(81))],
        "task_id": str(uid(81)),
        "serializer": "json",
        "ignore_result": True,
        "retry": False,
    }
    with pytest.raises(ValueError):
        await publish("arbitrary-task", (str(uid(80)), str(uid(81))), str(uid(81)))
