from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api import dependencies
from app.api.dependencies import (
    ensure_document_ingestion_ready,
)
from app.api.routes import documents as document_routes
from app.api.routes import ingestions as ingestion_routes
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.domain import (
    Document,
    DocumentProcessingRun,
    JobDispatchOutbox,
    MembershipRole,
    Project,
    Tenant,
    TenantMembership,
    User,
)
from app.services.readiness import IngestionReadinessError


async def _seed_document(user_id: UUID, tenant_id: UUID) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    async with SessionLocal() as db:
        project = Project(
            tenant_id=tenant_id,
            created_by=user_id,
            name=f"Ingestion project {suffix}",
        )
        db.add(project)
        await db.flush()
        document = Document(
            tenant_id=tenant_id,
            project_id=project.id,
            uploaded_by=user_id,
            kind="PROJECT",
            file_name="synthetic.pdf",
            content_type="application/pdf",
            size_bytes=32,
            storage_key=(f"tenants/{tenant_id}/projects/{project.id}/documents/{uuid4()}.pdf"),
        )
        db.add(document)
        await db.commit()
        return project.id, document.id


async def _seed_member(role: MembershipRole) -> tuple[str, UUID, UUID]:
    suffix = uuid4().hex
    tenant = Tenant(name=f"Ingestion {suffix}", slug=f"ingestion-{suffix}")
    user = User(
        external_subject=f"ingestion-{suffix}",
        email=f"ingestion-{suffix}@example.com",
        display_name="Ingestion User",
    )
    async with SessionLocal() as db:
        db.add_all([tenant, user])
        await db.flush()
        db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role.value))
        await db.commit()
    token, _ = create_access_token(user.id, uuid4(), user.auth_version, get_settings())
    return token, tenant.id, user.id


async def _counts(job_id: UUID) -> tuple[int, int, DocumentProcessingRun]:
    async with SessionLocal() as db:
        run = await db.scalar(
            select(DocumentProcessingRun).where(DocumentProcessingRun.job_id == job_id)
        )
        assert run is not None
        run_count = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentProcessingRun)
                .where(DocumentProcessingRun.job_id == job_id)
            )
            or 0
        )
        outbox_count = int(
            await db.scalar(
                select(func.count())
                .select_from(JobDispatchOutbox)
                .where(JobDispatchOutbox.job_id == job_id)
            )
            or 0
        )
        return run_count, outbox_count, run


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_ingestion_start_status_and_duplicate_are_safe_and_idempotent(client, monkeypatch):
    token, tenant_id, user_id = client.portal.call(_seed_member, MembershipRole.EDITOR)
    _, document_id = client.portal.call(_seed_document, user_id, tenant_id)
    published: list[tuple[UUID, UUID]] = []

    async def fake_publish(tenant: UUID, outbox: UUID):
        published.append((tenant, outbox))

    async def fake_delete_publish(_tenant: UUID, _outbox: UUID):
        return None

    client.app.dependency_overrides[ensure_document_ingestion_ready] = lambda: None
    monkeypatch.setattr(ingestion_routes, "publish_ingestion_dispatch", fake_publish)
    monkeypatch.setattr(document_routes, "publish_deletion_dispatch", fake_delete_publish)
    try:
        endpoint = f"/api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions"
        first = client.post(endpoint, headers=_headers(token))
        duplicate = client.post(endpoint, headers=_headers(token))
        current = client.get(f"{endpoint}/current", headers=_headers(token))
        cancellation = client.post(
            f"/api/v1/tenants/{tenant_id}/jobs/{first.json()['id']}/cancel",
            headers=_headers(token),
        )
        deletion = client.delete(
            f"/api/v1/tenants/{tenant_id}/documents/{document_id}",
            headers=_headers(token),
        )
        deletion_status = client.get(
            f"/api/v1/tenants/{tenant_id}/documents/{document_id}/deletion",
            headers=_headers(token),
        )
    finally:
        client.app.dependency_overrides.pop(ensure_document_ingestion_ready, None)

    assert first.status_code == 202, first.text
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["id"] == first.json()["id"]
    assert len(published) == 1
    assert cancellation.status_code == 409
    assert cancellation.json()["detail"] == "Document ingestion cancellation is not enabled."
    assert deletion.status_code == 202
    assert deletion.json()["job_type"] == "DOCUMENT_DELETION"
    assert deletion_status.status_code == 200
    assert deletion_status.json()["lifecycle_status"] == "DELETING"
    assert {
        "storage_key",
        "file_name",
        "content",
        "vectors",
        "endpoint",
        "error_message",
    }.isdisjoint(deletion_status.json())
    job_id = UUID(first.json()["id"])
    run_count, outbox_count, run = client.portal.call(_counts, job_id)
    assert (run_count, outbox_count) == (1, 1)
    assert run.document_content_sha256 is None
    assert run.extractor_name is None
    assert run.embedding_model is None

    assert current.status_code == 200, current.text
    payload = current.json()
    assert payload["job_id"] == str(job_id)
    assert payload["status"] == "QUEUED"
    assert payload["stage"] == "QUEUED"
    assert payload["progress"] == 0
    forbidden = {
        "content",
        "chunks",
        "vectors",
        "storage_key",
        "path",
        "broker_id",
        "credentials",
        "endpoint",
    }
    assert forbidden.isdisjoint(payload)


