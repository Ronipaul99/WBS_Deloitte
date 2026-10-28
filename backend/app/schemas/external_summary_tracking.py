"""Metadata only; deliberately no request/result payload or imported content fields."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExternalSummaryStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    execution_backend: Literal["external_summary"] = "external_summary"
    request_id: UUID
    job_id: UUID | None
    document_id: UUID
    workflow_id: UUID
    job_type: Literal["DOCUMENT_SUMMERIZATION"] = "DOCUMENT_SUMMERIZATION"
    submission_state: str = Field(max_length=24)
    binding_state: Literal["PENDING", "WAITING_FOR_JOB", "VERIFIED", "UNAVAILABLE", "STALE"]
    status: Literal["QUEUED", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED", "UNAVAILABLE"]
    provider_status: str | None = Field(default=None, max_length=24)
    progress: int = Field(default=0, strict=True, ge=0, le=100)
    current_step: str | None = Field(default=None, max_length=120)
    attempt_count: int = Field(default=0, strict=True, ge=0)
    updated_at: datetime
    result_state: Literal["NOT_READY", "IMPORT_PENDING", "IMPORTED", "INVALID", "STALE"] = (
        "NOT_READY"
    )
    summary_id: UUID | None = None
    summary_revision: int | None = Field(default=None, ge=1)
    error_code: str | None = None
    error_message: str | None = None
    can_retry: Literal[False] = False
    can_cancel: Literal[False] = False

    @model_validator(mode="after")
    def import_identity(self):
        if self.result_state == "IMPORTED":
            if (
                self.summary_id is None
                or self.summary_revision is None
                or self.status != "COMPLETED"
                or self.progress != 100
                or self.binding_state != "VERIFIED"
            ):
                raise ValueError("Imported status requires a committed matching summary")
        elif self.summary_id is not None or self.summary_revision is not None:
            raise ValueError("Unimported status cannot expose summary readiness")
        return self
