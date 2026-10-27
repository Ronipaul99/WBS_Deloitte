"""Four registered read-only tools; source text is data, never a dispatch instruction."""

import json

from app.services.agents.budgeting import render_chunk
from app.services.agents.evidence_types import EvidenceError, digest
from app.services.llm.contracts import ToolAction, ToolExchange


class EvidenceTools:
    def __init__(self, evidence, retriever, context_budget, allowance):
        expected = digest(
            {"inventory": evidence.inventory.sha256, "context": context_budget.sha256}
        )
        if allowance.binding != expected or retriever.evidence is not evidence:
            raise EvidenceError("evidence_tool_context_mismatch")
        self.evidence, self.retriever = evidence, retriever
        self.budget, self.allowance = context_budget, allowance

    async def run(self, action):
        expected = digest(
            {"inventory": self.evidence.inventory.sha256, "context": self.budget.sha256}
        )
        if (
            self.allowance.binding != expected
            or self.budget.profile.tenant_id != self.evidence.pin.scope.tenant_id
        ):
            raise EvidenceError("evidence_tool_context_mismatch")
        try:
            action = ToolAction.model_validate(action)
        except ValueError:
            raise EvidenceError("evidence_tool_arguments_invalid") from None
        await self.allowance.check()
        await self.evidence.guard()
        request_hash = digest(action.arguments)
        await self.allowance.reserve(request_hash)
        args = action.arguments
        try:
            if args.name == "search_document":
                hits = await self.retriever.search(
                    args.query, section=args.section_filter, limit=args.limit
                )
                chunks = await self.evidence.chunks(tuple(h.chunk_id for h in hits)) if hits else ()
                result = {
                    "chunks": [render_chunk(c) for c in chunks],
                    "ranking_only": [{"chunk_id": str(h.chunk_id), "score": h.score} for h in hits],
                }
            elif args.name == "read_section":
                chunks, cursor = await self.evidence.section(args.section_id, args.cursor)
                result = {"chunks": [render_chunk(c) for c in chunks], "next_cursor": cursor}
            elif args.name == "read_chunk_neighbors":
                chunks = await self.evidence.neighbors(args.chunk_ids, args.radius)
                result = {"chunks": [render_chunk(c) for c in chunks]}
            else:
                chunks, more = await self.evidence.definitions(args.term)
                result = {
                    "chunks": [render_chunk(c) for c in chunks],
                    "more_available": more,
                    "absence_proven": False,
                }
            result.update(
                {
                    "inventory_sha256": self.evidence.inventory.sha256,
                    "trust": "untrusted_source_data",
                    "coverage_processed": False,
                }
            )
            wire = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            policy = self.allowance.policy
            if (
                len(wire.encode()) > policy.response_bytes
                or self.budget.count(result) > policy.response_tokens
                or not self.budget.fits(
                    self.budget.count(
                        {
                            "instructions": self.budget.system_instructions,
                            "tools": self.budget.tool_schemas,
                            "tool_result": result,
                        }
                    )
                )
            ):
                raise EvidenceError("evidence_tool_result_oversized")
            await self.allowance.check()
            await self.evidence.guard()
            return ToolExchange(action=action, output_json=wire)
        except EvidenceError as error:
            # Known fixed error codes only; never include source/body/driver exceptions.
            return ToolExchange(
                action=action,
                is_error=True,
                output_json=json.dumps({"error": str(error), "coverage_processed": False}),
            )
        except Exception:
            return ToolExchange(
                action=action,
                is_error=True,
                output_json=json.dumps(
                    {"error": "evidence_tool_unavailable", "coverage_processed": False}
                ),
            )
