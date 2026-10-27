"""Generic worker probe execution; persistence/management APIs belong to Step 6."""

from dataclasses import dataclass

from app.core.permissions import Permission
from app.services.agents.graph import OrchestrationUnavailable
from app.services.agents.scoped_storage import ScopedStorage
from app.services.llm.capabilities import CapabilityProber, LiveProbePermit, ProbePlan


@dataclass(frozen=True)
class WorkerConnectionTest:
    sessions: object
    access: object
    provider: object
    plan: ProbePlan
    permit: LiveProbePermit | None = None

    async def execute(self):
        async with self.sessions.begin() as session:
            await ScopedStorage(session, self.access).authorize(Permission.LLM_MANAGE)
        if self.provider.profile.tenant_id != self.access.tenant_id:
            raise PermissionError("connection test scope mismatch")
        if self.provider.transport.execution_origin != "synthetic_fixture":
            # Step 2 has no document-free test-request ledger. Never replay a live
            # paid probe from an acks-late task with a fresh in-memory allowance.
            raise OrchestrationUnavailable("agent_connection_test_persistence_unqualified")
        # CapabilityProber uses fresh credential authorization for every attempt and
        # requires a separately supplied cost-bounded permit for any real network.
        report = await CapabilityProber(self.provider, permit=self.permit).run(self.plan)
        async with self.sessions.begin() as session:
            await ScopedStorage(session, self.access).authorize(Permission.LLM_MANAGE)
        return report
