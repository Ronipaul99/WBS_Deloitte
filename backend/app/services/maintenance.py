import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.observability import MAINTENANCE_RUNS
from app.models.auth import (
    AuthEvent,
    OidcAuthorizationState,
    PasswordResetToken,
    RefreshSession,
    TenantInvitation,
)
from app.models.domain import ExportFile, ProcessingStatus
from app.services.auth import utc_now
from app.services.storage import LocalObjectStorage

logger = logging.getLogger("uvicorn.error.wbs.maintenance")


class MaintenanceSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaintenanceResult:
    refresh_sessions: int = 0
    password_reset_tokens: int = 0
    tenant_invitations: int = 0
    oidc_authorization_states: int = 0
    auth_events: int = 0
    failed_export_files: int = 0
    temporary_files: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def _delete_in_batches(
    db: AsyncSession,
    model,
    where_clause,
    batch_size: int,
) -> int:
    total = 0
    while True:
        ids = list(await db.scalars(select(model.id).where(where_clause).limit(batch_size)))
        if not ids:
            return total
        result = await db.execute(delete(model).where(model.id.in_(ids)))
        await db.commit()
        total += result.rowcount or 0


async def _cleanup_failed_export_files(
    db: AsyncSession,
    storage: LocalObjectStorage,
    cutoff: datetime,
    batch_size: int,
) -> int:
    total = 0
    while True:
        exports = list(
            await db.scalars(
                select(ExportFile)
                .where(
                    ExportFile.status.in_(
                        [ProcessingStatus.FAILED.value, ProcessingStatus.CANCELLED.value]
                    ),
                    ExportFile.updated_at < cutoff,
                    ExportFile.storage_key.is_not(None),
                )
                .limit(batch_size)
            )
        )
        if not exports:
            return total

        cleaned_ids = []
        for export in exports:
            if not export.storage_key:
                continue
            parts = Path(export.storage_key).parts
            if not parts or parts[0] != str(export.tenant_id):
                logger.error(
                    "maintenance_rejected_cross_tenant_storage_key export_id=%s tenant_id=%s",
                    export.id,
                    export.tenant_id,
                )
                raise MaintenanceSafetyError(
                    "Failed export storage key violates the tenant boundary."
                )
            storage.delete(export.storage_key)
            cleaned_ids.append(export.id)

        if not cleaned_ids:
            return total
        await db.execute(
            update(ExportFile)
            .where(ExportFile.id.in_(cleaned_ids))
            .values(storage_key=None, file_name=None)
        )
        await db.commit()
        total += len(cleaned_ids)


def _cleanup_temporary_files(storage: LocalObjectStorage, cutoff: datetime) -> int:
    deleted = 0
    for pattern in ("*.part", "*.tmp"):
        for candidate in storage.root.rglob(pattern):
            try:
                if (
                    candidate.is_file()
                    and datetime.fromtimestamp(candidate.stat().st_mtime, tz=cutoff.tzinfo) < cutoff
                ):
                    candidate.unlink(missing_ok=True)
                    deleted += 1
            except FileNotFoundError:
                continue
    return deleted


async def run_maintenance(
    db: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> MaintenanceResult:
    current_time = now or utc_now()
    storage = LocalObjectStorage(settings)
    storage.root.mkdir(parents=True, exist_ok=True)

    try:
        refresh_cutoff = current_time - timedelta(days=settings.refresh_session_retention_days)
        reset_cutoff = current_time - timedelta(days=settings.password_reset_retention_days)
        invitation_cutoff = current_time - timedelta(days=settings.tenant_invitation_retention_days)
        oidc_state_cutoff = current_time - timedelta(days=settings.oidc_state_retention_days)
        event_cutoff = current_time - timedelta(days=settings.auth_event_retention_days)
        file_cutoff = current_time - timedelta(hours=settings.temporary_file_retention_hours)

        result = MaintenanceResult(
            refresh_sessions=await _delete_in_batches(
                db,
                RefreshSession,
                or_(
                    RefreshSession.expires_at < refresh_cutoff,
                    RefreshSession.revoked_at < refresh_cutoff,
                ),
                settings.maintenance_batch_size,
            ),
            password_reset_tokens=await _delete_in_batches(
                db,
                PasswordResetToken,
                or_(
                    PasswordResetToken.expires_at < reset_cutoff,
                    PasswordResetToken.used_at < reset_cutoff,
                ),
                settings.maintenance_batch_size,
            ),
            tenant_invitations=await _delete_in_batches(
                db,
                TenantInvitation,
                or_(
                    TenantInvitation.expires_at < invitation_cutoff,
                    TenantInvitation.accepted_at < invitation_cutoff,
                    TenantInvitation.revoked_at < invitation_cutoff,
                ),
                settings.maintenance_batch_size,
            ),
            oidc_authorization_states=await _delete_in_batches(
                db,
                OidcAuthorizationState,
                OidcAuthorizationState.expires_at < oidc_state_cutoff,
                settings.maintenance_batch_size,
            ),
            auth_events=await _delete_in_batches(
                db,
                AuthEvent,
                AuthEvent.created_at < event_cutoff,
                settings.maintenance_batch_size,
            ),
            failed_export_files=await _cleanup_failed_export_files(
                db, storage, file_cutoff, settings.maintenance_batch_size
            ),
            temporary_files=_cleanup_temporary_files(storage, file_cutoff),
        )
    except Exception:
        await db.rollback()
        MAINTENANCE_RUNS.labels(outcome="failure").inc()
        logger.exception("maintenance_failed")
        raise

    MAINTENANCE_RUNS.labels(outcome="success").inc()
    logger.info(
        "maintenance_completed refresh_sessions=%s password_reset_tokens=%s "
        "tenant_invitations=%s oidc_authorization_states=%s auth_events=%s "
        "failed_export_files=%s temporary_files=%s",
        *result.as_dict().values(),
    )
    return result
