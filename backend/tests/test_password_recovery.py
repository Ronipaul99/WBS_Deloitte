import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.passwords import hash_password
from app.core.security import token_digest
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import AuthIdentity, PasswordResetToken
from app.models.domain import User
from app.services.auth import cleanup_password_reset_tokens, utc_now
from app.services.email import InMemoryEmailProvider, get_email_provider

ACCEPTED_MESSAGE = "If the account is eligible, password reset instructions will be sent."
NEW_PASSWORD = "A-New-Correct-Horse-Battery-Staple-84"


@pytest.fixture
def email_provider() -> InMemoryEmailProvider:
    provider = get_email_provider()
    assert isinstance(provider, InMemoryEmailProvider)
    provider.clear()
    yield provider
    provider.clear()


async def _seed_user(active: bool = True, local_password: bool = True) -> tuple[str, str]:
    suffix = uuid4().hex
    email = f"recovery-{suffix}@example.com"
    password = "Original-Correct-Horse-Battery-71"
    user = User(
        external_subject=f"recovery-{suffix}",
        email=email,
        display_name="Recovery User",
        is_active=active,
    )
    async with SessionLocal() as db:
        db.add(user)
        await db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider="local" if local_password else "oidc",
                subject=email if local_password else f"oidc-{suffix}",
                password_hash=hash_password(password) if local_password else None,
            )
        )
        await db.commit()
    return email, password


def _raw_token(provider: InMemoryEmailProvider) -> str:
    assert provider.deliveries
    reset_url = urlsplit(provider.deliveries[-1].reset_url)
    assert reset_url.query == ""
    query = parse_qs(reset_url.fragment)
    return query["token"][0]


async def _stored_token(raw_token: str) -> PasswordResetToken | None:
    async with SessionLocal() as db:
        return await db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_digest(raw_token)
            )
        )


async def _expire_token(raw_token: str) -> None:
    async with SessionLocal() as db:
        token = await db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_digest(raw_token)
            )
        )
        assert token is not None
        token.expires_at = utc_now() - timedelta(minutes=1)
        await db.commit()


def test_known_and_unknown_requests_are_indistinguishable(client, email_provider):
    email, _ = client.portal.call(_seed_user)
    known = client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"unknown-{uuid4().hex}@example.com"},
    )

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"message": ACCEPTED_MESSAGE}
    assert known.headers["cache-control"] == "no-store"
    assert len(email_provider.deliveries) == 1
    assert email_provider.deliveries[0].recipient == email


def test_database_stores_only_the_token_digest(client, email_provider, caplog):
    email, _ = client.portal.call(_seed_user)
    response = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert response.status_code == 202

    raw_token = _raw_token(email_provider)
    stored = client.portal.call(_stored_token, raw_token)
    assert stored is not None
    assert stored.token_hash == token_digest(raw_token)
    assert raw_token not in stored.token_hash
    assert raw_token not in caplog.text
    assert raw_token not in response.text


def test_reset_is_single_use_and_revokes_access_and_refresh_sessions(client, email_provider):
    email, original_password = client.portal.call(_seed_user)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": original_password},
    )
    assert login.status_code == 200
    old_access = login.json()["access_token"]

    assert client.post("/api/v1/auth/forgot-password", json={"email": email}).status_code == 202
    raw_token = _raw_token(email_provider)
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": NEW_PASSWORD},
    )
    assert reset.status_code == 200
    assert "access_token" not in reset.text

    reused = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": NEW_PASSWORD},
    )
    assert reused.status_code == 400
    assert reused.json()["detail"] == "The password reset link is invalid or has expired."
    old_access_response = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {old_access}"}
    )
    assert old_access_response.status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": original_password},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": NEW_PASSWORD},
        ).status_code
        == 200
    )


def test_expired_token_returns_the_generic_error(client, email_provider):
    email, _ = client.portal.call(_seed_user)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw_token = _raw_token(email_provider)
    client.portal.call(_expire_token, raw_token)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The password reset link is invalid or has expired."


