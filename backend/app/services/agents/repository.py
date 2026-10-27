"""Scoped relational primitives only; no graph, dispatcher, or summary execution."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update

from app.core.permissions import Permission
from app.models.agent_workflows import (
    AgentCheckpoint,
    AgentStepRun,
    AgentWorkflowRun,
    SummaryApprovalEvent,
    SummaryEvidence,
    SummaryRevision,
    WorkflowDispatchOutbox,
)
from app.models.domain import Document, DocumentProcessingRun, DocumentSummary
from app.services.agents.contracts import SourceScope
from app.services.agents.scoped_storage import ScopedStorage, StorageAccess


class StaleRevisionError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowStorageScope:
    source: SourceScope
    workflow_run_id: UUID

    def __post_init__(self):
        if not isinstance(self.workflow_run_id, UUID) or self.workflow_run_id.int == 0:
            raise ValueError("workflow storage requires a non-nil run identity")


class WorkflowRepository(ScopedStorage):
    def __init__(self, session, access: StorageAccess, scope: WorkflowStorageScope):
        super().__init__(session, access)
        if access.tenant_id != scope.source.tenant_id:
            raise PermissionError("workflow is outside authorized tenant")
        self.scope = scope

    async def _authorize(self, permission=Permission.LLM_USE):
        await self.authorize(permission, self.scope.workflow_run_id)

    def _run_query(self):
        source = self.scope.source
        return select(AgentWorkflowRun).where(
            AgentWorkflowRun.id == self.scope.workflow_run_id,
            AgentWorkflowRun.tenant_id == source.tenant_id,
            AgentWorkflowRun.project_id == source.project_id,
            AgentWorkflowRun.document_id == source.document_id,
            AgentWorkflowRun.processing_run_id == source.processing_run_id,
            AgentWorkflowRun.source_sha256 == source.source_sha256,
        )

    async def _run(self):
        row = await self.session.scalar(self._run_query())
        if row is None:
            raise PermissionError("workflow scope unavailable")
        return row

    async def _current_source(self):
        source = self.scope.source
        current = await self.session.scalar(
            select(Document.id)
            .join(
                DocumentProcessingRun,
                Document.current_processing_run_id == DocumentProcessingRun.id,
            )
            .where(
                Document.id == source.document_id,
                Document.tenant_id == source.tenant_id,
                Document.project_id == source.project_id,
                Document.lifecycle_status == "ACTIVE",
                Document.current_processing_run_id == source.processing_run_id,
                DocumentProcessingRun.status == "COMPLETED",
                DocumentProcessingRun.document_content_sha256 == source.source_sha256,
            )
        )
        if current is None:
            raise StaleRevisionError("source is stale, incomplete, or deleting")

    async def add(self, record):
        if not isinstance(
            record,
            (
                AgentWorkflowRun,
                AgentStepRun,
                AgentCheckpoint,
                WorkflowDispatchOutbox,
                SummaryRevision,
                SummaryEvidence,
            ),
        ):
            raise TypeError("unsupported workflow record")
        await self._authorize()
        self.check_tenant(record)
        run_id = record.id if isinstance(record, AgentWorkflowRun) else record.workflow_run_id
        if run_id != self.scope.workflow_run_id:
            raise PermissionError("record is outside bound workflow")
        for key in ("project_id", "document_id", "processing_run_id", "source_sha256"):
            if hasattr(record, key) and getattr(record, key) != getattr(self.scope.source, key):
                raise PermissionError("record is outside pinned source")
        if isinstance(record, AgentWorkflowRun):
            if record.requested_by != self.access.user_id:
                raise PermissionError("requester differs from authenticated user")
            await self._current_source()
        else:
            await self._run()
        self.session.add(record)
        await self.session.flush()
        return record

    async def checkpoint(self, checkpoint_id: UUID):
        await self._authorize()
        await self._run()
        return await self.session.scalar(
            select(AgentCheckpoint).where(
                AgentCheckpoint.id == checkpoint_id,
                AgentCheckpoint.tenant_id == self.access.tenant_id,
                AgentCheckpoint.workflow_run_id == self.scope.workflow_run_id,
            )
        )

    async def revision(self, revision_id: UUID):
        await self._authorize(Permission.SUMMARY_READ)
        await self._run()
        return await self.session.scalar(
            select(SummaryRevision).where(
                SummaryRevision.id == revision_id,
                SummaryRevision.tenant_id == self.access.tenant_id,
                SummaryRevision.workflow_run_id == self.scope.workflow_run_id,
                SummaryRevision.document_id == self.scope.source.document_id,
            )
        )

    async def set_active_revision(self, summary_id: UUID, revision_id: UUID, expected_version: int):
        """Compare-and-swap storage operation; does not generate or approve content."""
        await self._authorize()
        await self._current_source()
        run = await self._run()
        revision = await self.revision(revision_id)
        if revision is None or revision.summary_id != summary_id or revision.quality == "stale":
            raise StaleRevisionError("revision is outside summary or stale")
        source = self.scope.source
        result = await self.session.execute(
            update(DocumentSummary)
            .where(
                DocumentSummary.id == summary_id,
                DocumentSummary.tenant_id == source.tenant_id,
                DocumentSummary.document_id == source.document_id,
                DocumentSummary.revision_version == expected_version,
                DocumentSummary.latest_request_sequence == run.request_sequence,
            )
            .values(
                active_revision_id=revision_id,
                revision_version=expected_version + 1,
                content_origin="agent_draft",
                is_approved=False,
                approved_at=None,
                summary_text=revision.content["executive_overview"],
                key_points=revision.content["key_points"],
                requirements=revision.content["requirements"],
            )
        )
        if result.rowcount != 1:
            raise StaleRevisionError("revision update lost optimistic concurrency check")

    async def append_approval_event(self, event: SummaryApprovalEvent):
        """Revision-specific audit persistence, without an approval API or agent."""
        await self._authorize(Permission.SUMMARY_APPROVE)
        self.check_tenant(event)
        await self._current_source()
        run = await self._run()
        if event.workflow_run_id != run.id or event.reviewer_id != self.access.user_id:
            raise PermissionError("approval identity mismatch")
        revision = await self.revision(event.revision_id)
        summary = await self.session.scalar(
            select(DocumentSummary)
            .where(
                DocumentSummary.id == event.summary_id,
                DocumentSummary.tenant_id == self.access.tenant_id,
                DocumentSummary.document_id == event.document_id,
            )
            .with_for_update()
        )
        if (
            revision is None
            or summary is None
            or event.document_id != run.document_id
            or revision.summary_id != event.summary_id
            or summary.active_revision_id != revision.id
            or summary.revision_version != event.expected_version
            or summary.latest_request_sequence != run.request_sequence
            or (event.decision == "approved" and revision.quality != "review_required")
        ):
            raise StaleRevisionError("approval targets a stale or blocked revision")
        self.session.add(event)
        await self.session.flush()
        # PostgreSQL's append-only audit trigger performs the same guarded CAS atomically.
        if self.session.get_bind().dialect.name != "postgresql":
            summary.revision_version += 1
            summary.is_approved = event.decision == "approved"
            summary.approved_at = event.decided_at if summary.is_approved else None
            await self.session.flush()

    async def usage_audit(self):
        await self._authorize(Permission.LLM_USAGE_AUDIT)
        await self._run()
        # Explicit projection: never return artifacts/prompts/ciphertext as usage data.
        return (
            await self.session.execute(
                select(
                    AgentStepRun.id, AgentStepRun.node, AgentStepRun.state, AgentStepRun.usage
                ).where(
                    AgentStepRun.tenant_id == self.access.tenant_id,
                    AgentStepRun.workflow_run_id == self.scope.workflow_run_id,
                )
            )
        ).all()


class LegacySummaryRepository(ScopedStorage):
    async def get(self, document_id: UUID):
        await self.authorize(Permission.SUMMARY_READ)
        return await self.session.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == document_id,
                DocumentSummary.tenant_id == self.access.tenant_id,
            )
        )
