import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import create_access_token, token_digest
from app.db.session import SessionLocal
from app.models.auth import AuthEvent, AuthIdentity, TenantInvitation
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.services.auth import utc_now
from app.services.email import InMemoryEmailProvider, get_email_provider
from app.services.members import (
    FinalAdministratorError,
    cleanup_tenant_invitations,
    update_member_role,
)

PASSWORD = "Correct-Horse-Battery-Staple-84"


@pytest.fixture
def invitation_email_provider() -> InMemoryEmailProvider:
    provider = get_email_provider()
    assert isinstance(provider, InMemoryEmailProvider)
    provider.clear()
    yield provider
    provider.clear()


def _invitation_token(provider: InMemoryEmailProvider) -> str:
    assert provider.invitation_deliveries
    invitation_url = urlsplit(provider.invitation_deliveries[-1].invitation_url)
    assert invitation_url.query == ""
    return parse_qs(invitation_url.fragment)["token"][0]


async def _seed_user(
    email: str,
    tenant_id: UUID | None = None,
    role: MembershipRole | None = None,
    with_identity: bool = False,
) -> tuple[UUID, str]:
    user = User(
        external_subject=f"test:{uuid4().hex}",
        email=email,
        display_name=email.split("@", 1)[0].replace("-", " ").title(),
    )
    async with SessionLocal() as db:
        db.add(user)
        await db.flush()
        if with_identity:
            from app.core.passwords import hash_password

            db.add(
                AuthIdentity(
                    user_id=user.id,
                    provider="local",
                    subject=email,
                    password_hash=hash_password(PASSWORD),
                )
            )
        if tenant_id is not None and role is not None:
            db.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=role))
        await db.commit()
    access_token, _ = create_access_token(user.id, uuid4(), user.auth_version, get_settings())
    return user.id, access_token


async def _stored_invitation(raw_token: str) -> TenantInvitation | None:
    async with SessionLocal() as db:
        return await db.scalar(
            select(TenantInvitation).where(TenantInvitation.token_hash == token_digest(raw_token))
        )


async def _expire_invitation(raw_token: str) -> None:
    async with SessionLocal() as db:
        invitation = await db.scalar(
            select(TenantInvitation).where(TenantInvitation.token_hash == token_digest(raw_token))
        )
        assert invitation is not None
        invitation.expires_at = utc_now() - timedelta(minutes=1)
        await db.commit()


def test_admin_invitation_lifecycle_hashes_and_rotates_tokens(
    client, tenant_id, invitation_email_provider, caplog
):
    email = f"invite-{uuid4().hex}@example.com"
    created = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email.upper(), "role": "EDITOR"},
    )
    assert created.status_code == 201, created.text
    invitation_id = created.json()["id"]
    first_token = _invitation_token(invitation_email_provider)
    stored = client.portal.call(_stored_invitation, first_token)
    assert stored is not None
    assert stored.email == email
    assert stored.token_hash == token_digest(first_token)
    assert first_token not in created.text
    assert first_token not in caplog.text

    listed = client.get(f"/api/v1/tenants/{tenant_id}/members", params={"search": email})
    assert listed.status_code == 200
    assert listed.json()["total_invitations"] == 1
    assert listed.json()["invitations"][0]["email"] == email

    duplicate = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email, "role": "VIEWER"},
    )
    assert duplicate.status_code == 409

    resent = client.post(f"/api/v1/tenants/{tenant_id}/invitations/{invitation_id}/resend")
    assert resent.status_code == 200
    second_token = _invitation_token(invitation_email_provider)
    assert second_token != first_token
    assert client.portal.call(_stored_invitation, first_token) is None

    stale = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": first_token, "display_name": "Stale", "password": PASSWORD},
    )
    assert stale.status_code == 400

    revoked = client.delete(f"/api/v1/tenants/{tenant_id}/invitations/{invitation_id}")
    assert revoked.status_code == 204
    rejected = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": second_token, "display_name": "Revoked", "password": PASSWORD},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "The invitation is invalid or has expired."

    replacement = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email, "role": "VIEWER"},
    )
    assert replacement.status_code == 201
    replacement_token = _invitation_token(invitation_email_provider)
    client.portal.call(_expire_invitation, replacement_token)
    expired = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": replacement_token, "display_name": "Expired", "password": PASSWORD},
    )
    assert expired.status_code == 400

    unknown_role = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": f"unknown-{uuid4().hex}@example.com", "role": "OWNER"},
    )
    assert unknown_role.status_code == 422


