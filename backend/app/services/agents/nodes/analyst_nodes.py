"""Step 8 handlers only. Deliberately not registered in any application endpoint."""

import json
from uuid import UUID

from app.services.agents.analyst_types import AnalystArtifact, GapRecord
from app.services.agents.coverage import CoverageTracker
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.agents.fact_register import consolidate, missing_categories
from app.services.agents.state import Node, NodeResult
from app.services.llm.contracts import ToolAction


class AnalystNodes:
    """Trusted worker composes one instance per fenced attempt, with the saved plan."""

    def __init__(self, analyst, plan):
        self.analyst, self.plan = analyst, plan
        # This also validates complete ordered primary coverage and blocked identities.
        CoverageTracker(analyst.evidence.inventory, plan)
        if not plan.batches or len(plan.batches) > 120:
            raise EvidenceError("analyst_reading_plan_unavailable")

    def handlers(self):
        # WorkflowGraph still refuses a partial registration. Later nodes are NOT stubs.
        return {Node.ANALYZE: self.analyze, Node.CONSOLIDATE: self.consolidate}

    async def history(self, context):
        await self.analyst.guard()
        binding = self.analyst.binding(context.workflow, self.plan)
        before, history = None, []
        while True:
            page = await context.checkpoints.list(before=before, limit=100)
            if not page:
                break
            history.extend(page)
            if len(history) > 10000:
                raise EvidenceError("analyst_history_overflow")
            cursor = min(p.after.sequence for p in page)
            if before is not None and cursor >= before:
                raise EvidenceError("analyst_history_cursor_invalid")
            before = cursor
        artifacts = []
        for completed in sorted(history, key=lambda p: p.before.sequence):
            if completed.workflow_run_id != context.workflow.workflow_run_id:
                raise EvidenceError("analyst_history_scope_mismatch")
            artifact = completed.result.artifact
            if isinstance(artifact, AnalystArtifact):
                payload = artifact.payload
                record = payload.extraction if hasattr(payload, "extraction") else None
                if (record.binding if record else payload.binding) != binding:
                    raise EvidenceError("analyst_replay_incompatible")
                if completed.before.sequence >= context.cursor.sequence:
                    raise EvidenceError("analyst_history_future")
                if record:
                    for ref in record.evidence:
                        await self.analyst.evidence.validate_reference(ref)
                artifacts.append(artifact)
            elif completed.before.node in {Node.ANALYZE, Node.CONSOLIDATE}:
                raise EvidenceError("analyst_replay_incompatible")
        batches = [a.payload for a in artifacts if a.kind == "analyst_batch.v1"]
        tracker = CoverageTracker(self.analyst.evidence.inventory, self.plan)
        for i, batch in enumerate(batches):
            if i >= len(self.plan.batches) or batch.batch != self.plan.batches[i]:
                raise EvidenceError("analyst_replay_batch_mismatch")
            for state in ("retrieved", "delivered", "processed"):
                tracker = tracker.record(
                    i,
                    state,
                    batch_sha256=digest(batch.batch),
                    completion=batch.completion if state == "processed" else None,
                )
        return binding, artifacts, tracker

    async def analyze(self, context):
        if context.cursor.node != Node.ANALYZE:
            raise EvidenceError("analyst_node_mismatch")
        binding, artifacts, _ = await self.history(context)
        completed = sum(a.kind == "analyst_batch.v1" for a in artifacts)
        if context.cursor.batch != completed or completed >= len(self.plan.batches):
            raise EvidenceError("analyst_cursor_mismatch")
        artifact, usage = await self.analyst.analyze(
            context.provider, self.plan.batches[completed], binding=binding
        )
        await self.analyst.guard()
        return NodeResult(
            next_node=Node.ANALYZE if completed + 1 < len(self.plan.batches) else Node.CONSOLIDATE,
            artifact=AnalystArtifact(kind="analyst_batch.v1", payload=artifact),
            usage=usage,
        )

    async def gap(self, context, binding, categories, round):
        """One controller-targeted category search, then optional bounded analyst follow-up."""
        category = categories[0]
        action = ToolAction(
            call_id=f"gap-{round}",
            arguments={
                "name": "search_document",
                "query": category.value.replace("_", " "),
                "limit": 5,
            },
        )
        base = dict(
            binding=binding,
            inventory_sha256=self.plan.inventory_sha256,
            round=round,
            requested_categories=(category,),
        )
        try:
            exchange = await self.analyst.tools.run(action)
            if exchange.is_error:
                return GapRecord(**base, outcome="blocked")
            data = json.loads(exchange.output_json)
            ids = tuple(UUID(c["chunk_id"]) for c in data.get("chunks", []))
            for chunk in data.get("chunks", []):
                (canonical,) = await self.analyst.evidence.chunks((UUID(chunk["chunk_id"]),))
                if chunk["content"] != canonical.content:
                    raise EvidenceError("analyst_tool_evidence_mismatch")
            record, usage = await self.analyst.extract(
                context.provider,
                {
                    "task": "resolve_one_missing_category",
                    "category": category.value,
                    "absence_proven": False,
                },
                ids,
                binding=binding,
                origin=digest(base),
                initial=(exchange,),
            )
            return GapRecord(**base, extraction=record, outcome="completed", usage=usage)
        except EvidenceError as error:
            if str(error) in {"evidence_tool_budget_exhausted", "analyst_budget_exhausted"}:
                return GapRecord(**base, outcome="budget_exhausted")
            raise

    async def consolidate(self, context):
        if context.cursor.node != Node.CONSOLIDATE:
            raise EvidenceError("analyst_node_mismatch")
        binding, artifacts, tracker = await self.history(context)
        batches = [a.payload for a in artifacts if a.kind == "analyst_batch.v1"]
        if len(batches) != len(self.plan.batches) or context.cursor.batch != len(batches):
            raise EvidenceError("analyst_coverage_incomplete")
        gaps = [a.payload for a in artifacts if a.kind == "analyst_gap.v1"]
        if [g.round for g in gaps] != list(range(len(gaps))):
            raise EvidenceError("analyst_gap_replay_invalid")
        records = [b.extraction for b in batches] + [g.extraction for g in gaps if g.extraction]
        requested = {c for g in gaps for c in g.requested_categories}
        missing = [c for c in missing_categories(records) if c not in requested]
        if (
            missing
            and tracker.report().complete
            and len(gaps) < self.analyst.policy.max_gap_rounds
            and not any(g.outcome == "budget_exhausted" for g in gaps)
        ):
            result = await self.gap(context, binding, missing, len(gaps))
            return NodeResult(
                next_node=Node.CONSOLIDATE,
                artifact=AnalystArtifact(kind="analyst_gap.v1", payload=result),
                usage=result.usage,
            )
        pages, seal = consolidate(
            records,
            inventory=self.analyst.evidence.inventory,
            binding=binding,
            policy=self.analyst.policy,
            reading_complete=tracker.report().complete,
            gap_records=gaps,
        )
        existing = [a.payload for a in artifacts if a.kind == "fact_register_page.v1"]
        if tuple(existing) != pages[: len(existing)] or len(existing) > len(pages):
            raise EvidenceError("analyst_register_replay_mismatch")
        if any(a.kind == "fact_register.v1" for a in artifacts):
            raise EvidenceError("analyst_register_already_sealed")
        await self.analyst.guard()
        if len(existing) < len(pages):
            return NodeResult(
                next_node=Node.CONSOLIDATE,
                artifact=AnalystArtifact(
                    kind="fact_register_page.v1", payload=pages[len(existing)]
                ),
            )
        # WRITE has no implementation here; the complete WorkflowGraph still cannot register.
        return NodeResult(
            next_node=Node.WRITE, artifact=AnalystArtifact(kind="fact_register.v1", payload=seal)
        )