def test_document_deletion_denies_viewers_and_cross_tenant_callers(client):
    viewer_token, viewer_tenant_id, viewer_user_id = client.portal.call(
        _seed_member, MembershipRole.VIEWER
    )
    _, viewer_document_id = client.portal.call(_seed_document, viewer_user_id, viewer_tenant_id)
    viewer_response = client.delete(
        f"/api/v1/tenants/{viewer_tenant_id}/documents/{viewer_document_id}",
        headers=_headers(viewer_token),
    )

    _, owner_tenant_id, owner_user_id = client.portal.call(_seed_member, MembershipRole.EDITOR)
    _, owner_document_id = client.portal.call(_seed_document, owner_user_id, owner_tenant_id)
    caller_token, _, _ = client.portal.call(_seed_member, MembershipRole.EDITOR)
    cross_tenant_response = client.delete(
        f"/api/v1/tenants/{owner_tenant_id}/documents/{owner_document_id}",
        headers=_headers(caller_token),
    )

    assert viewer_response.status_code == 403
    assert cross_tenant_response.status_code == 403


def test_ingestion_start_is_disabled_by_default(client, tenant_id):
    settings = get_settings()
    _, document_id = client.portal.call(_seed_document, settings.dev_user_id, UUID(tenant_id))
    response = client.post(f"/api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DOCUMENT_INGESTION_DISABLED"


def test_ingestion_start_requires_process_permission_and_tenant_scope(
    client, monkeypatch, tenant_id
):
    viewer_token, viewer_tenant, viewer_id = client.portal.call(_seed_member, MembershipRole.VIEWER)
    _, viewer_document = client.portal.call(_seed_document, viewer_id, viewer_tenant)
    other_token, other_tenant, other_id = client.portal.call(_seed_member, MembershipRole.EDITOR)
    _, other_document = client.portal.call(_seed_document, other_id, other_tenant)

    async def fake_publish(_tenant: UUID, _outbox: UUID):
        raise AssertionError("Denied request reached dispatch")

    client.app.dependency_overrides[ensure_document_ingestion_ready] = lambda: None
    monkeypatch.setattr(ingestion_routes, "publish_ingestion_dispatch", fake_publish)
    try:
        denied = client.post(
            f"/api/v1/tenants/{viewer_tenant}/documents/{viewer_document}/ingestions",
            headers=_headers(viewer_token),
        )
        viewer_cross_tenant = client.post(
            f"/api/v1/tenants/{viewer_tenant}/documents/{other_document}/ingestions",
            headers=_headers(viewer_token),
        )
        missing = client.post(
            f"/api/v1/tenants/{other_tenant}/documents/{uuid4()}/ingestions",
            headers=_headers(other_token),
        )
        admin_cross_tenant = client.post(
            f"/api/v1/tenants/{tenant_id}/documents/{other_document}/ingestions"
        )
    finally:
        client.app.dependency_overrides.pop(ensure_document_ingestion_ready, None)

    assert denied.status_code == 403
    assert viewer_cross_tenant.status_code == 403
    assert missing.status_code == 404
    assert admin_cross_tenant.status_code == 404


@pytest.mark.asyncio
async def test_ingestion_readiness_dependency_fails_closed_without_details(monkeypatch):
    settings = get_settings().model_copy(update={"document_ingestion_enabled": True})

    async def unavailable(_settings):
        raise IngestionReadinessError("redis")

    monkeypatch.setattr(dependencies, "api_ingestion_is_ready", unavailable)
    with pytest.raises(HTTPException) as error:
        await ensure_document_ingestion_ready(settings)

    assert error.value.status_code == 503
    assert error.value.detail == {
        "code": "DOCUMENT_INGESTION_UNREADY",
        "message": "Document ingestion is temporarily unavailable.",
    }
    assert "redis" not in str(error.value.detail).casefold()


def test_status_requires_read_permission_but_does_not_require_ingestion_enabled(
    client, monkeypatch
):
    editor_token, tenant_id, user_id = client.portal.call(_seed_member, MembershipRole.EDITOR)
    _, document_id = client.portal.call(_seed_document, user_id, tenant_id)

    async def fake_publish(_tenant: UUID, _outbox: UUID):
        return None

    client.app.dependency_overrides[ensure_document_ingestion_ready] = lambda: None
    monkeypatch.setattr(ingestion_routes, "publish_ingestion_dispatch", fake_publish)
    try:
        started = client.post(
            f"/api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions",
            headers=_headers(editor_token),
        )
    finally:
        client.app.dependency_overrides.pop(ensure_document_ingestion_ready, None)
    assert started.status_code == 202
    assert (
        client.get(
            f"/api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions/current",
            headers=_headers(editor_token),
        ).status_code
        == 200
    )
