"""Synthetic register/controller fixtures. No application settings, sockets or models."""

from types import SimpleNamespace

from agent_schema_fixtures import content, uid
from llm_adapter_fixtures import request

from app.services.agents.analyst_types import GapFinding, RegisterPage, RegisterSeal
from app.services.agents.budgeting import ContextBudget
from app.services.agents.contracts import (
    EvidenceReference,
    Fact,
    FactBatch,
    Requirement,
    TenderCategory,
    WorkflowInput,
    WriterClaim,
    WriterFragmentContent,
    WritingOmission,
)
from app.services.agents.evidence_types import digest
from app.services.agents.nodes.writer import SummaryWriter
from app.services.agents.nodes.writer_prompt import INSTRUCTIONS
from app.services.agents.writer_register import WriterRegister
from app.services.agents.writer_types import ReadingMetadata


class Guard:
    def __init__(self):
        self.active, self.calls = True, 0

    async def __call__(self):
        self.calls += 1
        if not self.active:
            raise PermissionError("synthetic authorization revoked")


def prepared(provider="openai", *, count=None, partial=False, policy=None, categories=None):
    req = request(provider, schema="writer_fragment.v1", native=False)
    workflow = WorkflowInput.model_validate({**content()["workflow"], "profile": req.profile})
    source_quote = (
        "Synthetic project. Total capacity 225 MW; each unit 75 MW. "
        "EMD A 100 INR if eligible; EMD B 200 INR otherwise. "
        "PPA 25 years. Deadline 1 May; addendum says 2 May. Supply panels."
    )
    ref = EvidenceReference(
        evidence_id=uid(12),
        scope=workflow.scope,
        chunk_id=uid(14),
        chunk_sha256="d" * 64,
        physical_pages=(1, 2),
        heading_path=("Synthetic",),
        exact_quote=source_quote,
        char_start=0,
        char_end=len(source_quote),
    )
    examples = (
        (
            ("overview", "Synthetic project", None, None, (), None),
            ("capacity_units", "Total capacity 225 MW", "225", "MW", (), None),
            ("capacity_units", "Each unit 75 MW", "75", "MW/unit", (), None),
            ("securities_emd_pbg", "EMD A", "100", None, ("if eligible",), "INR"),
            ("securities_emd_pbg", "EMD B", "200", None, ("otherwise",), "INR"),
            ("financial_commercial", "PPA duration", "25", "years", (), None),
        )
        if count is None
        else tuple(
            ("technical", f"Synthetic clause {i}", None, None, (), None) for i in range(count)
        )
    )
    facts = tuple(
        Fact(
            fact_id=uid(500 + i),
            category=category,
            critical_class="other",
            status="supported",
            statement=statement,
            original_value=number,
            normalized_number=number,
            unit=unit,
            currency=currency,
            conditions=conditions,
            evidence_ids=(ref.evidence_id,),
        )
        for i, (category, statement, number, unit, conditions, currency) in enumerate(examples)
        if categories is None or category in categories
    )
    reqs = (
        (
            Requirement(
                requirement_id=uid(800),
                display_code="REQ-stable-800",
                obligation="Supply panels.",
                status="supported",
                conditions=("when awarded",),
                evidence_ids=(ref.evidence_id,),
            ),
        )
        if count is None
        else ()
    )
    pages, previous = [], None
    rows = (*facts, *reqs)
    for start in range(0, len(rows), 100):
        chunk = rows[start : start + 100]
        page = RegisterPage(
            binding="b" * 64,
            inventory_sha256="a" * 64,
            level="document",
            index=len(pages),
            previous_sha256=previous,
            findings=FactBatch(
                facts=tuple(r for r in chunk if isinstance(r, Fact)),
                requirements=tuple(r for r in chunk if isinstance(r, Requirement)),
            ),
            evidence=(ref,),
            inputs_sha256="c" * 64,
        )
        pages.append(page)
        previous = digest(page)
    seal = RegisterSeal(
        binding="b" * 64,
        inventory_sha256="a" * 64,
        inputs_sha256="c" * 64,
        root_sha256=previous,
        page_count=len(pages),
        reading_complete=not partial,
        gaps=tuple(
            GapFinding(
                category=c,
                state="incomplete_reading"
                if partial
                else "candidate_found_unverified"
                if any(f.category == c for f in facts)
                else "unknown_not_searched",
            )
            for c in TenderCategory
        ),
    )
    reading = ReadingMetadata(
        coverage_sha256="e" * 64,
        primary_count=2,
        processed_count=1 if partial else 2,
        failed_count=0,
        unprocessed_count=1 if partial else 0,
        truncated=False,
        complete=not partial,
    )
    snapshot = WriterRegister(workflow, seal, tuple(pages), reading)
    guard = Guard()
    budget = ContextBudget(req.profile, INSTRUCTIONS, (), 1024)
    writer = SummaryWriter(budget, guard, policy=policy)
    return SimpleNamespace(
        request=req, snapshot=snapshot, writer=writer, guard=guard, budget=budget
    )


def output(snapshot, partition, *, keep=None, key_points=False):
    ids = tuple(partition.finding_ids if keep is None else keep)
    claims = tuple(
        WriterClaim(
            text=row.statement if isinstance(row, Fact) else row.obligation,
            fact_ids=(identity,) if isinstance(row, Fact) else (),
            requirement_ids=() if isinstance(row, Fact) else (identity,),
            evidence_ids=row.evidence_ids,
        )
        for identity in ids
        for row in (snapshot.findings[identity],)
    )
    return WriterFragmentContent(
        claims=claims,
        key_points=claims[:1] if key_points else (),
        omitted=tuple(
            WritingOmission(finding_id=i, reason="condensed")
            for i in partition.finding_ids
            if i not in ids
        ),
    )
