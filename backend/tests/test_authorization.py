import logging
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.core.config import get_settings
from app.core.permissions import (
    ADMIN_PERMISSIONS,
    EDITOR_PERMISSIONS,
    ROLE_PERMISSIONS,
    VIEWER_PERMISSIONS,
    Permission,
    permissions_for_role,
)
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.domain import (
    Document,
    DocumentKind,
    DocumentSummary,
    ExportFile,
    Job,
    JobType,
    MembershipRole,
    Project,
    Tenant,
    TenantMembership,
    User,
    ValidationRun,
    WbsTemplate,
    WbsVersion,
)
from app.services.storage import get_upload_storage


class RecordingStorage:
    def __init__(self) -> None:
        self.save_calls = 0

    async def save(self, *_args, **_kwargs):
        self.save_calls += 1
        raise AssertionError("Unauthorized request reached object storage")

    async def delete_object(self, _storage_key):
        return None

    async def check(self):
        return None


async def _seed_identity(role: str | None, tenant_active: bool = True) -> tuple[str, UUID, UUID]:
    suffix = uuid4().hex
    tenant = Tenant(name=f"Authorization {suffix}", slug=f"authorization-{suffix}")
    tenant.is_active = tenant_active
    user = User(
        external_subject=f"authorization-{suffix}",
        email=f"authorization-{suffix}@example.com",
        display_name="Authorization Test User",
    )
    async with SessionLocal() as db:
        db.add_all([tenant, user])
        await db.flush()
        if role is not None:
            db.add(TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role))
        await db.commit()

    token, _ = create_access_token(user.id, uuid4(), user.auth_version, get_settings())
    return token, tenant.id, user.id


async def _set_membership_role(tenant_id: UUID, user_id: UUID, role: str | None) -> None:
    async with SessionLocal() as db:
        membership = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
            )
        )
        if role is None:
            if membership is not None:
                await db.delete(membership)
        elif membership is None:
            db.add(TenantMembership(tenant_id=tenant_id, user_id=user_id, role=role))
        else:
            membership.role = role
        await db.commit()


async def _seed_other_tenant_resources(owner_id: UUID) -> dict[str, UUID]:
    suffix = uuid4().hex
    async with SessionLocal() as db:
        tenant = Tenant(name=f"Other {suffix}", slug=f"other-{suffix}")
        db.add(tenant)
        await db.flush()

        project = Project(tenant_id=tenant.id, created_by=owner_id, name="Other project")
        db.add(project)
        await db.flush()

        document = Document(
            tenant_id=tenant.id,
            project_id=project.id,
            uploaded_by=owner_id,
            kind=DocumentKind.PROJECT,
            file_name="other.pdf",
            content_type="application/pdf",
            size_bytes=1,
            storage_key=f"other/{suffix}/document.pdf",
        )
        template = WbsTemplate(
            tenant_id=tenant.id,
            uploaded_by=owner_id,
            name="Other template",
            file_name="other.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=1,
            storage_key=f"other/{suffix}/template.xlsx",
        )
        job = Job(
            tenant_id=tenant.id,
            project_id=project.id,
            created_by=owner_id,
            job_type=JobType.WBS_GENERATION,
        )
        db.add_all([document, template, job])
        await db.flush()

        summary = DocumentSummary(tenant_id=tenant.id, document_id=document.id)
        version = WbsVersion(
            tenant_id=tenant.id,
            project_id=project.id,
            generation_job_id=job.id,
            version_number=1,
        )
        db.add_all([summary, version])
        await db.flush()

        validation = ValidationRun(tenant_id=tenant.id, wbs_version_id=version.id)
        export = ExportFile(
            tenant_id=tenant.id,
            project_id=project.id,
            wbs_version_id=version.id,
            format="json",
        )
        db.add_all([validation, export])
        await db.commit()

        return {
            "tenant": tenant.id,
            "project": project.id,
            "document": document.id,
            "summary": summary.id,
            "template": template.id,
            "job": job.id,
            "wbs": version.id,
            "validation": validation.id,
            "export": export.id,
        }


def _authorization_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_role_permission_matrix_is_complete_and_fail_closed():
    assert ROLE_PERMISSIONS[MembershipRole.VIEWER] == VIEWER_PERMISSIONS
    assert ROLE_PERMISSIONS[MembershipRole.EDITOR] == EDITOR_PERMISSIONS
    assert ROLE_PERMISSIONS[MembershipRole.ADMIN] == ADMIN_PERMISSIONS
    assert ADMIN_PERMISSIONS == frozenset(Permission)
    assert VIEWER_PERMISSIONS < EDITOR_PERMISSIONS < ADMIN_PERMISSIONS
    assert permissions_for_role("UNKNOWN") == frozenset()

    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[MembershipRole.VIEWER] = frozenset()  # type: ignore[index]


def test_viewer_can_read_but_cannot_upload_or_generate(client):
    token, tenant_id, _ = client.portal.call(_seed_identity, MembershipRole.VIEWER)
    headers = _authorization_header(token)

    assert client.get(f"/api/v1/tenants/{tenant_id}/projects", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/tenants/{tenant_id}/projects",
            headers=headers,
            json={"name": "Forbidden project"},
        ).status_code
        == 403
    )
    storage = RecordingStorage()
    client.app.dependency_overrides[get_upload_storage] = lambda: storage
    try:
        malformed_upload = client.post(
            f"/api/v1/tenants/{tenant_id}/projects/{uuid4()}/documents",
            headers={**headers, "Content-Type": "multipart/form-data; boundary=invalid"},
            content=b"this body cannot be parsed as multipart",
        )
        denied_upload = client.post(
            f"/api/v1/tenants/{tenant_id}/projects/{uuid4()}/documents",
            headers=headers,
            data={"kind": "PROJECT"},
            files={"file": ("scope.pdf", b"scope", "application/pdf")},
        )
    finally:
        client.app.dependency_overrides.pop(get_upload_storage, None)
    assert malformed_upload.status_code == 403
    assert denied_upload.status_code == 403
    assert storage.save_calls == 0
    assert (
        client.post(
            f"/api/v1/tenants/{tenant_id}/projects/{uuid4()}/generations",
            headers=headers,
            json={"document_id": str(uuid4()), "summary_id": str(uuid4())},
        ).status_code
        == 403
    )


