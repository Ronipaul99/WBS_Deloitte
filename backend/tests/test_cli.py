from argparse import Namespace

import pytest
from sqlalchemy import select

from app.cli import require_confirmation, revoke_every_session, revoke_user_sessions
from app.db.session import SessionLocal
from app.models.auth import AuthEvent


def test_operator_commands_require_exact_confirmation():
    with pytest.raises(SystemExit, match="Refusing operation"):
        require_confirmation(None, "REVOKE_ALL_SESSIONS")


async def test_targeted_operator_revocation_invalidates_access_token(client, capsys):
    await revoke_user_sessions(
        Namespace(
            email="developer@example.com",
            confirm="REVOKE_USER_SESSIONS",
        )
    )

    assert client.get("/api/v1/me").status_code == 401
    output = capsys.readouterr().out
    assert '"status": "ok"' in output
    assert "developer@example.com" not in output
    async with SessionLocal() as db:
        event = await db.scalar(
            select(AuthEvent).where(AuthEvent.event_type == "operator_user_session_revocation")
        )
    assert event is not None


async def test_mass_operator_revocation_invalidates_access_token(client, capsys):
    await revoke_every_session(Namespace(confirm="REVOKE_ALL_SESSIONS"))

    assert client.get("/api/v1/me").status_code == 401
    assert '"users_invalidated"' in capsys.readouterr().out