def test_inactive_and_oidc_only_users_do_not_receive_reset_email(client, email_provider):
    inactive_email, _ = client.portal.call(_seed_user, False, True)
    oidc_email, _ = client.portal.call(_seed_user, True, False)

    inactive = client.post("/api/v1/auth/forgot-password", json={"email": inactive_email})
    oidc = client.post("/api/v1/auth/forgot-password", json={"email": oidc_email})
    assert inactive.status_code == oidc.status_code == 202
    assert inactive.json() == oidc.json() == {"message": ACCEPTED_MESSAGE}
    assert email_provider.deliveries == []


def test_password_reset_requests_are_rate_limited_without_account_detail(client, email_provider):
    email = f"rate-limit-{uuid4().hex}@example.com"
    for _ in range(3):
        assert client.post("/api/v1/auth/forgot-password", json={"email": email}).status_code == 202

    limited = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Too many password reset requests. Try again later."
    assert "retry-after" in limited.headers
    assert email_provider.deliveries == []


def test_email_failure_keeps_the_external_response_generic_and_invalidates_token(
    client, email_provider
):
    email, _ = client.portal.call(_seed_user)
    email_provider.should_fail = True
    response = client.post("/api/v1/auth/forgot-password", json={"email": email})

    assert response.status_code == 202
    assert response.json() == {"message": ACCEPTED_MESSAGE}
    email_provider.should_fail = False

    async def latest_token() -> PasswordResetToken | None:
        async with SessionLocal() as db:
            return await db.scalar(
                select(PasswordResetToken)
                .join(User, User.id == PasswordResetToken.user_id)
                .where(User.email == email)
                .order_by(PasswordResetToken.created_at.desc())
            )

    stored = client.portal.call(latest_token)
    assert stored is not None
    assert stored.used_at is not None


def test_new_request_invalidates_older_unused_token(client, email_provider):
    email, _ = client.portal.call(_seed_user)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    older_token = _raw_token(email_provider)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    newer_token = _raw_token(email_provider)

    older = client.portal.call(_stored_token, older_token)
    newer = client.portal.call(_stored_token, newer_token)
    assert older is not None and older.used_at is not None
    assert newer is not None and newer.used_at is None


def test_concurrent_reset_submissions_have_one_winner(client, email_provider):
    email, _ = client.portal.call(_seed_user)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    raw_token = _raw_token(email_provider)

    async def submit_twice():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
            payload = {"token": raw_token, "new_password": NEW_PASSWORD}
            return await asyncio.gather(
                async_client.post("/api/v1/auth/reset-password", json=payload),
                async_client.post("/api/v1/auth/reset-password", json=payload),
            )

    responses = client.portal.call(submit_twice)
    assert sorted(response.status_code for response in responses) == [200, 400]
    failure = next(response for response in responses if response.status_code == 400)
    assert failure.json()["detail"] == "The password reset link is invalid or has expired."


def test_recovery_rejects_untrusted_browser_origin(client, email_provider):
    email, _ = client.portal.call(_seed_user)
    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": email},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert email_provider.deliveries == []


async def test_cleanup_removes_only_records_past_retention(client):
    email, _ = await _seed_user()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        old = utc_now() - timedelta(days=31)
        retained = PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest("old-token"),
            expires_at=old,
            used_at=old,
        )
        active = PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest("active-token"),
            expires_at=utc_now() + timedelta(minutes=10),
        )
        db.add_all([retained, active])
        await db.commit()
        retained_id = retained.id
        active_id = active.id

    async with SessionLocal() as db:
        assert await cleanup_password_reset_tokens(db, retention_days=30) == 1

    async with SessionLocal() as db:
        assert await db.get(PasswordResetToken, retained_id) is None
        assert await db.get(PasswordResetToken, active_id) is not None
