import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document_workflows import DocumentContentClaim, DocumentUploadAttempt
from app.services.document_workflow_backfill import reconcile_uploads
from app.services.storage import LocalObjectStorage, ObjectStorageUnavailableError, _object_key
from tests.test_document_deduplication_api import CSV, project, upload
from tests.test_document_deduplication_api import workspace as workspace


async def seed_reservation(tenant, project_id, *, expired):
    token = uuid4()
    sha = hashlib.sha256(CSV).hexdigest()
    key = _object_key(UUID(tenant), "documents", ".csv", UUID(project_id))
    async with SessionLocal() as db:
        db.add(
            DocumentContentClaim(
                tenant_id=UUID(tenant),
                sha256=sha,
                size_bytes=len(CSV),
                state="RESERVED",
                owner_token=token,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=-10 if expired else 120),
                pending_storage_key=key,
            )
        )
        db.add(
            DocumentUploadAttempt(
                id=token,
                tenant_id=UUID(tenant),
                project_id=UUID(project_id),
                sha256=sha,
                storage_key=key,
                state="RESERVED",
            )
        )
        await db.commit()
    return token, key


async def test_live_reservation_returns_pending_without_calling_storage(
    client, workspace, monkeypatch
):
    p = project(client, workspace)
    token, _ = await seed_reservation(workspace, p, expired=False)

    async def must_not_save(*args, **kwargs):
        pytest.fail("A losing upload must not save an object")

    monkeypatch.setattr(LocalObjectStorage, "save", must_not_save)
    response = upload(client, workspace, p)
    assert response.status_code == 202, response.text
    assert response.json()["upload_handle"] == str(token)
    pending = client.get(f"/api/v1/tenants/{workspace}/document-workflows/uploads/{token}")
    assert pending.status_code == 202
    assert pending.headers["Retry-After"] == "2"


async def test_expired_owner_takeover_and_cleanup_preserve_winner_object(client, workspace):
    p = project(client, workspace)
    token, old_key = await seed_reservation(workspace, p, expired=True)
    storage = LocalObjectStorage(get_settings())
    old_path = storage.root / old_key
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(CSV)
    response = upload(client, workspace, p)
    assert response.status_code == 201, response.text
    async with SessionLocal() as db:
        old = await db.get(DocumentUploadAttempt, token)
        assert old.state == "ABANDONED"
        old.updated_at = datetime.now(UTC) - timedelta(hours=2)
        claim = await db.get(
            DocumentContentClaim, (UUID(workspace), hashlib.sha256(CSV).hexdigest())
        )
        assert claim.state == "READY" and claim.owner_token != token
        winner_key = claim.pending_storage_key
        await db.commit()
    dry = await reconcile_uploads(tenant_id=UUID(workspace), storage=storage)
    assert dry["eligible"] == 1 and dry["cleaned"] == 0
    assert old_path.exists()
    applied = await reconcile_uploads(tenant_id=UUID(workspace), storage=storage, apply=True)
    assert applied["cleaned"] == 1
    assert not old_path.exists()
    assert (storage.root / winner_key).exists()


async def test_late_owner_cannot_publish_or_remove_new_owners_claim(client, workspace, monkeypatch):
    p = project(client, workspace)
    original_save = LocalObjectStorage.save
    winner_token = uuid4()
    winner_key = _object_key(UUID(workspace), "documents", ".csv", UUID(p))
    own_keys = []

    async def lose_ownership(self, *args, **kwargs):
        result = await original_save(self, *args, **kwargs)
        own_keys.append(result[0])
        async with SessionLocal() as db:
            claim = await db.get(
                DocumentContentClaim, (UUID(workspace), hashlib.sha256(CSV).hexdigest())
            )
            claim.owner_token = winner_token
            claim.pending_storage_key = winner_key
            claim.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
            db.add(
                DocumentUploadAttempt(
                    id=winner_token,
                    tenant_id=UUID(workspace),
                    project_id=UUID(p),
                    sha256=claim.sha256,
                    storage_key=winner_key,
                    state="RESERVED",
                )
            )
            await db.commit()
        winner_path = self.root / winner_key
        winner_path.parent.mkdir(parents=True, exist_ok=True)
        winner_path.write_bytes(b"winner-owned-content")
        return result

    monkeypatch.setattr(LocalObjectStorage, "save", lose_ownership)
    response = upload(client, workspace, p)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_LEASE_LOST"
    storage = LocalObjectStorage(get_settings())
    assert not (storage.root / own_keys[0]).exists()
    assert (storage.root / winner_key).read_bytes() == b"winner-owned-content"
    async with SessionLocal() as db:
        claim = await db.get(
            DocumentContentClaim, (UUID(workspace), hashlib.sha256(CSV).hexdigest())
        )
        assert claim.owner_token == winner_token and claim.state == "RESERVED"


async def test_storage_failure_releases_claim_and_allows_retry(client, workspace, monkeypatch):
    p = project(client, workspace)
    save = LocalObjectStorage.save

    async def fail(self, *args, **kwargs):
        await save(self, *args, **kwargs)
        raise ObjectStorageUnavailableError("private storage details")

    monkeypatch.setattr(LocalObjectStorage, "save", fail)
    response = upload(client, workspace, p)
    assert response.status_code == 503, response.text
    assert "private storage" not in response.text
    async with SessionLocal() as db:
        assert (
            await db.get(DocumentContentClaim, (UUID(workspace), hashlib.sha256(CSV).hexdigest()))
            is None
        )
        attempt = await db.scalar(
            select(DocumentUploadAttempt).where(
                DocumentUploadAttempt.tenant_id == UUID(workspace),
            )
        )
        assert attempt.state == "CLEANED"
    monkeypatch.setattr(LocalObjectStorage, "save", save)
    assert upload(client, workspace, p).status_code == 201