def test_new_user_accepts_once_and_receives_the_fixed_role(
    client, tenant_id, invitation_email_provider
):
    email = f"new-member-{uuid4().hex}@example.com"
    invited = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email, "role": "VIEWER"},
    )
    assert invited.status_code == 201
    token = _invitation_token(invitation_email_provider)

    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": token, "display_name": "New Member", "password": PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["account_created"] is True
    assert accepted.json()["role"] == "VIEWER"

    replay = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": token, "display_name": "Changed", "password": PASSWORD},
    )
    assert replay.status_code == 400

    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    me = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["tenants"][0]["role"] == "VIEWER"


def test_existing_user_must_authenticate_with_the_invited_identity(
    client, tenant_id, invitation_email_provider
):
    email = f"Existing-{uuid4().hex}@Example.COM"
    _, invited_access = client.portal.call(_seed_user, email)
    invited = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email.casefold(), "role": "EDITOR"},
    )
    assert invited.status_code == 201
    token = _invitation_token(invitation_email_provider)

    unauthenticated = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": ""},
        json={"token": token},
    )
    assert unauthenticated.status_code == 401

    wrong_identity = client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": token},
    )
    assert wrong_identity.status_code == 400
    assert wrong_identity.json()["detail"] == "The invitation is invalid or has expired."

    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        headers={"Authorization": f"Bearer {invited_access}"},
        json={"token": token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["account_created"] is False
    assert accepted.json()["role"] == "EDITOR"


def test_role_changes_and_removal_take_effect_on_the_next_request(client, tenant_id):
    tenant_uuid = UUID(tenant_id)
    email = f"role-change-{uuid4().hex}@example.com"
    user_id, access_token = client.portal.call(
        _seed_user,
        email,
        tenant_uuid,
        MembershipRole.EDITOR,
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    before = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        headers=headers,
        json={"name": "Before role change"},
    )
    assert before.status_code == 201

    changed = client.patch(
        f"/api/v1/tenants/{tenant_id}/members/{user_id}",
        json={"role": "VIEWER"},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "VIEWER"
    after = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        headers=headers,
        json={"name": "After role change"},
    )
    assert after.status_code == 403

    removed = client.delete(f"/api/v1/tenants/{tenant_id}/members/{user_id}")
    assert removed.status_code == 204
    denied = client.get(f"/api/v1/tenants/{tenant_id}/projects", headers=headers)
    assert denied.status_code == 403


def test_viewer_and_editor_cannot_use_any_member_administration_api(client, tenant_id):
    tenant_uuid = UUID(tenant_id)
    target_id = uuid4()
    invitation_id = uuid4()
    operations = [
        ("get", f"/api/v1/tenants/{tenant_id}/members", None),
        (
            "post",
            f"/api/v1/tenants/{tenant_id}/invitations",
            {"email": f"denied-{uuid4().hex}@example.com", "role": "VIEWER"},
        ),
        (
            "post",
            f"/api/v1/tenants/{tenant_id}/invitations/{invitation_id}/resend",
            None,
        ),
        (
            "delete",
            f"/api/v1/tenants/{tenant_id}/invitations/{invitation_id}",
            None,
        ),
        (
            "patch",
            f"/api/v1/tenants/{tenant_id}/members/{target_id}",
            {"role": "ADMIN"},
        ),
        ("delete", f"/api/v1/tenants/{tenant_id}/members/{target_id}", None),
    ]

    for role in (MembershipRole.VIEWER, MembershipRole.EDITOR):
        _, access_token = client.portal.call(
            _seed_user,
            f"{role.value.lower()}-{uuid4().hex}@example.com",
            tenant_uuid,
            role,
        )
        headers = {"Authorization": f"Bearer {access_token}"}
        for method, path, body in operations:
            response = client.request(method, path, headers=headers, json=body)
            assert response.status_code == 403, (role, method, path, response.text)


def test_final_admin_and_cross_tenant_resources_are_protected(client, tenant_id):
    final_admin_id = client.get("/api/v1/me").json()["id"]
    demote = client.patch(
        f"/api/v1/tenants/{tenant_id}/members/{final_admin_id}",
        json={"role": "EDITOR"},
    )
    remove = client.delete(f"/api/v1/tenants/{tenant_id}/members/{final_admin_id}")
    assert demote.status_code == remove.status_code == 409

    async def seed_other_tenant():
        tenant = Tenant(name=f"Other {uuid4().hex[:8]}", slug=f"other-{uuid4().hex}")
        user = User(
            external_subject=f"other:{uuid4().hex}",
            email=f"other-{uuid4().hex}@example.com",
            display_name="Other Member",
        )
        async with SessionLocal() as db:
            db.add_all([tenant, user])
            await db.flush()
            db.add(
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role=MembershipRole.VIEWER,
                )
            )
            invitation = TenantInvitation(
                tenant_id=tenant.id,
                email=f"outside-{uuid4().hex}@example.com",
                role=MembershipRole.VIEWER,
                token_hash=token_digest(uuid4().hex),
                invited_by_user_id=user.id,
                expires_at=utc_now() + timedelta(hours=72),
            )
            db.add(invitation)
            await db.commit()
            return tenant.id, user.id, invitation.id

    other_tenant_id, other_user_id, other_invitation_id = client.portal.call(seed_other_tenant)
    assert client.get(f"/api/v1/tenants/{other_tenant_id}/members").status_code == 403
    wrong_member = client.patch(
        f"/api/v1/tenants/{tenant_id}/members/{other_user_id}",
        json={"role": "EDITOR"},
    )
    wrong_invitation = client.delete(
        f"/api/v1/tenants/{tenant_id}/invitations/{other_invitation_id}"
    )
    assert wrong_member.status_code == wrong_invitation.status_code == 404

    async def denied_events():
        async with SessionLocal() as db:
            return list(
                await db.scalars(
                    select(AuthEvent).where(
                        AuthEvent.event_type.in_(("tenant_access_denied", "tenant_resource_denied"))
                    )
                )
            )

    event_types = {event.event_type for event in client.portal.call(denied_events)}
    assert {"tenant_access_denied", "tenant_resource_denied"} <= event_types


