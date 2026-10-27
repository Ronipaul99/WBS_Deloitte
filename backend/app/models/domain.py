from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MembershipRole(StrEnum):
    ADMIN = "ADMIN"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class DocumentKind(StrEnum):
    PROJECT = "PROJECT"
    TEMPLATE = "TEMPLATE"


class ProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DocumentProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DocumentLifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DELETING = "DELETING"
    DELETED = "DELETED"


ACTIVE_DOCUMENT_PROCESSING_STATUSES = (
    DocumentProcessingStatus.QUEUED,
    DocumentProcessingStatus.IN_PROGRESS,
)


class JobType(StrEnum):
    DOCUMENT_INGESTION = "DOCUMENT_INGESTION"
    DOCUMENT_DELETION = "DOCUMENT_DELETION"
    DOCUMENT_SUMMARY = "DOCUMENT_SUMMARY"
    WBS_GENERATION = "WBS_GENERATION"
    WBS_VALIDATION = "WBS_VALIDATION"
    EXPORT = "EXPORT"


class IngestionStage(StrEnum):
    QUEUED = "QUEUED"
    SCANNING = "SCANNING"
    EXTRACTING = "EXTRACTING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    PERSISTING = "PERSISTING"
    ACTIVATING = "ACTIVATING"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DeletionStage(StrEnum):
    QUEUED = "QUEUED"
    DELETING_OBJECTS = "DELETING_OBJECTS"
    RETRY_WAIT = "RETRY_WAIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DispatchStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    DEAD = "DEAD"


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    external_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        Index("ix_tenant_memberships_role_tenant_user", "role", "tenant_id", "user_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default=MembershipRole.EDITOR)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.ACTIVE)


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant_project", "tenant_id", "project_id"),
        Index("ix_documents_upload_fingerprint", "tenant_id", "upload_sha256", "size_bytes"),
        UniqueConstraint("id", "tenant_id", "project_id", name="uq_documents_scope"),
        ForeignKeyConstraint(
            ["current_processing_run_id", "tenant_id", "project_id", "id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_documents_active_run_scope",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["deletion_job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_documents_deletion_job_scope",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint(
            "processing_status IS NULL OR processing_status IN "
            "('QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_documents_processing_status",
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR length(content_sha256) = 64",
            name="ck_documents_content_sha256",
        ),
        CheckConstraint(
            "lifecycle_status IN ('ACTIVE', 'DELETING', 'DELETED')",
            name="ck_documents_lifecycle_status",
        ),
        CheckConstraint(
            "(lifecycle_status = 'ACTIVE' AND deletion_requested_at IS NULL "
            "AND vectors_hidden_at IS NULL AND deletion_completed_at IS NULL) OR "
            "(lifecycle_status = 'DELETING' AND deletion_requested_at IS NOT NULL "
            "AND vectors_hidden_at IS NOT NULL AND deletion_completed_at IS NULL) OR "
            "(lifecycle_status = 'DELETED' AND deletion_requested_at IS NOT NULL "
            "AND vectors_hidden_at IS NOT NULL AND deletion_completed_at IS NOT NULL)",
            name="ck_documents_deletion_lifecycle",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), default=DocumentKind.PROJECT)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(600), unique=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    upload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_processing_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    processing_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), default=DocumentLifecycleStatus.ACTIVE, nullable=False
    )
    deletion_job_id: Mapped[UUID | None] = mapped_column(nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    vectors_hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DocumentProcessingRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_runs_document_scope",
        ),
        ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_runs_job_scope",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "project_id",
            "document_id",
            name="uq_runs_scope",
        ),
        UniqueConstraint(
            "document_id",
            "document_content_sha256",
            "extractor_name",
            "extractor_version",
            "chunker_version",
            "embedding_provider",
            "embedding_model",
            "embedding_model_revision",
            "embedding_dimensions",
            "embedding_formatting_version",
            name="uq_runs_idempotency",
        ),
        Index(
            "ix_runs_scope_history",
            "tenant_id",
            "project_id",
            "document_id",
            "created_at",
        ),
        Index(
            "uq_runs_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'IN_PROGRESS')"),
            sqlite_where=text("status IN ('QUEUED', 'IN_PROGRESS')"),
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_runs_status",
        ),
        CheckConstraint("embedding_dimensions = 384", name="ck_runs_embedding_dimensions"),
        CheckConstraint(
            "length(document_content_sha256) = 64",
            name="ck_runs_document_content_sha256",
        ),
        CheckConstraint(
            "((document_content_sha256 IS NULL AND extractor_name IS NULL "
            "AND extractor_version IS NULL AND chunker_version IS NULL "
            "AND embedding_provider IS NULL AND embedding_model IS NULL "
            "AND embedding_model_revision IS NULL AND embedding_dimensions IS NULL "
            "AND embedding_formatting_version IS NULL) OR "
            "(document_content_sha256 IS NOT NULL AND extractor_name IS NOT NULL "
            "AND extractor_version IS NOT NULL AND chunker_version IS NOT NULL "
            "AND embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_model_revision IS NOT NULL AND embedding_dimensions IS NOT NULL "
            "AND embedding_formatting_version IS NOT NULL) OR "
            "(status = 'COMPLETED' AND document_content_sha256 IS NOT NULL "
            "AND extractor_name IS NOT NULL AND extractor_version IS NOT NULL "
            "AND embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
            "AND embedding_dimensions IS NOT NULL AND chunker_version IS NULL "
            "AND embedding_model_revision IS NULL "
            "AND embedding_formatting_version IS NULL))",
            name="ck_runs_identity_state",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR document_content_sha256 IS NOT NULL",
            name="ck_runs_completed_identity",
        ),
        CheckConstraint(
            "current_stage IS NULL OR current_stage IN "
            "('QUEUED', 'SCANNING', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', "
            "'PERSISTING', 'ACTIVATING', 'RETRY_WAIT', 'COMPLETED', 'FAILED')",
            name="ck_runs_current_stage",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_runs_attempt_count_nonnegative"),
        CheckConstraint(
            "page_count >= 0 AND worksheet_count >= 0 AND block_count >= 0 AND chunk_count >= 0",
            name="ck_runs_counts_nonnegative",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    document_content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extractor_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    embedding_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_formatting_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    worksheet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    block_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warning_codes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False
    )


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_chunks_run_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("processing_run_id", "ordinal", name="uq_chunks_run_ordinal"),
        Index(
            "ix_chunks_scope",
            "tenant_id",
            "project_id",
            "document_id",
            "processing_run_id",
        ),
        CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        CheckConstraint("token_count > 0", name="ck_chunks_token_count_positive"),
        CheckConstraint("length(content_sha256) = 64", name="ck_chunks_content_sha256"),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_chunks_page_number_positive",
        ),
        CheckConstraint(
            "(row_start IS NULL AND row_end IS NULL) OR (row_start > 0 AND row_end >= row_start)",
            name="ck_chunks_row_range",
        ),
    )

    processing_run_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    block_type: Mapped[str] = mapped_column(String(40), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worksheet_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    row_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), default=dict, nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(384).with_variant(JSON(), "sqlite"), nullable=False
    )


class DocumentSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_summaries"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "document_id", name="uq_summary_document_scope"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)


class WbsTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wbs_templates"
    __table_args__ = (UniqueConstraint("id", "tenant_id", name="uq_template_tenant_scope"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(600), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_tenant_project", "tenant_id", "project_id"),
        UniqueConstraint("id", "tenant_id", "project_id", name="uq_jobs_scope"),
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_job_workflow_scope",
            use_alter=True,
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress_range"),
        CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count_nonnegative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    workflow_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=ProcessingStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class JobDispatchOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "job_dispatch_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_dispatch_outbox_job_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_dispatch_outbox_run_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "job_id",
            "processing_run_id",
            "task_name",
            name="uq_dispatch_outbox_delivery",
        ),
        Index(
            "ix_dispatch_outbox_pending",
            "tenant_id",
            "status",
            "available_at",
            "created_at",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'DEAD')",
            name="ck_dispatch_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_dispatch_outbox_attempt_count_nonnegative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    processing_run_id: Mapped[UUID] = mapped_column(nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=DispatchStatus.PENDING, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DocumentDeletionOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_deletion_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_deletion_outbox_document_scope",
        ),
        ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_deletion_outbox_job_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_id", "task_name", name="uq_deletion_outbox_delivery"),
        Index(
            "ix_deletion_outbox_pending",
            "tenant_id",
            "status",
            "available_at",
            "created_at",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'DEAD')",
            name="ck_deletion_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_deletion_outbox_attempt_count_nonnegative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=DispatchStatus.PENDING, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class WbsVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wbs_versions"
    __table_args__ = (
        Index("ix_wbs_versions_tenant_project", "tenant_id", "project_id"),
        UniqueConstraint("id", "tenant_id", "project_id", name="uq_wbs_project_scope"),
        ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_wbs_workflow_scope",
            use_alter=True,
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    generation_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    workflow_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    tree: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scope_coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ValidationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "validation_runs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "wbs_version_id", name="uq_validation_wbs_scope"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    wbs_version_id: Mapped[UUID] = mapped_column(ForeignKey("wbs_versions.id"), index=True)
    wbs_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wbs_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ProcessingStatus.QUEUED)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExportFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "export_files"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    wbs_version_id: Mapped[UUID] = mapped_column(ForeignKey("wbs_versions.id"))
    format: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=ProcessingStatus.QUEUED)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
