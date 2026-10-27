"""Conservative deterministic registers. Equivalent text is not semantic verification."""

import re
import unicodedata
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from app.services.agents.analyst_types import (
    ExtractionRecord,
    FindingAlias,
    GapFinding,
    RegisterPage,
    RegisterSeal,
)
from app.services.agents.contracts import (
    Fact,
    FactBatch,
    FindingStatus,
    Requirement,
    TenderCategory,
)
from app.services.agents.evidence_types import EvidenceError, digest


def text_key(text):
    # Preserve case and punctuation: changing units/negation must not merge entries.
    return " ".join(unicodedata.normalize("NFC", text).split())


def identity(claim, evidence, scope):
    """Canonical source anchors + structured attributes, never model IDs/list/prose."""
    body = claim.model_dump(mode="json")
    for name in (
        "fact_id",
        "requirement_id",
        "display_code",
        "statement",
        "obligation",
        "evidence_ids",
        "dependency_ids",
        "schema_version",
    ):
        body.pop(name, None)
    body["anchors"] = sorted({text_key(evidence[i].exact_quote) for i in claim.evidence_ids})
    if not body["anchors"] and not (
        isinstance(claim, Fact) and claim.status == FindingStatus.UNKNOWN
    ):
        raise EvidenceError("analyst_unanchored_finding")
    return uuid5(
        NAMESPACE_URL,
        digest(
            {
                "version": "finding_identity.v1",
                "scope": scope.model_dump(mode="json"),
                "kind": type(claim).__name__,
                "attributes": body,
            }
        ),
    )


def equivalent(left, right):
    """Only exact normalized claims may merge, including conditions and dependencies."""

    def key(claim):
        data = claim.model_dump(mode="json")
        for name in ("fact_id", "requirement_id", "display_code", "evidence_ids"):
            data.pop(name, None)
        for name in ("statement", "obligation"):
            if name in data:
                data[name] = text_key(data[name])
        return data

    return type(left) is type(right) and key(left) == key(right)


def merge_claim(left, right):
    if not equivalent(left, right):
        # Same anchor/attributes with incompatible prose: preserve no arbitrary winner.
        raise EvidenceError("analyst_identity_collision")
    ids = tuple(sorted(set(left.evidence_ids + right.evidence_ids), key=str))
    if len(ids) > 32:
        raise EvidenceError("analyst_evidence_overflow")
    data = left.model_dump()
    for field in ("statement", "obligation"):
        if field in data:
            data[field] = text_key(data[field])
    return type(left).model_validate({**data, "evidence_ids": ids})


