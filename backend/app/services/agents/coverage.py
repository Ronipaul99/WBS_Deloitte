"""Trusted completion accounting. Reading completeness never implies understanding."""

from dataclasses import dataclass

from app.services.agents.budgeting import ReadingPlan
from app.services.agents.contracts import CoverageReport, SectionCoverage
from app.services.agents.evidence_types import (
    BatchCompletion,
    BatchOutcome,
    CoveragePage,
    EvidenceError,
    digest,
)
from app.services.agents.inventory import Inventory


@dataclass(frozen=True)
class CoverageTracker:
    inventory: Inventory
    plan: ReadingPlan
    outcomes: tuple[BatchOutcome, ...] = ()

    def __post_init__(self):
        expected = [e.chunk_id for e in self.inventory.entries]
        actual = [i for b in self.plan.batches for i in b.primary_chunk_ids]
        if (
            self.plan.inventory_sha256 != self.inventory.sha256
            or actual != expected
            or len(set(actual)) != len(actual)
            or any(
                b.inventory_sha256 != self.inventory.sha256 or b.index != i
                for i, b in enumerate(self.plan.batches)
            )
        ):
            raise EvidenceError("evidence_coverage_partition_invalid")
        known = {digest(b) for b in self.plan.batches}
        ids = [o.batch_sha256 for o in self.outcomes]
        if len(set(ids)) != len(ids) or not set(ids) <= known:
            raise EvidenceError("evidence_coverage_outcome_invalid")
        for i in self.plan.blocked:
            outcome = next(
                (o for o in self.outcomes if o.batch_sha256 == digest(self.plan.batches[i])), None
            )
            if outcome and outcome.state != "blocked":
                raise EvidenceError("evidence_blocked_batch_unreadable")

    def record(self, index, state, *, batch_sha256, completion=None):
        if type(index) is not int or not 0 <= index < len(self.plan.batches):
            raise EvidenceError("evidence_batch_outside_plan")
        batch = self.plan.batches[index]
        if batch_sha256 != digest(batch) or index in self.plan.blocked:
            raise EvidenceError("evidence_batch_input_mismatch")
        if completion is not None:
            completion = BatchCompletion.model_validate(completion)
            if (
                completion.batch_sha256 != batch_sha256
                or completion.inventory_sha256 != self.inventory.sha256
                or completion.primary_chunk_ids != batch.primary_chunk_ids
            ):
                raise EvidenceError("evidence_completion_input_mismatch")
        completion_sha256 = digest(completion) if completion is not None else None
        previous = next((o for o in self.outcomes if o.batch_sha256 == batch_sha256), None)
        before = previous.state if previous else "assigned"
        edges = {
            "assigned": {"retrieved", "failed", "blocked"},
            "retrieved": {"delivered", "failed", "blocked"},
            "delivered": {"processed", "failed", "blocked"},
        }
        new = BatchOutcome(
            batch_sha256=batch_sha256, state=state, completion_sha256=completion_sha256
        )
        if previous == new:
            return self
        if state not in edges.get(before, set()):
            raise EvidenceError("evidence_coverage_transition_invalid")
        return CoverageTracker(
            self.inventory,
            self.plan,
            tuple(o for o in self.outcomes if o.batch_sha256 != batch_sha256) + (new,),
        )

    def report(self):
        if not self.inventory.entries:
            raise EvidenceError("evidence_empty_source_blocked")
        processed, failed = set(), set()
        by_hash = {o.batch_sha256: o for o in self.outcomes}
        for batch in self.plan.batches:
            outcome = by_hash.get(digest(batch))
            if outcome and outcome.state == "processed":
                processed.update(batch.primary_chunk_ids)
            if outcome and outcome.state == "failed":
                failed.update(batch.primary_chunk_ids)
        entries = self.inventory.entries
        primary = tuple(e.chunk_id for e in entries)
        sections = {}
        for entry in entries:
            sections.setdefault(entry.section_id, []).append(entry.chunk_id)
        return CoverageReport(
            truncated=bool(
                set(self.inventory.manifest.pin.warning_codes)
                & {"partial_element_skipped", "unsupported_element_skipped"}
            ),
            primary_chunk_ids=primary,
            processed_chunk_ids=tuple(i for i in primary if i in processed),
            failed_chunk_ids=tuple(i for i in primary if i in failed),
            unprocessed_chunk_ids=tuple(i for i in primary if i not in processed | failed),
            sections=tuple(
                SectionCoverage(
                    section_id=s,
                    status="processed"
                    if all(i in processed for i in ids)
                    else "failed"
                    if all(i in failed for i in ids)
                    else "partial"
                    if any(i in processed | failed for i in ids)
                    else "unprocessed",
                )
                for s, ids in sections.items()
            ),
        )

    def pages(self, *, sequence_start=0):
        """Bounded immutable report pages; caller persists fresh snapshot sequence IDs."""
        outcomes = {o.batch_sha256: o for o in self.outcomes}
        complete = tuple(
            outcomes.get(digest(b))
            or BatchOutcome(
                batch_sha256=digest(b),
                state="blocked" if b.index in self.plan.blocked else "assigned",
            )
            for b in self.plan.batches
        )
        if type(sequence_start) is not int or not 0 <= sequence_start <= 99000:
            raise EvidenceError("evidence_coverage_sequence_invalid")
        return tuple(
            CoveragePage(
                inventory_sha256=self.inventory.sha256,
                index=sequence_start + i // 128,
                outcomes=complete[i : i + 128],
            )
            for i in range(0, len(complete), 128)
        )
