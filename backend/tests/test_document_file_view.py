"""Isolated file-view API checks; use --noconftest -p tests.upload_transaction_support."""

from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from pypdf import PdfWriter
from sqlalchemy import select

from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.domain import Document
from app.services.storage import LocalObjectStorage, ObjectStorageUnavailableError
from tests.test_document_deduplication_api import CSV, project, upload
from tests.test_document_deduplication_api import workspace as workspace  # noqa: F401


def test_original_file_is_authenticated_scoped_and_not_cached(client, workspace):
    created = upload(client, workspace, project(client, workspace)).json()["workflow"]
    path = f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/file"
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.content == CSV
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert client.get(path.replace(workspace, str(uuid4()))).status_code in {403, 404}
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("change", ["deleting", "foreign_key", "wrong_hash"])
async def test_file_view_rejects_unavailable_or_altered_document(client, workspace, change):
    created = upload(client, workspace, project(client, workspace)).json()["workflow"]
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        document = await db.scalar(
            select(Document).where(Document.id == UUID(created["document_id"]))
        )
        if change == "deleting":
            document.lifecycle_status = "DELETING"
            document.deletion_requested_at = datetime.now(UTC)
            document.vectors_hidden_at = datetime.now(UTC)
        elif change == "foreign_key":
            document.storage_key = document.storage_key.replace(workspace, str(uuid4()))
        else:
            document.upload_sha256 = "0" * 64
        await db.commit()
    response = client.get(f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/file")
    assert response.status_code == 409, response.text
    assert "tenants/" not in response.text


def test_storage_failure_is_sanitized(client, workspace, monkeypatch):
    created = upload(client, workspace, project(client, workspace)).json()["workflow"]

    async def unavailable(*args, **kwargs):
        raise ObjectStorageUnavailableError("private object key and credentials")

    monkeypatch.setattr(LocalObjectStorage, "download_to_path", unavailable)
    response = client.get(f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/file")
    assert response.status_code == 503
    assert "private" not in response.text


def test_original_pdf_has_viewable_content_type(client, workspace):
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)
    content = output.getvalue()
    response = client.post(
        f"/api/v1/tenants/{workspace}/document-workflows/uploads",
        data={"project_id": project(client, workspace)},
        files={"file": ("synthetic.pdf", content, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["workflow"]["document_id"]
    original = client.get(f"/api/v1/tenants/{workspace}/documents/{document_id}/file")
    assert original.status_code == 200
    assert original.headers["content-type"] == "application/pdf"
    assert original.content == content
