"""Deterministic section/document assembly and paged prose-inclusion accounting."""

from app.services.agents.contracts import (
    EMPTY_EXECUTIVE,
    FindingStatus,
    SupportedSummaryContent,
    SupportedSummarySection,
    TenderCategory,
    WritingOmission,
)
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.writer_render import legacy_projection
from app.services.agents.writer_types import InclusionPage, IntermediateDraft

NOTES = {
    "unknown_not_searched": "Category completeness remains unresolved; no search proves absence.",
    "not_found_within_allowance": (
        "Not found within the bounded search allowance; absence is not proven."
    ),
    "conflicting": "Conflicting source information remains unresolved.",
    "incomplete_reading": "Source reading is incomplete; information may be missing.",
    "budget_exhausted": "Gap-search allowance was exhausted; information remains unresolved.",
    "search_unavailable": "Gap search was unavailable; information remains unresolved.",
    "candidate_found_unverified": (
        "Source-linked candidate information is not independently verified."
    ),
}


def prose_ids(content):
    return {
        i
        for c in (
            *content.executive_claims,
            *content.key_point_claims,
            *(c for section in content.sections for c in section.claims),
        )
        for i in c.fact_ids + c.requirement_ids
    }


def assemble_content(snapshot, fragments):
    sections, findings = [], snapshot.findings
    for gap in snapshot.seal.gaps:
        claims = tuple(
            c for f in fragments if f.partition.category == gap.category for c in f.claims
        )
        fact_ids = tuple(sorted({i for c in claims for i in c.fact_ids}))
        req_ids = tuple(sorted({i for c in claims for i in c.requirement_ids}))
        states = {findings[i].status for i in fact_ids + req_ids}
        status = (
            FindingStatus.CONFLICTING
            if (FindingStatus.CONFLICTING in states or gap.state == "conflicting")
            else FindingStatus.SUPPORTED
            if (
                claims
                and states == {FindingStatus.SUPPORTED}
                and snapshot.reading.complete
                and not gap.analyst_reported_unresolved
            )
            else FindingStatus.UNKNOWN
        )
        note = NOTES[gap.state]
        if status == FindingStatus.CONFLICTING and gap.state != "conflicting":
            note += " Conflicting source values remain unresolved."
        if gap.analyst_reported_unresolved:
            note += " The analyst reported unresolved information in this category."
        if not snapshot.reading.complete and gap.state != "incomplete_reading":
            note += " Reading coverage is partial."
        if not claims:
            note += " No factual prose was included for this section; see the inclusion manifest."
        sections.append(
            SupportedSummarySection(
                category=gap.category,
                status=status,
                claims=claims,
                context_note=note,
                text="\n".join((*[c.text for c in claims], note)),
                fact_ids=fact_ids,
                requirement_ids=req_ids,
            )
        )
    executive = tuple(
        c
        for s in sections
        if s.category in {TenderCategory.OVERVIEW, TenderCategory.ISSUER_PARTIES}
        for c in s.claims
    )
    points = tuple(c for f in fragments for c in f.key_points)
    return SupportedSummaryContent(
        executive_overview="\n".join(c.text for c in executive) or EMPTY_EXECUTIVE,
        executive_claims=executive,
        sections=tuple(sections),
        key_points=tuple(c.text for c in points),
        key_point_claims=points,
    )


def inclusion_pages(snapshot, content, fragments, binding):
    """Count FINAL references, never union intermediate findings into a fake final count."""
    included = prose_ids(content)
    if not included <= set(snapshot.findings):
        raise EvidenceError("writer_final_reference_unknown")
    reasons = {o.finding_id: o.reason for f in fragments for o in f.inclusion.omitted}
    pages, previous = [], None
    for source in snapshot.document_pages:
        available = tuple(
            sorted(
                [f.fact_id for f in source.findings.facts]
                + [r.requirement_id for r in source.findings.requirements]
            )
        )
        page = InclusionPage(
            binding=binding,
            stage="final_prose",
            index=len(pages),
            previous_sha256=previous,
            available=available,
            included=tuple(i for i in available if i in included),
            omitted=tuple(
                WritingOmission(finding_id=i, reason=reasons.get(i, "condensed"))
                for i in available
                if i not in included
            ),
        )
        pages.append(page)
        previous = digest(page)
    return tuple(pages)


def validate_inclusion(pages, draft, snapshot):
    if len(pages) != draft.inclusion_page_count:
        raise EvidenceError("writer_inclusion_pages_missing")
    previous, available, included = None, set(), set()
    for i, page in enumerate(pages):
        if (
            page.index != i
            or page.previous_sha256 != previous
            or page.binding != draft.binding
            or page.stage != "final_prose"
            or available & set(page.available)
        ):
            raise EvidenceError("writer_inclusion_chain_invalid")
        available.update(page.available)
        included.update(page.included)
        previous = digest(page)
    if (
        previous != draft.inclusion_root_sha256
        or available != set(snapshot.findings)
        or included != prose_ids(draft.content)
    ):
        raise EvidenceError("writer_inclusion_seal_mismatch")


def assemble_draft(snapshot, fragments, binding, policy):
    try:
        content = assemble_content(snapshot, fragments)
        pages = inclusion_pages(snapshot, content, fragments, binding)
        draft = IntermediateDraft(
            binding=binding,
            workflow=snapshot.workflow,
            register_seal=snapshot.seal,
            content=content,
            reading=snapshot.reading,
            inclusion_page_count=len(pages),
            inclusion_root_sha256=digest(pages[-1]) if pages else None,
        )
        if len(draft.model_dump_json().encode()) > policy.max_draft_bytes:
            raise ValueError("draft exceeds bound")
        validate_inclusion(pages, draft, snapshot)
        # Validate compatibility bounds now; project again deterministically when requested.
        legacy_projection(draft, snapshot)
        return pages, draft
    except EvidenceError:
        raise
    except (ValueError, TypeError):
        raise EvidenceError("writer_assembly_oversized_or_invalid") from None
