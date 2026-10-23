import argparse
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import cli
from app.core.passwords import verify_password
from app.db.base import Base
from app.models.auth import AuthIdentity
from app.models.domain import MembershipRole, Tenant, TenantMembership, User
from app.services.provisioning import (
    AdminProvisioningError,
    ProvisionedAdministrator,
    provision_local_administrator,
)


@pytest.fixture
async def session_factory(tmp_path):
    database_path = tmp_path / "provisioning.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_provisioning_creates_normalized_administrator_atomically(session_factory):
    async with session_factory() as db:
        result = await provision_local_administrator(
            db,
            email="  ADMIN@Example.COM ",
            display_name="WBS Administrator",
            tenant_slug="Default-Workspace",
            tenant_name="Default Workspace",
            password="Correct-Horse-Battery-Staple-42",
        )

        user = await db.get(User, result.user_id)
        tenant = await db.get(Tenant, result.tenant_id)
        identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == result.user_id)
        )
        membership = await db.get(TenantMembership, (result.tenant_id, result.user_id))

    assert result.email == "admin@example.com"
    assert result.tenant_slug == "default-workspace"
    assert user is not None and user.is_active
    assert tenant is not None and tenant.is_active
    assert identity is not None
    assert identity.password_hash != "Correct-Horse-Battery-Staple-42"
    assert verify_password("Correct-Horse-Battery-Staple-42", identity.password_hash)
    assert membership is not None and membership.role == MembershipRole.ADMIN


async def test_provisioning_rejects_weak_and_duplicate_credentials(session_factory):
    async with session_factory() as db:
        with pytest.raises(AdminProvisioningError, match="at least 12 characters"):
            await provision_local_administrator(
                db,
                email="weak@example.com",
                display_name="Weak Password",
                tenant_slug="weak-password",
                tenant_name="Weak Password",
                password="too-short",
            )
        assert await db.scalar(select(Tenant).where(Tenant.slug == "weak-password")) is None
        await db.rollback()

        arguments = {
            "email": "duplicate@example.com",
            "display_name": "Duplicate User",
            "tenant_slug": "duplicate",
            "tenant_name": "Duplicate Tenant",
            "password": "Correct-Horse-Battery-Staple-42",
        }
        await provision_local_administrator(db, **arguments)
        with pytest.raises(AdminProvisioningError, match="already exists"):
            await provision_local_administrator(db, **arguments)


async def test_existing_user_link_requires_explicit_operator_confirmation(session_factory):
    async with session_factory() as db:
        async with db.begin():
            db.add(
                User(
                    external_subject="oidc:verified-subject",
                    email="existing@example.com",
                    display_name="Existing User",
                )
            )

        arguments = {
            "email": "existing@example.com",
            "display_name": "Existing User",
            "tenant_slug": "existing-user-tenant",
            "tenant_name": "Existing User Tenant",
            "password": "Correct-Horse-Battery-Staple-42",
        }
        with pytest.raises(AdminProvisioningError, match="--link-existing-user"):
            await provision_local_administrator(db, **arguments)

        result = await provision_local_administrator(db, **arguments, link_existing_user=True)
        identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == result.user_id)
        )

    assert identity is not None and identity.subject == "existing@example.com"


async def test_late_database_failure_rolls_back_every_provisioned_record(session_factory):
    async with session_factory() as db:
        async with db.begin():
            db.add(
                User(
                    external_subject="local:rollback@example.com",
                    email="different@example.com",
                    display_name="Conflicting User",
                )
            )

        with pytest.raises(AdminProvisioningError, match="no changes were saved"):
            await provision_local_administrator(
                db,
                email="rollback@example.com",
                display_name="Rollback User",
                tenant_slug="must-rollback",
                tenant_name="Must Roll Back",
                password="Correct-Horse-Battery-Staple-42",
            )

        tenant = await db.scalar(select(Tenant).where(Tenant.slug == "must-rollback"))
        identity = await db.scalar(
            select(AuthIdentity).where(AuthIdentity.subject == "rollback@example.com")
        )

    assert tenant is None
    assert identity is None


async def test_cli_rejects_mismatched_passwords_before_opening_database(monkeypatch):
    prompts = iter(["first-password", "different-password"])
    monkeypatch.setattr(cli, "getpass", lambda _: next(prompts))
    session_factory = AsyncMock()
    monkeypatch.setattr(cli, "SessionLocal", session_factory)

    args = argparse.Namespace(
        email="admin@example.com",
        display_name="Admin",
        tenant_slug="default",
        tenant_name="Default",
        link_existing_user=False,
    )
    with pytest.raises(SystemExit, match="Passwords do not match"):
        await cli.create_admin(args)

    session_factory.assert_not_called()


async def test_cli_never_prints_password_hash_or_token(monkeypatch, capsys):
    password = "Correct-Horse-Battery-Staple-42"
    prompts = iter([password, password])
    monkeypatch.setattr(cli, "getpass", lambda _: next(prompts))

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(cli, "SessionLocal", FakeSessionContext)
    provision = AsyncMock(
        return_value=ProvisionedAdministrator(
            user_id=uuid4(),
            tenant_id=uuid4(),
            email="admin@example.com",
            tenant_slug="default",
        )
    )
    monkeypatch.setattr(cli, "provision_local_administrator", provision)

    args = argparse.Namespace(
        email="admin@example.com",
        display_name="Admin",
        tenant_slug="default",
        tenant_name="Default",
        link_existing_user=False,
    )
    await cli.create_admin(args)

    output = capsys.readouterr().out
    assert "Provisioned admin@example.com" in output
    assert password not in output
    assert "hash" not in output.casefold()
    assert "token" not in output.casefold()
