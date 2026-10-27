"""Step 8 synthetic extraction/reduction, isolated with --noconftest."""

import httpcore
import pytest
from agent_evidence_fixtures import canonical_source
from agent_evidence_fixtures import evidence_db as db_fixture  # noqa: F401
from agent_schema_fixtures import uid
from analyst_fixtures import encoded, extraction, no_facts, prepared
from llm_adapter_fixtures import SequenceBackend, adapter, reply, wire
from llm_security_fixtures import SENTINEL, FakeAuthorizer, FakeStream
from pydantic import ValidationError
from sqlalchemy import update

from app.models.domain import Document, TenantMembership
from app.services.agents.analyst_types import AnalystArtifact, AnalystPolicy
from app.services.agents.contracts import AnalystContent, TenderCategory
from app.services.agents.coverage import CoverageTracker
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.fact_register import (
    consolidate,
    missing_categories,
    normalize_extraction,
    validate_register,
)
from app.services.agents.graph import OrchestrationUnavailable, WorkflowGraph
from app.services.agents.nodes.analyst import AnalystFailure
from app.services.agents.nodes.analyst_nodes import AnalystNodes
from app.services.agents.persistence_types import safe_json
from app.services.agents.state import Cursor, Node, NodeResult, advance
from app.services.llm.contracts import ToolAction


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,native", [("openai", True), ("openai_compatible", False)])
async def test_actual_adapter_extraction_and_tool_replay(evidence_db, provider, native):
    p = await prepared(evidence_db, provider=provider, native=native)
    (chunk,) = await p.evidence.chunks((uid(14),))
    value = extraction(chunk)
    tool = ToolAction(
        call_id="read-context", arguments={"name": "lookup_definition", "term": "PPA"}
    )
    action = (
        reply(
            provider,
            status="tool_actions",
            tool="lookup_definition",
            arguments={"term": "PPA"},
            call_id=tool.call_id,
        )
        if native
        else reply(
            provider,
            {
                "kind": "tool_actions",
                "content": None,
                "actions": [tool.model_dump(mode="json")],
            },
        )
    )
    instance, backend, auth = adapter(
        p.request, wire(action), wire(reply(provider, encoded(value, native=native)))
    )
    record, _ = await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert record.extraction.findings.facts[0].normalized_number == "8"
    assert record.completion.artifact_sha256 == digest(record.extraction)
    assert record.extraction.findings.facts[0].fact_id != uid(500)
    assert record.extraction.evidence[0].physical_pages == (1,)
    assert record.extraction.evidence[0].printed_page_label == "printed-10"
    assert len(backend.calls) == 2 and p.allowance.usage.calls == 1
    assert len(instance.budget.records) == 2
    assert all(r.receipt is not None for r in instance.budget.records)
    serialized = AnalystArtifact(kind="analyst_batch.v1", payload=record).model_dump(mode="json")
    safe_json(serialized)
    assert "untrusted_source_data" in str(backend.payload())
    assert "synthetic-secret" not in str(serialized)
    tracker = CoverageTracker(p.inventory, p.plan)
    assert not tracker.report().complete
    for state in ("retrieved", "delivered", "processed"):
        tracker = tracker.record(
            0,
            state,
            batch_sha256=digest(record.batch),
            completion=record.completion if state == "processed" else None,
        )
    assert set(record.batch.primary_chunk_ids) <= set(tracker.report().processed_chunk_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["quote", "foreign", "range", "number", "unknown_requirement"])
async def test_invalid_extraction_rejected(evidence_db, change):
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    value = extraction(chunk).model_dump(mode="json")
    if change == "quote":
        value["quotes"][0]["exact_quote"] = "Capacity 9 MW"
    elif change == "foreign":
        value["quotes"][0]["chunk_id"] = str(uid(999))
    elif change == "range":
        value["quotes"][0]["char_start"] += 1
    elif change == "number":
        value["facts"][0].update(original_value="8 million", normalized_number="8000000")
    else:
        value = extraction(chunk, requirement=True).model_dump(mode="json")
        value["requirements"][0]["status"] = "unknown"
    with pytest.raises((ValueError, EvidenceError)):
        content = AnalystContent.model_validate(value)
        await normalize_extraction(
            content, p.evidence, {uid(14)}, binding=p.binding, origin="a" * 64
        )


