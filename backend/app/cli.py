import argparse
import asyncio
import json
from getpass import getpass

from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models.auth import RefreshSession
from app.models.domain import User
from app.services.auth import (
    add_auth_event,
    cleanup_password_reset_tokens,
    normalize_email,
    revoke_all_user_sessions,
)
from app.services.maintenance import run_maintenance
from app.services.members import cleanup_tenant_invitations
from app.services.provisioning import AdminProvisioningError, provision_local_administrator


async def create_admin(args: argparse.Namespace) -> None:
    password = getpass("Password (12+ characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        async with SessionLocal() as db:
            administrator = await provision_local_administrator(
                db,
                email=args.email,
                display_name=args.display_name,
                tenant_slug=args.tenant_slug,
                tenant_name=args.tenant_name,
                password=password,
                link_existing_user=args.link_existing_user,
            )
    except AdminProvisioningError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"Provisioned {administrator.email} as an administrator for tenant "
        f"'{administrator.tenant_slug}'."
    )


async def cleanup_reset_tokens() -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        deleted = await cleanup_password_reset_tokens(db, settings.password_reset_retention_days)
    print(f"Deleted {deleted} retained password reset token records.")


async def cleanup_invitations() -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        deleted = await cleanup_tenant_invitations(db, settings.tenant_invitation_retention_days)
    print(f"Deleted {deleted} retained tenant invitation records.")


async def execute_maintenance() -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        result = await run_maintenance(db, settings)
    print(json.dumps({"status": "ok", "deleted": result.as_dict()}, sort_keys=True))


def check_production_config() -> None:
    settings = get_settings()
    if settings.app_env != "production":
        raise SystemExit("APP_ENV must be production for this release gate.")
    print(
        json.dumps(
            {
                "status": "ok",
                "environment": settings.app_env,
                "auth_mode": settings.auth_mode,
                "database_backend": "postgresql",
                "cors_origin_count": len(settings.cors_origin_list),
                "secure_cookie": settings.auth_cookie_secure,
                "migration_readiness": settings.readiness_require_migration_head,
                "metrics_enabled": settings.metrics_enabled,
                "trusted_proxy_count": len(settings.forwarded_allow_ip_list),
            },
            sort_keys=True,
        )
    )


def require_confirmation(actual: str | None, expected: str) -> None:
    if actual != expected:
        raise SystemExit(f"Refusing operation. Pass --confirm {expected} after approval.")


async def revoke_user_sessions(args: argparse.Namespace) -> None:
    require_confirmation(args.confirm, "REVOKE_USER_SESSIONS")
    async with SessionLocal() as db:
        user = await db.scalar(
            select(User)
            .where(func.lower(User.email) == normalize_email(args.email))
            .with_for_update()
        )
        if user is None:
            raise SystemExit("User not found.")
        user.auth_version += 1
        await revoke_all_user_sessions(db, user.id, "operator_revocation")
        add_auth_event(
            db,
            event_type="operator_user_session_revocation",
            success=True,
            user_id=user.id,
            subject_hash=None,
            ip_hash=None,
            user_agent_hash=None,
        )
        await db.commit()
    print(json.dumps({"status": "ok", "user_id": str(user.id)}, sort_keys=True))


async def revoke_every_session(args: argparse.Namespace) -> None:
    require_confirmation(args.confirm, "REVOKE_ALL_SESSIONS")
    async with SessionLocal() as db:
        user_count = await db.scalar(select(func.count()).select_from(User))
        await db.execute(update(User).values(auth_version=User.auth_version + 1))
        await db.execute(
            update(RefreshSession)
            .where(RefreshSession.revoked_at.is_(None))
            .values(revoked_at=func.now(), revoked_reason="operator_mass_revocation")
        )
        add_auth_event(
            db,
            event_type="operator_mass_session_revocation",
            success=True,
            user_id=None,
            subject_hash=None,
            ip_hash=None,
            user_agent_hash=None,
            details={"user_count": str(user_count or 0)},
        )
        await db.commit()
    print(json.dumps({"status": "ok", "users_invalidated": user_count or 0}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="WBS backend administration commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-admin", help="Provision a local administrator")
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--tenant-slug", required=True)
    create.add_argument("--tenant-name", required=True)
    create.add_argument(
        "--link-existing-user",
        action="store_true",
        help="Link a verified existing user instead of creating a new user record",
    )
    subparsers.add_parser(
        "cleanup-password-reset-tokens",
        help="Delete used or expired password reset records past the retention period",
    )
    subparsers.add_parser(
        "cleanup-tenant-invitations",
        help="Delete accepted, revoked, or expired invitations past the retention period",
    )
    subparsers.add_parser(
        "run-maintenance",
        help="Run all idempotent authentication, audit, and temporary-file retention jobs",
    )
    subparsers.add_parser(
        "check-production-config",
        help="Validate production settings and print a secret-free readiness summary",
    )
    revoke_user = subparsers.add_parser(
        "revoke-user-sessions",
        help="Invalidate every access and refresh session for one user",
    )
    revoke_user.add_argument("--email", required=True)
    revoke_user.add_argument("--confirm")
    revoke_all = subparsers.add_parser(
        "revoke-all-sessions",
        help="Invalidate every access and refresh session in the environment",
    )
    revoke_all.add_argument("--confirm")
    args = parser.parse_args()

    try:
        if args.command == "create-admin":
            asyncio.run(create_admin(args))
        elif args.command == "cleanup-password-reset-tokens":
            asyncio.run(cleanup_reset_tokens())
        elif args.command == "cleanup-tenant-invitations":
            asyncio.run(cleanup_invitations())
        elif args.command == "run-maintenance":
            asyncio.run(execute_maintenance())
        elif args.command == "check-production-config":
            check_production_config()
        elif args.command == "revoke-user-sessions":
            asyncio.run(revoke_user_sessions(args))
        elif args.command == "revoke-all-sessions":
            asyncio.run(revoke_every_session(args))
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
