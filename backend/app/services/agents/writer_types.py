"""Step 9 bounded intermediate artifacts, without publication/verification authority."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.analyst_types import RegisterSeal
from app.services.agents.contracts import (
    SupportedClaim,
    SupportedSummaryContent,
    TenderCategory,
    WorkflowInput,
    WritingOmission,
)
from app.services.llm.contracts import Contract, Identity, Sha256, unique


class WriterPolicy(Contract):
    version: Literal["writer_policy.v1"] = "writer_policy.v1"
    fragment_entries: Annotated[int, Field(strict=True, ge=1, le=32)] = 12
    max_fragments: Annotated[int, Field(strict=True, ge=1, le=120)] = 100
    max_register_bytes: Annotated[int, Field(strict=True, ge=1024, le=8000000)] = 8000000
    max_draft_bytes: Annotated[int, Field(strict=True, ge=1024, le=700000)] = 600000


class WritingPartition(Contract):
    index: Annotated[int, Field(strict=True, ge=0, le=119)]
    category: TenderCategory
    finding_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def distinct(self):
        unique(self.finding_ids)
        return self


class InclusionPage(Contract):
    """Accounting of prose references, not semantic understanding or register retention."""

    version: Literal["writer_inclusion.v1"] = "writer_inclusion.v1"
    binding: Sha256
    stage: Literal["fragment", "final_prose"]
    index: Annotated[int, Field(strict=True, ge=0, le=10000)]
    previous_sha256: Sha256 | None = None
    available: Annotated[tuple[Identity, ...], Field(max_length=100)]
    included: Annotated[tuple[Identity, ...], Field(max_length=100)]
    omitted: Annotated[tuple[WritingOmission, ...], Field(max_length=100)]

    @model_validator(mode="after")
    def partition(self):
        omitted = tuple(o.finding_id for o in self.omitted)
        unique(self.available)
        unique(self.included + omitted)
        if set(self.included + omitted) != set(self.available):
            raise ValueError("inclusion manifest must account for every available finding")
        return self


class FragmentDraft(Contract):
    version: Literal["writer_fragment.v1"] = "writer_fragment.v1"
    binding: Sha256
    partition: WritingPartition
    claims: Annotated[tuple[SupportedClaim, ...], Field(max_length=12)]
    key_points: Annotated[tuple[SupportedClaim, ...], Field(max_length=3)]
    inclusion: InclusionPage

    @model_validator(mode="after")
    def accounting(self):
        if (
            self.inclusion.binding != self.binding
            or self.inclusion.stage != "fragment"
            or self.inclusion.index != self.partition.index
            or self.inclusion.available != self.partition.finding_ids
            or set(self.inclusion.included)
            != {i for c in self.claims + self.key_points for i in c.fact_ids + c.requirement_ids}
        ):
            raise ValueError("fragment accounting mismatch")
        unique(tuple(c.claim_id for c in self.claims + self.key_points))
        return self


class ReadingMetadata(Contract):
    coverage_sha256: Sha256
    primary_count: Annotated[int, Field(strict=True, ge=1, le=100000)]
    processed_count: Annotated[int, Field(strict=True, ge=0, le=100000)]
    failed_count: Annotated[int, Field(strict=True, ge=0, le=100000)]
    unprocessed_count: Annotated[int, Field(strict=True, ge=0, le=100000)]
    truncated: bool
    complete: bool

    @model_validator(mode="after")
    def honest(self):
        if self.processed_count + self.failed_count + self.unprocessed_count != self.primary_count:
            raise ValueError("reading metadata partition mismatch")
        if self.complete and (self.failed_count or self.unprocessed_count or self.truncated):
            raise ValueError("partial reading cannot become complete")
        return self


class IntermediateDraft(Contract):
    version: Literal["writer_draft.v1"] = "writer_draft.v1"
    prompt_version: Literal["summary_writer.v1"] = "summary_writer.v1"
    binding: Sha256
    workflow: WorkflowInput
    register_seal: RegisterSeal
    content: SupportedSummaryContent
    reading: ReadingMetadata
    inclusion_root_sha256: Sha256 | None
    inclusion_page_count: Annotated[int, Field(strict=True, ge=0, le=10000)]
    state: Literal["intermediate_unverified"] = "intermediate_unverified"

    @model_validator(mode="after")
    def truthful(self):
        if bool(self.inclusion_page_count) != (self.inclusion_root_sha256 is not None):
            raise ValueError("inclusion seal mismatch")
        if self.reading.complete != self.register_seal.reading_complete:
            raise ValueError("reading/register metadata mismatch")
        return self


class WriterArtifact(Contract):
    kind: Literal["writer_fragment.v1", "writer_inclusion.v1", "writer_draft.v1"]
    payload: FragmentDraft | InclusionPage | IntermediateDraft

    @model_validator(mode="after")
    def kind_and_bound(self):
        if self.kind != self.payload.version:
            raise ValueError("writer artifact kind mismatch")
        if len(self.model_dump_json().encode()) > 800000:
            raise ValueError("writer artifact exceeds storage bound")
        return self
