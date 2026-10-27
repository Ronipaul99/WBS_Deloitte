import hashlib
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import (
    Document,
    DocumentProcessingRun,
    Job,
    Tenant,
    TenantMembership,
    WbsVersion,
)
from tests.test_workflow import _seed_ready_ingestion

CSV = b"Task,Description\n1,Build the application\n"


@pytest.fixture
async def workspace(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "document_workflow_resume_enabled", True)
    monkeypatch.setattr(settings, "document_upload_reuse_enabled", True)
    tenant_id = uuid4()
    async with SessionLocal() as db:
        db.add(Tenant(id=tenant_id, name="Content test", slug=f"content-{tenant_id}"))
        await db.flush()
        db.add(TenantMembership(tenant_id=tenant_id, user_id=settings.dev_user_id, role="ADMIN"))
        await db.commit()
    yield str(tenant_id)
    async with SessionLocal() as db:
        await db.execute(delete(TenantMembership).where(TenantMembership.tenant_id == tenant_id))
        await db.commit()


def project(client, tenant):
    response = client.post(f"/api/v1/tenants/{tenant}/projects", json={"name": "Document project"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, tenant, project_id, *, name="scope.csv", content=CSV, headers=None, **fields):
    return client.post(
        f"/api/v1/tenants/{tenant}/document-workflows/uploads",
        data={"project_id": project_id, **fields},
        files={"file": (name, content, "text/csv")},
        headers=headers or {},
    )


def get_state(client, tenant, workflow):
    result = client.get(f"/api/v1/tenants/{tenant}/document-workflows/{workflow}")
    assert result.status_code == 200, result.text
    return result.json()


async def test_same_bytes_and_renamed_file_reuse_without_writing_another_object(client, workspace):
    p = project(client, workspace)
    first = upload(client, workspace, p)
    assert first.status_code == 201, first.text
    original = first.json()["workflow"]
    for filename in ["scope.csv", "renamed.csv"]:
        result = upload(client, workspace, p, name=filename)
        assert result.status_code == 200, result.text
        assert result.json()["disposition"] == "REUSED"
        assert result.json()["workflow"]["document_id"] == original["document_id"]
    async with SessionLocal() as db:
        documents = list(
            await db.scalars(
                select(Document).where(
                    Document.tenant_id == UUID(workspace),
                )
            )
        )
        assert len(documents) == 1
        assert documents[0].upload_sha256 == hashlib.sha256(CSV).hexdigest()
        assert (
            len(
                list(
                    await db.scalars(
                        select(DocumentWorkflow).where(
                            DocumentWorkflow.tenant_id == UUID(workspace),
                        )
                    )
                )
            )
            == 1
        )


def test_same_name_different_content_creates_another_document(client, workspace):
    p = project(client, workspace)
    first = upload(client, workspace, p).json()["workflow"]
    changed = upload(client, workspace, p, content=CSV + b"2,Another task\n")
    assert changed.status_code == 201, changed.text
    assert changed.json()["workflow"]["document_id"] != first["document_id"]


async def test_resolve_is_read_only_and_cross_project_upload_requires_switch(client, workspace):
    p = project(client, workspace)
    original = upload(client, workspace, p).json()["workflow"]
    other = project(client, workspace)
    resolved = client.post(
        f"/api/v1/tenants/{workspace}/document-workflows/resolve",
        json={
            "sha256": hashlib.sha256(CSV).hexdigest(),
            "size_bytes": len(CSV),
            "selected_project_id": other,
        },
    )
    assert resolved.status_code == 200, resolved.text
    candidate = resolved.json()["candidates"][0]
    assert candidate["requires_project_switch"] is True
    assert candidate["document_id"] == original["document_id"]
    blocked = upload(client, workspace, other)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "EXISTING_DOCUMENT_IN_OTHER_PROJECT"
    # Bypassing the new route must not publish another document either.
    legacy = client.post(
        f"/api/v1/tenants/{workspace}/projects/{other}/documents",
        files={"file": ("duplicate.csv", CSV, "text/csv")},
    )
    assert legacy.status_code == 409, legacy.text
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.tenant_id == UUID(workspace),
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.tenant_id == UUID(workspace),
                )
            )
            == 1
        )


