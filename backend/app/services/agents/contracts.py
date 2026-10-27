"""Bounded summary/review data contracts, independent of graph/provider runtimes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.llm.contracts import (
    Contract,
    Count,
    Flag,
    Identity,
    Label,
    ModelProfileSnapshot,
    Positive,
    Sha256,
    Text,
    Usage,
    Version,
    unique,
)


class SourceScope(Contract):
    tenant_id: Identity
    project_id: Identity
    document_id: Identity
    processing_run_id: Identity
    source_sha256: Sha256


class WorkflowInput(Contract):
    """Server-created only. A completion assertion is not a database authorization check."""

    workflow_run_id: Identity
    scope: SourceScope
    processing_state: Literal["completed"]
    requested_by: Identity
    profile: ModelProfileSnapshot
    workflow_version: Version
    prompt_version: Version
    output_schema_version: Literal["tender_summary.v1"]

    @model_validator(mode="after")
    def scoped_profile(self) -> WorkflowInput:
        if self.profile.tenant_id != self.scope.tenant_id:
            raise ValueError("profile belongs to another tenant")
        return self


class EvidenceReference(Contract):
    evidence_id: Identity
    scope: SourceScope
    chunk_id: Identity
    chunk_sha256: Sha256
    physical_pages: Annotated[tuple[Positive, ...], Field(min_length=1, max_length=500)]
    heading_path: Annotated[tuple[Label, ...], Field(max_length=16)] = ()
    exact_quote: Text
    char_start: Count
    char_end: Positive
    offset_unit: Literal["unicode_codepoint"] = "unicode_codepoint"
    printed_page_label: Label | None = None
    table_id: Label | None = None
    row_id: Label | None = None

    @model_validator(mode="after")
    def valid_locator(self) -> EvidenceReference:
        if self.char_end - self.char_start != len(self.exact_quote):
            raise ValueError("quote length must match Unicode code-point half-open range")
        if tuple(sorted(set(self.physical_pages))) != self.physical_pages:
            raise ValueError("physical pages must be sorted and unique")
        if self.row_id is not None and self.table_id is None:
            raise ValueError("row identity requires a table identity")
        return self


class TenderCategory(StrEnum):
    OVERVIEW = "overview"
    ISSUER_PARTIES = "issuer_parties"
    SCOPE_DELIVERABLES = "scope_deliverables"
    CAPACITY_UNITS = "capacity_units"
    ELIGIBILITY = "eligibility"
    TECHNICAL = "technical"
    DATES_MILESTONES = "dates_milestones"
    FINANCIAL_COMMERCIAL = "financial_commercial"
    SECURITIES_EMD_PBG = "securities_emd_pbg"
    SUBMISSION_EVALUATION_AWARD = "submission_evaluation_award"
    OBLIGATIONS_CONDITIONS = "obligations_conditions"
    EXCLUSIONS = "exclusions"
    RISKS_CONFLICTS_QUESTIONS = "risks_conflicts_questions"


class CriticalFactClass(StrEnum):
    OTHER = "other"
    ISSUER = "issuer"
    CAPACITY = "capacity"
    UNIT_COUNT = "unit_count"
    ELIGIBILITY = "eligibility"
    DATE = "date"
    FINANCIAL_VALUE = "financial_value"
    EMD = "emd"
    PBG = "pbg"
    CONDITIONAL_RULE = "conditional_rule"


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    UNSUPPORTED = "unsupported"


EvidenceIDs = Annotated[tuple[Identity, ...], Field(max_length=32)]


class Fact(Contract):
    fact_id: Identity
    category: TenderCategory
    critical_class: CriticalFactClass
    status: FindingStatus
    statement: Text
    original_value: Label | None = None
    # Exact decimal string: never a binary floating-point financial value.
    normalized_number: (
        Annotated[str, Field(strict=True, max_length=80, pattern=r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")]
        | None
    ) = None
    unit: Label | None = None
    currency: Annotated[str, Field(strict=True, pattern=r"^[A-Z]{3}$")] | None = None
    conditions: Annotated[tuple[Text, ...], Field(max_length=16)] = ()
    alternatives: Annotated[tuple[Label, ...], Field(max_length=8)] = ()
    evidence_ids: EvidenceIDs = ()

    @model_validator(mode="after")
    def honest_support(self) -> Fact:
        unique(self.evidence_ids)
        unique(self.alternatives)
        if self.status == FindingStatus.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported fact requires evidence")
        if self.status == FindingStatus.UNKNOWN and (
            self.original_value is not None
            or self.normalized_number is not None
            or self.unit is not None
            or self.currency is not None
            or self.evidence_ids
            or self.conditions
        ):
            raise ValueError("unknown fact cannot assert a sourced value")
        if self.status == FindingStatus.CONFLICTING:
            if len(self.alternatives) < 2 or not self.evidence_ids:
                raise ValueError("conflict requires alternatives and source evidence")
        elif self.alternatives:
            raise ValueError("alternatives require an explicit conflicting status")
        if self.normalized_number is not None and self.original_value is None:
            raise ValueError("normalized value requires its original representation")
        return self


class Requirement(Contract):
    requirement_id: Identity
    display_code: Label
    obligation: Text
    status: FindingStatus
    responsible_party: Label | None = None
    deliverable: Text | None = None
    acceptance_criteria: Annotated[tuple[Text, ...], Field(max_length=16)] = ()
    dependency_ids: Annotated[tuple[Identity, ...], Field(max_length=32)] = ()
    conditions: Annotated[tuple[Text, ...], Field(max_length=16)] = ()
    evidence_ids: EvidenceIDs = ()

    @model_validator(mode="after")
    def supported_obligation(self) -> Requirement:
        unique(self.evidence_ids)
        unique(self.dependency_ids)
        if self.requirement_id in self.dependency_ids:
            raise ValueError("requirement cannot depend on itself")
        if self.status == FindingStatus.SUPPORTED and not self.evidence_ids:
            raise ValueError("supported obligation requires evidence")
        if self.dependency_ids and not self.evidence_ids:
            raise ValueError("dependencies require source evidence")
        if self.status == FindingStatus.UNKNOWN and (
            self.responsible_party is not None
            or self.deliverable is not None
            or self.acceptance_criteria
            or self.dependency_ids
            or self.evidence_ids
            or self.conditions
        ):
            raise ValueError("unknown obligation cannot assert sourced attributes")
        return self


class FactBatch(Contract):
    """Analyst output; scope and evidence locators are never model-selected."""

    facts: Annotated[tuple[Fact, ...], Field(max_length=100)] = ()
    requirements: Annotated[tuple[Requirement, ...], Field(max_length=100)] = ()
    unresolved_categories: Annotated[tuple[TenderCategory, ...], Field(max_length=13)] = ()

    @model_validator(mode="after")
    def stable_claim_ids(self) -> FactBatch:
        unique(
            tuple(item.fact_id for item in self.facts)
            + tuple(item.requirement_id for item in self.requirements)
        )
        unique(self.unresolved_categories)
        return self


class AnalystQuote(Contract):
    """Untrusted quote proposal; trusted Step 7 code supplies the final locator."""

    quote_id: Identity
    chunk_id: Identity
    char_start: Count
    char_end: Positive
    exact_quote: Text

    @model_validator(mode="after")
    def range_length(self):
        if self.char_end - self.char_start != len(self.exact_quote):
            raise ValueError("quote range must use Unicode code points")
        return self


class AnalystContent(FactBatch):
    """Model-writable extraction only. IDs are proposals, not durable identities."""

    quotes: Annotated[tuple[AnalystQuote, ...], Field(max_length=128)] = ()
    no_facts_reason: Literal["irrelevant_material", "no_extractable_tender_facts"] | None = None

    @model_validator(mode="after")
    def explicit_outcome(self):
        unique(tuple(q.quote_id for q in self.quotes))
        if bool(self.facts or self.requirements) == (self.no_facts_reason is not None):
            raise ValueError("empty extraction requires an explicit no-facts reason")
        quotes = {q.quote_id for q in self.quotes}
        used = {q for item in self.facts + self.requirements for q in item.evidence_ids}
        if used != quotes:
            raise ValueError("extraction must link exactly its supplied quotes")
        return self


ChunkIDs = Annotated[tuple[Identity, ...], Field(max_length=100_000)]


class SectionCoverage(Contract):
    section_id: Label
    status: Literal["processed", "partial", "unprocessed", "failed"]


class CoverageReport(Contract):
    primary_chunk_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=100_000)]
    processed_chunk_ids: ChunkIDs = ()
    unprocessed_chunk_ids: ChunkIDs = ()
    failed_chunk_ids: ChunkIDs = ()
    sections: Annotated[tuple[SectionCoverage, ...], Field(min_length=1, max_length=10_000)]
    unresolved_categories: Annotated[tuple[TenderCategory, ...], Field(max_length=13)] = ()
    truncated: Flag = False

    @model_validator(mode="after")
    def partition_inventory(self) -> CoverageReport:
        unique(self.primary_chunk_ids)
        groups = self.processed_chunk_ids + self.unprocessed_chunk_ids + self.failed_chunk_ids
        unique(groups)
        if set(groups) != set(self.primary_chunk_ids):
            raise ValueError("each primary chunk must be accounted for exactly once")
        unique(tuple(section.section_id for section in self.sections))
        unique(self.unresolved_categories)
        return self

    @property
    def complete(self) -> bool:
        """Reading completeness, never semantic extraction accuracy."""
        return (
            not self.truncated
            and not self.unprocessed_chunk_ids
            and not self.failed_chunk_ids
            and all(section.status == "processed" for section in self.sections)
        )


class VerificationFinding(Contract):
    claim_id: Identity
    severity: Literal["info", "warning", "critical"]
    code: Literal[
        "citation_invalid",
        "scope_mismatch",
        "unsupported",
        "contradicted",
        "numeric_mismatch",
        "condition_missing",
        "coverage_incomplete",
    ]
    detail: Text
    evidence_ids: EvidenceIDs = ()


class VerificationContent(Contract):
    """Model verdict inputs; trusted code binds revision, repair count and final gate."""

    checked_claim_ids: Annotated[tuple[Identity, ...], Field(max_length=5000)]
    findings: Annotated[tuple[VerificationFinding, ...], Field(max_length=5000)] = ()

    @model_validator(mode="after")
    def checked_references(self) -> VerificationContent:
        unique(self.checked_claim_ids)
        if any(item.claim_id not in self.checked_claim_ids for item in self.findings):
            raise ValueError("finding references an unchecked claim")
        return self


class VerificationReport(VerificationContent):
    revision_id: Identity
    repair_pass: Annotated[int, Field(strict=True, ge=0, le=1)] = 0
    verdict: Literal["review_required", "quality_blocked"]

    @model_validator(mode="after")
    def critical_gate(self) -> VerificationReport:
        if any(item.severity == "critical" for item in self.findings):
            if self.verdict != "quality_blocked":
                raise ValueError("critical failures block acceptance")
        return self


class SummarySection(Contract):
    category: TenderCategory
    status: FindingStatus
    text: Text
    fact_ids: Annotated[tuple[Identity, ...], Field(max_length=1000)] = ()
    requirement_ids: Annotated[tuple[Identity, ...], Field(max_length=1000)] = ()


class SummaryContent(Contract):
    """Model-writable writer output. Scope/provenance/evidence locators stay server-owned.

    References must be resolved against the supplied fact register before assembly.
    Source validity and entailment are later-step responsibilities.
    """

    executive_overview: Text
    sections: Annotated[tuple[SummarySection, ...], Field(min_length=13, max_length=13)]
    key_points: Annotated[tuple[Text, ...], Field(max_length=30)] = ()

    @model_validator(mode="after")
    def required_categories(self) -> SummaryContent:
        if {section.category for section in self.sections} != set(TenderCategory):
            raise ValueError("every tender category must occur exactly once")
        return self


class TenderSummary(SummaryContent):
    revision_id: Identity
    workflow: WorkflowInput
    generated_at: datetime
    review_state: Literal["draft"] = "draft"
    facts: Annotated[tuple[Fact, ...], Field(max_length=2500)] = ()
    requirements: Annotated[tuple[Requirement, ...], Field(max_length=2500)] = ()
    evidence: Annotated[tuple[EvidenceReference, ...], Field(max_length=5000)] = ()
    coverage: CoverageReport
    verification: VerificationReport | None = None
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def coherent_draft(self) -> TenderSummary:
        if self.generated_at.utcoffset() is None:
            raise ValueError("generation timestamp requires a timezone")
        fact_ids = tuple(item.fact_id for item in self.facts)
        req_ids = tuple(item.requirement_id for item in self.requirements)
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        unique(fact_ids + req_ids + evidence_ids)
        unique(tuple(item.display_code for item in self.requirements))
        facts_by_id = {item.fact_id: item for item in self.facts}
        requirements_by_id = {item.requirement_id: item for item in self.requirements}
        for item in self.evidence:
            if item.scope != self.workflow.scope:
                raise ValueError("evidence is outside the pinned source scope")
            if item.chunk_id not in self.coverage.primary_chunk_ids:
                raise ValueError("evidence chunk is outside the source inventory")
        for claim in self.facts + self.requirements:
            if not set(claim.evidence_ids) <= set(evidence_ids):
                raise ValueError("claim references missing evidence")
        for requirement in self.requirements:
            if not set(requirement.dependency_ids) <= set(req_ids):
                raise ValueError("requirement references missing dependency")
        for section in self.sections:
            unique(section.fact_ids)
            unique(section.requirement_ids)
            if not set(section.fact_ids) <= set(fact_ids) or not set(
                section.requirement_ids
            ) <= set(req_ids):
                raise ValueError("section references a missing claim")
            if section.status == FindingStatus.SUPPORTED and not (
                section.fact_ids or section.requirement_ids
            ):
                raise ValueError("supported section requires grounded claim references")
            if section.status == FindingStatus.SUPPORTED and any(
                item.status != FindingStatus.SUPPORTED
                for item in (
                    *(facts_by_id[key] for key in section.fact_ids),
                    *(requirements_by_id[key] for key in section.requirement_ids),
                )
            ):
                raise ValueError("supported section cannot promote unresolved claims")
        if self.verification is not None:
            if self.verification.revision_id != self.revision_id:
                raise ValueError("verification targets another revision")
            if set(self.verification.checked_claim_ids) != set(fact_ids + req_ids):
                raise ValueError("verification must account for every claim")
            if any(
                not set(item.evidence_ids) <= set(evidence_ids)
                for item in self.verification.findings
            ):
                raise ValueError("verification references missing evidence")
            blocked = not self.coverage.complete or any(
                item.status in (FindingStatus.CONFLICTING, FindingStatus.UNSUPPORTED)
                and item.critical_class != CriticalFactClass.OTHER
                for item in self.facts
            )
            if blocked and self.verification.verdict != "quality_blocked":
                raise ValueError("partial coverage or unsupported critical facts block acceptance")
        return self


class WriterClaim(Contract):
    """Writer-selected prose and existing IDs only; no locators or authority flags."""

    text: Text
    fact_ids: Annotated[tuple[Identity, ...], Field(max_length=32)] = ()
    requirement_ids: Annotated[tuple[Identity, ...], Field(max_length=32)] = ()
    evidence_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def linked(self):
        unique(self.fact_ids + self.requirement_ids)
        unique(self.evidence_ids)
        if not (self.fact_ids or self.requirement_ids):
            raise ValueError("writer claim requires source finding identities")
        return self


class WritingOmission(Contract):
    finding_id: Identity
    reason: Literal["condensed", "output_limit", "context_limit", "unresolved_source"]


class WriterFragmentContent(Contract):
    claims: Annotated[tuple[WriterClaim, ...], Field(max_length=12)] = ()
    key_points: Annotated[tuple[WriterClaim, ...], Field(max_length=3)] = ()
    omitted: Annotated[tuple[WritingOmission, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def omissions(self):
        unique(tuple(o.finding_id for o in self.omitted))
        return self


class SupportedClaim(WriterClaim):
    claim_id: Identity


class SupportedSummarySection(SummarySection):
    claims: Annotated[tuple[SupportedClaim, ...], Field(max_length=100)]
    context_note: Text

    @model_validator(mode="after")
    def coherent_text(self):
        expected = "\n".join((*[c.text for c in self.claims], self.context_note))
        if self.text != expected:
            raise ValueError("section text differs from linked claims")
        if set(self.fact_ids) != {i for c in self.claims for i in c.fact_ids} or (
            set(self.requirement_ids) != {i for c in self.claims for i in c.requirement_ids}
        ):
            raise ValueError("section finding references differ from linked claims")
        unique(tuple(c.claim_id for c in self.claims))
        return self


EMPTY_EXECUTIVE = (
    "Executive prose is unavailable or omitted; consult the register and inclusion manifest."
)


class SupportedSummaryContent(SummaryContent):
    """Minimal linked extension; old SummaryContent/TenderSummary remain compatible."""

    support_version: Literal["writer_support.v1"] = "writer_support.v1"
    execution_state: Literal["intermediate_unverified"] = "intermediate_unverified"
    sections: Annotated[tuple[SupportedSummarySection, ...], Field(min_length=13, max_length=13)]
    executive_claims: Annotated[tuple[SupportedClaim, ...], Field(max_length=100)]
    key_point_claims: Annotated[tuple[SupportedClaim, ...], Field(max_length=30)]

    @model_validator(mode="after")
    def linked_prose(self):
        if self.executive_overview != (
            "\n".join(c.text for c in self.executive_claims) or EMPTY_EXECUTIVE
        ):
            raise ValueError("executive prose differs from linked claims")
        if self.key_points != tuple(c.text for c in self.key_point_claims):
            raise ValueError("key points differ from linked claims")
        return self


OUTPUT_CONTRACTS = MappingProxyType(
    {
        "facts.v1": FactBatch,
        "analyst.v1": AnalystContent,
        "writer_fragment.v1": WriterFragmentContent,
        "summary_content.v1": SummaryContent,
        "verification.v1": VerificationContent,
    }
)


class AgentRole(StrEnum):
    CONTROLLER = "controller"
    ANALYST = "analyst"
    WRITER = "writer"
    VERIFIER = "verifier"
    HUMAN = "human_reviewer"


class Stage(StrEnum):
    PINNED = "pinned"
    READING = "reading"
    CONSOLIDATING = "consolidating"
    WRITING = "writing"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    REVIEW = "human_review"
    APPROVED = "approved"
    BLOCKED = "quality_blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Transition(Contract):
    """Legal transition assertion only; not an executor or authorization decision."""

    source: Stage
    target: Stage
    actor: AgentRole
    repair_pass: Annotated[int, Field(strict=True, ge=0, le=1)] = 0

    @model_validator(mode="after")
    def legal_transition(self) -> Transition:
        edges = {
            (Stage.PINNED, Stage.READING): AgentRole.CONTROLLER,
            (Stage.READING, Stage.CONSOLIDATING): AgentRole.ANALYST,
            (Stage.CONSOLIDATING, Stage.WRITING): AgentRole.CONTROLLER,
            (Stage.WRITING, Stage.VERIFYING): AgentRole.WRITER,
            (Stage.VERIFYING, Stage.REPAIRING): AgentRole.VERIFIER,
            (Stage.REPAIRING, Stage.VERIFYING): AgentRole.WRITER,
            (Stage.VERIFYING, Stage.REVIEW): AgentRole.VERIFIER,
            (Stage.VERIFYING, Stage.BLOCKED): AgentRole.VERIFIER,
            (Stage.REVIEW, Stage.APPROVED): AgentRole.HUMAN,
        }
        terminal = {Stage.APPROVED, Stage.BLOCKED, Stage.FAILED, Stage.CANCELLED}
        if self.source not in terminal and self.target in (Stage.FAILED, Stage.CANCELLED):
            expected = AgentRole.CONTROLLER
        else:
            expected = edges.get((self.source, self.target))
        if expected is None or self.actor != expected:
            raise ValueError("illegal role or stage transition")
        if self.target == Stage.REPAIRING and self.repair_pass != 0:
            raise ValueError("only the first verification may request a repair")
        if self.source == Stage.REPAIRING and self.repair_pass != 1:
            raise ValueError("verification after repair must record the consumed pass")
        return self
