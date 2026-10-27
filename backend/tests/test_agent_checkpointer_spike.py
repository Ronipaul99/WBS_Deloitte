"""Run with --noconftest: no production application/settings or upload fixtures."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from agent_contract_fixtures.checkpointer_spike import ScopedSpikeSaver, graph
from langgraph.checkpoint.sqlite import SqliteSaver

SCRIPT = Path(__file__).parent / "agent_contract_fixtures" / "checkpointer_spike.py"


def child(mode, root, tenant="tenant-a", run="run-a"):
    # Use distinct OS processes to prove recovery, not just object reconstruction.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), mode, str(root), tenant, run],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"},
    )
    return json.loads(result.stdout)


def test_process_restart_resume_and_replay(tmp_path):
    started = child("start", tmp_path)
    assert started["next"] == ["review"]
    assert started["values"]["prepared_count"] == 1
    assert started["values"]["reviewed"] is False
    resumed = child("resume", tmp_path)
    assert resumed["next"] == []
    assert resumed["values"] == {
        "prepared_count": 1,
        "marker": "tenant-a",
        "reviewed": True,
    }
    replayed = child("resume", tmp_path)
    assert replayed["values"] == resumed["values"]
    assert replayed["history_count"] == resumed["history_count"]


def test_two_tenants_and_raw_saver_negative_control(tmp_path):
    child("start", tmp_path)
    child("start", tmp_path, "tenant-b", "run-b")
    assert child("inspect", tmp_path)["values"]["marker"] == "tenant-a"
    assert child("inspect", tmp_path, "tenant-b", "run-b")["values"]["marker"] == "tenant-b"
    with sqlite3.connect(tmp_path / "synthetic-checkpoints.sqlite") as connection:
        # Raw SqliteSaver has NO tenant authorization: thread knowledge exposes state.
        raw = SqliteSaver(connection)
        leaked = raw.get_tuple({"configurable": {"thread_id": "run-a"}})
        assert leaked.checkpoint["channel_values"]["marker"] == "tenant-a"
        with pytest.raises(PermissionError):
            ScopedSpikeSaver(connection, "tenant-b", "run-a")


@pytest.mark.parametrize("other_run", ["run-a", "run-a2", "unknown-run"])
@pytest.mark.parametrize(
    "operation", ["read", "history", "write", "pending_write", "delete", "delta", "history_before"]
)
def test_every_spike_operation_checks_bound_run(tmp_path, other_run, operation):
    with sqlite3.connect(tmp_path / "spike.sqlite") as connection:
        saver = ScopedSpikeSaver(connection, "tenant-b", "run-b")
        config = {"configurable": {"thread_id": other_run, "tenant_id": "tenant-b"}}
        own_config = {"configurable": {"thread_id": "run-b"}}
        with pytest.raises(PermissionError):
            if operation == "read":
                saver.get_tuple(config)
            elif operation == "history":
                list(saver.list(config))
            elif operation == "write":
                saver.put(config, {}, {}, {})
            elif operation == "pending_write":
                saver.put_writes(config, [], "synthetic-task")
            elif operation == "delete":
                saver.delete_thread(other_run)
            elif operation == "delta":
                saver.get_delta_channel_history(config=config, channels=["marker"])
            else:
                list(saver.list(own_config, before=config))


def test_unscoped_listing_denied_and_scope_survives_graph_calls(tmp_path):
    with sqlite3.connect(tmp_path / "spike.sqlite", check_same_thread=False) as connection:
        saver = ScopedSpikeSaver(connection, "tenant-a", "run-a")
        with pytest.raises(PermissionError):
            list(saver.list(None))
        with pytest.raises(PermissionError):
            graph(saver).get_state({"configurable": {"thread_id": "run-a2"}})


def test_own_run_mutation_history_and_delete(tmp_path):
    child("start", tmp_path)
    with sqlite3.connect(
        tmp_path / "synthetic-checkpoints.sqlite", check_same_thread=False
    ) as connection:
        saver = ScopedSpikeSaver(connection, "tenant-a", "run-a")
        config = {"configurable": {"thread_id": "run-a"}}
        assert list(saver.list(config))
        graph(saver).update_state(config, {"marker": "synthetic updated marker"})
        assert graph(saver).get_state(config).values["marker"] == "synthetic updated marker"
        saver.delete_thread("run-a")
        assert saver.get_tuple(config) is None
        assert list(saver.list(config)) == []
