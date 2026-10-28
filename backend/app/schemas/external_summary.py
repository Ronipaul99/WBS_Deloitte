"""Submission-only contracts. No shared-job lookup or result contract lives here."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class SubmissionBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    document_id: UUID


class SubmissionAcknowledgement(SubmissionBody):
    job_id: UUID
    job_type: Literal["DOCUMENT_SUMMERIZATION"]
    # RUNNING is the only supplied/qualified acknowledgement status so far.
    status: Literal["RUNNING"]
    progress: int = Field(strict=True, ge=0, le=100)
    current_step: str | None = Field(max_length=120)
    attempt_count: int = Field(strict=True, ge=0, le=1000)
    error_code: str | None = Field(max_length=80)
    error_message: str | None = Field(max_length=500)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    result_url: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def check_metadata(self):
        expected = f"/api/v2.1/project-summary/jobs/{self.job_id}/result"
        if self.result_url is not None and self.result_url != expected:
            raise ValueError("Unsupported result path")
        if self.updated_at < self.created_at or any(
            ord(char) < 32 for char in (self.current_step or "")
        ):
            raise ValueError("Invalid acknowledgement metadata")
        if self.error_code is not None or self.error_message is not None:
            raise ValueError("Acknowledgement contains an upstream error")
        return self


class ExternalSubmissionResponse(BaseModel):
    execution_backend: Literal["external_summary"] = "external_summary"
    request_id: UUID
    job_id: UUID | None = None
    document_id: UUID
    job_type: Literal["DOCUMENT_SUMMERIZATION"] = "DOCUMENT_SUMMERIZATION"
    submission_state: str
    # These describe submission only; Step 2 must verify any acknowledged job.
    status: Literal["QUEUED", "UNAVAILABLE"]
    provider_status: Literal["RUNNING"] | None = None
    progress: int = 0
    current_step: str = "Summary submission awaiting verified job tracking"
    result_state: Literal["NOT_READY"] = "NOT_READY"
    summary_id: None = None