async def normalize_extraction(content, evidence, allowed_ids, *, binding, origin):
    """Convert untrusted quote/claim IDs into canonical evidence and stable IDs."""
    refs, proposals = {}, {}
    for quote in content.quotes:
        if quote.chunk_id not in allowed_ids:
            raise EvidenceError("analyst_undelivered_evidence")
        ref = await evidence.reference(
            quote.chunk_id, quote.char_start, quote.char_end, quote=quote.exact_quote
        )
        refs[ref.evidence_id] = ref
        proposals[quote.quote_id] = ref.evidence_id
    claims, aliases, proposed = {}, [], {}
    all_claims = content.facts + content.requirements
    for claim in all_claims:
        # A normalized number is accepted only as a literal decimal rendering here.
        # Magnitude/unit conversion and semantic numeric verification remain Step 10.
        if isinstance(claim, Fact) and claim.normalized_number is not None:
            from decimal import Decimal

            original = claim.original_value
            literal = original.replace(",", "")
            if not re.fullmatch(
                r"-?(0|[1-9][0-9]*|[1-9][0-9]{0,2}(,[0-9]{3})+)(\.[0-9]+)?", original
            ) or (Decimal(literal) != Decimal(claim.normalized_number)):
                raise EvidenceError("analyst_normalization_unsupported")
            if not any(original in refs[proposals[i]].exact_quote for i in claim.evidence_ids):
                raise EvidenceError("analyst_original_value_not_quoted")
        mapped = type(claim).model_validate(
            {
                **claim.model_dump(),
                "evidence_ids": tuple(sorted({proposals[i] for i in claim.evidence_ids}, key=str)),
            }
        )
        stable = identity(mapped, refs, evidence.pin.scope)
        old_id = claim.fact_id if isinstance(claim, Fact) else claim.requirement_id
        proposed[old_id] = stable
        aliases.append(FindingAlias(origin_sha256=origin, proposed_id=old_id, stable_id=stable))
        name = "fact_id" if isinstance(mapped, Fact) else "requirement_id"
        mapped = mapped.model_copy(update={name: stable})
        if isinstance(mapped, Requirement):
            mapped = mapped.model_copy(update={"display_code": "REQ-" + stable.hex})
        claims[old_id] = mapped
    merged = {}
    for old_id, claim in claims.items():
        if isinstance(claim, Requirement):
            if not set(claim.dependency_ids) <= {r.requirement_id for r in content.requirements}:
                raise EvidenceError("analyst_dependency_unresolved")
            claim = Requirement.model_validate(
                {
                    **claim.model_dump(),
                    "dependency_ids": tuple(proposed[i] for i in claim.dependency_ids),
                }
            )
        stable = proposed[old_id]
        merged[stable] = merge_claim(merged[stable], claim) if stable in merged else claim
    record = ExtractionRecord(
        binding=binding,
        origin_sha256=origin,
        findings=FactBatch(
            facts=tuple(c for _, c in sorted(merged.items()) if isinstance(c, Fact)),
            requirements=tuple(c for _, c in sorted(merged.items()) if isinstance(c, Requirement)),
            unresolved_categories=content.unresolved_categories,
        ),
        evidence=tuple(refs[i] for i in sorted(refs)),
        aliases=tuple(sorted(aliases, key=lambda a: str(a.proposed_id))),
        no_facts_reason=content.no_facts_reason,
    )
    await evidence.guard()
    return record


def missing_categories(records):
    present = {
        f.category for r in records for f in r.findings.facts if f.status == FindingStatus.SUPPORTED
    }
    return tuple(c for c in TenderCategory if c not in present)


def validate_register(pages, seal):
    """Validate a complete immutable page chain; partial pages never imply a seal."""
    if len(pages) != seal.page_count:
        raise EvidenceError("analyst_register_pages_missing")
    previous, document_ids, alias_targets = None, set(), {}
    for i, page in enumerate(pages):
        if (
            page.index != i
            or page.previous_sha256 != previous
            or page.binding != seal.binding
            or page.inventory_sha256 != seal.inventory_sha256
            or page.inputs_sha256 != seal.inputs_sha256
        ):
            raise EvidenceError("analyst_register_chain_invalid")
        if page.level == "document":
            ids = {f.fact_id for f in page.findings.facts} | {
                r.requirement_id for r in page.findings.requirements
            }
            if ids & document_ids:
                raise EvidenceError("analyst_register_duplicate_entry")
            document_ids.update(ids)
        for alias in page.aliases:
            key = (alias.origin_sha256, alias.proposed_id)
            if key in alias_targets and alias_targets[key] != alias.stable_id:
                raise EvidenceError("analyst_register_alias_collision")
            alias_targets[key] = alias.stable_id
        previous = digest(page)
    if previous != seal.root_sha256:
        raise EvidenceError("analyst_register_root_invalid")


