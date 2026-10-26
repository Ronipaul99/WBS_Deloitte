import logging
from uuid import UUID

import pytest

from app.api.routes.documents import _persist_document
from app.core.upload_errors import UploadErrorCode
from app.main import app
from app.models.domain import Document, DocumentKind
from app.services.storage import ObjectStorageUnavailableError, get_upload_storage
from tests.pdf_fixtures import encrypted_pdf_bytes, scanned_pdf_bytes, text_pdf_bytes


def _create_project(client, tenant_id: str) -> str:
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/projects",
        json={"name": "PDF upload verification"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload_document(
    client,
    tenant_id: str,
    project_id: str,
    *,
    name: str,
    body: bytes,
    content_type: str,
):
    return client.post(
        f"/api/v1/tenants/{tenant_id}/projects/{project_id}/documents",
        data={"kind": "PROJECT"},
        files={"file": (name, body, content_type)},
    )


@pytest.mark.parametrize(
    ("name", "body_factory", "content_type"),
    [
        ("project.scope.final.pdf", text_pdf_bytes, "application/pdf"),
        ("project scope.pdf", text_pdf_bytes, "application/octet-stream"),
        ("scanned-scope.pdf", scanned_pdf_bytes, "application/pdf"),
    ],
)
def test_genuine_pdf_uploads_are_normalized(
    client,
    tenant_id,
    name,
    body_factory,
    content_type,
):
    project_id = _create_project(client, tenant_id)

    response = _upload_document(
        client,
        tenant_id,
        project_id,
        name=name,
        body=body_factory(),
        content_type=content_type,
    )

    assert response.status_code == 201
    assert response.json()["file_name"] == name
    assert response.json()["content_type"] == "application/pdf"


@pytest.mark.parametrize(
    ("name", "body", "content_type", "expected_status", "expected_code"),
    [
        (
            "renamed.pdf",
            b"plain text",
            "application/pdf",
            415,
            UploadErrorCode.DOCUMENT_TYPE_MISMATCH,
        ),
        (
            "malformed.pdf",
            b"%PDF-1.7\nnot a real PDF\n%%EOF",
            "application/pdf",
            422,
            UploadErrorCode.PDF_MALFORMED,
        ),
        (
            "truncated.pdf",
            text_pdf_bytes()[:200],
            "application/pdf",
            422,
            UploadErrorCode.PDF_MALFORMED,
        ),
        (
            "encrypted.pdf",
            encrypted_pdf_bytes(),
            "application/pdf",
            422,
            UploadErrorCode.PDF_ENCRYPTED,
        ),
        ("empty.pdf", b"", "application/pdf", 400, UploadErrorCode.DOCUMENT_EMPTY),
        (
            "legacy.doc",
            b"legacy",
            "application/msword",
            415,
            UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT,
        ),
        (
            "legacy.xls",
            b"legacy",
            "application/vnd.ms-excel",
            415,
            UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT,
        ),
        (
            "mismatch.docx",
            text_pdf_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            415,
            UploadErrorCode.DOCUMENT_TYPE_MISMATCH,
        ),
        (
            "declared-wrong.pdf",
            text_pdf_bytes(),
            "text/plain",
            415,
            UploadErrorCode.DOCUMENT_TYPE_MISMATCH,
        ),
    ],
)
def test_invalid_pdf_uploads_return_stable_errors(
    client,
    tenant_id,
    name,
    body,
    content_type,
    expected_status,
    expected_code,
):
    project_id = _create_project(client, tenant_id)

    response = _upload_document(
        client,
        tenant_id,
        project_id,
        name=name,
        body=body,
        content_type=content_type,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert set(response.json()["detail"]) == {"code", "message"}


def test_storage_failure_returns_safe_stable_error(client, tenant_id):
    class UnavailableStorage:
        async def save(self, *_args, **_kwargs):
            raise ObjectStorageUnavailableError("private provider endpoint and bucket details")

        async def delete_object(self, _storage_key):
            return None

        async def check(self):
            return None

    project_id = _create_project(client, tenant_id)
    app.dependency_overrides[get_upload_storage] = UnavailableStorage
    try:
        response = _upload_document(
            client,
            tenant_id,
            project_id,
            name="scope.pdf",
            body=text_pdf_bytes(),
            content_type="application/pdf",
        )
    finally:
        app.dependency_overrides.pop(get_upload_storage, None)

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "OBJECT_STORAGE_UNAVAILABLE",
        "message": "Document storage is temporarily unavailable.",
    }
    assert "private provider" not in response.text


def _document(storage_key: str) -> Document:
    return Document(
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        project_id=UUID("00000000-0000-0000-0000-000000000002"),
        uploaded_by=UUID("00000000-0000-0000-0000-000000000003"),
        kind=DocumentKind.PROJECT,
        file_name="scope.pdf",
        content_type="application/pdf",
        size_bytes=100,
        storage_key=storage_key,
    )


@pytest.mark.asyncio
async def test_database_failure_cleans_up_uploaded_object() -> None:
    class FailingDatabase:
        rollback_calls = 0

        def add(self, _document):
            return None

        async def commit(self):
            raise RuntimeError("synthetic database failure")

        async def rollback(self):
            self.rollback_calls += 1

    class CleanupStorage:
        deleted: list[str] = []

        async def delete_object(self, storage_key):
            self.deleted.append(storage_key)

    storage_key = "tenants/opaque/projects/opaque/documents/opaque.pdf"
    db = FailingDatabase()
    storage = CleanupStorage()

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        await _persist_document(db, storage, _document(storage_key))

    assert db.rollback_calls == 1
    assert storage.deleted == [storage_key]


@pytest.mark.asyncio
async def test_cleanup_failure_is_bounded_and_does_not_log_storage_details(caplog) -> None:
    class FailingDatabase:
        def add(self, _document):
            return None

        async def commit(self):
            raise RuntimeError("synthetic database failure")

        async def rollback(self):
            return None

    class FailingCleanupStorage:
        calls = 0

        async def delete_object(self, _storage_key):
            self.calls += 1
            raise ObjectStorageUnavailableError("private bucket provider diagnostic")

    storage_key = "tenants/secret/projects/secret/documents/secret.pdf"
    storage = FailingCleanupStorage()
    with caplog.at_level(logging.ERROR, logger="app.api.routes.documents"):
        with pytest.raises(RuntimeError, match="synthetic database failure"):
            await _persist_document(FailingDatabase(), storage, _document(storage_key))

    assert storage.calls == 2
    assert "cleanup failed after database rollback" in caplog.text
    assert storage_key not in caplog.text
    assert "private bucket" not in caplog.text