@pytest.mark.asyncio
async def test_no_facts_unicode_and_no_coverage_from_retrieval(evidence_db):
    p = await prepared(evidence_db)
    instance, _, _ = adapter(p.request, wire(reply("openai", no_facts().model_dump(mode="json"))))
    result, _ = await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert result.extraction.no_facts_reason == "irrelevant_material"
    assert not result.extraction.findings.facts
    assert not CoverageTracker(p.inventory, p.plan).report().complete
    (chunk,) = await p.evidence.chunks((uid(14),))
    quote = "🌞"
    # Code point offsets differ from UTF-8 byte offsets; no normalization of source text.
    value = extraction(chunk, quote=quote, number=None, unit=None)
    canonical = await normalize_extraction(
        value, p.evidence, {uid(14)}, binding=p.binding, origin="a" * 64
    )
    assert canonical.evidence[0].char_end - canonical.evidence[0].char_start == 1
    with pytest.raises(ValidationError):
        AnalystContent()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["refused", "truncated"])
async def test_incomplete_results_never_issue_receipt(evidence_db, status):
    p = await prepared(evidence_db)
    instance, _, _ = adapter(p.request, wire(reply("openai", status=status)))
    with pytest.raises(AnalystFailure):
        await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert not CoverageTracker(p.inventory, p.plan).outcomes


@pytest.mark.asyncio
async def test_malformed_output_shared_repair_and_tool_limits(evidence_db):
    p = await prepared(evidence_db, policy=AnalystPolicy(max_tool_rounds=1))
    instance, backend, _ = adapter(
        p.request,
        wire(reply("openai", "{}")),
        wire(reply("openai", no_facts().model_dump(mode="json"))),
    )
    await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert len(backend.calls) == 2 and instance.budget.records[-1].repair
    # Another malformed batch cannot obtain a fresh shared format repair.
    backend.attempts = (wire(reply("openai", "{}")),)
    with pytest.raises(AnalystFailure, match="budget_exhausted"):
        await p.analyst.analyze(instance, p.plan.batches[1], binding=p.binding)
    instance, backend, _ = adapter(p.request, wire(reply("openai", status="tool_actions")))
    with pytest.raises(AnalystFailure, match="tool_limit"):
        await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert len(backend.calls) == 2


@pytest.mark.asyncio
async def test_stable_ids_reorder_aliases_and_conservative_collision(evidence_db):
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    a = extraction(chunk, requirement=True, claim_id=500)
    b = extraction(chunk, requirement=True, claim_id=600)
    records = [
        await normalize_extraction(x, p.evidence, {uid(14)}, binding=p.binding, origin=str(i) * 64)
        for i, x in enumerate((a, b), 1)
    ]
    first = records[0].findings.requirements[0]
    assert first.requirement_id == records[1].findings.requirements[0].requirement_id
    pages, seal = consolidate(
        records,
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=False,
    )
    again = consolidate(
        reversed(records),
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=False,
    )
    assert (pages, seal) == again
    doc = [pg for pg in pages if pg.level == "document"][0]
    assert len(doc.findings.requirements) == 1 and len(doc.aliases) == 2
    assert first.display_code.startswith("REQ-") and first.display_code != "REQ-999"
    changed = extraction(chunk, requirement=True, statement="Different prose", claim_id=700)
    changed = await normalize_extraction(
        changed, p.evidence, {uid(14)}, binding=p.binding, origin="3" * 64
    )
    assert changed.findings.requirements[0].requirement_id == first.requirement_id
    with pytest.raises(EvidenceError, match="identity_collision"):
        consolidate(
            [*records, changed],
            inventory=p.inventory,
            binding=p.binding,
            policy=p.analyst.policy,
            reading_complete=True,
        )


