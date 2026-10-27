"""Step 8 allowlisted artifacts. No raw requests, transcripts or model confidence."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.contracts import EvidenceReference, FactBatch, TenderCategory
from app.services.agents.evidence_types import BatchCompletion, ReadingBatch, digest
from app.services.llm.contracts import Contract, Identity, Sha256, Usage, unique


class AnalystPolicy(Contract):
    version: Literal["analyst_policy.v1"] = "analyst_policy.v1"
    max_tool_rounds: Annotated[int, Field(strict=True, ge=0, le=3)] = 2
    max_gap_rounds: Annotated[int, Field(strict=True, ge=0, le=3)] = 1
    max_register_entries: Annotated[int, Field(strict=True, ge=1, le=5000)] = 2500
    max_register_bytes: Annotated[int, Field(strict=True, ge=1024, le=8000000)] = 4000000


class FindingAlias(Contract):
    origin_sha256: Sha256
    proposed_id: Identity
    stable_id: Identity


class ExtractionRecord(Contract):
    version: Literal["extraction.v1"] = "extraction.v1"
    binding: Sha256
    origin_sha256: Sha256
    findings: FactBatch
    evidence: Annotated[tuple[EvidenceReference, ...], Field(max_length=128)] = ()
    aliases: Annotated[tuple[FindingAlias, ...], Field(max_length=200)] = ()
    no_facts_reason: Literal["irrelevant_material", "no_extractable_tender_facts"] | None = None
    semantic_support: Literal["analyst_asserted_not_independently_verified"] = (
        "analyst_asserted_not_independently_verified"
    )

    @model_validator(mode="after")
    def links(self):
        facts, requirements = self.findings.facts, self.findings.requirements
        if bool(facts or requirements) == (self.no_facts_reason is not None):
            raise ValueError("extraction outcome missing")
        evidence = {e.evidence_id for e in self.evidence}
        unique(tuple(e.evidence_id for e in self.evidence))
        ids = {f.fact_id for f in facts} | {r.requirement_id for r in requirements}
        if {i for f in facts + requirements for i in f.evidence_ids} != evidence:
            raise ValueError("extraction evidence links mismatch")
        if any(not set(r.dependency_ids) <= ids for r in requirements):
            raise ValueError("extraction dependency missing")
        unique(tuple((a.origin_sha256, a.proposed_id) for a in self.aliases))
        if any(
            a.origin_sha256 != self.origin_sha256 or a.stable_id not in ids for a in self.aliases
        ):
            raise ValueError("extraction alias mismatch")
        if {a.stable_id for a in self.aliases} != ids:
            raise ValueError("extraction alias missing")
        return self


class AnalystBatch(Contract):
    version: Literal["analyst_batch.v1"] = "analyst_batch.v1"
    batch: ReadingBatch
    extraction: ExtractionRecord
    completion: BatchCompletion

    @model_validator(mode="after")
    def bound_completion(self):
        if (
            self.batch.blocked_reason is not None
            or self.extraction.origin_sha256 != digest(self.batch)
            or self.completion.batch_sha256 != digest(self.batch)
            or self.completion.inventory_sha256 != self.batch.inventory_sha256
            or self.completion.primary_chunk_ids != self.batch.primary_chunk_ids
            or self.completion.artifact_sha256 != digest(self.extraction)
        ):
            raise ValueError("analyst completion binding mismatch")
        return self


class GapFinding(Contract):
    category: TenderCategory
    state: Literal[
        "unknown_not_searched",
        "not_found_within_allowance",
        "conflicting",
        "incomplete_reading",
        "budget_exhausted",
        "search_unavailable",
        "candidate_found_unverified",
    ]
    absence_proven: Literal[False] = False
    analyst_reported_unresolved: bool = False


class GapRecord(Contract):
    version: Literal["analyst_gap.v1"] = "analyst_gap.v1"
    binding: Sha256
    inventory_sha256: Sha256
    round: Annotated[int, Field(strict=True, ge=0, le=2)]
    requested_categories: Annotated[tuple[TenderCategory, ...], Field(min_length=1, max_length=13)]
    extraction: ExtractionRecord | None = None
    outcome: Literal["completed", "budget_exhausted", "blocked"]
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def honest(self):
        unique(self.requested_categories)
        if (self.outcome == "completed") != (self.extraction is not None):
            raise ValueError("gap outcome mismatch")
        if self.extraction and self.extraction.binding != self.binding:
            raise ValueError("gap binding mismatch")
        return self


class RegisterPage(Contract):
    version: Literal["fact_register_page.v1"] = "fact_register_page.v1"
    binding: Sha256
    inventory_sha256: Sha256
    level: Literal["section", "document"]
    section_id: Sha256 | None = None
    index: Annotated[int, Field(strict=True, ge=0, le=10000)]
    previous_sha256: Sha256 | None = None
    findings: FactBatch
    evidence: Annotated[tuple[EvidenceReference, ...], Field(max_length=128)] = ()
    aliases: Annotated[tuple[FindingAlias, ...], Field(max_length=1000)] = ()
    inputs_sha256: Sha256

    @model_validator(mode="after")
    def bounded(self):
        if (self.level == "section") != (self.section_id is not None):
            raise ValueError("register section identity mismatch")
        if len(self.findings.facts) + len(self.findings.requirements) > 100:
            raise ValueError("register page too many entries")
        evidence = {e.evidence_id for e in self.evidence}
        unique(tuple(e.evidence_id for e in self.evidence))
        ids = {f.fact_id for f in self.findings.facts} | {
            r.requirement_id for r in self.findings.requirements
        }
        if {
            i for f in self.findings.facts + self.findings.requirements for i in f.evidence_ids
        } != (evidence) or any(a.stable_id not in ids for a in self.aliases):
            raise ValueError("register links mismatch")
        if len(self.model_dump_json().encode()) > 200000:
            raise ValueError("register page exceeds bytes")
        return self


class RegisterSeal(Contract):
    version: Literal["fact_register.v1"] = "fact_register.v1"
    binding: Sha256
    inventory_sha256: Sha256
    inputs_sha256: Sha256
    root_sha256: Sha256 | None
    page_count: Annotated[int, Field(strict=True, ge=0, le=10000)]
    reading_complete: bool
    gaps: Annotated[tuple[GapFinding, ...], Field(min_length=13, max_length=13)]
    semantic_support: Literal["not_independently_verified"] = "not_independently_verified"

    @model_validator(mode="after")
    def seal(self):
        if bool(self.page_count) != (self.root_sha256 is not None):
            raise ValueError("register seal mismatch")
        if {g.category for g in self.gaps} != set(TenderCategory):
            raise ValueError("register requires every category")
        return self


class AnalystArtifact(Contract):
    """Nested in existing orchestration checkpoint; receipt and extraction commit together."""

    kind: Literal["analyst_batch.v1", "analyst_gap.v1", "fact_register_page.v1", "fact_register.v1"]
    payload: AnalystBatch | GapRecord | RegisterPage | RegisterSeal

    @model_validator(mode="after")
    def kind_and_bounds(self):
        if self.kind != self.payload.version:
            raise ValueError("analyst artifact kind mismatch")
        if len(self.model_dump_json().encode()) > 300000:
            raise ValueError("analyst artifact oversized")
        return self
