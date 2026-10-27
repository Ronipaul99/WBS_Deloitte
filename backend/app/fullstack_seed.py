import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.passwords import hash_password
from app.core.security import token_digest
from app.db.session import SessionLocal, engine
from app.models.auth import AuthIdentity, PasswordResetToken, TenantInvitation
from app.models.domain import MembershipRole, Tenant, TenantMembership, User


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required for full-stack seeding")
    return value


def _assert_disposable_database(run_id: str) -> None:
    settings = get_settings()
    if settings.app_env != "test":
        raise RuntimeError("Full-stack seeding requires APP_ENV=test")
    if os.environ.get("FULLSTACK_SEED_GUARD") != run_id:
        raise RuntimeError("Full-stack seed guard does not match this run")
    database_url = settings.sqlalchemy_database_url.casefold()
    if "wbs_fullstack" not in database_url and ".fullstack" not in database_url:
        raise RuntimeError("Refusing to seed a database that is not full-stack-test scoped")


async def _create_user(
    *,
    email: str,
    display_name: str,
    password: str | None,
    active: bool = True,
    provider: str = "local",
) -> User:
    async with SessionLocal() as db:
        user = User(
            external_subject=f"{provider}:{email}",
            email=email,
            display_name=display_name,
            is_active=active,
        )
        db.add(user)
        await db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=provider,
                subject=email,
                password_hash=hash_password(password) if password else None,
            )
        )
        await db.commit()
        await db.refresh(user)
        return user


async def seed() -> dict[str, object]:
    raw_run_id = _required("FULLSTACK_RUN_ID")
    run_id = re.sub(r"[^a-z0-9]", "", raw_run_id.casefold())[:24]
    if not run_id:
        raise RuntimeError("FULLSTACK_RUN_ID must contain letters or numbers")
    _assert_disposable_database(raw_run_id)
    password = _required("FULLSTACK_TEST_PASSWORD")
    reset_token = _required("FULLSTACK_RESET_TOKEN")
    expired_reset_token = _required("FULLSTACK_EXPIRED_RESET_TOKEN")
    invitation_token = _required("FULLSTACK_INVITATION_TOKEN")

    async with SessionLocal() as db:
        existing = await db.scalar(select(Tenant).limit(1))
        if existing is not None:
            raise RuntimeError("Full-stack seed database must be empty")
        tenant_a = Tenant(name=f"Tenant A {run_id}", slug=f"tenant-a-{run_id}")
        tenant_b = Tenant(name=f"Tenant B {run_id}", slug=f"tenant-b-{run_id}")
        inactive_tenant = Tenant(
            name=f"Inactive Tenant {run_id}",
            slug=f"inactive-{run_id}",
            is_active=False,
        )
        final_admin_tenant = Tenant(
            name=f"Final Admin Tenant {run_id}",
            slug=f"final-admin-{run_id}",
        )
        db.add_all([tenant_a, tenant_b, inactive_tenant, final_admin_tenant])
        await db.commit()
        for tenant in (tenant_a, tenant_b, inactive_tenant, final_admin_tenant):
            await db.refresh(tenant)

    emails = {
        "admin_a": f"admin.a.{run_id}@example.com",
        "editor_a": f"editor.a.{run_id}@example.com",
        "viewer_a": f"viewer.a.{run_id}@example.com",
        "admin_b": f"admin.b.{run_id}@example.com",
        "multi": f"multi.{run_id}@example.com",
        "reset": f"reset.{run_id}@example.com",
        "password_change": f"password.change.{run_id}@example.com",
        "session": f"session.{run_id}@example.com",
        "sso": f"sso.{run_id}@example.com",
        "inactive": f"inactive.{run_id}@example.com",
        "inactive_tenant": f"inactive.tenant.{run_id}@example.com",
        "invited": f"invited.{run_id}@example.com",
        "final_admin": f"final.admin.{run_id}@example.com",
    }
    users = {
        "admin_a": await _create_user(
            email=emails["admin_a"], display_name="Admin A", password=password
        ),
        "editor_a": await _create_user(
            email=emails["editor_a"], display_name="Editor A", password=password
        ),
        "viewer_a": await _create_user(
            email=emails["viewer_a"], display_name="Viewer A", password=password
        ),
        "admin_b": await _create_user(
            email=emails["admin_b"], display_name="Admin B", password=password
        ),
        "multi": await _create_user(
            email=emails["multi"], display_name="Multi Tenant User", password=password
        ),
        "reset": await _create_user(
            email=emails["reset"], display_name="Reset User", password=password
        ),
        "password_change": await _create_user(
            email=emails["password_change"],
            display_name="Password Change User",
            password=password,
        ),
        "session": await _create_user(
            email=emails["session"],
            display_name="Session User",
            password=password,
        ),
        "sso": await _create_user(
            email=emails["sso"],
            display_name="SSO User",
            password=None,
            provider="oidc",
        ),
        "inactive": await _create_user(
            email=emails["inactive"],
            display_name="Inactive User",
            password=password,
            active=False,
        ),
        "inactive_tenant": await _create_user(
            email=emails["inactive_tenant"],
            display_name="Inactive Tenant User",
            password=password,
        ),
        "final_admin": await _create_user(
            email=emails["final_admin"],
            display_name="Final Admin",
            password=password,
        ),
    }

    memberships = [
        (tenant_a, users["admin_a"], MembershipRole.ADMIN),
        (tenant_a, users["editor_a"], MembershipRole.EDITOR),
        (tenant_a, users["viewer_a"], MembershipRole.VIEWER),
        (tenant_b, users["admin_b"], MembershipRole.ADMIN),
        (tenant_a, users["multi"], MembershipRole.VIEWER),
        (tenant_b, users["multi"], MembershipRole.ADMIN),
        (tenant_a, users["reset"], MembershipRole.VIEWER),
        (tenant_a, users["password_change"], MembershipRole.VIEWER),
        (tenant_a, users["session"], MembershipRole.VIEWER),
        (tenant_a, users["sso"], MembershipRole.VIEWER),
        (tenant_a, users["inactive"], MembershipRole.VIEWER),
        (inactive_tenant, users["inactive_tenant"], MembershipRole.ADMIN),
        (final_admin_tenant, users["final_admin"], MembershipRole.ADMIN),
    ]
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        db.add_all(
            TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role)
            for tenant, user, role in memberships
        )
        db.add_all(
            [
                PasswordResetToken(
                    user_id=users["reset"].id,
                    token_hash=token_digest(reset_token),
                    expires_at=now + timedelta(minutes=20),
                ),
                PasswordResetToken(
                    user_id=users["reset"].id,
                    token_hash=token_digest(expired_reset_token),
                    expires_at=now - timedelta(minutes=1),
                ),
                TenantInvitation(
                    tenant_id=tenant_a.id,
                    email=emails["invited"],
                    role=MembershipRole.VIEWER,
                    token_hash=token_digest(invitation_token),
                    invited_by_user_id=users["admin_a"].id,
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )
        await db.commit()

    return {
        "run_id": raw_run_id,
        "tenant_a_id": str(tenant_a.id),
        "tenant_b_id": str(tenant_b.id),
        "inactive_tenant_id": str(inactive_tenant.id),
        "final_admin_tenant_id": str(final_admin_tenant.id),
        "emails": emails,
        "user_ids": {name: str(user.id) for name, user in users.items()},
    }


async def main() -> None:
    state_path = Path(_required("FULLSTACK_STATE_PATH")).resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = await seed()
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
