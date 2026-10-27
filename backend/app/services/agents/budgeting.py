"""Context planning only. Reservations/provider calls remain the Step 5 boundary."""

import json
import math
from dataclasses import dataclass

from app.services.agents.evidence_types import EvidenceError, ReadingBatch, digest
from app.services.llm.contracts import ModelProfileSnapshot


def render_chunk(chunk):
    return {
        "chunk_id": str(chunk.descriptor.chunk_id),
        "content": chunk.content,
        "heading_path": list(chunk.descriptor.heading_path),
        "physical_pages": list(chunk.descriptor.physical_pages),
        "source_references": [
            r.model_dump(mode="json") for r in chunk.descriptor.source_references
        ],
        "warning_codes": list(chunk.descriptor.warning_codes),
        "trust": "untrusted_source_data",
    }


@dataclass(frozen=True)
class ContextBudget:
    profile: ModelProfileSnapshot
    system_instructions: str
    tool_schemas: tuple
    output_tokens: int
    tokenizer: object = None
    tokenizer_identity: str | None = None

    def __post_init__(self):
        caps = self.profile.capabilities
        if (
            caps.qualification not in {"live_worker", "synthetic_fixture"}
            or caps.context_tokens is None
            or caps.output_tokens is None
            or type(self.output_tokens) is not int
            or not 1 <= self.output_tokens <= caps.output_tokens
            or len(self.system_instructions) > 100000
            or len(self.tool_schemas) > 4
            or bool(self.tokenizer) != bool(self.tokenizer_identity)
        ):
            raise EvidenceError("evidence_context_unqualified")

    @property
    def sha256(self):
        return digest(
            {
                "profile": self.profile.model_dump(mode="json"),
                "instructions_sha256": digest(self.system_instructions),
                "tools_sha256": digest(self.tool_schemas),
                "output": self.output_tokens,
                "tokenizer": self.tokenizer_identity,
                "policy": "evidence_context.v1",
            }
        )

    @property
    def accounting(self):
        return "approved_tokenizer" if self.tokenizer else "utf8_upper_estimate"

    def count(self, value):
        wire = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if self.tokenizer:
            count = self.tokenizer(wire)
            if type(count) is not int or count < 0:
                raise EvidenceError("evidence_tokenizer_invalid")
            return count
        # Conservative byte-based estimate, not a tokenizer or usage assertion.
        return len(wire.encode())

    def estimate(self, chunks):
        return self.count(
            {
                "instructions": self.system_instructions,
                "tools": self.tool_schemas,
                "evidence": [render_chunk(c) for c in chunks],
            }
        )

    def fits(self, tokens):
        headroom = max(512, math.ceil(self.profile.capabilities.context_tokens * 0.1))
        return tokens + self.output_tokens + headroom <= self.profile.capabilities.context_tokens


@dataclass(frozen=True)
class ReadingPlan:
    inventory_sha256: str
    batches: tuple[ReadingBatch, ...]
    blocked: tuple[int, ...]

    def __post_init__(self):
        if (
            len(self.batches) > 100000
            or tuple(sorted(set(self.blocked))) != self.blocked
            or any(type(i) is not int or not 0 <= i < len(self.batches) for i in self.blocked)
            or tuple(i for i, b in enumerate(self.batches) if b.blocked_reason is not None)
            != self.blocked
        ):
            raise EvidenceError("evidence_reading_plan_invalid")


async def build_reading_plan(repository, inventory, budget):
    pin = inventory.manifest.pin
    if budget.profile.tenant_id != pin.scope.tenant_id:
        raise EvidenceError("evidence_profile_scope_mismatch")
    batches, blocked, pending, current, spent = [], [], [], None, 0

    def flush():
        nonlocal pending, spent
        if not pending:
            return
        tokens = budget.estimate(pending)
        reason = (
            "oversized_context"
            if not budget.fits(tokens)
            else "run_budget_exhausted"
            if spent + tokens + budget.output_tokens > budget.profile.max_total_tokens
            or len(batches) >= budget.profile.max_calls
            else None
        )
        batch = ReadingBatch(
            inventory_sha256=inventory.sha256,
            budget_sha256=budget.sha256,
            index=len(batches),
            primary_chunk_ids=tuple(c.descriptor.chunk_id for c in pending),
            section_id=pending[0].descriptor.section_id,
            input_estimate=tokens,
            accounting=budget.accounting,
            blocked_reason=reason,
        )
        if reason:
            blocked.append(batch.index)
        else:
            spent += tokens + budget.output_tokens
        batches.append(batch)
        pending = []

    for page in inventory.pages:
        for entry in page.entries:
            (chunk,) = await repository.chunks(pin, (entry.chunk_id,))
            inventory.verify(chunk)
            if pending and (
                entry.section_id != current
                or len(pending) >= 64
                or not budget.fits(budget.estimate(pending + [chunk]))
            ):
                flush()
            current = entry.section_id
            pending.append(chunk)
    flush()
    await repository.guard(pin)
    return ReadingPlan(inventory.sha256, tuple(batches), tuple(blocked))


async def attach_context(repository, inventory, budget, plan, index, identities):
    """Explicit context references are scoped and budgeted; never additional primary coverage."""
    if (
        type(index) is not int
        or not 0 <= index < len(plan.batches)
        or plan.inventory_sha256 != inventory.sha256
        or len(identities) > 4
        or not identities
    ):
        raise EvidenceError("evidence_context_invalid")
    batch = plan.batches[index]
    if batch.budget_sha256 != budget.sha256:
        raise EvidenceError("evidence_context_budget_changed")
    for identity in identities:
        inventory.entry(identity)
    pin = inventory.manifest.pin
    primary = await repository.chunks(pin, batch.primary_chunk_ids)
    context = await repository.chunks(pin, identities)
    for chunk in primary + context:
        inventory.verify(chunk)
    estimate = budget.estimate(primary + context)
    reason = batch.blocked_reason
    if not budget.fits(estimate):
        reason = "oversized_context"
    elif (
        sum(
            b.input_estimate + budget.output_tokens
            for b in plan.batches
            if b.index != index and b.blocked_reason is None
        )
        + estimate
        + budget.output_tokens
        > budget.profile.max_total_tokens
    ):
        reason = "run_budget_exhausted"
    replacement = ReadingBatch.model_validate(
        {
            **batch.model_dump(),
            "context_chunk_ids": tuple(identities),
            "input_estimate": estimate,
            "blocked_reason": reason,
        }
    )
    batches = tuple(replacement if i == index else b for i, b in enumerate(plan.batches))
    await repository.guard(pin)
    return ReadingPlan(
        inventory.sha256, batches, tuple(i for i, b in enumerate(batches) if b.blocked_reason)
    )
