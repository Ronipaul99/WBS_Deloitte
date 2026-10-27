"""Private worker integration boundary. No routes, real nodes or credentials installed.

The application composition root must resolve run/delivery IDs from trusted SQL
routing metadata and return an authorized runner/store. Broker identity is never
an authorization decision. Until that integration is qualified, fail closed.
"""

from uuid import UUID


class AgentWorkerUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


_runtime = None


def install_worker_runtime(runtime):
    """Trusted process composition only; no API/model input may call this function."""
    global _runtime
    if _runtime is not None or runtime is None:
        raise AgentWorkerUnavailable("agent_runtime_already_bound")
    _runtime = runtime


async def advance(settings, run_id: UUID, delivery_id: UUID):
    if not settings.agentic_summary_enabled:
        raise AgentWorkerUnavailable("agentic_summary_disabled")
    if _runtime is None:
        raise AgentWorkerUnavailable("agent_worker_runtime_unavailable")
    # Implementations must authorize/rebind on every SQL transaction and attempt.
    runner = await _runtime.resolve_runner(run_id, delivery_id)
    if runner.store.scope.workflow_run_id != run_id:
        raise AgentWorkerUnavailable("agent_worker_scope_mismatch")
    await runner.run(delivery_id)


async def reconcile(settings):
    if not settings.agentic_summary_enabled:
        return
    if _runtime is None:
        raise AgentWorkerUnavailable("agent_worker_runtime_unavailable")
    await _runtime.reconcile_bounded(limit=100)


async def test_connection(settings, request_id: UUID):
    if not settings.agentic_summary_enabled:
        raise AgentWorkerUnavailable("agentic_summary_disabled")
    if _runtime is None:
        raise AgentWorkerUnavailable("agent_worker_runtime_unavailable")
    # Durable, tenant-admin authorized request loaded by ID. No secret task args.
    test = await _runtime.resolve_connection_test(request_id)
    return await test.execute()