def test_server_rejects_forged_hash_and_idempotency_key_reuse(client, workspace):
    p = project(client, workspace)
    rejected = upload(client, workspace, p, sha256="0" * 64)
    assert rejected.status_code == 422, rejected.text
    key = {"Idempotency-Key": "test-upload-request"}
    first = upload(client, workspace, p, headers=key)
    assert first.status_code == 201, first.text
    retried = upload(client, workspace, p, headers=key)
    assert retried.status_code == 200, retried.text
    assert retried.json()["workflow"]["document_id"] == first.json()["workflow"]["document_id"]
    changed = upload(client, workspace, p, headers=key, content=CSV + b"2,Changed\n")
    assert changed.status_code == 409, changed.text
    assert changed.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def ready_ingestion(document_id):
    await _seed_ready_ingestion(UUID(document_id))
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(document_id))
        run = await db.get(DocumentProcessingRun, document.current_processing_run_id)
        document.content_sha256 = document.upload_sha256
        run.document_content_sha256 = document.upload_sha256
        run.extractor_name, run.extractor_version = "python-csv", "1.0.0"
        run.chunker_version = "1.1.0"
        settings = get_settings()
        for key in (
            "embedding_provider",
            "embedding_model",
            "embedding_model_revision",
            "embedding_dimensions",
            "embedding_formatting_version",
        ):
            setattr(run, key, getattr(settings, key))
        await db.commit()


async def test_resume_exact_wbs_and_saved_edits_and_stale_validation(client, workspace):
    p = project(client, workspace)
    created = upload(client, workspace, p).json()["workflow"]
    workflow_id, document_id = created["workflow_id"], created["document_id"]
    await ready_ingestion(document_id)
    base = f"/api/v1/tenants/{workspace}"
    assert get_state(client, workspace, workflow_id)["stage"] == "INGESTED"
    summary = client.post(f"{base}/documents/{document_id}/summary?workflow_id={workflow_id}")
    assert summary.status_code == 202, summary.text
    state = get_state(client, workspace, workflow_id)
    assert state["stage"] == "SUMMARY_REVIEW"
    saved = client.patch(
        f"{base}/documents/{document_id}/summary",
        json={"summary_text": "Persisted user scope edit"},
    )
    assert saved.status_code == 200
    assert client.post(f"{base}/documents/{document_id}/summary/approve").status_code == 200
    generation_input = {
        "document_id": document_id,
        "summary_id": state["summary_id"],
        "workflow_id": workflow_id,
    }
    generated = client.post(f"{base}/projects/{p}/generations", json=generation_input)
    assert generated.status_code == 202, generated.text
    state = get_state(client, workspace, workflow_id)
    assert state["stage"] == "WBS_READY"
    version = state["wbs_version_id"]
    # Repeating the same start must attach to the same completed attempt.
    repeated = client.post(f"{base}/projects/{p}/generations", json=generation_input)
    assert repeated.json()["id"] == generated.json()["id"]
    tree = [{"id": "saved", "code": "1", "name": "Saved WBS edit", "children": []}]
    assert client.put(f"{base}/wbs/{version}", json={"tree": tree}).status_code == 200
    validation = client.post(f"{base}/wbs/{version}/validations")
    assert validation.status_code == 202, validation.text
    assert get_state(client, workspace, workflow_id)["stage"] == "VALIDATED"
    # Unrelated project output must never replace this document's result.
    async with SessionLocal() as db:
        db.add(
            WbsVersion(
                tenant_id=UUID(workspace),
                project_id=UUID(p),
                version_number=999,
                tree=[{"name": "Unrelated"}],
            )
        )
        await db.commit()
        before = await db.scalar(select(func.count()).select_from(Job))
    for _ in range(3):
        resumed = get_state(client, workspace, workflow_id)
        assert resumed["wbs_version_id"] == version
    assert client.get(f"{base}/wbs/{version}").json()["tree"] == tree
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Job)) == before
    assert client.put(f"{base}/wbs/{version}", json={"tree": []}).status_code == 200
    resumed = get_state(client, workspace, workflow_id)
    assert resumed["validation_stale"] is True
    assert resumed["stage"] == "WBS_READY"


def test_other_tenant_cannot_read_or_discover_workflow(client, workspace):
    p = project(client, workspace)
    original = upload(client, workspace, p).json()["workflow"]
    default_tenant = str(get_settings().dev_tenant_id)
    other_p = project(client, default_tenant)
    denied = client.get(
        f"/api/v1/tenants/{default_tenant}/document-workflows/" + original["workflow_id"]
    )
    assert denied.status_code == 404
    resolved = client.post(
        f"/api/v1/tenants/{default_tenant}/document-workflows/resolve",
        json={
            "sha256": hashlib.sha256(CSV).hexdigest(),
            "size_bytes": len(CSV),
            "selected_project_id": other_p,
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["candidates"] == []
