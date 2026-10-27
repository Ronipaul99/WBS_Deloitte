import argparse
import asyncio
import json
from getpass import getpass
from uuid import UUID

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
from app.services.document_maintenance import (
    MaintenanceSafetyError as DocumentMaintenanceSafetyError,
)
from app.services.document_maintenance import (
    reconcile_document_lifecycle,
    recover_document_deletion_dispatches,
    run_document_retention,
)
from app.services.ingestion.reconciliation import reconcile_ingestion_dispatches
from app.services.maintenance import run_maintenance
from app.services.members import cleanup_tenant_invitations
from app.services.provisioning import AdminProvisioningError, provision_local_administrator
from app.services.readiness import IngestionReadinessError, worker_ingestion_is_ready


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
                "document_ingestion_enabled": settings.document_ingestion_enabled,
            },
            sort_keys=True,
        )
    )


async def check_ingestion_worker_readiness() -> None:
    settings = get_settings()
    if not settings.document_ingestion_enabled:
        raise SystemExit("Document ingestion is disabled.")
    try:
        await worker_ingestion_is_ready(settings)
    except IngestionReadinessError as exc:
        raise SystemExit(f"Worker ingestion readiness failed: {exc.category}.") from None
    print(
        json.dumps(
            {
                "status": "ready",
                "checks": [
                    "redis",
                    "malware_scanner",
                    "embedding_model",
                    "tokenizer_runtime",
                    "embedding_runtime",
                    "ocr_runtime",
                    "extractor_registry",
                ],
            },
            sort_keys=True,
        )
    )


async def reconcile_document_ingestion() -> None:
    settings = get_settings()
    result = await reconcile_ingestion_dispatches(settings=settings)
    print(
        json.dumps(
            {
                "status": "ok",
                "repaired": result.repaired_count,
                "republished": result.republished_count,
                "failed": result.failed_count,
            },
            sort_keys=True,
        )
    )


async def reconcile_document_lifecycle_command(args: argparse.Namespace) -> None:
    apply_changes = bool(args.repair)
    if apply_changes:
        require_confirmation(args.confirm, "APPLY_DOCUMENT_REPAIRS")
    try:
        result = await reconcile_document_lifecycle(
            tenant_id=UUID(args.tenant_id) if args.tenant_id else None,
            apply_changes=apply_changes,
            approved=apply_changes,
        )
    except (ValueError, DocumentMaintenanceSafetyError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result.as_dict(), sort_keys=True))


async def run_document_retention_command(args: argparse.Namespace) -> None:
    apply_changes = bool(args.execute)
    if apply_changes:
        require_confirmation(args.confirm, "APPLY_DOCUMENT_RETENTION")
    try:
        result = await run_document_retention(
            tenant_id=UUID(args.tenant_id) if args.tenant_id else None,
            apply_changes=apply_changes,
            approved=apply_changes,
        )
    except (ValueError, DocumentMaintenanceSafetyError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result.as_dict(), sort_keys=True))


async def recover_document_deletions_command(args: argparse.Namespace) -> None:
    result = await recover_document_deletion_dispatches(
        tenant_id=UUID(args.tenant_id) if args.tenant_id else None,
    )
    print(json.dumps(result.as_dict(), sort_keys=True))


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


async def document_workflow_maintenance(args: argparse.Namespace) -> None:
    from app.services.document_workflow_backfill import backfill_workflows, reconcile_uploads
    from app.services.storage import get_upload_storage

    if args.apply:
        require_confirmation(args.confirm, "APPLY_DOCUMENT_WORKFLOW_MAINTENANCE")
    if args.command == "reconcile-document-workflow-dispatches":
        from app.services.document_workflow_dispatch import reconcile_dispatches

        result = await reconcile_dispatches(UUID(args.tenant_id), apply=args.apply,
                                            limit=args.batch_size)
    elif args.command == "backfill-document-workflows":
        result = await backfill_workflows(
            tenant_id=UUID(args.tenant_id), storage=get_upload_storage(), settings=get_settings(),
            apply=args.apply, batch_size=args.batch_size,
            after=UUID(args.after) if args.after else None,
        )
    else:
        result = await reconcile_uploads(
            tenant_id=UUID(args.tenant_id), storage=get_upload_storage(),
            apply=args.apply, batch_size=args.batch_size,
        )
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="WBS backend administration commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        (
            "backfill-document-workflows",
            "Verify stored content and recover unambiguous workflow lineage",
        ),
        (
            "reconcile-document-uploads",
            "Reconcile expired upload ownership and owned orphan objects",
        ),
        (
            "reconcile-document-workflow-dispatches",
            "Republish pending workflow attempts after failure",
        ),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--tenant-id", required=True)
        command.add_argument("--batch-size", type=int, default=100)
        command.add_argument("--after")
        command.add_argument("--apply", action="store_true")
        command.add_argument("--confirm")
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
    subparsers.add_parser(
        "check-ingestion-worker-readiness",
        help="Verify release worker dependencies without loading an embedding model",
    )
    subparsers.add_parser(
        "reconcile-document-ingestion",
        help="Repair and republish bounded document-ingestion work",
    )
    lifecycle = subparsers.add_parser(
        "reconcile-document-lifecycle",
        help="Report document lifecycle inconsistencies or apply approved bounded repairs",
    )
    lifecycle.add_argument("--tenant-id")
    lifecycle.add_argument("--repair", action="store_true")
    lifecycle.add_argument("--confirm")
    retention = subparsers.add_parser(
        "run-document-retention",
        help="Report approved retention candidates or execute approved bounded retention",
    )
    retention.add_argument("--tenant-id")
    retention.add_argument("--execute", action="store_true")
    retention.add_argument("--confirm")
    recovery = subparsers.add_parser(
        "recover-document-deletions",
        help="Republish bounded pending or stale document cleanup dispatches",
    )
    recovery.add_argument("--tenant-id")
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
        if args.command in {"backfill-document-workflows", "reconcile-document-uploads",
                             "reconcile-document-workflow-dispatches"}:
            asyncio.run(document_workflow_maintenance(args))
        elif args.command == "create-admin":
            asyncio.run(create_admin(args))
        elif args.command == "cleanup-password-reset-tokens":
            asyncio.run(cleanup_reset_tokens())
        elif args.command == "cleanup-tenant-invitations":
            asyncio.run(cleanup_invitations())
        elif args.command == "run-maintenance":
            asyncio.run(execute_maintenance())
        elif args.command == "check-production-config":
            check_production_config()
        elif args.command == "check-ingestion-worker-readiness":
            asyncio.run(check_ingestion_worker_readiness())
        elif args.command == "reconcile-document-ingestion":
            asyncio.run(reconcile_document_ingestion())
        elif args.command == "reconcile-document-lifecycle":
            asyncio.run(reconcile_document_lifecycle_command(args))
        elif args.command == "run-document-retention":
            asyncio.run(run_document_retention_command(args))
        elif args.command == "recover-document-deletions":
            asyncio.run(recover_document_deletions_command(args))
        elif args.command == "revoke-user-sessions":
            asyncio.run(revoke_user_sessions(args))
        elif args.command == "revoke-all-sessions":
            asyncio.run(revoke_every_session(args))
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
