"""Disposable, synchronous SQLite qualification ONLY. No production imports/DB.

The owner registry and authenticated context are supplied by the synthetic harness.
This guard demonstrates an integration boundary, not PostgreSQL RLS or real auth.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

# Block tracing even if the developer has tracing configured in their environment.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

OWNERS = {"run-a": "tenant-a", "run-b": "tenant-b", "run-a2": "tenant-a"}


class ScopedSpikeSaver(SqliteSaver):
    """Every supported sync checkpoint operation checks a server-bound tenant/run.

    Unscoped listing is forbidden; caller-provided tenant fields confer no authority.
    Deliberately test-only: ownership here is a synthetic immutable fixture registry.
    """

    def __init__(self, connection, tenant: str, run: str):
        super().__init__(connection)
        self.tenant = tenant
        self.run = run
        self._authorize({"configurable": {"thread_id": run}})

    def _authorize(self, config):
        run = (config or {}).get("configurable", {}).get("thread_id")
        if run != self.run or OWNERS.get(run) != self.tenant:
            raise PermissionError("checkpoint scope denied")

    def get_tuple(self, config):
        self._authorize(config)
        return super().get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        self._authorize(config)
        if before is not None:
            self._authorize(before)
        return super().list(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):
        self._authorize(config)
        return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        self._authorize(config)
        return super().put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id):
        self._authorize({"configurable": {"thread_id": thread_id}})
        return super().delete_thread(thread_id)

    def get_delta_channel_history(self, *, config, channels):
        self._authorize(config)
        return super().get_delta_channel_history(config=config, channels=channels)


class SpikeState(TypedDict):
    prepared_count: int
    marker: str
    reviewed: bool


def prepare(state: SpikeState):
    return {"prepared_count": state.get("prepared_count", 0) + 1}


def review(state: SpikeState):
    accepted = interrupt({"review": "synthetic review only"})
    return {"reviewed": accepted is True}


def graph(saver):
    builder = StateGraph(SpikeState)
    builder.add_node("prepare", prepare)
    builder.add_node("review", review)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "review")
    builder.add_edge("review", END)
    return builder.compile(checkpointer=saver)


def main():
    # The parent creates a disposable directory; no env/config database URLs accepted.
    mode, root, tenant, run = sys.argv[1:]
    database = Path(root) / "synthetic-checkpoints.sqlite"
    with sqlite3.connect(database, check_same_thread=False) as connection:
        saver = ScopedSpikeSaver(connection, tenant, run)
        compiled = graph(saver)
        config = {"configurable": {"thread_id": run}}
        if mode == "start":
            compiled.invoke({"prepared_count": 0, "marker": tenant, "reviewed": False}, config)
        elif mode == "resume":
            compiled.invoke(Command(resume=True), config)
        elif mode != "inspect":
            raise ValueError("unknown spike mode")
        state = compiled.get_state(config)
        print(
            json.dumps(
                {
                    "values": state.values,
                    "next": state.next,
                    "history_count": len(list(compiled.get_state_history(config))),
                }
            )
        )


if __name__ == "__main__":
    main()
