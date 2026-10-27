"""Isolated Step 7 evidence tests. Run with --noconftest."""

from dataclasses import replace

import pytest
from agent_evidence_fixtures import TEXTS, QueryProvider, canonical_source, profile, source
from agent_evidence_fixtures import evidence_db as db_fixture  # noqa: F401
from agent_schema_fixtures import access, uid
from sqlalchemy import update

from app.models.domain import Document, DocumentChunk, DocumentProcessingRun, TenantMembership
from app.services.agents.budgeting import ContextBudget, attach_context, build_reading_plan
from app.services.agents.coverage import CoverageTracker
from app.services.agents.evidence import EvidenceAccess, PinnedRetriever
from app.services.agents.evidence_types import (
    BatchCompletion,
    EvidenceArtifact,
    EvidenceError,
    ToolPolicy,
    digest,
)
from app.services.agents.inventory import Inventory, build_inventory
from app.services.agents.tool_budget import reserve_usage
from app.services.agents.tools import EvidenceTools
from app.services.ingestion.pinned import PinnedEvidenceRepository
from app.services.llm.contracts import ToolAction


async def prepared(db):
    inventory = await build_inventory(db.repository)
    return inventory, EvidenceAccess(db.repository, inventory)


def budget(context=12000, **kwargs):
    return ContextBudget(profile(context, **kwargs), "Synthetic controller instructions", (), 128)


@pytest.mark.asyncio
async def test_inventory_chain_metadata_and_replay(evidence_db):
    db = evidence_db
    first, evidence = await prepared(db)
    again = await build_inventory(db.repository, first.manifest.pin)
    assert first == again and first.sha256 == again.sha256
    assert len(first.entries) == len(TEXTS)
    assert first.manifest.pin.warning_codes == ("repeated_margin_removed",)
    assert first.entries[3].source_references[1].role == "header_context"
    assert first.entries[4].heading_path[0] == "GLOSSARY"
    assert (
        len(
            EvidenceArtifact(kind="inventory_manifest.v1", payload=first.manifest).model_dump_json()
        )
        < 10000
    )
    with pytest.raises(EvidenceError, match="chain_invalid"):
        Inventory(
            first.manifest, (first.pages[0].model_copy(update={"previous_sha256": "b" * 64}),)
        )
    with pytest.raises(EvidenceError, match="pages_missing"):
        Inventory(first.manifest, ())
    async with db.sessions.begin() as session:
        row = await session.get(DocumentChunk, uid(14))
        row.content += " modified"
    with pytest.raises(EvidenceError, match="input_changed"):
        await evidence.chunks((uid(14),))
    with pytest.raises(EvidenceError, match="input_changed"):
        await evidence.publication_guard()


@pytest.mark.asyncio
async def test_multi_page_inventory_and_section_cursors(evidence_db):
    await canonical_source(
        evidence_db.sessions, texts=tuple(f"Synthetic section item {i}" for i in range(70))
    )
    inventory, evidence = await prepared(evidence_db)
    assert len(inventory.pages) == 2 and len(inventory.entries) == 70
    assert inventory.pages[1].previous_sha256 == digest(inventory.pages[0])
    section = inventory.entries[5].section_id
    cursor, seen = 0, []
    while cursor is not None:
        chunks, cursor = await evidence.section(section, cursor)
        seen.extend(c.descriptor.chunk_id for c in chunks)
    assert seen == [e.chunk_id for e in inventory.entries if e.section_id == section]
    assert Inventory(inventory.manifest, inventory.pages) == inventory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uid(101)),
        ("project_id", uid(999)),
        ("document_id", uid(999)),
        ("processing_run_id", uid(999)),
    ],
)
async def test_scope_override_known_ids_denied(evidence_db, field, value):
    with pytest.raises((EvidenceError, PermissionError)):
        repo = PinnedEvidenceRepository(
            evidence_db.sessions, access(), source().model_copy(update={field: value})
        )
        await repo.pin()


