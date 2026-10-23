from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.passwords import hash_password
from app.core.security import create_access_token, token_digest
from app.db.session import SessionLocal
from app.models.auth import AuthEvent, AuthIdentity, RefreshSession
from app.models.domain import User
from app.services.auth import utc_now


def login(client):
    return client.post(
        "/api/v1/auth/login",
        json={
            "email": "developer@example.com",
            "password": "Correct-Horse-Battery-Staple-42",
        },
    )


def test_login_is_generic_and_sets_protected_refresh_cookie(client):
    failure = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "not-the-password"},
    )
    assert failure.status_code == 401
    assert failure.json()["detail"] == "Invalid email or password."

    success = login(client)
    assert success.status_code == 200
    assert success.json()["token_type"] == "bearer"
    assert success.json()["expires_in"] == 900
    cookie = success.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/v1/auth" in cookie
    assert success.headers["cache-control"] == "no-store"


def test_protected_endpoint_rejects_invalid_access_token(client):
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401


def test_protected_endpoint_rejects_anonymous_access(client):
    response = client.get("/api/v1/me", headers={"Authorization": ""})
    assert response.status_code == 401


def test_current_user_exposes_only_safe_identity_capabilities(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["identity_providers"] == ["local"]
    assert body["can_change_password"] is True
    assert body["can_manage_sessions"] is True
    assert "password_hash" not in response.text
    assert "subject" not in body


def test_login_rejects_an_untrusted_browser_origin(client):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://attacker.example"},
        json={
            "email": "developer@example.com",
            "password": "Correct-Horse-Battery-Staple-42",
        },
    )
    assert response.status_code == 403


def test_refresh_rotation_detects_replay_and_revokes_family(client):
    login(client)
    old_token = client.cookies.get("wbs_refresh")
    assert old_token

    first_refresh = client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200
    new_token = client.cookies.get("wbs_refresh")
    assert new_token and new_token != old_token

    client.cookies.set("wbs_refresh", old_token, path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    client.cookies.set("wbs_refresh", new_token, path="/api/v1/auth")
    revoked_family = client.post("/api/v1/auth/refresh")
    assert revoked_family.status_code == 401


def test_session_listing_and_revocation_are_scoped_to_current_user(client):
    response = client.get("/api/v1/auth/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert sessions
    assert any(item["current"] for item in sessions)

    current = next(item for item in sessions if item["current"])
    revoked = client.delete(f"/api/v1/auth/sessions/{current['id']}")
    assert revoked.status_code == 200
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_session_id_cannot_revoke_another_users_session(client):
    async def seed_other_session():
        suffix = uuid4().hex
        user = User(
            external_subject=f"other-session-{suffix}",
            email=f"other-session-{suffix}@example.com",
            display_name="Other Session User",
        )
        session = RefreshSession(
            user_id=user.id,
            family_id=uuid4(),
            token_hash=token_digest(f"other-session-token-{suffix}"),
            expires_at=utc_now() + timedelta(days=1),
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            session.user_id = user.id
            db.add(session)
            await db.commit()
            return session.id

    async def session_is_active(session_id):
        async with SessionLocal() as db:
            session = await db.get(RefreshSession, session_id)
            return session is not None and session.revoked_at is None

    other_session_id = client.portal.call(seed_other_session)
    response = client.delete(f"/api/v1/auth/sessions/{other_session_id}")
    assert response.status_code == 404
    assert client.portal.call(session_is_active, other_session_id) is True


def test_revoking_session_records_safe_audit_event(client):
    session_id = client.get("/api/v1/auth/sessions").json()[0]["id"]
    response = client.delete(f"/api/v1/auth/sessions/{session_id}")
    assert response.status_code == 200

    async def matching_event():
        async with SessionLocal() as db:
            events = list(
                await db.scalars(select(AuthEvent).where(AuthEvent.event_type == "session_revoked"))
            )
            return next(
                (item for item in events if item.details.get("session_id") == session_id),
                None,
            )

    event = client.portal.call(matching_event)
    assert event is not None
    assert event.success is True
    assert event.details == {"session_id": session_id}
    assert "token" not in str(event.details).lower()


def test_oidc_only_identity_cannot_change_password(client):
    async def seed_oidc_user():
        suffix = uuid4().hex
        user = User(
            external_subject=f"oidc-only-{suffix}",
            email=f"oidc-only-{suffix}@example.com",
            display_name="OIDC Only User",
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="oidc",
                    subject=f"enterprise-{suffix}",
                )
            )
            await db.commit()
        access_token, _ = create_access_token(
            user.id,
            uuid4(),
            user.auth_version,
            get_settings(),
        )
        return access_token

    access_token = client.portal.call(seed_oidc_user)
    headers = {"Authorization": f"Bearer {access_token}"}
    identity = client.get("/api/v1/me", headers=headers)
    assert identity.status_code == 200
    assert identity.json()["identity_providers"] == ["oidc"]
    assert identity.json()["can_change_password"] is False
    assert identity.json()["can_manage_sessions"] is True

    response = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "No-Local-Password-42",
            "new_password": "New-Local-Password-84",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Current password is incorrect."


def test_password_change_requires_current_password_and_revokes_every_session(client):
    async def seed_local_user():
        suffix = uuid4().hex
        email = f"password-change-{suffix}@example.com"
        old_password = "Original-Password-Value-42"
        user = User(
            external_subject=f"password-change-{suffix}",
            email=email,
            display_name="Password Change User",
        )
        async with SessionLocal() as db:
            db.add(user)
            await db.flush()
            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="local",
                    subject=email,
                    password_hash=hash_password(old_password),
                )
            )
            await db.commit()
        return email, old_password

    email, old_password = client.portal.call(seed_local_user)
    signed_in = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": old_password},
    )
    assert signed_in.status_code == 200
    access_token = signed_in.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    incorrect = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "Incorrect-Password-Value-12",
            "new_password": "Updated-Password-Value-84",
        },
    )
    assert incorrect.status_code == 400
    assert incorrect.json()["detail"] == "Current password is incorrect."
    assert client.get("/api/v1/me", headers=headers).status_code == 200

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": old_password,
            "new_password": "Updated-Password-Value-84",
        },
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": old_password},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Updated-Password-Value-84"},
        ).status_code
        == 200
    )


def test_logout_all_invalidates_existing_access_tokens(client):
    old_access_token = client.headers["Authorization"]
    response = client.post("/api/v1/auth/logout-all")
    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()

    stale = client.get("/api/v1/me", headers={"Authorization": old_access_token})
    assert stale.status_code == 401


def test_logout_revokes_refresh_session_and_clears_cookie(client):
    assert login(client).status_code == 200
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert client.post("/api/v1/auth/refresh").status_code == 401
