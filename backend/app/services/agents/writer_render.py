"""Deterministic linked prose and legacy projection. No SQL, inference or approval."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.contracts import Fact, FindingStatus, Requirement, WorkflowInput
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.writer_types import ReadingMetadata
from app.services.llm.contracts import Contract, Identity, Label, Text
from app.services.llm.protocol_support import compact


def finding_ids(claim):
    return set(claim.fact_ids + claim.requirement_ids)


def validate_links(claim, snapshot, allowed):
    findings = snapshot.findings
    if not finding_ids(claim) <= set(allowed):
        raise EvidenceError("writer_finding_outside_fragment")
    if any(not isinstance(findings.get(i), Fact) for i in claim.fact_ids) or any(
        not isinstance(findings.get(i), Requirement) for i in claim.requirement_ids
    ):
        raise EvidenceError("writer_reference_kind_mismatch")
    if any(
        findings[i].status not in {FindingStatus.SUPPORTED, FindingStatus.CONFLICTING}
        for i in finding_ids(claim)
    ):
        raise EvidenceError("writer_unresolved_source_assertion")
    expected = {e for i in finding_ids(claim) for e in findings[i].evidence_ids}
    if set(claim.evidence_ids) != expected:
        raise EvidenceError("writer_evidence_links_mismatch")


def source_attributes(claim, snapshot):
    attributes = []
    findings = snapshot.findings
    for identity in sorted(finding_ids(claim)):
        row = findings[identity].model_dump(mode="json")
        # Preserve source qualifiers exactly, without asking a second model to regenerate them.
        fields = (
            "original_value",
            "normalized_number",
            "unit",
            "currency",
            "conditions",
            "alternatives",
            "responsible_party",
            "deliverable",
            "acceptance_criteria",
            "dependency_ids",
            "status",
        )
        attributes.append(
            {
                "finding_id": str(identity),
                **{k: row[k] for k in fields if k in row and row[k] is not None and row[k] != []},
            }
        )
    return "[Source attributes: " + compact(attributes) + "]"


class LegacyRequirement(Contract):
    id: Identity
    title: Text
    source: Label
    status: Literal["REVIEW_REQUIRED"] = "REVIEW_REQUIRED"
    requirement: Requirement

    @model_validator(mode="after")
    def identity(self):
        if self.id != self.requirement.requirement_id or self.title != self.requirement.obligation:
            raise ValueError("legacy requirement identity mismatch")
        return self


class LegacyProjection(Contract):
    summary_text: Annotated[str, Field(min_length=1, max_length=50000)]
    key_points: Annotated[tuple[Text, ...], Field(max_length=30)]
    requirements: Annotated[tuple[LegacyRequirement, ...], Field(max_length=2500)]
    workflow: WorkflowInput
    reading: ReadingMetadata
    register_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["intermediate_unverified"] = "intermediate_unverified"


def legacy_projection(draft, snapshot, *, maximum_characters=50000):
    """All structured requirements survive; inclusion manifests count prose references only."""
    if (
        type(maximum_characters) is not int
        or not 1 <= maximum_characters <= 50000
        or draft.workflow != snapshot.workflow
        or draft.register_seal != snapshot.seal
        or draft.reading != snapshot.reading
    ):
        raise EvidenceError("writer_projection_input_mismatch")
    text = "\n\n".join(
        [
            "Intermediate draft — not independently verified.",
            draft.content.executive_overview,
            *(
                section.category.value.replace("_", " ").title() + "\n" + section.text
                for section in draft.content.sections
            ),
        ]
    )
    if len(text) > maximum_characters:
        raise EvidenceError("writer_legacy_text_oversized")
    claims = (
        *draft.content.executive_claims,
        *draft.content.key_point_claims,
        *(c for section in draft.content.sections for c in section.claims),
    )
    for claim in claims:
        validate_links(claim, snapshot, snapshot.findings)
    requirements = tuple(
        LegacyRequirement(
            id=i,
            title=row.obligation,
            source="document:" + str(snapshot.workflow.scope.document_id),
            requirement=row,
        )
        for i, row in sorted(snapshot.findings.items())
        if isinstance(row, Requirement)
    )
    try:
        result = LegacyProjection(
            summary_text=text,
            key_points=draft.content.key_points,
            requirements=requirements,
            workflow=draft.workflow,
            reading=draft.reading,
            register_sha256=digest(draft.register_seal),
        )
        if len(result.model_dump_json().encode()) > 8000000:
            raise ValueError("oversized projection")
        return result
    except ValueError:
        raise EvidenceError("writer_legacy_projection_oversized") from None
