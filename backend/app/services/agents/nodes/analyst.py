"""Bounded analyst/controller. All inference uses existing secure Step 4 adapters."""

import json
from uuid import uuid4

from app.services.agents.analyst_types import AnalystBatch, AnalystPolicy
from app.services.agents.budgeting import render_chunk
from app.services.agents.contracts import AnalystContent
from app.services.agents.evidence_types import BatchCompletion, EvidenceError, digest
from app.services.agents.fact_register import normalize_extraction
from app.services.agents.nodes.analyst_prompt import INSTRUCTIONS, PROMPT_VERSION
from app.services.llm.base import BaseProvider
from app.services.llm.contracts import (
    GenerationRequest,
    Message,
    Support,
    Usage,
    validate_result_binding,
)
from app.services.llm.protocol_support import compact, parse_json, tool_schemas, wire_input

TOOL_NAMES = ("search_document", "read_section", "read_chunk_neighbors", "lookup_definition")


class AnalystFailure(EvidenceError):
    """Fixed metadata-only controller codes; no upstream response or document text."""


class EvidenceAnalyst:
    def __init__(self, evidence, tools, context_budget, *, policy=None):
        self.evidence, self.tools, self.budget = evidence, tools, context_budget
        self.policy = policy or AnalystPolicy()
        if (
            tools.evidence is not evidence
            or tools.budget != context_budget
            or context_budget.system_instructions != INSTRUCTIONS
            or context_budget.tool_schemas != tuple(tool_schemas(TOOL_NAMES))
        ):
            raise AnalystFailure("analyst_context_mismatch")

    def binding(self, workflow, plan):
        if (
            workflow.scope != self.evidence.pin.scope
            or workflow.profile != self.budget.profile
            or plan.inventory_sha256 != self.evidence.inventory.sha256
            or any(b.budget_sha256 != self.budget.sha256 for b in plan.batches)
        ):
            raise AnalystFailure("analyst_input_mismatch")
        return digest(
            {
                "workflow": workflow.model_dump(mode="json"),
                "inventory": self.evidence.inventory.sha256,
                "plan": [digest(b) for b in plan.batches],
                "context": self.budget.sha256,
                "prompt_version": PROMPT_VERSION,
                "policy": self.policy.model_dump(mode="json"),
            }
        )

    async def guard(self):
        await self.tools.allowance.check()
        await self.evidence.guard()

    def request(self, provider, payload, exchanges):
        # Only application-owned registered adapters. Tests use their fake network boundary.
        if not isinstance(provider, BaseProvider) or provider.profile != self.budget.profile:
            raise AnalystFailure("analyst_provider_mismatch")
        try:
            request = GenerationRequest(
                request_id=uuid4(),
                profile=provider.profile,
                messages=(
                    Message(role="system", content=INSTRUCTIONS),
                    Message(role="user", content=compact(payload)),
                ),
                response_schema="analyst.v1",
                allowed_tools=TOOL_NAMES,
                output_mode="native_json_schema"
                if (provider.profile.capabilities.json_schema == Support.SUPPORTED)
                else "validated_json",
                input_token_budget=1,
                max_output_tokens=self.budget.output_tokens,
                tool_results=tuple(exchanges),
            )
            # Count the ACTUAL encoded protocol, output schema, tools and replay wrappers.
            # Include possible Step 4 format repair overhead before admitting the first call.
            payloads = [provider.encode(wire_input(request, repair)) for repair in (False, True)]
            tokens = max(
                max(len(compact(p).encode()) + 256, self.budget.count(p)) for p in payloads
            )
            if not self.budget.fits(tokens):
                raise AnalystFailure("analyst_context_overflow")
            return GenerationRequest.model_validate(
                {
                    **request.model_dump(),
                    "input_token_budget": tokens,
                }
            )
        except AnalystFailure:
            raise
        except (ValueError, TypeError, KeyError):
            raise AnalystFailure("analyst_request_invalid") from None

    async def extract(self, provider, payload, allowed_ids, *, binding, origin, initial=()):
        exchanges = list(initial)
        used_ids, rounds = {e.action.call_id for e in exchanges}, 0
        usages = []
        allowed_ids = set(allowed_ids)
        while True:
            await self.guard()
            request = self.request(provider, payload, exchanges)
            result = await provider.generate(request)
            usages.append(result.usage)
            await self.guard()
            try:
                validate_result_binding(request, result)
            except ValueError:
                raise AnalystFailure("analyst_result_mismatch") from None
            if result.status == "completed":
                try:
                    content = AnalystContent.model_validate(parse_json(result.output_json))
                    record = await normalize_extraction(
                        content, self.evidence, allowed_ids, binding=binding, origin=origin
                    )
                except EvidenceError:
                    raise
                except (ValueError, TypeError, KeyError):
                    raise AnalystFailure("analyst_output_invalid") from None
                await self.guard()
                usage = (
                    Usage()
                    if any(u.source == "unknown" for u in usages)
                    else Usage(
                        source="estimated"
                        if any(u.source == "estimated" for u in usages)
                        else "reported",
                        input_tokens=sum(u.input_tokens for u in usages),
                        output_tokens=sum(u.output_tokens for u in usages),
                    )
                )
                return record, usage
            if result.status != "tool_actions":
                raise AnalystFailure(
                    "analyst_"
                    + (result.failure.code.value if result.failure else "provider_unavailable")
                )
            # Complete history is bounded, never silently drop old exchanges.
            if rounds >= self.policy.max_tool_rounds or len(exchanges) + len(result.actions) > 4:
                raise AnalystFailure("analyst_tool_limit")
            rounds += 1
            for action in result.actions:
                if action.call_id in used_ids:
                    raise AnalystFailure("analyst_repeated_action")
                used_ids.add(action.call_id)
                exchange = await self.tools.run(action)
                if not exchange.is_error:
                    data = json.loads(exchange.output_json)
                    for chunk in data.get("chunks", []):
                        from uuid import UUID

                        identity = UUID(chunk["chunk_id"])
                        (canonical,) = await self.evidence.chunks((identity,))
                        if chunk["content"] != canonical.content:
                            raise AnalystFailure("analyst_tool_evidence_mismatch")
                        allowed_ids.add(identity)
                exchanges.append(exchange)

    async def analyze(self, provider, batch, *, binding):
        if (
            batch.inventory_sha256 != self.evidence.inventory.sha256
            or batch.budget_sha256 != self.budget.sha256
            or batch.blocked_reason is not None
        ):
            raise AnalystFailure("analyst_batch_unavailable")
        await self.guard()
        ids = batch.primary_chunk_ids + batch.context_chunk_ids
        chunks = await self.evidence.chunks(ids)
        record, usage = await self.extract(
            provider,
            {
                "task": "extract_assigned_batch",
                "primary_chunk_ids": list(map(str, batch.primary_chunk_ids)),
                "evidence": [render_chunk(c) for c in chunks],
                "trust": "untrusted_source_data",
            },
            ids,
            binding=binding,
            origin=digest(batch),
        )
        receipt = BatchCompletion(
            inventory_sha256=batch.inventory_sha256,
            batch_sha256=digest(batch),
            primary_chunk_ids=batch.primary_chunk_ids,
            artifact_sha256=digest(record),
        )
        return AnalystBatch(batch=batch, extraction=record, completion=receipt), usage
