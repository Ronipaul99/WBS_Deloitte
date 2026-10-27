"""Pure permission checks; no application conftest or settings."""

import re
from pathlib import Path

import pytest

from app.core.permissions import Permission, assert_llm_permission, permissions_for_role


@pytest.mark.parametrize(
    "role,permission,allowed",
    [
        (
            role,
            permission,
            role == "ADMIN" or (role == "EDITOR" and permission == Permission.LLM_USE),
        )
        for role in ("ADMIN", "EDITOR", "VIEWER", "UNKNOWN", "admin", "")
        for permission in (Permission.LLM_MANAGE, Permission.LLM_USE, Permission.LLM_USAGE_AUDIT)
    ],
)
def test_llm_role_matrix(role, permission, allowed):
    if allowed:
        assert_llm_permission(role, permission)
    else:
        with pytest.raises(PermissionError):
            assert_llm_permission(role, permission)


def test_model_use_also_requires_summary_update(monkeypatch):
    monkeypatch.setattr(
        "app.core.permissions.permissions_for_role", lambda role: frozenset({Permission.LLM_USE})
    )
    with pytest.raises(PermissionError):
        assert_llm_permission("EDITOR", Permission.LLM_USE)


def test_frontend_backend_permission_identifiers_match():
    frontend = (Path(__file__).resolve().parents[2] / "WBS_UI/src/auth/permissions.ts").read_text()
    assert set(re.findall(r"\w+: '([^']+)'", frontend)) == {item.value for item in Permission}
    assert Permission.LLM_USE in permissions_for_role("EDITOR")
    assert Permission.LLM_MANAGE not in permissions_for_role("EDITOR")