async def test_concurrent_demotions_cannot_remove_every_administrator(client):
    tenant = Tenant(name=f"Concurrent {uuid4().hex[:8]}", slug=f"concurrent-{uuid4().hex}")
    admin_one = User(
        external_subject=f"admin-one:{uuid4().hex}",
        email=f"admin-one-{uuid4().hex}@example.com",
        display_name="Admin One",
    )
    admin_two = User(
        external_subject=f"admin-two:{uuid4().hex}",
        email=f"admin-two-{uuid4().hex}@example.com",
        display_name="Admin Two",
    )
    async with SessionLocal() as db:
        db.add_all([tenant, admin_one, admin_two])
        await db.flush()
        db.add_all(
            [
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=admin_one.id,
                    role=MembershipRole.ADMIN,
                ),
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=admin_two.id,
                    role=MembershipRole.ADMIN,
                ),
            ]
        )
        await db.commit()

    async def demote(target_id: UUID):
        async with SessionLocal() as db:
            return await update_member_role(
                db,
                tenant_id=tenant.id,
                target_user_id=target_id,
                role=MembershipRole.EDITOR,
                actor_id=admin_one.id,
                ip_hash="i" * 64,
                user_agent_hash="u" * 64,
            )

    results = await asyncio.gather(
        demote(admin_one.id), demote(admin_two.id), return_exceptions=True
    )
    assert sum(isinstance(result, FinalAdministratorError) for result in results) == 1
    async with SessionLocal() as db:
        admin_count = await db.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.role == MembershipRole.ADMIN,
            )
        )
    assert admin_count == 1


def test_delivery_failure_revokes_invitation_and_audit_metadata_excludes_secrets(
    client, tenant_id, invitation_email_provider
):
    email = f"delivery-failure-{uuid4().hex}@example.com"
    invitation_email_provider.should_fail = True
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/invitations",
        json={"email": email, "role": "VIEWER"},
    )
    assert response.status_code == 201
    invitation_id = UUID(response.json()["id"])

    async def invitation_and_events():
        async with SessionLocal() as db:
            invitation = await db.get(TenantInvitation, invitation_id)
            events = list(
                await db.scalars(
                    select(AuthEvent).where(AuthEvent.event_type.like("tenant_invitation%"))
                )
            )
            return invitation, events

    invitation, events = client.portal.call(invitation_and_events)
    assert invitation is not None and invitation.revoked_at is not None
    assert events
    for event in events:
        serialized = str(event.details)
        assert email not in serialized
        assert "token" not in serialized.casefold()


async def test_invitation_cleanup_retains_recent_history(client):
    now = utc_now()
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    actor_id = UUID("00000000-0000-0000-0000-000000000001")
    expired = TenantInvitation(
        tenant_id=tenant_id,
        email=f"expired-{uuid4().hex}@example.com",
        role=MembershipRole.VIEWER,
        token_hash=token_digest(uuid4().hex),
        invited_by_user_id=actor_id,
        expires_at=now - timedelta(days=31),
    )
    recent = TenantInvitation(
        tenant_id=tenant_id,
        email=f"recent-{uuid4().hex}@example.com",
        role=MembershipRole.VIEWER,
        token_hash=token_digest(uuid4().hex),
        invited_by_user_id=actor_id,
        expires_at=now - timedelta(days=1),
    )
    async with SessionLocal() as db:
        db.add_all([expired, recent])
        await db.commit()
        deleted = await cleanup_tenant_invitations(db, 30)
        assert deleted >= 1
        assert await db.get(TenantInvitation, expired.id) is None
        assert await db.get(TenantInvitation, recent.id) is not None
