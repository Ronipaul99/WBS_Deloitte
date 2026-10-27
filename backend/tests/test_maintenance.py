import os
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.auth import AuthEvent, PasswordResetToken, RefreshSession, TenantInvitation
from app.models.domain import ExportFile, Job, ProcessingStatus, Project, User, WbsVersion
from app.services.auth import utc_now
from app.services.maintenance import MaintenanceSafetyError, run_maintenance


async def test_maintenance_is_idempotent_and_preserves_recent_records(client, tenant_id):
    settings = get_settings()
    now = utc_now()
    old = now - timedelta(days=400)
    tenant_uuid = UUID(tenant_id)

    async with SessionLocal() as db:
        user_id = await db.scalar(select(Project.created_by).limit(1))
        if user_id is None:
            user_id = await db.scalar(select(User.id).limit(1))

        project = Project(
            tenant_id=tenant_uuid,
            created_by=user_id,
            name="Maintenance test",
        )
        db.add(project)
        await db.flush()
        job = Job(
            tenant_id=tenant_uuid,
            project_id=project.id,
            created_by=user_id,
            job_type="WBS_GENERATION",
            status=ProcessingStatus.COMPLETED.value,
        )
        db.add(job)
        await db.flush()
        version = WbsVersion(
            tenant_id=tenant_uuid,
            project_id=project.id,
            generation_job_id=job.id,
            version_number=1,
        )
        db.add(version)
        await db.flush()

        storage_key = f"{tenant_id}/exports/stale/export.csv"
        export_path = settings.upload_root.resolve() / storage_key
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("stale", encoding="utf-8")
        stale_export = ExportFile(
            tenant_id=tenant_uuid,
            project_id=project.id,
            wbs_version_id=version.id,
            format="csv",
            status=ProcessingStatus.FAILED.value,
            file_name="export.csv",
            storage_key=storage_key,
            created_at=old,
            updated_at=old,
        )
        recent_event = AuthEvent(
            user_id=user_id,
            event_type="maintenance_recent",
            success=True,
            created_at=now,
        )
        stale_event = AuthEvent(
            user_id=user_id,
            event_type="maintenance_stale",
            success=True,
            created_at=old,
        )
        db.add_all(
            [
                RefreshSession(
                    user_id=user_id,
                    family_id=project.id,
                    token_hash="1" * 64,
                    expires_at=old,
                    created_at=old,
                    updated_at=old,
                ),
                PasswordResetToken(
                    user_id=user_id,
                    token_hash="2" * 64,
                    expires_at=old,
                    created_at=old,
                ),
                TenantInvitation(
                    tenant_id=tenant_uuid,
                    email="stale@example.com",
                    role="VIEWER",
                    token_hash="3" * 64,
                    invited_by_user_id=user_id,
                    expires_at=old,
                    created_at=old,
                    updated_at=old,
                ),
                stale_event,
                recent_event,
                stale_export,
            ]
        )
        await db.commit()

        temporary_path = settings.upload_root.resolve() / str(tenant_id) / "temp" / "stale.part"
        temporary_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text("partial", encoding="utf-8")
        old_timestamp = old.timestamp()
        os.utime(temporary_path, (old_timestamp, old_timestamp))

        first = await run_maintenance(db, settings, now=now)
        second = await run_maintenance(db, settings, now=now)
        preserved = await db.scalar(
            select(AuthEvent).where(AuthEvent.event_type == "maintenance_recent")
        )
        cleaned_export = await db.get(ExportFile, stale_export.id)

    assert first.refresh_sessions == 1
    assert first.password_reset_tokens == 1
    assert first.tenant_invitations == 1
    assert first.auth_events >= 1
    assert first.failed_export_files == 1
    assert first.temporary_files == 1
    assert second.as_dict() == {
        "refresh_sessions": 0,
        "password_reset_tokens": 0,
        "tenant_invitations": 0,
        "oidc_authorization_states": 0,
        "auth_events": 0,
        "failed_export_files": 0,
        "temporary_files": 0,
    }
    assert preserved is not None
    assert cleaned_export is not None and cleaned_export.storage_key is None
    assert not export_path.exists()
    assert not temporary_path.exists()


async def test_maintenance_processes_large_retention_sets_in_batches(client):
    settings = get_settings().model_copy(update={"maintenance_batch_size": 100})
    now = utc_now()
    old = now - timedelta(days=400)

    async with SessionLocal() as db:
        db.add_all(
            [
                AuthEvent(
                    event_type="stale_batch_event",
                    success=False,
                    created_at=old,
                )
                for _ in range(205)
            ]
        )
        await db.commit()

        result = await run_maintenance(db, settings, now=now)
        remaining = await db.scalar(
            select(AuthEvent).where(AuthEvent.event_type == "stale_batch_event").limit(1)
        )

    assert result.auth_events == 205
    assert remaining is None


async def test_maintenance_fails_closed_for_cross_tenant_export_key(client, tenant_id):
    settings = get_settings()
    now = utc_now()
    old = now - timedelta(days=2)
    tenant_uuid = UUID(tenant_id)

    async with SessionLocal() as db:
        user_id = await db.scalar(select(User.id).limit(1))
        project = Project(tenant_id=tenant_uuid, created_by=user_id, name="Safety test")
        db.add(project)
        await db.flush()
        version = WbsVersion(
            tenant_id=tenant_uuid,
            project_id=project.id,
            version_number=1,
        )
        db.add(version)
        await db.flush()
        db.add(
            ExportFile(
                tenant_id=tenant_uuid,
                project_id=project.id,
                wbs_version_id=version.id,
                format="csv",
                status=ProcessingStatus.FAILED.value,
                file_name="unsafe.csv",
                storage_key="00000000-0000-0000-0000-000000000099/exports/unsafe.csv",
                created_at=old,
                updated_at=old,
            )
        )
        await db.commit()

        with pytest.raises(MaintenanceSafetyError, match="tenant boundary"):
            await run_maintenance(db, settings, now=now)
