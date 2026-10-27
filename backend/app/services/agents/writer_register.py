"""Authorized Step 8 register restoration for writing; no new retrieval or analysis."""

from dataclasses import dataclass

from app.services.agents.analyst_types import AnalystArtifact, RegisterSeal
from app.services.agents.budgeting import ReadingPlan
from app.services.agents.contracts import Fact, Requirement, WorkflowInput
from app.services.agents.coverage import CoverageTracker
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.fact_register import validate_register
from app.services.agents.writer_types import ReadingMetadata, WriterArtifact


@dataclass(frozen=True)
class WriterRegister:
    workflow: WorkflowInput
    seal: RegisterSeal
    pages: tuple
    reading: ReadingMetadata

    def __post_init__(self):
        validate_register(self.pages, self.seal)
        if self.reading.complete != self.seal.reading_complete:
            raise EvidenceError("writer_coverage_mismatch")
        if any(ref.scope != self.workflow.scope for p in self.pages for ref in p.evidence):
            raise EvidenceError("writer_register_scope_mismatch")
        findings = self.findings
        ids = set(findings)
        requirement_ids = {i for i, claim in findings.items() if isinstance(claim, Requirement)}
        if len(ids) > 5000:
            raise EvidenceError("writer_register_overflow")
        for p in self.document_pages:
            for ref in p.evidence:
                if self.evidence[ref.evidence_id] != ref:
                    raise EvidenceError("writer_register_evidence_collision")
            for r in p.findings.requirements:
                if not set(r.dependency_ids) <= requirement_ids:
                    raise EvidenceError("writer_register_dependency_missing")

    @property
    def document_pages(self):
        return tuple(p for p in self.pages if p.level == "document")

    @property
    def findings(self):
        return {
            (c.fact_id if isinstance(c, Fact) else c.requirement_id): c
            for p in self.document_pages
            for c in p.findings.facts + p.findings.requirements
        }

    @property
    def evidence(self):
        return {r.evidence_id: r for p in self.document_pages for r in p.evidence}


async def restore_writer_register(context, evidence, plan: ReadingPlan, guard, policy):
    """Only scoped checkpoints enter here. Never trust thread IDs or browser snapshots."""
    await guard()
    history, before, used = [], None, 0
    while True:
        page = await context.checkpoints.list(before=before, limit=100)
        if not page:
            break
        for completed in page:
            used += len(completed.model_dump_json().encode())
            if used > 32000000 or len(history) >= 10000:
                raise EvidenceError("writer_history_overflow")
            if (
                completed.workflow_run_id != context.workflow.workflow_run_id
                or completed.after.sequence > context.cursor.sequence
            ):
                raise EvidenceError("writer_history_scope_mismatch")
            history.append(completed)
        cursor = min(c.after.sequence for c in page)
        if before is not None and cursor >= before:
            raise EvidenceError("writer_history_cursor_invalid")
        before = cursor
    artifacts, writing, seal_sequence = [], [], None
    for c in sorted(history, key=lambda c: c.before.sequence):
        a = c.result.artifact
        if isinstance(a, AnalystArtifact):
            if seal_sequence is not None:
                raise EvidenceError("writer_register_changed_after_seal")
            artifacts.append(a)
            if a.kind == "fact_register.v1":
                seal_sequence = c.after.sequence
        elif isinstance(a, WriterArtifact):
            if seal_sequence is None or c.before.node.value != "write":
                raise EvidenceError("writer_history_order_invalid")
            writing.append(a)
        elif c.before.node.value in {"analyze", "consolidate", "write"}:
            raise EvidenceError("writer_history_incompatible")
    seals = [a.payload for a in artifacts if a.kind == "fact_register.v1"]
    if len(seals) != 1:
        raise EvidenceError("writer_register_not_sealed")
    seal = seals[0]
    if (
        seal.inventory_sha256 != evidence.inventory.sha256
        or context.workflow.scope != evidence.pin.scope
    ):
        raise EvidenceError("writer_register_scope_mismatch")
    pages = tuple(a.payload for a in artifacts if a.kind == "fact_register_page.v1")
    if sum(len(p.model_dump_json().encode()) for p in pages) > policy.max_register_bytes:
        raise EvidenceError("writer_register_overflow")
    validate_register(pages, seal)
    batches = [a.payload for a in artifacts if a.kind == "analyst_batch.v1"]
    gaps = [a.payload for a in artifacts if a.kind == "analyst_gap.v1"]
    records = [b.extraction for b in batches] + [g.extraction for g in gaps if g.extraction]
    if (
        digest(sorted(digest(r) for r in records)) != seal.inputs_sha256
        or any(r.binding != seal.binding for r in records)
        or any(g.binding != seal.binding for g in gaps)
    ):
        raise EvidenceError("writer_register_inputs_mismatch")
    tracker = CoverageTracker(evidence.inventory, plan)
    seen = set()
    for b in batches:
        i = b.batch.index
        if i in seen or i >= len(plan.batches) or b.batch != plan.batches[i]:
            raise EvidenceError("writer_reading_plan_mismatch")
        seen.add(i)
        for state in ("retrieved", "delivered", "processed"):
            tracker = tracker.record(
                i,
                state,
                batch_sha256=digest(b.batch),
                completion=b.completion if state == "processed" else None,
            )
    report = tracker.report()
    reading = ReadingMetadata(
        coverage_sha256=digest(report),
        primary_count=len(report.primary_chunk_ids),
        processed_count=len(report.processed_chunk_ids),
        failed_count=len(report.failed_chunk_ids),
        unprocessed_count=len(report.unprocessed_chunk_ids),
        truncated=report.truncated,
        complete=report.complete,
    )
    snapshot = WriterRegister(context.workflow, seal, pages, reading)
    # Reuse canonical integrity guards; no entailment/numeric verification here.
    for ref in snapshot.evidence.values():
        await evidence.validate_reference(ref)
    await guard()
    return snapshot, tuple(writing)
