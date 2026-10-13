from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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


class JobType(StrEnum):
    DOCUMENT_SUMMARY = "DOCUMENT_SUMMARY"
    WBS_GENERATION = "WBS_GENERATION"
    WBS_VALIDATION = "WBS_VALIDATION"
    EXPORT = "EXPORT"


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


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"

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
    __table_args__ = (Index("ix_documents_tenant_project", "tenant_id", "project_id"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), default=DocumentKind.PROJECT)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(600), unique=True)


class DocumentSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_summaries"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), unique=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WbsTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wbs_templates"

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
    __table_args__ = (Index("ix_jobs_tenant_project", "tenant_id", "project_id"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default=ProcessingStatus.QUEUED)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WbsVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wbs_versions"
    __table_args__ = (Index("ix_wbs_versions_tenant_project", "tenant_id", "project_id"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    generation_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    tree: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scope_coverage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ValidationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "validation_runs"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    wbs_version_id: Mapped[UUID] = mapped_column(ForeignKey("wbs_versions.id"), index=True)
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
