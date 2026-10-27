"""Bounded node execution, with current checks and fenced SQL completion."""

import asyncio
from contextlib import suppress

from app.services.agents.budgets import DurableCallBudget
from app.services.agents.checkpoints import ScopedCheckpoints
from app.services.agents.graph import NodeContext, OrchestrationUnavailable
from app.services.agents.repository import StaleRevisionError
from app.services.agents.storage import FencedAttempt, InactiveWorkflow
from app.services.llm.adapter_types import BudgetExhausted
from app.services.llm.base import BaseProvider


class WorkflowRunner:
    def __init__(
        self, store, graph, provider_factory, *, publisher=None, heartbeat_seconds=10, enabled=False
    ):
        if not 0 < heartbeat_seconds <= 20:
            raise ValueError("invalid heartbeat interval")
        self.store, self.graph, self.provider_factory = store, graph, provider_factory
        self.publisher, self.heartbeat_seconds = publisher, heartbeat_seconds
        self.enabled = enabled

    async def _watch(self, fence):
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await self.store.check(fence)
            await self.store.heartbeat(fence)

    async def run(self, delivery_id):
        if not self.enabled:
            raise OrchestrationUnavailable("agentic_summary_disabled")
        claim = await self.store.claim(delivery_id)
        if claim is None:
            return
        watch, execution = None, None
        try:
            budget = DurableCallBudget(self.store, claim)
            # Factory must compose Step 4 adapters and Step 3 transport; never raw HTTP.
            provider = self.provider_factory(claim.workflow, budget)
            if not isinstance(provider, BaseProvider) or provider.budget is not budget:
                raise InactiveWorkflow()
            budget.validate_provider(provider.profile, provider.pinned, provider.options)
            context = NodeContext(
                claim.workflow, claim.cursor, provider, ScopedCheckpoints(self.store)
            )
            watch = asyncio.create_task(self._watch(claim.fence))
            execution = asyncio.create_task(self.graph.step(context))
            remaining = max(0, (claim.deadline - self.store.now()).total_seconds())
            async with asyncio.timeout(remaining):
                done, _ = await asyncio.wait(
                    {execution, watch}, return_when=asyncio.FIRST_COMPLETED
                )
                if watch in done:
                    await watch
                result = await execution
                await self.store.complete(claim, result, publisher=self.publisher)
        except FencedAttempt:
            # Cancellation or a newer lease owns the durable status.
            return
        except (StaleRevisionError, InactiveWorkflow, PermissionError):
            with suppress(FencedAttempt, PermissionError):
                await self.store.stop(claim.fence, "stale", "agent_source_stale")
        except (TimeoutError, BudgetExhausted):
            with suppress(FencedAttempt, PermissionError):
                await self.store.stop(claim.fence, code="agent_budget_exhausted")
        except asyncio.CancelledError:
            # No implicit retry: charged unfinished attempts remain ambiguous.
            raise
        except Exception:
            with suppress(FencedAttempt, PermissionError):
                await self.store.stop(claim.fence)
        finally:
            for task in (execution, watch):
                if task is not None:
                    task.cancel()
            for task in (execution, watch):
                if task is not None:
                    with suppress(Exception, asyncio.CancelledError):
                        await task
