"""Trusted SQL job routing for ID-only worker messages. No global protected-table scan."""

from uuid import UUID

from sqlalchemy import select

from app.models.agent_workflows import WorkflowDispatchOutbox
from app.models.domain import Job
from app.services.agents.contracts import SourceScope
from app.services.agents.outbox import WorkflowOutbox
from app.services.agents.repository import WorkflowRepository, WorkflowStorageScope
from app.services.agents.runner import WorkflowRunner
from app.services.agents.scoped_storage import StorageAccess
from app.services.agents.storage import TASK, InactiveWorkflow, WorkflowStore
from app.services.agents.worker_runtime import AgentWorkerUnavailable
from app.services.llm.contracts import Contract, Identity


class WorkRoute(Contract):
    agent_workflow_run_id: Identity
    source: SourceScope


class SqlWorkerRuntime:
    def __init__(self, sessions, graph, provider_factory, broker, *, publisher=None, now=None):
        self.sessions, self.graph, self.provider_factory = sessions, graph, provider_factory
        self.broker, self.publisher = broker, publisher
        self.now = now

    async def _store(self, run_id: UUID):
        async with self.sessions.begin() as session:
            # Existing application jobs contain server-created tenant/requester
            # columns. Routing is a hint only; authorize and cross-check protected
            # run identity, requester, source and job FK before returning a store.
            job = await session.scalar(
                select(Job)
                .where(
                    Job.job_type == "DOCUMENT_SUMMARY",
                    Job.request_payload["agent_workflow_run_id"].as_string() == str(run_id),
                )
                .limit(1)
            )
            if job is None:
                raise PermissionError("agent routing unavailable")
            route = WorkRoute.model_validate(job.request_payload)
            access = StorageAccess(job.tenant_id, job.created_by)
            if (
                route.agent_workflow_run_id != run_id
                or route.source.tenant_id != job.tenant_id
                or route.source.project_id != job.project_id
            ):
                raise PermissionError("agent routing scope mismatch")
            scope = WorkflowStorageScope(route.source, run_id)
            repo = WorkflowRepository(session, access, scope)
            await repo._authorize()
            run = await repo._run()
            if run.job_id != job.id or run.requested_by != job.created_by:
                raise PermissionError("agent routing identity mismatch")
        return WorkflowStore(self.sessions, access, scope, now=self.now)

    async def resolve_runner(self, run_id, delivery_id):
        store = await self._store(run_id)
        async with self.sessions.begin() as session:
            repo, run = await store._locked(session)
            found = await session.scalar(
                select(WorkflowDispatchOutbox.id).where(
                    WorkflowDispatchOutbox.id == delivery_id,
                    WorkflowDispatchOutbox.workflow_run_id == run.id,
                    WorkflowDispatchOutbox.tenant_id == run.tenant_id,
                    WorkflowDispatchOutbox.job_id == run.job_id,
                    WorkflowDispatchOutbox.task_name == TASK,
                )
            )
            if found is None:
                raise PermissionError("agent delivery unavailable")
        return WorkflowRunner(
            store, self.graph, self.provider_factory, publisher=self.publisher, enabled=True
        )

    async def reconcile_bounded(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid reconciliation bound")
        async with self.sessions.begin() as session:
            hints = (
                await session.scalars(
                    select(Job.request_payload)
                    .where(
                        Job.job_type == "DOCUMENT_SUMMARY",
                        Job.status.in_(("QUEUED", "IN_PROGRESS")),
                        Job.request_payload["agent_workflow_run_id"].as_string().is_not(None),
                    )
                    .order_by(Job.updated_at, Job.id)
                    .limit(limit)
                )
            ).all()
        for hint in hints:
            try:
                route = WorkRoute.model_validate(hint)
                store = await self._store(route.agent_workflow_run_id)
                outbox = WorkflowOutbox(store)
                await outbox.reconcile()
                await outbox.publish(self.broker)
            except (PermissionError, ValueError, InactiveWorkflow):
                # No secret/raw exception is logged and no other job path is changed.
                continue

    async def resolve_connection_test(self, request_id):
        raise AgentWorkerUnavailable("agent_connection_test_persistence_unqualified")
