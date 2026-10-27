"""Step 2 relational storage only; no graph or queue execution."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.agent_types import (
    TenantRecord,
    WorkflowChild,
    WorkflowState,
    bounded_json,
    enum_check,
    json_column,
    scoped_run_fk,
)


class AgentWorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantRecord, Base):
    __tablename__ = "agent_workflow_runs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_agent_run_tenant"),
        UniqueConstraint(
            "id",
            "tenant_id",
            "project_id",
            "document_id",
            "processing_run_id",
            name="uq_agent_run_source",
        ),
        UniqueConstraint("id", "tenant_id", "job_id", name="uq_agent_run_job"),
        UniqueConstraint("job_id", name="uq_agent_workflow_job"),
        UniqueConstraint("document_id", "request_sequence", name="uq_agent_request_sequence"),
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_agent_document",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_agent_processing_run",
        ),
        ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_agent_job",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_agent_requester_membership",
        ),
        ForeignKeyConstraint(
            ["profile_version_id", "tenant_id", "profile_id", "connection_id"],
            [
                "llm_model_profile_versions.id",
                "llm_model_profile_versions.tenant_id",
                "llm_model_profile_versions.profile_id",
                "llm_model_profile_versions.connection_id",
            ],
            name="fk_agent_profile",
        ),
        enum_check("state", WorkflowState, "ck_agent_workflow_state"),
        CheckConstraint(
            "request_sequence > 0 AND fencing_token >= 0", name="ck_agent_run_counters"
        ),
        bounded_json("execution", "ck_agent_execution_size", 131072),
        CheckConstraint("length(source_sha256) = 64", name="ck_agent_source_hash"),
        bounded_json("input_snapshot", "ck_agent_input_size", 32768),
        bounded_json("budget", "ck_agent_budget_size", 4096),
        Index("ix_agent_runs_document", "tenant_id", "document_id", "created_at"),
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(nullable=False)
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_version_id: Mapped[UUID] = mapped_column(nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict] = json_column()
    budget: Mapped[dict] = json_column()
    # Step 5 mutable admission ledger, separate from the immutable policy budget.
    execution: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    state: Mapped[str] = mapped_column(String(24), server_default="queued", nullable=False)
    request_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AgentStepRun(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "agent_step_runs"
    __table_args__ = (
        scoped_run_fk("fk_agent_step_run"),
        UniqueConstraint(
            "workflow_run_id", "node", "batch", "attempt", name="uq_agent_step_identity"
        ),
        CheckConstraint("batch >= 0 AND attempt BETWEEN 1 AND 10", name="ck_agent_step_attempt"),
        enum_check("state", ("pending", "completed", "failed"), "ck_agent_step_state"),
        CheckConstraint("length(input_sha256) = 64", name="ck_agent_step_input_hash"),
        bounded_json("artifact", "ck_agent_step_artifact_size"),
        bounded_json("usage", "ck_agent_step_usage_size", 2048),
        Index("ix_agent_steps_run", "tenant_id", "workflow_run_id", "node", "batch"),
    )
    node: Mapped[str] = mapped_column(String(80), nullable=False)
    batch: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    artifact: Mapped[dict] = json_column()
    usage: Mapped[dict] = json_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentCheckpoint(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "agent_checkpoints"
    __table_args__ = (
        scoped_run_fk("fk_agent_checkpoint_run"),
        UniqueConstraint("workflow_run_id", "sequence", name="uq_agent_checkpoint_sequence"),
        CheckConstraint("sequence > 0", name="ck_agent_checkpoint_sequence"),
        CheckConstraint("length(input_sha256) = 64", name="ck_agent_checkpoint_input_hash"),
        bounded_json("artifact", "ck_agent_checkpoint_size"),
        Index("ix_agent_checkpoints_run", "tenant_id", "workflow_run_id", "sequence"),
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str] = mapped_column(String(80), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact: Mapped[dict] = json_column()


class WorkflowDispatchOutbox(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "workflow_dispatch_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id", "job_id"],
            [
                "agent_workflow_runs.id",
                "agent_workflow_runs.tenant_id",
                "agent_workflow_runs.job_id",
            ],
            name="fk_workflow_outbox_run_job",
        ),
        UniqueConstraint(
            "workflow_run_id", "task_name", "continuation", name="uq_workflow_delivery"
        ),
        enum_check(
            "status",
            ("pending", "claimed", "publishing", "published", "retry", "dead"),
            "ck_workflow_delivery_state",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND continuation >= 0", name="ck_workflow_delivery_counts"
        ),
        CheckConstraint("fencing_token >= 0", name="ck_workflow_fence"),
        Index("ix_workflow_outbox_pending", "tenant_id", "status", "available_at", "created_at"),
    )
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    continuation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class SummaryRevision(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "summary_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "tenant_id", "document_id", "summary_id", name="uq_summary_revision_scope"
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "document_id",
            "summary_id",
            "workflow_run_id",
            name="uq_summary_revision_approval",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "workflow_run_id",
            "project_id",
            "document_id",
            "processing_run_id",
            name="uq_summary_revision_source",
        ),
        UniqueConstraint("summary_id", "version", name="uq_summary_revision_version"),
        ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_revision_summary",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id", "project_id", "document_id", "processing_run_id"],
            [
                "agent_workflow_runs.id",
                "agent_workflow_runs.tenant_id",
                "agent_workflow_runs.project_id",
                "agent_workflow_runs.document_id",
                "agent_workflow_runs.processing_run_id",
            ],
            name="fk_revision_source",
        ),
        CheckConstraint("version > 0", name="ck_summary_revision_version"),
        enum_check(
            "quality",
            ("review_required", "partial", "quality_blocked", "stale"),
            "ck_summary_revision_quality",
        ),
        bounded_json("content", "ck_summary_revision_content_size", 8_388_608),
        Index("ix_summary_revision_history", "tenant_id", "summary_id", "created_at"),
    )
    summary_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = json_column()
    quality: Mapped[str] = mapped_column(String(24), nullable=False)


class SummaryEvidence(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "summary_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "revision_id",
                "tenant_id",
                "workflow_run_id",
                "project_id",
                "document_id",
                "processing_run_id",
            ],
            [
                "summary_revisions.id",
                "summary_revisions.tenant_id",
                "summary_revisions.workflow_run_id",
                "summary_revisions.project_id",
                "summary_revisions.document_id",
                "summary_revisions.processing_run_id",
            ],
            name="fk_summary_evidence_revision",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "tenant_id", "project_id", "document_id", "processing_run_id"],
            [
                "document_chunks.id",
                "document_chunks.tenant_id",
                "document_chunks.project_id",
                "document_chunks.document_id",
                "document_chunks.processing_run_id",
            ],
            name="fk_summary_evidence_chunk",
        ),
        UniqueConstraint(
            "revision_id", "claim_id", "evidence_id", name="uq_summary_claim_evidence"
        ),
        bounded_json("locator", "ck_summary_evidence_size", 65536),
        CheckConstraint("length(chunk_sha256) = 64", name="ck_summary_evidence_hash"),
        Index("ix_summary_evidence_revision", "tenant_id", "revision_id", "claim_id"),
    )
    revision_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(nullable=False)
    claim_id: Mapped[UUID] = mapped_column(nullable=False)
    chunk_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[dict] = json_column()


class SummaryApprovalEvent(UUIDPrimaryKeyMixin, TimestampMixin, WorkflowChild, Base):
    __tablename__ = "summary_approval_events"
    __table_args__ = (
        scoped_run_fk("fk_summary_approval_run"),
        ForeignKeyConstraint(
            ["revision_id", "tenant_id", "document_id", "summary_id", "workflow_run_id"],
            [
                "summary_revisions.id",
                "summary_revisions.tenant_id",
                "summary_revisions.document_id",
                "summary_revisions.summary_id",
                "summary_revisions.workflow_run_id",
            ],
            name="fk_summary_approval_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_summary_approval_reviewer",
        ),
        UniqueConstraint("summary_id", "expected_version", name="uq_summary_approval_version"),
        enum_check("decision", ("approved", "rejected"), "ck_summary_approval_decision"),
        CheckConstraint("expected_version >= 0", name="ck_summary_approval_version"),
    )
    summary_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_id: Mapped[UUID] = mapped_column(nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
