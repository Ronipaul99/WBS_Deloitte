from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class TenantResponse(ORMModel):
    id: UUID
    name: str
    slug: str
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)


class UserResponse(ORMModel):
    id: UUID
    email: str
    display_name: str


class CurrentUserResponse(UserResponse):
    identity_providers: list[str] = Field(default_factory=list)
    can_change_password: bool = False
    can_manage_sessions: bool = False
    tenants: list[TenantResponse] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class ProjectResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    kind: str
    file_name: str
    content_type: str
    size_bytes: int
    lifecycle_status: str
    deletion_requested_at: datetime | None
    deletion_completed_at: datetime | None
    created_at: datetime


class DocumentDeletionStatusResponse(BaseModel):
    document_id: UUID
    job_id: UUID
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    attempt_count: int = Field(ge=0)
    lifecycle_status: str
    deletion_requested_at: datetime
    vectors_hidden_at: datetime
    deletion_completed_at: datetime | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class SummaryUpdate(BaseModel):
    summary_text: str | None = Field(default=None, max_length=50_000)
    key_points: list[str] | None = None
    requirements: list[dict[str, Any]] | None = None


class SummaryResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    document_id: UUID
    summary_text: str
    key_points: list[str]
    requirements: list[dict[str, Any]]
    is_approved: bool
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TemplateResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    name: str
    file_name: str
    content_type: str
    size_bytes: int
    is_active: bool
    created_at: datetime


class JobResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID | None
    workflow_id: UUID | None = None
    workflow_id: UUID | None = None
    job_type: str
    status: str
    progress: int
    current_step: str | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    result_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IngestionStatusResponse(BaseModel):
    job_id: UUID
    processing_run_id: UUID
    document_id: UUID
    status: str
    stage: str
    progress: int = Field(ge=0, le=100)
    attempt_count: int = Field(ge=0)
    maximum_attempts: int = Field(ge=1)
    page_count: int = Field(ge=0)
    worksheet_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    extractor_name: str | None
    extractor_version: str | None
    embedding_provider: str | None
    embedding_model: str | None
    embedding_model_revision: str | None
    warning_codes: list[str] = Field(default_factory=list)
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GenerationCreate(BaseModel):
    document_id: UUID
    template_id: UUID | None = None
    summary_id: UUID
    workflow_id: UUID | None = None
    regenerate: bool = False
    request_key: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class WbsVersionUpdate(BaseModel):
    tree: list[dict[str, Any]]
    scope_coverage: dict[str, Any] | None = None


class WbsVersionResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    generation_job_id: UUID | None
    version_number: int
    status: str
    tree: list[dict[str, Any]]
    scope_coverage: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ValidationResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    wbs_version_id: UUID
    status: str
    result: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExportCreate(BaseModel):
    format: Literal["json", "csv", "p6_xml"]


class ExportResponse(ORMModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    wbs_version_id: UUID
    format: str
    status: str
    file_name: str | None
    download_url: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    message: str
