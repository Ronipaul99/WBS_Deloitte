"""Step 4-compatible ledger with committed admission before every outbound attempt."""

from app.services.llm.adapter_types import CallBudget


class DurableCallBudget(CallBudget):
    def __init__(self, store, claim):
        policy = claim.workflow.profile
        remaining = max(0.001, (claim.deadline - store.now()).total_seconds())
        super().__init__(
            max_calls=policy.max_calls,
            max_tokens=policy.max_total_tokens,
            total_seconds=min(remaining, 3600),
        )
        self.store, self.claim = store, claim

    def validate_provider(self, profile, pinned, options):
        endpoint = self.claim.endpoint
        approval = pinned.approval
        if profile != self.claim.workflow.profile or (
            approval.host,
            approval.port,
            approval.path_prefix,
            approval.approval_id,
        ) != (endpoint.host, endpoint.port, endpoint.path_prefix, endpoint.approval_id):
            raise ValueError("provider differs from pinned workflow")

    def reserve(self, *args):
        raise RuntimeError("durable admission requires async before_attempt")

    def begin_repair(self, *args):
        raise RuntimeError("durable repair requires async before_repair")

    def record(self, *args):
        raise RuntimeError("durable receipt requires async after_attempt")

    def observe_overrun(self, *args):
        raise RuntimeError("durable accounting requires async after_overrun")

    async def before_attempt(self, input_ceiling, output_ceiling):
        ledger = await self.store.mutate_budget(
            self.claim.fence,
            "reserve",
            tokens=input_ceiling + output_ceiling,
            binding=self._binding,
        )
        self.calls, self.reserved_tokens = ledger.calls, ledger.reserved_tokens
        return ledger.calls

    async def before_repair(self, request_id):
        await self.store.mutate_budget(self.claim.fence, "repair")

    async def after_attempt(self, item):
        await self.store.mutate_budget(self.claim.fence, "record", record=item)
        self._records.append(item)

    async def after_overrun(self, extra_tokens):
        await self.store.mutate_budget(self.claim.fence, "overrun", tokens=extra_tokens)
        self._violated = True