def test_editor_can_mutate_workflow_but_cannot_archive_project(client):
    token, tenant_id, _ = client.portal.call(_seed_identity, MembershipRole.EDITOR)
    headers = _authorization_header(token)

    created = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        headers=headers,
        json={"name": "Editor project"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}",
        headers=headers,
        json={"name": "Updated by editor"},
    )
    assert updated.status_code == 200
    assert (
        client.delete(
            f"/api/v1/tenants/{tenant_id}/projects/{project_id}", headers=headers
        ).status_code
        == 403
    )


def test_role_change_and_membership_removal_apply_to_existing_token(client):
    token, tenant_id, user_id = client.portal.call(_seed_identity, MembershipRole.VIEWER)
    headers = _authorization_header(token)
    endpoint = f"/api/v1/tenants/{tenant_id}/projects"

    assert client.post(endpoint, headers=headers, json={"name": "Denied"}).status_code == 403

    client.portal.call(_set_membership_role, tenant_id, user_id, MembershipRole.EDITOR)
    assert client.post(endpoint, headers=headers, json={"name": "Allowed"}).status_code == 201

    client.portal.call(_set_membership_role, tenant_id, user_id, None)
    assert client.get(endpoint, headers=headers).status_code == 403


def test_absent_membership_and_inactive_tenant_are_denied(client):
    token, tenant_id, _ = client.portal.call(_seed_identity, None)
    assert (
        client.get(
            f"/api/v1/tenants/{tenant_id}/projects", headers=_authorization_header(token)
        ).status_code
        == 403
    )

    inactive_token, inactive_tenant_id, _ = client.portal.call(_seed_identity, "ADMIN", False)
    assert (
        client.get(
            f"/api/v1/tenants/{inactive_tenant_id}/projects",
            headers=_authorization_header(inactive_token),
        ).status_code
        == 404
    )


def test_unknown_role_has_no_permissions_and_logs_no_sensitive_context(client, caplog):
    unknown_role = f"UNKNOWN-{uuid4()}"
    token, tenant_id, _ = client.portal.call(_seed_identity, unknown_role)
    headers = _authorization_header(token)

    with caplog.at_level(logging.WARNING, logger="app.core.permissions"):
        denied = client.get(f"/api/v1/tenants/{tenant_id}/projects", headers=headers)
        identity = client.get("/api/v1/me", headers=headers)

    assert denied.status_code == 403
    membership = next(item for item in identity.json()["tenants"] if item["id"] == str(tenant_id))
    assert membership["permissions"] == []
    assert unknown_role not in caplog.text
    assert str(tenant_id) not in caplog.text


def test_cross_tenant_resource_ids_return_not_found(client, tenant_id):
    owner_id = get_settings().dev_user_id
    other = client.portal.call(_seed_other_tenant_resources, owner_id)
    base = f"/api/v1/tenants/{tenant_id}"
    storage = RecordingStorage()
    client.app.dependency_overrides[get_upload_storage] = lambda: storage
    try:
        cross_tenant_upload = client.post(
            f"{base}/projects/{other['project']}/documents",
            data={"kind": "PROJECT"},
            files={"file": ("scope.pdf", b"scope", "application/pdf")},
        )
    finally:
        client.app.dependency_overrides.pop(get_upload_storage, None)
    assert cross_tenant_upload.status_code == 404
    assert storage.save_calls == 0

    requests = [
        ("get", f"{base}/projects/{other['project']}", None),
        ("get", f"{base}/documents/{other['document']}", None),
        ("get", f"{base}/documents/{other['document']}/summary", None),
        ("get", f"{base}/templates/{other['template']}", None),
        ("get", f"{base}/jobs/{other['job']}", None),
        ("put", f"{base}/wbs/{other['wbs']}", {"tree": []}),
        ("get", f"{base}/validations/{other['validation']}", None),
        ("get", f"{base}/exports/{other['export']}", None),
    ]
    for method, url, payload in requests:
        response = client.request(method, url, json=payload)
        assert response.status_code == 404, f"{method.upper()} {url}: {response.text}"


def test_tenant_routes_document_auth_outcomes_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    tenant_operations = [
        operation
        for path, methods in paths.items()
        if "/tenants/{tenant_id}" in path
        for method, operation in methods.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert tenant_operations
    for operation in tenant_operations:
        assert {"401", "403", "404"}.issubset(operation["responses"])

    def walk_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            nested_router = getattr(route, "original_router", None)
            nested_routes = getattr(nested_router, "routes", None)
            if nested_routes:
                yield from walk_routes(nested_routes)

    tenant_routes = [
        route for route in walk_routes(client.app.routes) if "/tenants/{tenant_id}" in route.path
    ]
    assert tenant_routes
    for route in tenant_routes:
        permission_dependencies = [
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "__name__", "").startswith("require_")
        ]
        assert len(permission_dependencies) == 1, (
            f"{','.join(route.methods)} {route.path} must declare exactly one primary permission"
        )
