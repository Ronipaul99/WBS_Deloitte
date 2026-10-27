"""Tenant-scoped upload ownership and durable document workflow references."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DocumentContentClaim(TimestampMixin, Base):
    __tablename__ = "document_content_claims"
    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="ck_claim_hash_length"),
        CheckConstraint("size_bytes >= 0", name="ck_claim_size"),
        CheckConstraint(
            "(state = 'RESERVED' AND owner_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state IN ('READY', 'DELETING') AND document_id IS NOT NULL "
            "AND project_id IS NOT NULL)",
            name="ck_claim_state",
        ),
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_claim_document_scope",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    owner_token: Mapped[UUID | None] = mapped_column(nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_storage_key: Mapped[str | None] = mapped_column(String(600))


class DocumentUploadAttempt(TimestampMixin, Base):
    """Retain owned object keys after takeover; cleanup never targets another attempt's key."""

    __tablename__ = "document_upload_attempts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_upload_attempt_tenant"),
        CheckConstraint("length(sha256) = 64", name="ck_attempt_hash_length"),
        Index("ix_upload_attempt_cleanup", "state", "updated_at"),
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_attempt_document_scope",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    storage_key: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="RESERVED", nullable=False)


class DocumentWorkflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_workflows"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "project_id", name="uq_workflow_project_scope"),
        UniqueConstraint("id", "tenant_id", name="uq_workflow_tenant_scope"),
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_workflow_document_scope",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_workflow_run_scope",
        ),
        ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_workflow_summary_scope",
        ),
        ForeignKeyConstraint(
            ["template_id", "tenant_id"],
            ["wbs_templates.id", "wbs_templates.tenant_id"],
            name="fk_workflow_template_scope",
        ),
        ForeignKeyConstraint(
            ["generation_job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_generation_scope",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["summary_job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_summary_job_scope",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["wbs_version_id", "tenant_id", "project_id"],
            ["wbs_versions.id", "wbs_versions.tenant_id", "wbs_versions.project_id"],
            name="fk_workflow_wbs_scope",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["validation_id", "tenant_id", "wbs_version_id"],
            ["validation_runs.id", "validation_runs.tenant_id", "validation_runs.wbs_version_id"],
            name="fk_workflow_validation_scope",
            use_alter=True,
        ),
        Index("ix_workflow_document", "tenant_id", "document_id", "created_at"),
        Index(
            "uq_workflow_base_document",
            "tenant_id",
            "document_id",
            unique=True,
            postgresql_where=text("is_base"),
            sqlite_where=text("is_base = 1"),
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processing_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    summary_id: Mapped[UUID | None] = mapped_column(nullable=True)
    summary_job_id: Mapped[UUID | None] = mapped_column(nullable=True)
    summary_revision: Mapped[int | None] = mapped_column(Integer)
    template_id: Mapped[UUID | None] = mapped_column(nullable=True)
    template_identity: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    generation_job_id: Mapped[UUID | None] = mapped_column(nullable=True)
    wbs_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    validation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    generation_input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    checkpoint_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorkflowRequestKey(TimestampMixin, Base):
    __tablename__ = "workflow_request_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["document_upload_attempts.id", "document_upload_attempts.tenant_id"],
            name="fk_request_upload_scope",
        ),
        ForeignKeyConstraint(
            ["result_workflow_id", "tenant_id"],
            ["document_workflows.id", "document_workflows.tenant_id"],
            name="fk_request_workflow_scope",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_id: Mapped[UUID | None] = mapped_column(nullable=True)
    result_workflow_id: Mapped[UUID | None] = mapped_column(nullable=True)


class WorkflowDispatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_workflow_dispatches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_workflow_dispatch_scope",
        ),
        ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_dispatch_job",
        ),
        ForeignKeyConstraint(
            ["validation_id", "tenant_id", "wbs_version_id"],
            ["validation_runs.id", "validation_runs.tenant_id", "validation_runs.wbs_version_id"],
            name="fk_workflow_dispatch_validation",
        ),
        CheckConstraint(
            "(kind IN ('summary', 'generation') AND job_id IS NOT NULL AND validation_id IS NULL) "
            "OR (kind = 'validation' AND validation_id IS NOT NULL AND wbs_version_id IS NOT NULL "
            "AND job_id IS NULL)",
            name="ck_workflow_dispatch_target",
        ),
        UniqueConstraint("job_id", name="uq_workflow_dispatch_job"),
        UniqueConstraint("validation_id", name="uq_workflow_dispatch_validation"),
        Index("ix_workflow_dispatch_pending", "tenant_id", "status", "lease_expires_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    workflow_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    job_id: Mapped[UUID | None] = mapped_column(nullable=True)
    validation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    wbs_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentContentRejection(TimestampMixin, Base):
    """Remember verified malware identity even after deleting its source document."""

    __tablename__ = "document_content_rejections"
    __table_args__ = (CheckConstraint("length(sha256) = 64", name="ck_rejection_hash_length"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