@pytest.mark.asyncio
async def test_readers_foreign_ids_cursors_and_auth_revocation(evidence_db):
    inventory, evidence = await prepared(evidence_db)
    with pytest.raises(EvidenceError, match="outside_inventory"):
        await evidence.neighbors((uid(999),), 1)
    with pytest.raises(EvidenceError, match="cursor_invalid"):
        await evidence.repository.page(evidence.pin, after=True)
    with pytest.raises(EvidenceError, match="section_cursor_invalid"):
        await evidence.section(inventory.entries[1].section_id, 5)
    with pytest.raises(EvidenceError, match="outside_inventory"):
        await evidence.section("f" * 64)
    page, cursor = await evidence.section(inventory.entries[1].section_id)
    assert [c.descriptor.ordinal for c in page] == [1, 2, 3] and cursor is None
    async with evidence_db.sessions.begin() as session:
        await session.execute(
            update(TenantMembership).where(TenantMembership.user_id == uid(9)).values(role="VIEWER")
        )
    with pytest.raises(PermissionError):
        await evidence.guard()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["active", "hash", "status", "deleting", "count"])
async def test_lifecycle_changes_fail_closed(evidence_db, mutation):
    _, evidence = await prepared(evidence_db)
    from agent_schema_fixtures import NOW

    async with evidence_db.sessions.begin() as session:
        doc = await session.get(Document, uid(3))
        if mutation == "active":
            doc.current_processing_run_id = None
        elif mutation == "hash":
            doc.content_sha256 = "b" * 64
        elif mutation == "status":
            doc.processing_status = "FAILED"
        elif mutation == "deleting":
            doc.lifecycle_status, doc.deletion_requested_at, doc.vectors_hidden_at = (
                "DELETING",
                NOW,
                NOW,
            )
        else:
            run = await session.get(DocumentProcessingRun, uid(4))
            run.chunk_count += 1
    with pytest.raises(EvidenceError):
        await evidence.chunks((uid(14),))


@pytest.mark.asyncio
async def test_exact_unicode_physical_pages_and_table_locators(evidence_db):
    _, evidence = await prepared(evidence_db)
    start = TEXTS[0].index("🌞")
    ref = await evidence.reference(uid(14), start, start + 1, quote="🌞")
    assert ref.physical_pages == (1,) and ref.printed_page_label == "printed-10"
    assert ref.char_end - ref.char_start == 1
    assert await evidence.validate_reference(ref) == ref
    for bad in [
        ref.model_copy(update={"physical_pages": (2,)}),
        ref.model_copy(update={"chunk_sha256": "0" * 64}),
        ref.model_copy(update={"exact_quote": "X"}),
        ref.model_copy(update={"scope": source().model_copy(update={"document_id": uid(99)})}),
    ]:
        with pytest.raises(EvidenceError):
            await evidence.validate_reference(bad)
    for a, b in [(-1, 1), (True, 2), (0, 100000), (2, 1)]:
        with pytest.raises(EvidenceError):
            await evidence.reference(uid(14), a, b)
    table = await evidence.reference(uid(202), 0, 5)
    assert table.table_id == "page:2/table:0" and table.row_id == "row:0"
    # Same table but repeated header context never fabricates primary coverage.
    row = await evidence.reference(uid(203), 0, 5)
    assert row.table_id == "page:2/table:0" and row.row_id is None


