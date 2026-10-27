"""Transactional Step 5 state, checkpoints and admission. Never owns network I/O."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.agent_types import workflow_job_status
from app.models.agent_workflows import (
    AgentCheckpoint,
    AgentStepRun,
    AgentWorkflowRun,
    WorkflowDispatchOutbox,
)
from app.models.domain import Document, DocumentSummary, Job, TenantMembership
from app.models.llm import (
    LlmConnection,
    LlmCredentialVersion,
    LlmModelProfile,
    LlmModelProfileVersion,
)
from app.services.agents.contracts import WorkflowInput
from app.services.agents.persistence_types import EndpointPolicyRecord, RunBudget, safe_json
from app.services.agents.repository import WorkflowRepository, WorkflowStorageScope
from app.services.agents.state import (
    CompletedNode,
    Cursor,
    ExecutionLedger,
    Node,
    NodeResult,
    OrchestrationArtifact,
    Progress,
    advance,
    node_input_hash,
)
from app.services.llm.adapter_types import AttemptRecord, BudgetExhausted

TASK = "wbs.advance_agent_workflow"
TERMINAL = {"review_required", "partial", "quality_blocked", "stale", "failed", "cancelled"}


class FencedAttempt(RuntimeError):
    def __init__(self):
        super().__init__("agent_attempt_fenced")


class InactiveWorkflow(RuntimeError):
    def __init__(self):
        super().__init__("agent_workflow_unavailable")


@dataclass(frozen=True)
class Claim:
    fence: int
    cursor: Cursor
    workflow: WorkflowInput
    deadline: datetime
    endpoint: EndpointPolicyRecord


def aware(value):
    # SQLite unit fixtures return naive dates; production PG columns are timestamptz.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class WorkflowStore:
    def __init__(self, sessions, access, scope: WorkflowStorageScope, *, now=None):
        self.sessions, self.access, self.scope = sessions, access, scope
        self.now = now or (lambda: datetime.now(UTC))

    async def _locked(self, session):
        repo = WorkflowRepository(session, self.access, self.scope)
        await repo._authorize()
        # Lock order is run -> membership -> document -> connection -> profile.
        run = await session.scalar(repo._run_query().with_for_update())
        if run is None or run.requested_by != self.access.user_id:
            raise PermissionError("workflow access denied")
        await session.scalar(
            select(TenantMembership)
            .where(
                TenantMembership.tenant_id == self.access.tenant_id,
                TenantMembership.user_id == self.access.user_id,
            )
            .with_for_update()
        )
        return repo, run

    async def _available(self, session, repo, run):
        await session.scalar(
            select(Document)
            .where(
                Document.id == run.document_id,
                Document.tenant_id == run.tenant_id,
            )
            .with_for_update()
        )
        await repo._current_source()
        connection = await session.scalar(
            select(LlmConnection)
            .where(
                LlmConnection.id == run.connection_id,
                LlmConnection.tenant_id == run.tenant_id,
            )
            .with_for_update()
        )
        profile = await session.scalar(
            select(LlmModelProfile)
            .where(
                LlmModelProfile.id == run.profile_id,
                LlmModelProfile.tenant_id == run.tenant_id,
                LlmModelProfile.connection_id == run.connection_id,
            )
            .with_for_update()
        )
        ledger = ExecutionLedger.model_validate(run.execution)
        if (
            connection is None
            or profile is None
            or not connection.enabled
            or not profile.enabled
            or connection.active_credential_id is None
            or connection.endpoint_policy != ledger.endpoint.model_dump(mode="json")
        ):
            raise InactiveWorkflow()
        credential = await session.scalar(
            select(LlmCredentialVersion).where(
                LlmCredentialVersion.id == connection.active_credential_id,
                LlmCredentialVersion.tenant_id == run.tenant_id,
                LlmCredentialVersion.connection_id == run.connection_id,
                LlmCredentialVersion.retired_at.is_(None),
            )
        )
        if credential is None:
            raise InactiveWorkflow()
        # Active model version may advance; the pinned immutable version stays fixed.
        pinned = await session.scalar(
            select(LlmModelProfileVersion).where(
                LlmModelProfileVersion.id == run.profile_version_id,
                LlmModelProfileVersion.tenant_id == run.tenant_id,
                LlmModelProfileVersion.profile_id == run.profile_id,
                LlmModelProfileVersion.connection_id == run.connection_id,
            )
        )
        if pinned is None or pinned.snapshot != run.input_snapshot["profile"]:
            raise InactiveWorkflow()
        summary = await session.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == run.document_id,
                DocumentSummary.tenant_id == run.tenant_id,
            )
        )
        if summary is None or summary.latest_request_sequence != run.request_sequence:
            raise InactiveWorkflow()
        return ledger

    def _fence(self, run, fence):
        if (
            run.state != "running"
            or run.fencing_token != fence
            or run.lease_expires_at is None
            or aware(run.lease_expires_at) <= self.now()
        ):
            raise FencedAttempt()

    def _write(self, run, ledger):
        run.execution = safe_json(ledger.model_dump(mode="json"), 131072)

    async def create(self, workflow: WorkflowInput, profile_version_id: UUID, budget: RunBudget):
        """Internal primitive only. No existing summary route calls this method."""
        workflow = WorkflowInput.model_validate(workflow)
        if (
            workflow.workflow_run_id != self.scope.workflow_run_id
            or workflow.scope != self.scope.source
        ):
            raise PermissionError("creation scope mismatch")
        async with self.sessions.begin() as session:
            repo = WorkflowRepository(session, self.access, self.scope)
            await repo._authorize()
            await repo._current_source()
            await session.scalar(
                select(Document)
                .where(
                    Document.id == self.scope.source.document_id,
                    Document.tenant_id == self.access.tenant_id,
                )
                .with_for_update()
            )
            summary = await session.scalar(
                select(DocumentSummary)
                .where(
                    DocumentSummary.document_id == self.scope.source.document_id,
                    DocumentSummary.tenant_id == self.access.tenant_id,
                )
                .with_for_update()
            )
            if summary is None:
                raise InactiveWorkflow()
            connection = await session.scalar(
                select(LlmConnection).where(
                    LlmConnection.id == workflow.profile.connection_id,
                    LlmConnection.tenant_id == self.access.tenant_id,
                )
            )
            if connection is None:
                raise InactiveWorkflow()
            summary.latest_request_sequence += 1
            job = Job(
                id=uuid4(),
                tenant_id=self.access.tenant_id,
                project_id=workflow.scope.project_id,
                created_by=self.access.user_id,
                job_type="DOCUMENT_SUMMARY",
                status="QUEUED",
                request_payload={
                    "agent_workflow_run_id": str(workflow.workflow_run_id),
                    "source": workflow.scope.model_dump(mode="json"),
                },
                result_payload={},
            )
            session.add(job)
            await session.flush()
            run = AgentWorkflowRun(
                id=workflow.workflow_run_id,
                tenant_id=self.access.tenant_id,
                project_id=workflow.scope.project_id,
                document_id=workflow.scope.document_id,
                processing_run_id=workflow.scope.processing_run_id,
                job_id=job.id,
                requested_by=self.access.user_id,
                connection_id=workflow.profile.connection_id,
                profile_id=workflow.profile.profile_id,
                profile_version_id=profile_version_id,
                source_sha256=workflow.scope.source_sha256,
                input_snapshot=workflow.model_dump(mode="json"),
                budget=budget.model_dump(mode="json"),
                request_sequence=summary.latest_request_sequence,
                state="queued",
                fencing_token=0,
                execution=ExecutionLedger(
                    deadline=self.now() + timedelta(seconds=budget.timeout_seconds),
                    endpoint=connection.endpoint_policy,
                ).model_dump(mode="json"),
            )
            await repo.add(run)
            await self._available(session, repo, run)
            await repo.add(self._delivery(run, 0))
            return job.id

    def _delivery(self, run, continuation):
        return WorkflowDispatchOutbox(
            id=uuid4(),
            tenant_id=run.tenant_id,
            workflow_run_id=run.id,
            job_id=run.job_id,
            task_name=TASK,
            continuation=continuation,
            status="pending",
            attempt_count=0,
            fencing_token=0,
            available_at=self.now(),
        )

    async def claim(self, delivery_id: UUID, *, lease_seconds=60) -> Claim | None:
        if not 1 <= lease_seconds <= 600:
            raise ValueError("invalid lease")
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            delivery = await session.scalar(
                select(WorkflowDispatchOutbox).where(
                    WorkflowDispatchOutbox.id == delivery_id,
                    WorkflowDispatchOutbox.tenant_id == run.tenant_id,
                    WorkflowDispatchOutbox.workflow_run_id == run.id,
                    WorkflowDispatchOutbox.task_name == TASK,
                )
            )
            if delivery is None:
                raise PermissionError("delivery outside run")
            if run.state in TERMINAL:
                return None
            try:
                ledger = await self._available(session, repo, run)
            except (InactiveWorkflow, ValueError):
                await self._status(session, run, "stale", "agent_source_stale")
                return None
            if delivery.continuation != ledger.cursor.sequence or delivery.status == "dead":
                return None
            if run.lease_expires_at and aware(run.lease_expires_at) > self.now():
                return None
            if run.state == "running" and ledger.calls > ledger.node_start_calls:
                await self._status(session, run, "failed", "agent_ambiguous_attempt")
                run.fencing_token += 1
                run.lease_expires_at = None
                return None
            if ledger.deadline <= self.now() or ledger.violated:
                await self._status(session, run, "failed", "agent_budget_exhausted")
                return None
            run.state = "running"
            run.fencing_token += 1
            run.lease_expires_at = self.now() + timedelta(seconds=lease_seconds)
            await self._status(session, run, "running")
            return Claim(
                run.fencing_token,
                ledger.cursor,
                WorkflowInput.model_validate(run.input_snapshot),
                ledger.deadline,
                ledger.endpoint,
            )

    async def check(self, fence):
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            self._fence(run, fence)
            ledger = await self._available(session, repo, run)
            if ledger.deadline <= self.now() or ledger.violated:
                raise BudgetExhausted()
            return ledger

    async def heartbeat(self, fence, *, lease_seconds=60):
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            self._fence(run, fence)
            await self._available(session, repo, run)
            run.lease_expires_at = self.now() + timedelta(seconds=lease_seconds)

    async def complete(self, claim: Claim, result: NodeResult, *, publisher=None):
        """Artifact + checkpoint + next delivery + optional publication, one transaction."""
        result = NodeResult.model_validate(result)
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            self._fence(run, claim.fence)
            lease_deadline = aware(run.lease_expires_at)
            ledger = await self._available(session, repo, run)
            if ledger.deadline <= self.now() or ledger.violated:
                raise BudgetExhausted()
            if ledger.cursor != claim.cursor:
                raise FencedAttempt()
            after = advance(claim.cursor, result)
            completed = CompletedNode(
                workflow_run_id=run.id,
                input_sha256=node_input_hash(run.input_snapshot, claim.cursor),
                before=claim.cursor,
                after=after,
                result=result,
            )
            artifact = OrchestrationArtifact(payload=completed).model_dump(mode="json")
            await repo.add(
                AgentStepRun(
                    id=uuid4(),
                    tenant_id=run.tenant_id,
                    workflow_run_id=run.id,
                    node=claim.cursor.node.value,
                    batch=claim.cursor.sequence,
                    attempt=1,
                    input_sha256=completed.input_sha256,
                    state="completed",
                    artifact=artifact,
                    usage=result.usage.model_dump(mode="json"),
                    completed_at=self.now(),
                )
            )
            await repo.add(
                AgentCheckpoint(
                    id=uuid4(),
                    tenant_id=run.tenant_id,
                    workflow_run_id=run.id,
                    sequence=after.sequence,
                    node=claim.cursor.node.value,
                    input_sha256=completed.input_sha256,
                    artifact=artifact,
                )
            )
            self._write(
                run, ledger.model_copy(update={"cursor": after, "node_start_calls": ledger.calls})
            )
            run.lease_expires_at = None
            if after.node == Node.DONE:
                if publisher is None:
                    raise InactiveWorkflow()
                # Trusted application DB-only callback; never a graph/provider tool.
                await publisher(session, repo, result)
                await self._status(session, run, "review_required")
            elif after.node == Node.BLOCKED:
                await self._status(session, run, "quality_blocked")
            else:
                await self._status(session, run, "queued")
                await repo.add(self._delivery(run, after.sequence))
            # A DB-only publication hook must not extend an expired execution lease.
            if lease_deadline <= self.now() or ledger.deadline <= self.now():
                raise FencedAttempt()

    async def _status(self, session, run, state, error=None):
        run.state, run.error_code = state, error
        job = await session.scalar(
            select(Job)
            .where(
                Job.id == run.job_id,
                Job.tenant_id == run.tenant_id,
                Job.project_id == run.project_id,
            )
            .with_for_update()
        )
        if job is None:
            raise InactiveWorkflow()
        job.status, job.error_code = workflow_job_status(state), error
        job.current_step = "agent_" + state
        ledger = ExecutionLedger.model_validate(run.execution)
        job.result_payload = Progress(
            workflow_run_id=run.id,
            state=state,
            node=ledger.cursor.node,
            completed_nodes=ledger.cursor.sequence,
            calls_reserved=ledger.calls,
            tokens_reserved=ledger.reserved_tokens,
            usage_unknown=(
                len(ledger.records) < ledger.calls
                or any(record.usage.source != "reported" for record in ledger.records)
            ),
        ).model_dump(mode="json")

    async def cancel(self):
        async with self.sessions.begin() as session:
            _, run = await self._locked(session)
            if run.state not in TERMINAL:
                run.fencing_token += 1
                run.lease_expires_at = None
                await self._status(session, run, "cancelled", "agent_cancelled")

    async def resume(self):
        """Explicit safe retry; never reset allowance, delivery counts or pinned inputs."""
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            ledger = await self._available(session, repo, run)
            if (
                run.state != "failed"
                or ledger.resumes >= 3
                or ledger.violated
                or ledger.deadline <= self.now()
                or ledger.calls > ledger.node_start_calls
                or ledger.cursor.node in {Node.DONE, Node.BLOCKED}
            ):
                raise InactiveWorkflow()
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
            if row is None or row.attempt_count >= 5:
                raise InactiveWorkflow()
            run.fencing_token += 1
            run.lease_expires_at = None
            self._write(run, ledger.model_copy(update={"resumes": ledger.resumes + 1}))
            row.fencing_token += 1
            row.status, row.available_at, row.lease_expires_at = "retry", self.now(), None
            await self._status(session, run, "queued")

    async def stop(self, fence, state="failed", code="agent_execution_failed"):
        if state not in {"failed", "stale", "partial", "quality_blocked"} or code not in {
            "agent_execution_failed",
            "agent_source_stale",
            "agent_runtime_unavailable",
            "agent_budget_exhausted",
            "agent_ambiguous_attempt",
        }:
            raise ValueError("unsupported status")
        async with self.sessions.begin() as session:
            _, run = await self._locked(session)
            self._fence(run, fence)
            run.fencing_token += 1
            run.lease_expires_at = None
            await self._status(session, run, state, code)

    async def mutate_budget(self, fence, operation, *, tokens=0, binding=None, record=None):
        """Reserve before submission; unknown reservations survive crashes without refunds."""
        async with self.sessions.begin() as session:
            repo, run = await self._locked(session)
            self._fence(run, fence)
            ledger = await self._available(session, repo, run)
            policy = RunBudget.model_validate(run.budget)
            if ledger.deadline <= self.now():
                raise BudgetExhausted()
            data = ledger.model_dump()
            if operation == "reserve":
                if (
                    type(tokens) is not int
                    or tokens < 1
                    or ledger.violated
                    or ledger.calls >= policy.max_calls
                    or ledger.reserved_tokens + tokens > policy.max_total_tokens
                    or (ledger.binding is not None and ledger.binding != binding)
                    or binding is None
                ):
                    raise BudgetExhausted()
                data.update(
                    calls=ledger.calls + 1,
                    reserved_tokens=ledger.reserved_tokens + tokens,
                    binding=binding,
                )
            elif operation == "repair":
                if ledger.format_repairs or ledger.violated:
                    raise BudgetExhausted()
                data["format_repairs"] = 1
            elif operation == "overrun":
                data.update(violated=True, reserved_tokens=ledger.reserved_tokens + max(0, tokens))
            elif operation == "record":
                record = AttemptRecord.model_validate(record)
                receipt = record.receipt
                if receipt is not None and (
                    (
                        receipt.tenant_id,
                        receipt.connection_id,
                        receipt.actor_id,
                        receipt.endpoint_approval_id,
                        receipt.purpose,
                    )
                    != (
                        run.tenant_id,
                        run.connection_id,
                        run.requested_by,
                        ledger.endpoint.approval_id,
                        record.purpose,
                    )
                ):
                    raise PermissionError("attempt receipt outside workflow scope")
                if record.sequence > ledger.calls or any(
                    item.sequence == record.sequence for item in ledger.records
                ):
                    raise ValueError("attempt receipt identity mismatch")
                data["records"] = (*ledger.records, record)
            else:
                raise ValueError("unsupported budget operation")
            updated = ExecutionLedger.model_validate(data)
            self._write(run, updated)
            return updated
