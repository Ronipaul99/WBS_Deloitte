"""Durable tool admission reuses the fenced execution JSON ledger, not Redis."""

from app.services.agents.evidence_types import EvidenceError, RequestCount, ToolUsage
from app.services.agents.state import ExecutionLedger


def reserve_usage(previous, binding, policy, request_hash):
    old = previous or ToolUsage(binding=binding, policy=policy)
    if old.binding != binding or old.policy != policy:
        raise EvidenceError("evidence_tool_budget_binding_changed")
    counts = {r.request_sha256: r.count for r in old.requests}
    if (
        old.calls >= policy.max_calls
        or counts.get(request_hash, 0) >= policy.max_repeats
        or old.reserved_bytes + policy.response_bytes > policy.total_bytes
        or old.reserved_tokens + policy.response_tokens > policy.total_tokens
    ):
        raise EvidenceError("evidence_tool_budget_exhausted")
    counts[request_hash] = counts.get(request_hash, 0) + 1
    return ToolUsage(
        binding=binding,
        policy=policy,
        calls=old.calls + 1,
        reserved_bytes=old.reserved_bytes + policy.response_bytes,
        reserved_tokens=old.reserved_tokens + policy.response_tokens,
        requests=tuple(RequestCount(request_sha256=k, count=v) for k, v in sorted(counts.items())),
    )


class WorkflowToolAllowance:
    def __init__(self, store, fence, binding, policy, *, profile):
        self.store, self.fence, self.binding, self.policy = store, fence, binding, policy
        self.profile = profile

    async def check(self):
        await self.store.check(self.fence)

    async def reserve(self, request_hash):
        store = self.store
        async with store.sessions.begin() as session:
            repo, run = await store._locked(session)
            store._fence(run, self.fence)
            ledger = await store._available(session, repo, run)
            if run.input_snapshot["profile"] != self.profile.model_dump(mode="json"):
                raise EvidenceError("evidence_tool_profile_mismatch")
            if ledger.deadline <= store.now() or ledger.violated:
                raise EvidenceError("evidence_workflow_budget_exhausted")
            usage = reserve_usage(ledger.evidence_tools, self.binding, self.policy, request_hash)
            data = ledger.model_dump()
            data["evidence_tools"] = usage
            run.execution = ExecutionLedger.model_validate(data).model_dump(mode="json")
            return usage
