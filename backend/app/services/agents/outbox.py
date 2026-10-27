"""Scoped bounded publication/reconciliation; PostgreSQL owns delivery identity."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.agent_workflows import WorkflowDispatchOutbox
from app.services.agents.state import ExecutionLedger
from app.services.agents.storage import TASK, TERMINAL, FencedAttempt, aware


@dataclass(frozen=True)
class DeliveryClaim:
    delivery_id: UUID
    run_id: UUID
    token: int


class WorkflowOutbox:
    def __init__(self, store, *, max_attempts=5, base_seconds=5, max_seconds=300, lease_seconds=60):
        if not 1 <= max_attempts <= 10 or not 1 <= base_seconds <= max_seconds <= 300:
            raise ValueError("invalid outbox bounds")
        self.store, self.max_attempts = store, max_attempts
        self.base_seconds, self.max_seconds = base_seconds, max_seconds
        if not 1 <= lease_seconds <= 60:
            raise ValueError("invalid publish lease")
        self.lease_seconds = lease_seconds

    async def claim(self):
        store = self.store
        async with store.sessions.begin() as session:
            repo, run = await store._locked(session)
            if run.state in TERMINAL:
                return None
            await store._available(session, repo, run)
            ledger = ExecutionLedger.model_validate(run.execution)
            if ledger.deadline <= store.now() or ledger.violated:
                await store._status(session, run, "failed", "agent_budget_exhausted")
                return None
            cursor = ledger.cursor
            row = await session.scalar(
                select(WorkflowDispatchOutbox)
                .where(
                    WorkflowDispatchOutbox.workflow_run_id == run.id,
                    WorkflowDispatchOutbox.tenant_id == run.tenant_id,
                    WorkflowDispatchOutbox.continuation == cursor.sequence,
                    WorkflowDispatchOutbox.task_name == TASK,
                )
                .with_for_update()
            )
            if row is None or aware(row.available_at) > store.now():
                return None
            active = (
                row.status in {"claimed", "publishing"}
                and row.lease_expires_at
                and aware(row.lease_expires_at) > store.now()
            )
            if active or row.status in {"published", "dead"}:
                return None
            if row.attempt_count >= self.max_attempts:
                row.status = "dead"
                await store._status(session, run, "failed", "agent_delivery_exhausted")
                return None
            row.status = "claimed"
            row.attempt_count += 1
            row.fencing_token += 1
            row.lease_expires_at = store.now() + timedelta(seconds=self.lease_seconds)
            return DeliveryClaim(row.id, run.id, row.fencing_token)

    async def _finish(self, claim, *, published=False, publishing=False):
        store = self.store
        async with store.sessions.begin() as session:
            _, run = await store._locked(session)
            row = await session.scalar(
                select(WorkflowDispatchOutbox)
                .where(
                    WorkflowDispatchOutbox.id == claim.delivery_id,
                    WorkflowDispatchOutbox.workflow_run_id == run.id,
                    WorkflowDispatchOutbox.tenant_id == run.tenant_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or claim.run_id != run.id
                or row.fencing_token != claim.token
                or row.status not in {"claimed", "publishing"}
                or row.lease_expires_at is None
                or aware(row.lease_expires_at) <= store.now()
            ):
                raise FencedAttempt()
            if run.state in TERMINAL:
                row.status = "dead"
                row.lease_expires_at = None
                return False
            elif publishing:
                row.status = "publishing"
                return True
            elif published:
                row.status, row.published_at = "published", store.now()
            else:
                row.status = "dead" if row.attempt_count >= self.max_attempts else "retry"
                row.last_error_code = "agent_broker_publish_failed"
                row.available_at = store.now() + timedelta(
                    seconds=min(self.max_seconds, self.base_seconds * 2 ** (row.attempt_count - 1))
                )
                if row.status == "dead":
                    await store._status(session, run, "failed", "agent_delivery_exhausted")
            row.lease_expires_at = None
            return True

    async def publish(self, broker):
        claim = await self.claim()
        if claim is None:
            return False
        if not await self._finish(claim, publishing=True):
            return False
        # No SQL txn across this call. Stable identity permits duplicate delivery.
        try:
            await broker(TASK, (str(claim.run_id), str(claim.delivery_id)), str(claim.delivery_id))
        except Exception:
            await self._finish(claim)
            return False
        await self._finish(claim, published=True)
        return True

    async def reconcile(self):
        store = self.store
        async with store.sessions.begin() as session:
            _, run = await store._locked(session)
            if run.state in TERMINAL:
                return False
            ledger = ExecutionLedger.model_validate(run.execution)
            if run.lease_expires_at and aware(run.lease_expires_at) > store.now():
                return False
            row = await session.scalar(
                select(WorkflowDispatchOutbox)
                .where(
                    WorkflowDispatchOutbox.workflow_run_id == run.id,
                    WorkflowDispatchOutbox.tenant_id == run.tenant_id,
                    WorkflowDispatchOutbox.continuation == ledger.cursor.sequence,
                    WorkflowDispatchOutbox.task_name == TASK,
                )
                .with_for_update()
            )
            if row is None or row.status == "dead":
                return False
            if (row.lease_expires_at and aware(row.lease_expires_at) > store.now()) or (
                row.status == "published"
                and row.published_at
                and aware(row.published_at) + timedelta(seconds=60) > store.now()
            ):
                return False
            # Even fully recorded calls inside an uncommitted node may have been billed.
            # Refuse automatic node replay when that node made an external attempt.
            if run.state == "running" and ledger.calls > ledger.node_start_calls:
                await store._status(session, run, "failed", "agent_ambiguous_attempt")
                run.fencing_token += 1
                run.lease_expires_at = None
                return False
            row.fencing_token += 1
            row.lease_expires_at = None
            row.status = "retry"
            row.available_at = store.now()
            run.fencing_token += 1
            run.lease_expires_at = None
            return True
