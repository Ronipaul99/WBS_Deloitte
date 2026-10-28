"""Strict external-summary-v1. Canonical support is not semantic verification."""

import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.domain import SummaryResponse

KEYS = (
    "project_overview",
    "project_scope",
    "key_deliverables",
    "assumptions",
    "constraints",
    "exclusions",
    "milestones_timeline",
)
Page = Annotated[int, Field(strict=True, ge=1, le=100_000)]
Pages = Annotated[list[Page], Field(max_length=500)]


class ResultContract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class ResultCitation(ResultContract):
    chunk_id: UUID
    quote: str = Field(min_length=1, max_length=20_000)
    citation_number: int = Field(strict=True, ge=1, le=100)
    pages: Pages = Field(min_length=1)


class ResultReferences(ResultContract):
    label: str = Field(max_length=300)
    pages: Pages


SectionKey = Literal[
    "project_overview",
    "project_scope",
    "key_deliverables",
    "assumptions",
    "constraints",
    "exclusions",
    "milestones_timeline",
]


class ResultSection(ResultContract):
    id: str = Field(min_length=1, max_length=80)
    order: int = Field(strict=True, ge=1, le=7)
    key: SectionKey
    title: str = Field(min_length=1, max_length=160)
    badge: Literal["AI Draft"]
    subtitle: str = Field(max_length=200)
    content: str = Field(max_length=20_000)
    max_length: int = Field(strict=True, ge=1, le=20_000)
    source_references: ResultReferences
    question_id: str = Field(min_length=1, max_length=80)
    answer_status: Literal["answered", "insufficient_evidence"]
    evidence_context_truncated: bool = Field(strict=True)
    evidence_citations: list[ResultCitation] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_references(self):
        if len(self.content) > self.max_length:
            raise ValueError("Content exceeds advertised edit limit")
        numbers = [c.citation_number for c in self.evidence_citations]
        inline = {int(n) for n in re.findall(r"\[(\d+)\]", self.content)}
        if numbers != list(range(1, len(numbers) + 1)) or inline != set(numbers):
            raise ValueError("Invalid section-local citation numbering")
        pages = self.source_references.pages
        if len(pages) != len(set(pages)) or any(
            len(c.pages) != len(set(c.pages)) for c in self.evidence_citations
        ):
            raise ValueError("Duplicate pages")
        if set(pages) != {p for c in self.evidence_citations for p in c.pages}:
            raise ValueError("Unsupported section pages")
        if self.answer_status == "answered" and (not self.content.strip() or not numbers):
            raise ValueError("Answered content requires source citations")
        if self.answer_status == "insufficient_evidence" and numbers:
            raise ValueError("Unsupported insufficient-evidence citations")
        return self


class ResultDocumentInformation(ResultContract):
    filename: str = Field(min_length=1, max_length=255)
    file_size: str = Field(max_length=80)
    file_type: Literal["PDF"]
    extraction_confidence: (
        Annotated[int, Field(strict=True, ge=0, le=100)]
        | Annotated[float, Field(strict=True, ge=0, le=100)]
        | None
    )
    confidence_status: str = Field(max_length=500)


class ResultData(ResultContract):
    project_id: UUID
    document_id: UUID
    processing_run_id: UUID
    document_information: ResultDocumentInformation
    summary_sections: list[ResultSection] = Field(min_length=7, max_length=7)
    question_set_id: str = Field(min_length=1, max_length=100)
    llm_model: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def complete_sections(self):
        sections = self.summary_sections
        if (
            {s.key for s in sections} != set(KEYS)
            or len({s.id for s in sections}) != 7
            or {s.order for s in sections} != set(range(1, 8))
        ):
            raise ValueError("Incomplete or duplicate sections")
        return self


class ExternalSummaryResult(ResultContract):
    status: Literal["success"]
    message: str = Field(max_length=500)
    data: ResultData


class SectionEdit(ResultContract):
    id: str = Field(strict=True, min_length=1, max_length=80)
    key: SectionKey
    content: str = Field(strict=True, max_length=20_000)

    @field_validator("content")
    @classmethod
    def valid_content_encoding(cls, value):
        if "\x00" in value:
            raise ValueError("Unsupported text encoding")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Unsupported text encoding") from None
        return value


class StructuredSummaryPatch(ResultContract):
    format: Literal["external_summary_v1"]
    expected_revision: int = Field(strict=True, ge=1)
    sections: list[SectionEdit] = Field(max_length=7)

    @model_validator(mode="after")
    def unique_sections(self):
        if len({s.id for s in self.sections}) != len(self.sections) or len(
            {s.key for s in self.sections}
        ) != len(self.sections):
            raise ValueError("Duplicate section identity")
        return self


class StructuredSummaryApproval(ResultContract):
    format: Literal["external_summary_v1"]
    expected_revision: int = Field(strict=True, ge=1)


class StoredExternalSummary(ResultContract):
    schema_version: Literal["external-summary-v1"] = "external-summary-v1"
    content_state: Literal["generated_unreviewed", "edited_review_required"] = (
        "generated_unreviewed"
    )
    edit_schema_version: Literal["section-edits-v1"] = "section-edits-v1"
    current_sections: list[SectionEdit] = Field(default_factory=list, max_length=7)
    canonical_validation: Literal["exact_quotes_chunk_page_coverage"] = (
        "exact_quotes_chunk_page_coverage"
    )
    generated_result: ExternalSummaryResult

    @model_validator(mode="after")
    def valid_edits(self):
        original = {s.id: s for s in self.generated_result.data.summary_sections}
        seen = set()
        for edit in self.current_sections:
            section = original.get(edit.id)
            if (
                edit.id in seen
                or section is None
                or section.key != edit.key
                or len(edit.content) > section.max_length
            ):
                raise ValueError("Invalid current section edit")
            seen.add(edit.id)
        changed = any(e.content != original[e.id].content for e in self.current_sections)
        if changed != (self.content_state == "edited_review_required"):
            raise ValueError("Invalid content state")
        return self

    def current_content(self, section):
        return next(
            (s.content for s in self.current_sections if s.id == section.id), section.content
        )


class SummaryImportProvenance(ResultContract):
    request_id: UUID
    job_id: UUID
    processing_run_id: UUID
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported_revision: int = Field(ge=1)


class SummaryCapabilities(ResultContract):
    structured_review_available: Literal[True] = True
    can_generate_wbs: Literal[False] = False
    reason: Literal["REQUIREMENTS_CONTRACT_UNAVAILABLE"] = "REQUIREMENTS_CONTRACT_UNAVAILABLE"


class StructuredSummaryResponse(SummaryResponse):
    representation: Literal["external-summary-v1"] = "external-summary-v1"
    revision: int
    structured_summary: StoredExternalSummary
    provenance: SummaryImportProvenance
    capabilities: SummaryCapabilities = Field(default_factory=SummaryCapabilities)