@pytest.mark.asyncio
async def test_emd_options_units_conditions_conflicts_and_table_rows(evidence_db):
    texts = (
        "Total capacity 225 MW. Each unit 75 MW. "
        "EMD option A 100 if eligible; option B 200 otherwise.",
        "Table: item | quantity\nPanel | 200",
        "Table: item | quantity\nInverter | 20",
        "Deadline 1 May. Conflicting addendum deadline 2 May.",
    )
    await canonical_source(evidence_db.sessions, texts=texts)
    p = await prepared(evidence_db)
    chunks = await p.evidence.chunks(tuple(e.chunk_id for e in p.inventory.entries))
    specifications = [
        (chunks[0], "Total capacity 225 MW", "225", "MW", (), "capacity_units"),
        (chunks[0], "Each unit 75 MW", "75", "MW/unit", (), "capacity_units"),
        (
            chunks[0],
            "option A 100 if eligible",
            "100",
            None,
            ("if eligible",),
            "securities_emd_pbg",
        ),
        (chunks[0], "option B 200 otherwise", "200", None, ("otherwise",), "securities_emd_pbg"),
        (chunks[1], "Panel | 200", "200", "panels", (), "technical"),
        (chunks[2], "Inverter | 20", "20", "inverters", (), "technical"),
    ]
    records = []
    for i, (chunk, quote, number, unit, conditions, category) in enumerate(specifications):
        content = extraction(
            chunk,
            quote=quote,
            number=number,
            unit=unit,
            conditions=conditions,
            category=category,
            claim_id=500 + i,
        )
        records.append(
            await normalize_extraction(
                content,
                p.evidence,
                {chunk.descriptor.chunk_id},
                binding=p.binding,
                origin=f"{i + 1:064x}",
            )
        )
    pages, seal = consolidate(
        records,
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
    )
    facts = [f for page in pages if page.level == "document" for f in page.findings.facts]
    assert len(facts) == 6
    assert {f.normalized_number for f in facts} == {"225", "75", "100", "200", "20"}
    assert all(f.conditions for f in facts if f.category.value == "securities_emd_pbg")
    gaps = {g.category: g.state for g in seal.gaps}
    assert gaps[TenderCategory.ISSUER_PARTIES] == "unknown_not_searched"
    assert gaps[TenderCategory.DATES_MILESTONES] == "unknown_not_searched"
    assert TenderCategory.ISSUER_PARTIES in missing_categories(records)


@pytest.mark.asyncio
async def test_register_overflow_and_oversized_request_fail_explicitly(evidence_db):
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    record = await normalize_extraction(
        extraction(chunk), p.evidence, {uid(14)}, binding=p.binding, origin="a" * 64
    )
    with pytest.raises(EvidenceError, match="register_overflow"):
        consolidate(
            [record],
            inventory=p.inventory,
            binding=p.binding,
            policy=AnalystPolicy(max_register_bytes=1024),
            reading_complete=True,
        )
    instance, backend, _ = adapter(p.request)
    with pytest.raises(AnalystFailure, match="request_invalid"):
        await p.analyst.extract(
            instance, {"evidence": "x" * 10000}, {uid(14)}, binding=p.binding, origin="a" * 64
        )
    assert not backend.calls
    with pytest.raises(OrchestrationUnavailable):
        WorkflowGraph(AnalystNodes(p.analyst, p.plan).handlers())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "membership", "allowance"])
async def test_revoked_lifecycle_blocks_acceptance(evidence_db, change):
    p = await prepared(evidence_db)
    instance, _, _ = adapter(p.request, wire(reply("openai", no_facts().model_dump(mode="json"))))
    if change == "allowance":
        p.allowance.active = False
    else:
        async with evidence_db.sessions.begin() as session:
            if change == "membership":
                await session.execute(
                    update(TenantMembership)
                    .where(TenantMembership.user_id == uid(9))
                    .values(role="VIEWER")
                )
            else:
                await session.execute(
                    update(Document)
                    .where(Document.id == uid(3))
                    .values(
                        lifecycle_status="DELETING",
                        deletion_requested_at=p.request.profile.capabilities.tested_at,
                        vectors_hidden_at=p.request.profile.capabilities.tested_at,
                    )
                )
    with pytest.raises((EvidenceError, PermissionError)):
        await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)


