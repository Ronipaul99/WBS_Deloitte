from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document_workflows import DocumentContentClaim, WorkflowDispatch
from app.models.domain import Document, DocumentProcessingRun, Job, TenantMembership
from app.services.document_content import record_content_rejection
from app.services.document_lifecycle import process_document_deletion, request_document_deletion
from app.services.document_workflow_dispatch import reconcile_dispatches
from app.services.storage import LocalObjectStorage
from tests.test_document_deduplication_api import (
    get_state,
    project,
    ready_ingestion,
    upload,
)
from tests.test_document_deduplication_api import workspace as workspace


async def test_explicit_regeneration_is_idempotent_and_preserves_saved_output(client, workspace):
    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    doc, wf = state["document_id"], state["workflow_id"]
    await ready_ingestion(doc)
    base = f"/api/v1/tenants/{workspace}"
    assert client.post(f"{base}/documents/{doc}/summary?workflow_id={wf}").status_code == 202
    assert client.post(f"{base}/documents/{doc}/summary/approve").status_code == 200
    state = get_state(client, workspace, wf)
    payload = {"document_id": doc, "summary_id": state["summary_id"], "workflow_id": wf}
    first = client.post(f"{base}/projects/{p}/generations", json=payload)
    assert first.status_code == 202, first.text
    original = get_state(client, workspace, wf)
    assert (
        client.patch(
            f"{base}/documents/{doc}/summary", json={"summary_text": "Saved change"}
        ).status_code
        == 200
    )
    assert client.post(f"{base}/documents/{doc}/summary/approve").status_code == 200
    assert get_state(client, workspace, wf)["input_compatibility"] == "CHANGED"
    blocked = client.post(f"{base}/projects/{p}/generations", json=payload)
    assert blocked.status_code == 409
    payload.update(regenerate=True, request_key=str(uuid4()))
    newer = client.post(f"{base}/projects/{p}/generations", json=payload)
    assert newer.status_code == 202, newer.text
    replay = client.post(f"{base}/projects/{p}/generations", json=payload)
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == newer.json()["id"] != first.json()["id"]
    assert newer.json()["workflow_id"] != wf
    assert get_state(client, workspace, wf)["wbs_version_id"] == original["wbs_version_id"]
    assert get_state(client, workspace, newer.json()["workflow_id"])["stage"] == "WBS_READY"


async def test_stale_ingestion_and_newer_failure_resume_without_dispatch(client, workspace):
    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    doc, wf = state["document_id"], state["workflow_id"]
    await ready_ingestion(doc)
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(doc))
        run = await db.get(DocumentProcessingRun, document.current_processing_run_id)
        run.chunker_version = "outdated"
        await db.commit()
    stale = get_state(client, workspace, wf)
    assert stale["source_requires_processing"] is True
    assert stale["stage"] == "DOCUMENT_READY" and "start_ingestion" in stale["allowed_actions"]
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(doc))
        job = Job(
            tenant_id=UUID(workspace),
            project_id=UUID(p),
            job_type="DOCUMENT_INGESTION",
            created_by=document.uploaded_by,
            status="FAILED",
            request_payload={"document_id": doc},
        )
        db.add(job)
        await db.flush()
        failed = DocumentProcessingRun(
            tenant_id=UUID(workspace),
            project_id=UUID(p),
            document_id=UUID(doc),
            job_id=job.id,
            status="FAILED",
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
        db.add(failed)
        await db.commit()
        failed_id = str(failed.id)
        before = await db.scalar(select(func.count()).select_from(Job))
    for _ in range(2):
        state = get_state(client, workspace, wf)
        assert state["stage"] == "FAILED" and state["failed_stage"] == "ingestion"
        assert state["processing_run_id"] == failed_id
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Job)) == before


async def test_failed_publication_remains_durable_and_reconciliation_is_idempotent(
    client,
    workspace,
    monkeypatch,
):
    from app.services.dispatcher import dispatch_app

    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    doc, wf = state["document_id"], state["workflow_id"]
    await ready_ingestion(doc)
    monkeypatch.setattr(get_settings(), "tasks_eager", False)

    def offline(*args, **kwargs):
        raise ConnectionError("Test broker offline")

    monkeypatch.setattr(dispatch_app, "send_task", offline)
    response = client.post(f"/api/v1/tenants/{workspace}/documents/{doc}/summary?workflow_id={wf}")
    assert response.status_code == 202, response.text
    assert get_state(client, workspace, wf)["stage"] == "SUMMARIZING"
    async with SessionLocal() as db:
        record = await db.scalar(
            select(WorkflowDispatch).where(WorkflowDispatch.workflow_id == UUID(wf))
        )
        assert record.status == "PENDING" and record.attempts == 1
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    dry = await reconcile_dispatches(UUID(workspace))
    assert dry["eligible"] == 1 and dry["published"] == 0
    monkeypatch.setattr(get_settings(), "tasks_eager", True)
    applied = await reconcile_dispatches(UUID(workspace), apply=True)
    assert applied["published"] == 1
    assert get_state(client, workspace, wf)["stage"] == "SUMMARY_REVIEW"
    assert (await reconcile_dispatches(UUID(workspace), apply=True))["eligible"] == 0


async def test_known_threat_is_not_reuploaded_after_tombstone(client, workspace):
    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(state["document_id"]))
        await record_content_rejection(db, document, "DOCUMENT_REJECTED_MALWARE")
        job, _ = await request_document_deletion(
            db,
            tenant_id=UUID(workspace),
            document_id=document.id,
            requested_by=document.uploaded_by,
        )
        await db.commit()
        job_id, document_id, sha256 = job.id, document.id, document.upload_sha256
        claim = await db.get(DocumentContentClaim, (UUID(workspace), sha256))
        assert claim.state == "DELETING"
    result = await process_document_deletion(
        job_id, document_id, storage=LocalObjectStorage(get_settings()), settings=get_settings()
    )
    assert result.disposition == "COMPLETED"
    async with SessionLocal() as db:
        assert await db.get(DocumentContentClaim, (UUID(workspace), sha256)) is None
    rejected = upload(client, workspace, p, name="renamed-threat.csv")
    assert rejected.status_code == 409, rejected.text


async def test_viewer_can_resume_but_cannot_upload_or_fork(client, workspace):
    p = project(client, workspace)
    state = upload(client, workspace, p).json()["workflow"]
    async with SessionLocal() as db:
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == UUID(workspace),
                TenantMembership.user_id == get_settings().dev_user_id,
            )
        )
        membership.role = "VIEWER"
        await db.commit()
    resumed = get_state(client, workspace, state["workflow_id"])
    assert resumed["allowed_actions"] == []
    assert upload(client, workspace, p).status_code == 403
    assert (
        client.post(
            f"/api/v1/tenants/{workspace}/document-workflows/{state['workflow_id']}/fork", json={}
        ).status_code
        == 403
    )