async def build_analyst_nodes(
    store,
    claim,
    plan,
    context_budget,
    query_embedder,
    *,
    reranker=None,
    policy=None,
    tool_policy=None,
):
    """Explicit trusted composition hook; never loads models or enables a graph."""
    from app.services.agents.evidence import (
        EvidenceAccess,
        PinnedRetriever,
        repository_for_workflow,
    )
    from app.services.agents.evidence_storage import EvidenceArtifactStore
    from app.services.agents.evidence_types import ToolPolicy
    from app.services.agents.nodes.analyst import EvidenceAnalyst
    from app.services.agents.tool_budget import WorkflowToolAllowance
    from app.services.agents.tools import EvidenceTools

    await store.check(claim.fence)
    if context_budget.profile != claim.workflow.profile:
        raise EvidenceError("analyst_profile_mismatch")
    inventory = await EvidenceArtifactStore(store, claim.fence).load_inventory()
    repository = await repository_for_workflow(store)
    evidence = EvidenceAccess(repository, inventory)
    retriever = PinnedRetriever(evidence, query_embedder, reranker=reranker)
    allowance = WorkflowToolAllowance(
        store,
        claim.fence,
        digest({"inventory": inventory.sha256, "context": context_budget.sha256}),
        tool_policy or ToolPolicy(),
        profile=claim.workflow.profile,
    )
    tools = EvidenceTools(evidence, retriever, context_budget, allowance)
    return AnalystNodes(EvidenceAnalyst(evidence, tools, context_budget, policy=policy), plan)