def test_no_transcripts_or_arbitrary_actions_and_continuation_edges():
    with pytest.raises(ValidationError):
        AnalystContent(no_facts_reason="irrelevant_material", api_key="synthetic-secret")
    with pytest.raises(ValidationError):
        ToolAction(call_id="bad", arguments={"name": "shell", "command": "printenv"})
    with pytest.raises(ValidationError):
        ToolAction(
            call_id="bad",
            arguments={"name": "lookup_definition", "term": "PPA", "tenant_id": str(uid(999))},
        )
    assert (
        advance(Cursor(node=Node.CONSOLIDATE), NodeResult(next_node=Node.CONSOLIDATE)).node
        == Node.CONSOLIDATE
    )
    with pytest.raises(ValidationError):
        advance(
            Cursor(node=Node.CONSOLIDATE, sequence=10000), NodeResult(next_node=Node.CONSOLIDATE)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_injection_unknown_actions_and_repeated_ids_fail_closed(evidence_db, native):
    p = await prepared(evidence_db, native=native)
    provider = p.request.profile.provider
    malicious = (
        reply(
            provider,
            status="tool_actions",
            tool="fetch_url",
            arguments={
                "url": "http://169.254.169.254/",
                "api_key": "source-request-not-a-credential",
            },
        )
        if native
        else reply(
            provider,
            {
                "kind": "tool_actions",
                "content": None,
                "actions": [
                    {"call_id": "evil", "arguments": {"name": "shell", "command": "printenv"}}
                ],
            },
        )
    )
    from app.services.llm.adapter_types import AttemptPolicy

    instance, backend, _ = adapter(p.request, wire(malicious), policy=AttemptPolicy(max_attempts=1))
    with pytest.raises(AnalystFailure, match="invalid_schema") as caught:
        await p.analyst.analyze(instance, p.plan.batches[-1], binding=p.binding)
    assert SENTINEL not in str(caught.value) and p.allowance.usage.calls == 0
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == "8.8.8.8"  # fake checked IP; never the injected URL
    action = ToolAction(call_id="repeated", arguments={"name": "lookup_definition", "term": "PPA"})
    response = (
        reply(
            provider,
            status="tool_actions",
            tool="lookup_definition",
            arguments={"term": "PPA"},
            call_id="repeated",
        )
        if native
        else reply(
            provider,
            {
                "kind": "tool_actions",
                "content": None,
                "actions": [action.model_dump(mode="json")],
            },
        )
    )
    p = await prepared(evidence_db, native=native, policy=AnalystPolicy(max_tool_rounds=3))
    instance, backend, _ = adapter(p.request, wire(response))
    with pytest.raises(AnalystFailure, match="repeated_action"):
        await p.analyst.analyze(instance, p.plan.batches[-1], binding=p.binding)
    assert len(backend.calls) == 2 and p.allowance.usage.calls == 1


@pytest.mark.asyncio
async def test_timeout_after_submit_is_not_replayed_and_usage_remains_unknown(evidence_db):
    p = await prepared(evidence_db)
    stream = FakeStream(b"")

    async def timeout(*args, **kwargs):
        raise httpcore.ReadTimeout(SENTINEL)

    stream.read = timeout
    instance, backend, _ = adapter(p.request, backend=SequenceBackend(stream))
    with pytest.raises(AnalystFailure, match="provider_unavailable") as caught:
        await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
    assert len(backend.calls) == 1 and instance.budget.records[0].submitted
    assert instance.budget.records[0].usage.source == "unknown"
    assert SENTINEL not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rotate", "revoke", "cancel"])
async def test_authorization_changes_between_calls_and_after_submission(evidence_db, change):
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    auth = FakeAuthorizer()
    stream = FakeStream(wire(reply("openai", status="tool_actions")))
    original_read = stream.read

    async def changed_read(*args, **kwargs):
        result = await original_read(*args, **kwargs)
        if result:
            if change == "rotate":
                auth.version = 2
            elif change == "revoke":
                auth.enabled = False
            else:
                p.allowance.active = False
        return result

    stream.read = changed_read
    instance, backend, _ = adapter(
        p.request,
        backend=SequenceBackend(
            stream, wire(reply("openai", extraction(chunk).model_dump(mode="json")))
        ),
        auth=auth,
    )
    if change == "rotate":
        output, usage = await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
        assert output.completion
        assert [r.receipt.credential_version for r in instance.budget.records] == [1, 2]
        assert usage.input_tokens == 20 and usage.output_tokens == 10
    else:
        with pytest.raises((AnalystFailure, PermissionError)):
            await p.analyst.analyze(instance, p.plan.batches[0], binding=p.binding)
        assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_conflicting_dates_preserved_and_gap_search_is_bounded(evidence_db):
    await canonical_source(
        evidence_db.sessions,
        texts=("Deadline 1 May. Conflicting addendum deadline 2 May. No issuer stated.",),
    )
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    content = extraction(
        chunk,
        quote="Deadline 1 May. Conflicting addendum deadline 2 May.",
        number=None,
        unit=None,
        category="dates_milestones",
    ).model_dump(mode="json")
    content["facts"][0].update(
        status="conflicting", alternatives=["1 May", "2 May"], critical_class="date"
    )
    record = await normalize_extraction(
        AnalystContent.model_validate(content),
        p.evidence,
        {uid(14)},
        binding=p.binding,
        origin="a" * 64,
    )
    _, seal = consolidate(
        [record],
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
    )
    assert (
        next(g for g in seal.gaps if g.category == TenderCategory.DATES_MILESTONES).state
        == "conflicting"
    )
    instance, backend, _ = adapter(
        p.request, wire(reply("openai", no_facts().model_dump(mode="json")))
    )
    from types import SimpleNamespace

    context = SimpleNamespace(provider=instance)
    nodes = AnalystNodes(p.analyst, p.plan)
    result = await nodes.gap(context, p.binding, (TenderCategory.ISSUER_PARTIES,), 0)
    assert result.outcome == "completed" and result.requested_categories == (
        TenderCategory.ISSUER_PARTIES,
    )
    assert p.allowance.usage.calls == 1 and len(backend.calls) == 1
    _, seal = consolidate(
        [record, result.extraction],
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
        gap_records=(result,),
    )
    assert (
        next(g for g in seal.gaps if g.category == TenderCategory.ISSUER_PARTIES).state
        == "not_found_within_allowance"
    )
    assert not any(g.absence_proven for g in seal.gaps)


@pytest.mark.asyncio
async def test_register_pages_retain_every_requirement_and_hash_chain(evidence_db):
    await canonical_source(
        evidence_db.sessions,
        texts=("\n".join(f"Requirement {i}: deliver item {i}." for i in range(120)),),
    )
    p = await prepared(evidence_db)
    (chunk,) = await p.evidence.chunks((uid(14),))
    records = []
    for start in (0, 60):
        values = [
            extraction(
                chunk,
                quote=f"Requirement {i}: deliver item {i}.",
                requirement=True,
                claim_id=500 + i,
            )
            for i in range(start, start + 60)
        ]
        content = AnalystContent(
            requirements=tuple(r for v in values for r in v.requirements),
            quotes=tuple(q for v in values for q in v.quotes),
        )
        records.append(
            await normalize_extraction(
                content, p.evidence, {uid(14)}, binding=p.binding, origin=f"{start + 1:064x}"
            )
        )
    pages, seal = consolidate(
        records,
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
    )
    document = [page for page in pages if page.level == "document"]
    requirements = [r for page in document for r in page.findings.requirements]
    assert (
        len(document) > 1
        and len(requirements) == len({r.requirement_id for r in requirements}) == 120
    )
    assert sum(len(page.aliases) for page in document) == 120
    assert seal.root_sha256 == digest(pages[-1]) and seal.page_count == len(pages)
    assert pages[0].previous_sha256 is None
    assert all(
        page.previous_sha256 == digest(previous)
        for previous, page in zip(pages[:-1], pages[1:], strict=True)
    )
    assert all(len(page.model_dump_json().encode()) <= 200000 for page in pages)
    validate_register(pages, seal)
    with pytest.raises(EvidenceError, match="pages_missing"):
        validate_register(pages[:-1], seal)
    with pytest.raises(EvidenceError, match="chain_invalid"):
        validate_register(
            (pages[0].model_copy(update={"previous_sha256": "f" * 64}), *pages[1:]), seal
        )
    assert consolidate(
        list(reversed(records)),
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
    ) == (pages, seal)
    with pytest.raises(EvidenceError, match="register_overflow"):
        consolidate(
            records,
            inventory=p.inventory,
            binding=p.binding,
            policy=AnalystPolicy(max_register_entries=1),
            reading_complete=True,
        )


@pytest.mark.asyncio
async def test_duplicate_source_mentions_retain_all_citations_and_unresolved_flags(evidence_db):
    await canonical_source(evidence_db.sessions, texts=("Supply equipment.", "Supply equipment."))
    p = await prepared(evidence_db)
    chunks = await p.evidence.chunks(tuple(e.chunk_id for e in p.inventory.entries))
    records = []
    for i, chunk in enumerate(chunks):
        data = extraction(
            chunk, quote="Supply equipment.", requirement=True, claim_id=500 + i
        ).model_dump(mode="json")
        data["unresolved_categories"] = ["scope_deliverables"]
        records.append(
            await normalize_extraction(
                AnalystContent.model_validate(data),
                p.evidence,
                {chunk.descriptor.chunk_id},
                binding=p.binding,
                origin=f"{i + 1:064x}",
            )
        )
    pages, seal = consolidate(
        records,
        inventory=p.inventory,
        binding=p.binding,
        policy=p.analyst.policy,
        reading_complete=True,
    )
    reqs = [r for page in pages if page.level == "document" for r in page.findings.requirements]
    assert len(reqs) == 1 and len(reqs[0].evidence_ids) == 2
    assert next(
        g for g in seal.gaps if g.category == TenderCategory.SCOPE_DELIVERABLES
    ).analyst_reported_unresolved