@pytest.mark.asyncio
async def test_batches_exact_partition_context_budget_and_coverage(evidence_db):
    inventory, _ = await prepared(evidence_db)
    plan = await build_reading_plan(evidence_db.repository, inventory, budget())
    again = await build_reading_plan(evidence_db.repository, inventory, budget())
    assert plan == again and not plan.blocked
    assert [i for b in plan.batches for i in b.primary_chunk_ids] == [
        e.chunk_id for e in inventory.entries
    ]
    tracker = CoverageTracker(inventory, plan)
    assert all(o.state == "assigned" for p in tracker.pages() for o in p.outcomes)
    assert not tracker.report().complete
    for i, b in enumerate(plan.batches):
        with pytest.raises(EvidenceError):
            tracker.record(
                i,
                "processed",
                batch_sha256=digest(b),
                completion=BatchCompletion(
                    inventory_sha256=inventory.sha256,
                    batch_sha256=digest(b),
                    primary_chunk_ids=b.primary_chunk_ids,
                    artifact_sha256="c" * 64,
                ),
            )
        tracker = tracker.record(i, "retrieved", batch_sha256=digest(b))
        assert not tracker.report().complete
        tracker = tracker.record(i, "delivered", batch_sha256=digest(b))
        with pytest.raises(EvidenceError, match="completion_input_mismatch"):
            tracker.record(
                i,
                "processed",
                batch_sha256=digest(b),
                completion=BatchCompletion(
                    inventory_sha256=inventory.sha256,
                    batch_sha256=digest(b),
                    primary_chunk_ids=(uid(999),),
                    artifact_sha256="c" * 64,
                ),
            )
        tracker = tracker.record(
            i,
            "processed",
            batch_sha256=digest(b),
            completion=BatchCompletion(
                inventory_sha256=inventory.sha256,
                batch_sha256=digest(b),
                primary_chunk_ids=b.primary_chunk_ids,
                artifact_sha256="c" * 64,
            ),
        )
    assert tracker.report().complete
    await prepared(evidence_db)  # No read or inventory operation mutates processed coverage.
    assert CoverageTracker(inventory, plan).report().processed_chunk_ids == ()
    contextual = await attach_context(
        evidence_db.repository, inventory, budget(), plan, 0, (uid(201),)
    )
    assert contextual.batches[0].context_chunk_ids == (uid(201),)
    assert [i for b in contextual.batches for i in b.primary_chunk_ids] == [
        e.chunk_id for e in inventory.entries
    ]
    with pytest.raises(EvidenceError):
        await attach_context(evidence_db.repository, inventory, budget(), plan, 0, (uid(999),))
    smaller = await build_reading_plan(evidence_db.repository, inventory, budget(2048))
    assert smaller != plan and len(smaller.batches) >= len(plan.batches)
    limited = await build_reading_plan(evidence_db.repository, inventory, budget(max_calls=1))
    assert limited.blocked and not CoverageTracker(inventory, limited).report().complete
    assert (await evidence_db.repository.pin()).processing == inventory.manifest.pin.processing


@pytest.mark.asyncio
async def test_oversized_and_empty_sources_are_explicit(evidence_db):
    await canonical_source(evidence_db.sessions, texts=("table " * 10000,))
    inventory, _ = await prepared(evidence_db)
    plan = await build_reading_plan(evidence_db.repository, inventory, budget(2048))
    assert plan.blocked == (0,) and plan.batches[0].primary_chunk_ids == (uid(14),)
    # Recreate only this disposable fixture's source as empty.
    from sqlalchemy import delete

    async with evidence_db.sessions.begin() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.processing_run_id == uid(4))
        )
        (await session.get(DocumentProcessingRun, uid(4))).chunk_count = 0
    inventory, _ = await prepared(evidence_db)
    plan = await build_reading_plan(evidence_db.repository, inventory, budget())
    with pytest.raises(EvidenceError, match="empty_source"):
        CoverageTracker(inventory, plan).report()


class Allowance:
    """Test-only serialized allowance. Production uses WorkflowToolAllowance."""

    def __init__(self, binding, policy=None):
        self.binding, self.policy, self.usage = binding, policy or ToolPolicy(), None

    async def check(self):
        pass

    async def reserve(self, key):
        self.usage = reserve_usage(self.usage, self.binding, self.policy, key)


@pytest.mark.asyncio
async def test_tools_are_scoped_bounded_untrusted_and_not_coverage(evidence_db):
    inventory, evidence = await prepared(evidence_db)
    context = budget()
    allowance = Allowance(digest({"inventory": inventory.sha256, "context": context.sha256}))
    tools = EvidenceTools(evidence, PinnedRetriever(evidence, QueryProvider()), context, allowance)
    action = ToolAction(
        call_id="test",
        arguments={"name": "read_chunk_neighbors", "chunk_ids": [str(uid(205))], "radius": 0},
    )
    reply = await tools.run(action)
    assert not reply.is_error and "execute SQL" in reply.output_json
    assert '"coverage_processed":false' in reply.output_json
    assert '"trust":"untrusted_source_data"' in reply.output_json
    await tools.run(action)
    await tools.run(action)
    with pytest.raises(EvidenceError, match="budget_exhausted"):
        await tools.run(action.model_copy(update={"call_id": "new-id-does-not-reset"}))
    for arguments in [
        {"name": "shell", "command": "id"},
        {"name": "lookup_definition", "term": "PPA", "tenant_id": str(uid(101))},
    ]:
        with pytest.raises(EvidenceError, match="arguments_invalid"):
            await tools.run({"call_id": "bad", "arguments": arguments})
    defined = await tools.run(
        {"call_id": "definition", "arguments": {"name": "lookup_definition", "term": "PPA"}}
    )
    assert not defined.is_error and "electricity sale agreement" in defined.output_json
    assert '"absence_proven":false' in defined.output_json


