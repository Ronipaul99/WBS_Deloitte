from io import BytesIO
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.core.config import Settings
from app.services.storage import ObjectStorageUnavailableError, S3ObjectStorage

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeS3Client:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []
        self.deletes: list[dict[str, str]] = []
        self.checked_buckets: list[str] = []

    def upload_fileobj(
        self,
        file,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, str],
    ) -> None:
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "body": file.read(),
                "extra_args": ExtraArgs,
            }
        )

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deletes.append({"bucket": Bucket, "key": Key})

    def head_bucket(self, *, Bucket: str) -> None:
        self.checked_buckets.append(Bucket)


def _settings(**overrides) -> Settings:
    values = {
        "storage_backend": "s3",
        "object_storage_bucket": "assets",
        "aws_endpoint_url_s3": "https://storage.example.com",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "aws_region": "us-east-2",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _upload(name: str, body: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        BytesIO(body),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_s3_upload_uses_private_generated_tenant_project_key() -> None:
    client = FakeS3Client()
    storage = S3ObjectStorage(_settings(), client=client)
    body = b"%PDF-1.4\nproject scope"

    key, size = await storage.save(
        TENANT_ID,
        "documents",
        _upload("client-secret-name.pdf", body, "application/pdf"),
        suffix=".pdf",
        content_type="application/pdf",
        project_id=PROJECT_ID,
    )

    assert key.startswith(f"tenants/{TENANT_ID}/projects/{PROJECT_ID}/documents/")
    assert key.endswith(".pdf")
    assert "client-secret-name" not in key
    assert size == len(body)
    assert client.uploads == [
        {
            "bucket": "assets",
            "key": key,
            "body": body,
            "extra_args": {"ContentType": "application/pdf"},
        }
    ]

    await storage.delete_object(key)
    await storage.check()
    assert client.deletes == [{"bucket": "assets", "key": key}]
    assert client.checked_buckets == ["assets"]


@pytest.mark.asyncio
async def test_s3_upload_enforces_actual_size_before_provider_call() -> None:
    client = FakeS3Client()
    storage = S3ObjectStorage(_settings(max_upload_bytes=8), client=client)

    with pytest.raises(HTTPException) as exc_info:
        await storage.save(
            TENANT_ID,
            "documents",
            _upload("scope.pdf", b"%PDF-1.4-too-large", "application/pdf"),
            suffix=".pdf",
            content_type="application/pdf",
            project_id=PROJECT_ID,
        )

    assert exc_info.value.status_code == 413
    assert client.uploads == []


@pytest.mark.asyncio
async def test_s3_provider_errors_are_normalized() -> None:
    class FailingClient(FakeS3Client):
        def upload_fileobj(self, *args, **kwargs) -> None:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "provider details"}},
                "PutObject",
            )

    storage = S3ObjectStorage(_settings(), client=FailingClient())
    with pytest.raises(ObjectStorageUnavailableError, match="Object storage upload failed"):
        await storage.save(
            TENANT_ID,
            "documents",
            _upload("scope.pdf", b"%PDF-1.4\nscope", "application/pdf"),
            suffix=".pdf",
            content_type="application/pdf",
            project_id=PROJECT_ID,
        )
