"""Run with --noconftest -p tests.upload_transaction_support; synthetic data only."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.permissions import permissions_for_role
from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.document_workflows import DocumentContentClaim, DocumentUploadAttempt
from app.models.domain import Document, Tenant, User
from app.services import document_content
from app.services.document_lifecycle import process_document_deletion
from app.services.storage import LocalObjectStorage, ObjectStorageUnavailableError, PreparedUpload
from tests.test_document_deduplication_api import CSV, get_state, project, upload
from tests.test_document_deduplication_api import workspace as workspace


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_upload_preflight(client, origin):
    response = client.options(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/document-workflows/uploads",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize(
    ("origin", "header"),
    [
        ("https://foreign.example", "idempotency-key"),
        ("http://localhost:5173", "idempotency-key,x-unapproved"),
    ],
)
def test_preflight_rejects_unapproved_inputs(client, origin, header):
    response = client.options(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000001/document-workflows/uploads",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": header,
        },
    )
    assert response.status_code == 400


async def test_begin_join_commit_rollback_preserves_caller_transaction():
    async with SessionLocal() as db:
        for finish in (db.commit, db.rollback):
            await ensure_tenant_transaction(db, UUID(int=1))
            transaction = db.get_transaction()
            await ensure_tenant_transaction(db, UUID(int=1))
            assert db.get_transaction() is transaction
            await finish()
            assert not db.in_transaction()
        with pytest.raises(ValueError):
            await ensure_tenant_transaction(db, "invalid")
        assert not db.in_transaction()


async def test_postgres_guard_remains_strict_and_scope_is_transaction_local(monkeypatch):
    from tests.upload_transaction_support import _original_scope

    async with SessionLocal() as db:
        # No PostgreSQL connection: inspect the production guard's SQL only.
        monkeypatch.setattr(
            db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        )
        execute = AsyncMock()
        monkeypatch.setattr(db, "execute", execute)
        with pytest.raises(RuntimeError, match="active database transaction"):
            await _original_scope(db, UUID(int=1))
        execute.assert_not_awaited()
        await ensure_tenant_transaction(db, UUID(int=1))
        assert str(execute.call_args.args[0]) == f"SET LOCAL app.tenant_id = '{UUID(int=1)}'"
        await db.commit()
        assert not db.in_transaction()
        with pytest.raises(RuntimeError, match="active database transaction"):
            await _original_scope(db, UUID(int=1))


async def test_upload_delete_pending_completed_reupload_and_old_delivery(
    client, workspace, monkeypatch
):
    from app.api.routes import documents

    p = project(client, workspace)
    key = {"Idempotency-Key": "first-lifecycle-upload"}
    first = upload(client, workspace, p, headers=key)
    assert first.status_code == 201, first.text
    original = first.json()["workflow"]
    doc_id = UUID(original["document_id"])
    storage = LocalObjectStorage(get_settings())
    async with SessionLocal() as db:
        document = await db.get(Document, doc_id)
        old_key = document.storage_key
        assert (storage.root / old_key).read_bytes() == CSV
        assert document.upload_sha256 == hashlib.sha256(CSV).hexdigest()
        attempt = await db.scalar(
            select(DocumentUploadAttempt).where(DocumentUploadAttempt.document_id == doc_id)
        )
        assert attempt.state == "COMMITTED"

    async def deferred(*args, **kwargs):
        return None  # Execute the real deletion processor explicitly below.

    monkeypatch.setattr(documents, "publish_deletion_dispatch", deferred)
    base = f"/api/v1/tenants/{workspace}"
    deleted = client.delete(f"{base}/documents/{doc_id}")
    assert deleted.status_code == 202, deleted.text
    job_id = UUID(deleted.json()["id"])
    assert upload(client, workspace, p).status_code == 409
    result = await process_document_deletion(job_id, doc_id, storage=storage)
    assert result.disposition == "COMPLETED"
    status = client.get(f"{base}/documents/{doc_id}/deletion")
    assert status.status_code == 200 and status.json()["lifecycle_status"] == "DELETED"
    assert not (storage.root / old_key).exists()
    assert upload(client, workspace, p, headers=key).status_code == 410
    replacement = upload(client, workspace, p, headers={"Idempotency-Key": "replacement"})
    assert replacement.status_code == 201, replacement.text
    new = replacement.json()["workflow"]
    assert new["document_id"] != str(doc_id)
    get_state(client, workspace, new["workflow_id"])
    duplicate = await process_document_deletion(job_id, doc_id, storage=storage)
    assert duplicate.disposition in {"DUPLICATE", "COMPLETED"}
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(new["document_id"]))
        claim = await db.get(DocumentContentClaim, (UUID(workspace), document.upload_sha256))
        assert claim.document_id == document.id and claim.state == "READY"
        assert (storage.root / document.storage_key).read_bytes() == CSV


async def test_response_failure_after_commit_reuses_document(client, workspace, monkeypatch):
    from app.api.routes import document_workflows

    p = project(client, workspace)
    original = document_workflows.resume_state

    async def fail_response(*args, **kwargs):
        raise ValueError("Synthetic response failure")

    monkeypatch.setattr(document_workflows, "resume_state", fail_response)
    key = {"Idempotency-Key": "response-failure"}
    with pytest.raises(ValueError, match="Synthetic response failure"):
        upload(client, workspace, p, headers=key)
    monkeypatch.setattr(document_workflows, "resume_state", original)
    retry = upload(client, workspace, p, headers=key)
    assert retry.status_code == 200, retry.text
    async with SessionLocal() as db:
        docs = list(await db.scalars(select(Document).where(Document.tenant_id == UUID(workspace))))
        assert len(docs) == 1
        attempts = list(
            await db.scalars(
                select(DocumentUploadAttempt).where(
                    DocumentUploadAttempt.tenant_id == UUID(workspace)
                )
            )
        )
        assert len(attempts) == 1 and attempts[0].state == "COMMITTED"


def test_cleanup_failure_preserves_primary_error(client, workspace, monkeypatch, caplog):
    p = project(client, workspace)

    async def fail_save(*args, **kwargs):
        raise ObjectStorageUnavailableError("private synthetic provider message")

    async def fail_cleanup(*args, **kwargs):
        raise RuntimeError("private synthetic cleanup message")

    monkeypatch.setattr(LocalObjectStorage, "save", fail_save)
    monkeypatch.setattr(document_content, "_abandon", fail_cleanup)
    response = upload(client, workspace, p)
    assert response.status_code == 503
    assert "ownership reconciliation required" in caplog.text
    assert "private synthetic" not in response.text + caplog.text


async def test_committed_attempt_is_never_abandoned(client, workspace):
    p = project(client, workspace)
    created = upload(client, workspace, p).json()["workflow"]
    storage = LocalObjectStorage(get_settings())
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(created["document_id"]))
        attempt = await db.scalar(
            select(DocumentUploadAttempt).where(DocumentUploadAttempt.document_id == document.id)
        )
        storage_key = document.storage_key
        await document_content._abandon(
            db,
            storage,
            UUID(workspace),
            PreparedUpload(document.upload_sha256, document.size_bytes, document.storage_key),
            attempt.id,
        )
        assert not db.in_transaction()
        assert (storage.root / storage_key).exists()


async def test_workflow_mutations_render_after_commit(client, workspace):
    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    base = f"/api/v1/tenants/{workspace}/document-workflows/{state['workflow_id']}"
    changed = client.patch(
        base + "/template",
        json={"template_id": None, "expected_revision": state["checkpoint_revision"]},
    )
    assert changed.status_code == 200, changed.text
    fork = client.post(
        base + "/fork",
        json={"template_id": None, "expected_revision": changed.json()["checkpoint_revision"]},
    )
    assert fork.status_code == 201, fork.text


@pytest.mark.parametrize("mode", ["heartbeat_error", "cancel"])
async def test_heartbeat_failure_and_cancellation_do_not_publish(
    client, workspace, monkeypatch, mode
):
    p = project(client, workspace)
    async with SessionLocal() as db:
        tenant = await db.get(Tenant, UUID(workspace))
        user = await db.get(User, get_settings().dev_user_id)
    context = SimpleNamespace(tenant=tenant, user=user, permissions=permissions_for_role("ADMIN"))
    entered = asyncio.Event()
    storage = LocalObjectStorage(get_settings())
    save = storage.save

    async def interrupted_save(*args, **kwargs):
        assert not db.in_transaction(), "Request transaction must end before storage I/O"
        result = await save(*args, **kwargs)
        entered.set()
        if mode == "cancel":
            await asyncio.Event().wait()
        await asyncio.sleep(0.01)
        return result

    async def fail_heartbeat(*args):
        raise RuntimeError("synthetic private heartbeat error")

    monkeypatch.setattr(storage, "save", interrupted_save)
    if mode == "heartbeat_error":
        monkeypatch.setattr(document_content, "_renew", fail_heartbeat)
    async with SessionLocal() as db:
        file = UploadFile(BytesIO(CSV), filename="scope.csv")
        task = asyncio.create_task(
            document_content.upload_or_reuse(
                db,
                context=context,
                project_id=UUID(p),
                file=file,
                suffix=".csv",
                content_type="text/csv",
                storage=storage,
                settings=get_settings(),
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.detail["code"] == "UPLOAD_LEASE_LOST"
    async with SessionLocal() as db:
        assert (
            list(await db.scalars(select(Document).where(Document.tenant_id == UUID(workspace))))
            == []
        )
        attempts = list(
            await db.scalars(
                select(DocumentUploadAttempt).where(
                    DocumentUploadAttempt.tenant_id == UUID(workspace)
                )
            )
        )
        assert len(attempts) == 1 and attempts[0].state == "CLEANED"


async def test_fresh_session_heartbeat_extends_lease_then_stops_on_expiry(
    client, workspace, monkeypatch
):
    from tests.test_document_content_claims import seed_reservation

    p = project(client, workspace)
    token, _ = await seed_reservation(workspace, p, expired=False)
    tenant_id, sha = UUID(workspace), hashlib.sha256(CSV).hexdigest()
    before = datetime.now(UTC)
    sleep = asyncio.sleep
    rounds = 0

    async def next_round(_):
        nonlocal rounds
        await sleep(0)
        rounds += 1
        if rounds == 2:
            async with SessionLocal() as db:
                claim = await db.get(DocumentContentClaim, (tenant_id, sha))
                expiry = document_content.utc(claim.lease_expires_at)
                assert expiry > before + timedelta(seconds=250)
                claim.lease_expires_at = before - timedelta(seconds=1)
                await db.commit()

    monkeypatch.setattr(document_content.asyncio, "sleep", next_round)
    await asyncio.wait_for(document_content._renew(SessionLocal, tenant_id, sha, token, 300), 5)
    assert rounds == 2


async def test_backfill_uses_fresh_scoped_transactions(client, workspace):
    from app.services.document_workflow_backfill import backfill_workflows

    p = project(client, workspace)
    assert upload(client, workspace, p).status_code == 201
    result = await backfill_workflows(
        tenant_id=UUID(workspace),
        storage=LocalObjectStorage(get_settings()),
        settings=get_settings(),
        apply=True,
    )
    assert result["verified"] == 1 and result["remaining_unverified"] == 0


async def test_ambiguous_commit_does_not_remove_committed_upload(client, workspace, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    p = project(client, workspace)
    commit = AsyncSession.commit
    fired = False

    async def commit_then_fail(db):
        nonlocal fired
        publishing = any(isinstance(obj, Document) for obj in db.identity_map.values())
        await commit(db)
        if publishing and not fired:
            fired = True
            raise RuntimeError("Synthetic acknowledgment loss after commit")

    monkeypatch.setattr(AsyncSession, "commit", commit_then_fail)
    key = {"Idempotency-Key": "ambiguous-commit"}
    with pytest.raises(RuntimeError, match="acknowledgment loss"):
        upload(client, workspace, p, headers=key)
    assert fired
    monkeypatch.setattr(AsyncSession, "commit", commit)
    retry = upload(client, workspace, p, headers=key)
    assert retry.status_code == 200
    async with SessionLocal() as db:
        docs = list(await db.scalars(select(Document).where(Document.tenant_id == UUID(workspace))))
        assert len(docs) == 1
        assert (LocalObjectStorage(get_settings()).root / docs[0].storage_key).read_bytes() == CSV


async def test_conflict_rollback_uses_trusted_scalar_scope(client, workspace, monkeypatch):
    from app.schemas.document_workflows import ResolveResponse
    from tests.test_document_content_claims import seed_reservation

    p = project(client, workspace)
    winner, _ = await seed_reservation(workspace, p, expired=False)
    original_resolve = document_content.resolve_content
    calls = 0

    async def raced_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ResolveResponse(disposition="NEW")
        return await original_resolve(*args, **kwargs)

    monkeypatch.setattr(document_content, "resolve_content", raced_lookup)
    response = upload(client, workspace, p)
    assert response.status_code == 202, response.text
    assert response.json()["upload_handle"] == str(winner)
    assert calls == 2
