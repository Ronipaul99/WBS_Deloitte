from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.domain import DocumentResponse, JobResponse, ProjectResponse, TemplateResponse
from app.schemas.external_summary_tracking import ExternalSummaryStatus


class ResolveDocument(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    selected_project_id: UUID


class WorkflowCandidate(BaseModel):
    workflow_id: UUID | None
    document_id: UUID
    project_id: UUID
    project_name: str
    file_name: str
    stage: str
    updated_at: datetime
    requires_project_switch: bool


class ResolveResponse(BaseModel):
    disposition: Literal[
        "NEW", "MATCH", "MULTIPLE_MATCHES", "UPLOAD_PENDING", "TEMPORARILY_UNAVAILABLE"
    ]
    candidates: list[WorkflowCandidate] = Field(default_factory=list)
    upload_handle: UUID | None = None


class WorkflowState(BaseModel):
    workflow_id: UUID
    project_id: UUID
    document_id: UUID
    checkpoint_revision: int
    stage: Literal[
        "DOCUMENT_READY",
        "INGESTING",
        "INGESTED",
        "SUMMARIZING",
        "SUMMARY_REVIEW",
        "SUMMARY_APPROVED",
        "GENERATING",
        "WBS_READY",
        "VALIDATING",
        "VALIDATED",
        "FAILED",
        "CANCELLED",
    ]
    resume_screen: Literal[
        "checkpoint", "doc_processing", "doc_summary", "analyzing", "results", "validation"
    ]
    project: ProjectResponse
    document: DocumentResponse
    template: TemplateResponse | None = None
    processing_run_id: UUID | None = None
    ingestion_job_id: UUID | None = None
    summary_id: UUID | None = None
    summary_revision: int | None = None
    summary_job_id: UUID | None = None
    external_summary: ExternalSummaryStatus | None = None
    generation_job_id: UUID | None = None
    wbs_version_id: UUID | None = None
    validation_id: UUID | None = None
    validation_stale: bool = False
    source_requires_processing: bool = False
    input_compatibility: Literal["CURRENT", "CHANGED", "UNKNOWN"] = "UNKNOWN"
    job: JobResponse | None = None
    failed_stage: Literal["ingestion", "summary", "generation", "validation"] | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class UploadWorkflowResponse(BaseModel):
    disposition: Literal["CREATED", "REUSED", "UPLOAD_PENDING"]
    workflow: WorkflowState | None = None
    upload_handle: UUID | None = None


class ForkWorkflow(BaseModel):
    template_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
