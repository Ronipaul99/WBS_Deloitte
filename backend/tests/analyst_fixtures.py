"""Synthetic analyst inputs; fake network and allowance implementations stay in tests."""

from types import SimpleNamespace

from agent_schema_fixtures import uid
from llm_adapter_fixtures import request

from app.services.agents.budgeting import ContextBudget, build_reading_plan
from app.services.agents.contracts import (
    AnalystContent,
    AnalystQuote,
    Fact,
    Requirement,
    WorkflowInput,
)
from app.services.agents.evidence import EvidenceAccess
from app.services.agents.evidence_types import ToolPolicy, ToolUsage, digest
from app.services.agents.inventory import build_inventory
from app.services.agents.nodes.analyst import TOOL_NAMES, EvidenceAnalyst
from app.services.agents.nodes.analyst_prompt import INSTRUCTIONS
from app.services.agents.tool_budget import reserve_usage
from app.services.agents.tools import EvidenceTools
from app.services.llm.protocol_support import tool_schemas


class MemoryAllowance:
    def __init__(self, binding, policy=None):
        self.binding, self.policy = binding, policy or ToolPolicy()
        self.usage = ToolUsage(binding=binding, policy=self.policy)
        self.active = True

    async def check(self):
        if not self.active:
            raise PermissionError("synthetic revoked authorization")

    async def reserve(self, request_hash):
        await self.check()
        self.usage = reserve_usage(self.usage, self.binding, self.policy, request_hash)
        return self.usage


class Retrieval:
    def __init__(self, evidence):
        self.evidence = evidence

    async def search(self, query, section=None, limit=5):
        return tuple(
            SimpleNamespace(chunk_id=e.chunk_id, score=0.5)
            for e in self.evidence.inventory.entries[:limit]
        )


async def prepared(db, *, provider="openai", native=True, policy=None):
    inventory = await build_inventory(db.repository)
    evidence = EvidenceAccess(db.repository, inventory)
    req = request(provider, schema="analyst.v1", native=native)
    budget = ContextBudget(req.profile, INSTRUCTIONS, tuple(tool_schemas(TOOL_NAMES)), 1024)
    allowance = MemoryAllowance(digest({"inventory": inventory.sha256, "context": budget.sha256}))
    tools = EvidenceTools(evidence, Retrieval(evidence), budget, allowance)
    analyst = EvidenceAnalyst(evidence, tools, budget, policy=policy)
    plan = await build_reading_plan(db.repository, inventory, budget)
    workflow = WorkflowInput(
        workflow_run_id=uid(80),
        scope=evidence.pin.scope,
        processing_state="completed",
        requested_by=uid(9),
        profile=req.profile,
        workflow_version="summary-v1",
        prompt_version="summary-prompts-v1",
        output_schema_version="tender_summary.v1",
    )
    return SimpleNamespace(
        analyst=analyst,
        plan=plan,
        inventory=inventory,
        evidence=evidence,
        request=req,
        allowance=allowance,
        workflow=workflow,
        binding=analyst.binding(workflow, plan),
    )


def no_facts():
    return AnalystContent(no_facts_reason="irrelevant_material")


def extraction(
    chunk,
    *,
    quote="Capacity 8 MW",
    number="8",
    unit="MW",
    conditions=(),
    category="capacity_units",
    claim_id=500,
    requirement=False,
    statement=None,
):
    start = chunk.content.index(quote)
    evidence = AnalystQuote(
        quote_id=uid(claim_id + 1000),
        chunk_id=chunk.descriptor.chunk_id,
        char_start=start,
        char_end=start + len(quote),
        exact_quote=quote,
    )
    if requirement:
        claim = Requirement(
            requirement_id=uid(claim_id),
            display_code="REQ-999",
            obligation=statement or quote,
            status="supported",
            conditions=conditions,
            evidence_ids=(evidence.quote_id,),
        )
        return AnalystContent(requirements=(claim,), quotes=(evidence,))
    claim = Fact(
        fact_id=uid(claim_id),
        category=category,
        critical_class="capacity",
        status="supported",
        statement=statement or quote,
        original_value=number,
        normalized_number=number,
        unit=unit,
        conditions=conditions,
        evidence_ids=(evidence.quote_id,),
    )
    return AnalystContent(facts=(claim,), quotes=(evidence,))


def encoded(content, *, native):
    content = content.model_dump(mode="json")
    return content if native else {"kind": "completed", "content": content, "actions": []}
