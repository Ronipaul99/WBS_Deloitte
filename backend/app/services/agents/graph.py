"""One durable node per LangGraph invocation; SQL owns cross-invocation recovery.

There is deliberately no generic LangGraph saver/serializer. Completed node,
cursor and continuation are committed together by runner/storage. Framework state
history, subgraphs, pending writes and arbitrary state edits are unavailable.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.services.agents.contracts import WorkflowInput
from app.services.agents.state import Cursor, Node, NodeResult, advance


class OrchestrationUnavailable(RuntimeError):
    def __init__(self, code="agent_nodes_unavailable"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NodeContext:
    workflow: WorkflowInput
    cursor: Cursor
    # Trusted application factory, not a model-selected provider or raw key.
    provider: object
    checkpoints: object


NodeHandler = Callable[[NodeContext], Awaitable[NodeResult]]


class _State(TypedDict):
    context: NodeContext
    result: NodeResult


class WorkflowGraph:
    def __init__(self, handlers: Mapping[Node, NodeHandler], *, workflow_version="summary-v1"):
        self.workflow_version = workflow_version
        required = set(Node) - {Node.DONE, Node.BLOCKED}
        if set(handlers) != required or not all(callable(h) for h in handlers.values()):
            raise OrchestrationUnavailable()
        handlers = dict(handlers)
        graph = StateGraph(_State)
        for node in required:

            async def execute(state, node=node):
                context = state["context"]
                if context.cursor.node != node:
                    raise OrchestrationUnavailable("agent_state_incompatible")
                result = NodeResult.model_validate(await handlers[node](context))
                advance(context.cursor, result)
                return {"result": result}

            graph.add_node(node.value, execute)
            graph.add_edge(node.value, END)
        graph.add_conditional_edges(
            START,
            lambda state: state["context"].cursor.node.value,
            {node.value: node.value for node in required},
        )
        # No hidden framework snapshots: application-owned SQL checkpoints only.
        self._graph = graph.compile()

    async def step(self, context: NodeContext) -> NodeResult:
        if context.workflow.workflow_version != self.workflow_version:
            raise OrchestrationUnavailable("agent_state_incompatible")
        # No external tracing of source artifacts or provider-bound objects.
        with tracing_context(enabled=False):
            state = await self._graph.ainvoke(
                {"context": context}, {"recursion_limit": 4, "callbacks": []}
            )
        return NodeResult.model_validate(state["result"])


def require_enabled(settings):
    if not settings.agentic_summary_enabled:
        raise OrchestrationUnavailable("agentic_summary_disabled")


def orchestration_readiness(settings, *, nodes_registered=False):
    if not settings.agentic_summary_enabled:
        return {"ready": False, "code": "agentic_summary_disabled"}
    if not nodes_registered:
        return {"ready": False, "code": "agent_nodes_unavailable"}
    # Registration alone cannot prove PG/RLS, qualifications or worker compatibility.
    return {"ready": False, "code": "agent_runtime_qualification_required"}
