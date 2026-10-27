"""Bounded document-free storage and append-only completed test observations."""

from sqlalchemy import event, inspect

from app.models.llm import LlmConnectionTest, LlmModelProfileVersion
from app.schemas.llm import ProfileSettings
from app.services.agents.persistence_types import safe_json
from app.services.llm.management_types import TestConfiguration, TestLedger


def validate(mapper, connection, row):
    if isinstance(row, LlmModelProfileVersion):
        if row.settings:
            row.settings = ProfileSettings.model_validate(row.settings).model_dump(mode="json")
        return
    config = TestConfiguration.model_validate(row.configuration)
    ledger = TestLedger.model_validate(row.ledger)
    if (config.profile.tenant_id, config.profile.connection_id, config.profile.profile_id) != (
        row.tenant_id,
        row.connection_id,
        row.profile_id,
    ):
        raise ValueError("test profile outside tenant scope")
    safe_json(row.configuration, 65536)
    safe_json(ledger.model_dump(mode="json"), 32768)
    safe_json(row.result, 65536)


def update(mapper, connection, row):
    state = inspect(row)
    changes = {a.key for a in state.attrs if a.history.has_changes()}
    if set(state.attrs.state.history.deleted) & {"succeeded", "failed", "unavailable"}:
        raise ValueError("completed test is immutable")
    if row.state in {"succeeded", "failed", "unavailable"} and "state" not in changes:
        raise ValueError("completed test is immutable")
    if changes & {
        "id",
        "tenant_id",
        "connection_id",
        "profile_id",
        "profile_version_id",
        "requested_by",
        "configuration",
    }:
        raise ValueError("test input is immutable")
    old = state.attrs.ledger.history.deleted
    if old:
        if old[0].get("violated") and not row.ledger.get("violated"):
            raise ValueError("test budget cannot reset")
        if old[0]["deadline"] != row.ledger.get("deadline") or any(
            row.ledger.get(k, -1) < old[0][k] for k in ("calls", "reserved_tokens")
        ):
            raise ValueError("test budget cannot reset")
    validate(mapper, connection, row)


event.listen(LlmConnectionTest, "before_insert", validate)
event.listen(LlmConnectionTest, "before_update", update)
event.listen(LlmModelProfileVersion, "before_insert", validate)


def deny_delete(mapper, connection, row):
    raise ValueError("test history requires privileged lifecycle cleanup")


event.listen(LlmConnectionTest, "before_delete", deny_delete)