@pytest.mark.asyncio
async def test_search_embedding_identity_and_pg_only_boundary(evidence_db):
    _, evidence = await prepared(evidence_db)
    provider = QueryProvider()
    provider.model_revision = "wrong"
    with pytest.raises(EvidenceError, match="embedding_identity"):
        await PinnedRetriever(evidence, provider).search("capacity")
    with pytest.raises(EvidenceError, match="pgvector_required"):
        await PinnedRetriever(evidence, QueryProvider()).search("capacity")
    with pytest.raises(EvidenceError, match="outside_inventory"):
        await PinnedRetriever(evidence, QueryProvider()).search("capacity", section="f" * 64)


@pytest.mark.asyncio
async def test_source_loss_warnings_cannot_report_full_coverage(evidence_db):
    async with evidence_db.sessions.begin() as session:
        (await session.get(DocumentProcessingRun, uid(4))).warning_codes = [
            "partial_element_skipped"
        ]
    inventory, _ = await prepared(evidence_db)
    plan = await build_reading_plan(evidence_db.repository, inventory, budget())
    tracker = CoverageTracker(inventory, plan)
    for i, b in enumerate(plan.batches):
        tracker = tracker.record(i, "retrieved", batch_sha256=digest(b))
        tracker = tracker.record(i, "delivered", batch_sha256=digest(b))
        tracker = tracker.record(
            i,
            "processed",
            batch_sha256=digest(b),
            completion=BatchCompletion(
                inventory_sha256=inventory.sha256,
                batch_sha256=digest(b),
                primary_chunk_ids=b.primary_chunk_ids,
                artifact_sha256="c" * 64,
            ),
        )
    assert tracker.report().truncated and not tracker.report().complete


@pytest.mark.asyncio
async def test_tool_failures_exclude_raw_exception_and_oversized_results(evidence_db):
    inventory, evidence = await prepared(evidence_db)

    class FailingProvider(QueryProvider):
        def embed_query(self, query):
            raise RuntimeError("SYNTHETIC_PRIVATE_KEY_NOT_FOR_ERRORS")

    context = budget()
    allowance = Allowance(digest({"inventory": inventory.sha256, "context": context.sha256}))
    tools = EvidenceTools(
        evidence, PinnedRetriever(evidence, FailingProvider()), context, allowance
    )
    reply = await tools.run(
        {"call_id": "failure", "arguments": {"name": "search_document", "query": "capacity"}}
    )
    assert reply.is_error and "SYNTHETIC_PRIVATE" not in reply.output_json
    small = Allowance(allowance.binding, ToolPolicy(response_bytes=512))
    tools = EvidenceTools(evidence, PinnedRetriever(evidence, QueryProvider()), context, small)
    reply = await tools.run(
        {
            "call_id": "large",
            "arguments": {
                "name": "read_chunk_neighbors",
                "chunk_ids": [str(uid(203))],
                "radius": 2,
            },
        }
    )
    assert reply.is_error and "result_oversized" in reply.output_json
    assert small.usage.calls == 1


def test_tool_ledger_reconstruction_and_tokenizer_bounds():
    policy = ToolPolicy(max_calls=2)
    first = reserve_usage(None, "a" * 64, policy, "b" * 64)
    from app.services.agents.evidence_types import ToolUsage

    restored = ToolUsage.model_validate_json(first.model_dump_json())
    second = reserve_usage(restored, "a" * 64, policy, "c" * 64)
    with pytest.raises(EvidenceError):
        reserve_usage(second, "a" * 64, policy, "d" * 64)
    with pytest.raises(EvidenceError):
        reserve_usage(restored, "b" * 64, policy, "d" * 64)
    b = budget()
    assert b.accounting == "utf8_upper_estimate" and b.count("🌞") >= 4
    exact = replace(
        b, tokenizer=lambda s: len(s), tokenizer_identity="synthetic-reviewed-tokenizer"
    )
    assert exact.accounting == "approved_tokenizer"
    with pytest.raises(EvidenceError):
        replace(b, tokenizer=lambda s: True, tokenizer_identity="bad").count("x")
    with pytest.raises(EvidenceError):
        replace(b, tokenizer=lambda s: 1)
