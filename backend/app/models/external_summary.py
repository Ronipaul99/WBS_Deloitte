"""Durable submission intents, deliberately independent of externally owned jobs."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SummaryApiRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "summary_api_requests"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_summary_submission_tenant"),
        UniqueConstraint("id", "tenant_id", "document_id", name="uq_summary_request_document"),
        UniqueConstraint(
            "id", "tenant_id", "project_id", "document_id", name="uq_summary_request_binding_scope"
        ),
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_summary_request_document",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_summary_request_run",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_summary_request_workflow",
        ),
        UniqueConstraint(
            "tenant_id", "document_id", "processing_run_id", name="uq_summary_submission_run"
        ),
        UniqueConstraint("tenant_id", "created_by", "key_digest", name="uq_summary_submission_key"),
        CheckConstraint(
            "state IN ('SUBMIT_PENDING','SUBMITTING','ACKNOWLEDGED',"
            "'SUBMISSION_UNKNOWN','REJECTED')",
            name="ck_summary_submission_state",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5", name="ck_summary_submission_attempts"
        ),
        CheckConstraint(
            "length(input_digest) = 64 AND length(config_digest) = 64 AND length(key_digest) = 64",
            name="ck_summary_submission_hashes",
        ),
        CheckConstraint(
            "(state = 'SUBMITTING' AND owner_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state != 'SUBMITTING' AND owner_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_summary_submission_lease",
        ),
        CheckConstraint(
            "(state = 'ACKNOWLEDGED' AND external_job_id IS NOT NULL) OR "
            "(state != 'ACKNOWLEDGED' AND external_job_id IS NULL)",
            name="ck_summary_submission_ack",
        ),
        Index("ix_summary_submission_delivery", "tenant_id", "state", "available_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    project_id: Mapped[UUID] = mapped_column()
    document_id: Mapped[UUID] = mapped_column()
    processing_run_id: Mapped[UUID] = mapped_column()
    workflow_id: Mapped[UUID] = mapped_column()
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    auth_version: Mapped[int] = mapped_column(Integer)
    expected_summary_revision: Mapped[int | None] = mapped_column(Integer)
    key_digest: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    config_digest: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(32), default="submission-v1")
    state: Mapped[str] = mapped_column(String(24), default="SUBMIT_PENDING")
    owner_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_job_id: Mapped[UUID | None] = mapped_column()
    acknowledgement: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    database_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SummarySubmissionKey(TimestampMixin, Base):
    """Bind every supplied/reused key, including aliases for the same active intent."""

    __tablename__ = "summary_submission_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["summary_api_requests.id", "summary_api_requests.tenant_id"],
            name="fk_summary_key_request",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(nullable=False)


class SummaryWorkflowBinding(TimestampMixin, Base):
    """Each workflow pins its own guarded association, without changing Job.workflow_id."""

    __tablename__ = "summary_workflow_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "tenant_id", "project_id", "document_id"],
            [
                "summary_api_requests.id",
                "summary_api_requests.tenant_id",
                "summary_api_requests.project_id",
                "summary_api_requests.document_id",
            ],
            name="fk_summary_binding_request",
        ),
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id", "document_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
                "document_workflows.document_id",
            ],
            name="fk_summary_binding_workflow",
        ),
        CheckConstraint("expected_checkpoint >= 1", name="ck_summary_binding_checkpoint"),
    )
    workflow_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    document_id: Mapped[UUID] = mapped_column()
    request_id: Mapped[UUID] = mapped_column()
    expected_checkpoint: Mapped[int] = mapped_column(Integer)
    previous_job_id: Mapped[UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SummaryResultImport(TimestampMixin, Base):
    __tablename__ = "summary_result_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["request_id", "tenant_id", "project_id", "document_id"],
            [
                "summary_api_requests.id",
                "summary_api_requests.tenant_id",
                "summary_api_requests.project_id",
                "summary_api_requests.document_id",
            ],
            name="fk_summary_import_request",
        ),
        ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_summary_import_summary",
        ),
        CheckConstraint(
            "state IN ('WAITING','VALIDATING','IMPORTED','INVALID','STALE')",
            name="ck_summary_import_state",
        ),
        CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_summary_import_attempts"),
        CheckConstraint(
            "(state = 'VALIDATING' AND owner_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (state != 'VALIDATING' "
            "AND owner_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_summary_import_lease",
        ),
        CheckConstraint(
            "(state = 'IMPORTED' AND summary_id IS NOT NULL "
            "AND imported_revision IS NOT NULL AND imported_revision > 0 "
            "AND result_digest IS NOT NULL AND length(result_digest) = 64 "
            "AND imported_at IS NOT NULL) OR (state != 'IMPORTED' "
            "AND summary_id IS NULL AND imported_revision IS NULL "
            "AND result_digest IS NULL AND imported_at IS NULL)",
            name="ck_summary_import_identity",
        ),
        Index("ix_summary_import_due", "tenant_id", "state", "available_at"),
    )
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="WAITING")
    first_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    owner_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    summary_id: Mapped[UUID | None] = mapped_column()
    imported_revision: Mapped[int | None] = mapped_column(Integer)
    result_digest: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