def consolidate(records, *, inventory, binding, policy, reading_complete, gap_records=()):
    """Bounded Python reduction, not a whole-document LLM call. No silent eviction."""
    records = tuple(records)
    if len(records) > 123 or any(r.binding != binding for r in records):
        raise EvidenceError("analyst_register_inputs_invalid")
    if sum(len(r.model_dump_json().encode()) for r in records) > policy.max_register_bytes:
        raise EvidenceError("analyst_register_overflow")
    inputs = digest(sorted(digest(r) for r in records))
    evidence, aliases, claims = {}, defaultdict(list), {}
    for record in records:
        for ref in record.evidence:
            if ref.scope != inventory.manifest.pin.scope:
                raise EvidenceError("analyst_register_scope_mismatch")
            inventory.entry(ref.chunk_id)
            if ref.evidence_id in evidence and evidence[ref.evidence_id] != ref:
                raise EvidenceError("analyst_register_evidence_collision")
            evidence[ref.evidence_id] = ref
        for alias in record.aliases:
            if alias not in aliases[alias.stable_id]:
                aliases[alias.stable_id].append(alias)
        for claim in record.findings.facts + record.findings.requirements:
            key = claim.fact_id if isinstance(claim, Fact) else claim.requirement_id
            claims[key] = merge_claim(claims[key], claim) if key in claims else claim
            if len(claims) > policy.max_register_entries:
                raise EvidenceError("analyst_register_overflow")
    sections = defaultdict(set)
    for key, claim in claims.items():
        for ref in claim.evidence_ids:
            sections[inventory.entry(evidence[ref].chunk_id).section_id].add(key)
    pages, previous = [], None

    def page_for(keys, level, section):
        chosen = [claims[k] for k in keys]
        ids = {i for c in chosen for i in c.evidence_ids}
        return RegisterPage(
            binding=binding,
            inventory_sha256=inventory.sha256,
            level=level,
            section_id=section,
            index=len(pages),
            previous_sha256=previous,
            findings=FactBatch(
                facts=tuple(c for c in chosen if isinstance(c, Fact)),
                requirements=tuple(c for c in chosen if isinstance(c, Requirement)),
            ),
            evidence=tuple(evidence[i] for i in sorted(ids)),
            aliases=tuple(
                sorted(
                    (a for k in keys for a in aliases[k]),
                    key=lambda a: (a.origin_sha256, str(a.proposed_id)),
                )
            ),
            inputs_sha256=inputs,
        )

    # Identical merge rules at both levels; cross-section links remain on document entries.
    for level, section, keys in [
        *(("section", s, sorted(ids)) for s, ids in sorted(sections.items())),
        ("document", None, sorted(claims)),
    ]:
        pending = []
        for key in keys:
            try:
                page_for(pending + [key], level, section)
            except ValueError:
                if not pending:
                    raise EvidenceError("analyst_register_entry_oversized") from None
                page = page_for(pending, level, section)
                pages.append(page)
                previous = digest(page)
                pending = []
                try:
                    page_for([key], level, section)
                except ValueError:
                    raise EvidenceError("analyst_register_entry_oversized") from None
            pending.append(key)
        if pending:
            page = page_for(pending, level, section)
            pages.append(page)
            previous = digest(page)
    if len(pages) > 9900:
        raise EvidenceError("analyst_register_overflow")
    facts = [c for c in claims.values() if isinstance(c, Fact)]
    searched = {c for g in gap_records if g.outcome == "completed" for c in g.requested_categories}
    exhausted = any(g.outcome == "budget_exhausted" for g in gap_records)
    unavailable = {c for g in gap_records if g.outcome == "blocked" for c in g.requested_categories}
    gaps = tuple(
        GapFinding(
            category=category,
            analyst_reported_unresolved=any(
                category in r.findings.unresolved_categories for r in records
            ),
            state=(
                "incomplete_reading"
                if not reading_complete
                else "conflicting"
                if any(
                    f.category == category and f.status == FindingStatus.CONFLICTING for f in facts
                )
                else "candidate_found_unverified"
                if any(
                    f.category == category and f.status == FindingStatus.SUPPORTED for f in facts
                )
                else "not_found_within_allowance"
                if category in searched
                else "search_unavailable"
                if category in unavailable
                else "budget_exhausted"
                if exhausted
                else "unknown_not_searched"
            ),
        )
        for category in TenderCategory
    )
    seal = RegisterSeal(
        binding=binding,
        inventory_sha256=inventory.sha256,
        inputs_sha256=inputs,
        root_sha256=previous,
        page_count=len(pages),
        reading_complete=reading_complete,
        gaps=gaps,
    )
    validate_register(pages, seal)
    return tuple(pages), seal
