from uuid import UUID

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Document, WbsVersion
from app.services.document_workflow_backfill import backfill_workflows
from app.services.storage import LocalObjectStorage
from tests.test_document_deduplication_api import CSV, project
from tests.test_document_deduplication_api import workspace as workspace


def legacy_upload(client, tenant, project_id, monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(get_settings(), "document_upload_reuse_enabled", False)
        context.setattr(get_settings(), "document_workflow_resume_enabled", False)
        response = client.post(
            f"/api/v1/tenants/{tenant}/projects/{project_id}/documents",
            files={"file": ("legacy.csv", CSV, "text/csv")},
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_backfill_dry_run_and_apply_preserve_legacy_duplicates(
    client, workspace, monkeypatch
):
    p = project(client, workspace)
    ids = [legacy_upload(client, workspace, p, monkeypatch) for _ in range(2)]
    settings = get_settings()
    storage = LocalObjectStorage(settings)
    dry = await backfill_workflows(tenant_id=UUID(workspace), storage=storage, settings=settings)
    assert dry["verified"] == 2 and dry["remaining_unverified"] == 2
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(DocumentWorkflow)
                .where(
                    DocumentWorkflow.tenant_id == UUID(workspace),
                )
            )
            == 0
        )
    applied = await backfill_workflows(
        tenant_id=UUID(workspace), storage=storage, settings=settings, apply=True
    )
    assert applied["remaining_unverified"] == 0 and applied["duplicate_groups"] == 1
    repeated = await backfill_workflows(
        tenant_id=UUID(workspace), storage=storage, settings=settings, apply=True
    )
    assert repeated["ambiguous_histories"] == 0
    async with SessionLocal() as db:
        documents = list(
            await db.scalars(select(Document).where(Document.tenant_id == UUID(workspace)))
        )
        assert {str(d.id) for d in documents} == set(ids)
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
            == 2
        )
        assert all((storage.root / d.storage_key).exists() for d in documents)


async def test_project_latest_without_source_lineage_is_not_attached(
    client, workspace, monkeypatch
):
    p = project(client, workspace)
    document_id = legacy_upload(client, workspace, p, monkeypatch)
    async with SessionLocal() as db:
        db.add(
            WbsVersion(
                tenant_id=UUID(workspace),
                project_id=UUID(p),
                version_number=99,
                tree=[{"name": "Unknown source"}],
            )
        )
        await db.commit()
    report = await backfill_workflows(
        tenant_id=UUID(workspace),
        settings=get_settings(),
        storage=LocalObjectStorage(get_settings()),
        apply=True,
    )
    assert report["ambiguous_histories"] == 1
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(DocumentWorkflow.id).where(
                    DocumentWorkflow.document_id == UUID(document_id),
                )
            )
            is None
        )


async def test_missing_object_does_not_create_a_verified_fingerprint(
    client, workspace, monkeypatch
):
    p = project(client, workspace)
    document_id = legacy_upload(client, workspace, p, monkeypatch)
    storage = LocalObjectStorage(get_settings())
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(document_id))
        (storage.root / document.storage_key).unlink()
    report = await backfill_workflows(
        tenant_id=UUID(workspace), settings=get_settings(), storage=storage, apply=True
    )
    assert report["missing_objects"] == 1 and report["verified"] == 0
    async with SessionLocal() as db:
        assert (await db.get(Document, UUID(document_id))).upload_sha256 is None
