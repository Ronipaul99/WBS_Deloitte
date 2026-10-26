import base64
import hashlib
import os
from io import BytesIO

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from app.core.config import Settings
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.storage import LocalObjectStorage, S3ObjectStorage

STORAGE_KEY = (
    "tenants/00000000-0000-0000-0000-000000000001/"
    "projects/00000000-0000-0000-0000-000000000002/"
    "documents/00000000-0000-0000-0000-000000000003.pdf"
)


class ClosingBody(BytesIO):
    closed_by_storage = False

    def close(self) -> None:
        self.closed_by_storage = True
        super().close()


class DownloadClient:
    def __init__(self, body: bytes) -> None:
        self.body_bytes = body
        self.last_body: ClosingBody | None = None
        self.head_response = {
            "ContentLength": len(body),
            "ContentType": "application/pdf",
            "ETag": '"not-a-content-hash"',
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(body).digest()).decode(),
        }

    def head_object(self, **_kwargs):
        return self.head_response

    def get_object(self, **_kwargs):
        self.last_body = ClosingBody(self.body_bytes)
        return {"ContentLength": len(self.body_bytes), "Body": self.last_body}


def settings(maximum: int = 1024) -> Settings:
    return Settings(
        _env_file=None,
        storage_backend="s3",
        object_storage_bucket="assets",
        aws_endpoint_url_s3="https://storage.example.test",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        max_upload_bytes=maximum,
    )


async def test_s3_stat_and_streamed_download_return_safe_verified_metadata(tmp_path) -> None:
    body = b"bounded fixture"
    client = DownloadClient(body)
    storage = S3ObjectStorage(settings(), client=client)
    destination = tmp_path / "input.pdf"

    metadata = await storage.stat_object(STORAGE_KEY)
    result = await storage.download_to_path(STORAGE_KEY, destination, maximum_bytes=len(body))

    assert metadata.size_bytes == len(body)
    assert metadata.content_type == "application/pdf"
    assert metadata.checksum_sha256 == hashlib.sha256(body).hexdigest()
    assert metadata.entity_tag == "not-a-content-hash"
    assert metadata.entity_tag != metadata.checksum_sha256
    assert result.byte_count == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert destination.read_bytes() == body
    if os.name == "posix":
        assert destination.stat().st_mode & 0o077 == 0
    assert client.last_body is not None and client.last_body.closed_by_storage


async def test_local_protocol_supports_bounded_internal_download_without_release_enablement(
    tmp_path,
) -> None:
    local_settings = Settings(_env_file=None, upload_root=tmp_path / "uploads")
    storage = LocalObjectStorage(local_settings)
    source = storage.root / STORAGE_KEY
    source.parent.mkdir(parents=True)
    source.write_bytes(b"local fixture")
    destination = tmp_path / "processing" / "input.pdf"
    destination.parent.mkdir()

    metadata = await storage.stat_object(STORAGE_KEY)
    result = await storage.download_to_path(STORAGE_KEY, destination, maximum_bytes=1024)

    assert local_settings.document_ingestion_enabled is False
    assert metadata.size_bytes == len(b"local fixture")
    assert result.sha256 == hashlib.sha256(b"local fixture").hexdigest()


async def test_s3_download_accepts_exact_limit_and_rejects_one_byte_over(tmp_path) -> None:
    exact = S3ObjectStorage(settings(4), client=DownloadClient(b"1234"))
    result = await exact.download_to_path(STORAGE_KEY, tmp_path / "exact.pdf", maximum_bytes=4)
    assert result.byte_count == 4

    over = S3ObjectStorage(settings(4), client=DownloadClient(b"12345"))
    destination = tmp_path / "over.pdf"
    with pytest.raises(DocumentInputError) as error:
        await over.download_to_path(STORAGE_KEY, destination, maximum_bytes=4)
    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert not destination.exists()


async def test_s3_download_rejects_declared_size_mismatch_and_closes_body(tmp_path) -> None:
    client = DownloadClient(b"fixture")

    def mismatched_get(**_kwargs):
        client.last_body = ClosingBody(client.body_bytes)
        return {"ContentLength": len(client.body_bytes) + 1, "Body": client.last_body}

    client.get_object = mismatched_get
    storage = S3ObjectStorage(settings(), client=client)
    destination = tmp_path / "mismatch.pdf"

    with pytest.raises(DocumentInputError) as error:
        await storage.download_to_path(STORAGE_KEY, destination, maximum_bytes=1024)

    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert not destination.exists()
    assert client.last_body is not None and client.last_body.closed_by_storage


async def test_s3_download_enforces_limit_during_stream_when_provider_size_is_wrong(
    tmp_path,
) -> None:
    client = DownloadClient(b"12345")

    def lying_get(**_kwargs):
        client.last_body = ClosingBody(client.body_bytes)
        return {"ContentLength": 4, "Body": client.last_body}

    client.get_object = lying_get
    storage = S3ObjectStorage(settings(4), client=client)
    destination = tmp_path / "bounded.pdf"

    with pytest.raises(DocumentInputError) as error:
        await storage.download_to_path(STORAGE_KEY, destination, maximum_bytes=4)

    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert not destination.exists()
    assert client.last_body is not None and client.last_body.closed_by_storage


async def test_s3_stream_failure_removes_partial_destination_and_closes_body(tmp_path) -> None:
    class FailingBody:
        closed = False
        reads = 0

        def read(self, _size: int) -> bytes:
            self.reads += 1
            if self.reads == 1:
                return b"partial"
            raise ConnectTimeoutError(endpoint_url="https://storage.example.test")

        def close(self) -> None:
            self.closed = True

    client = DownloadClient(b"partial remains")
    body = FailingBody()
    client.get_object = lambda **_kwargs: {"ContentLength": 15, "Body": body}
    storage = S3ObjectStorage(settings(), client=client)
    destination = tmp_path / "partial.pdf"

    with pytest.raises(DocumentInputError) as error:
        await storage.download_to_path(STORAGE_KEY, destination, maximum_bytes=1024)

    assert error.value.code == DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
    assert not destination.exists()
    assert body.closed


async def test_s3_stat_rejects_object_above_configured_limit() -> None:
    client = DownloadClient(b"12345")
    storage = S3ObjectStorage(settings(4), client=client)

    with pytest.raises(DocumentInputError) as error:
        await storage.stat_object(STORAGE_KEY)

    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED


async def test_s3_missing_object_uses_stable_non_retryable_error(tmp_path) -> None:
    class MissingClient(DownloadClient):
        def head_object(self, **_kwargs):
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey", "Message": "private provider detail"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            )

    storage = S3ObjectStorage(settings(), client=MissingClient(b"fixture"))
    with pytest.raises(DocumentInputError) as error:
        await storage.stat_object(STORAGE_KEY)
    assert error.value.code == DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING
    assert error.value.retryable is False
    assert "private provider detail" not in str(error.value)


async def test_s3_timeout_is_retryable_and_does_not_disclose_endpoint(caplog) -> None:
    private_endpoint = "https://private-storage.internal.example.test"

    class TimeoutClient(DownloadClient):
        def head_object(self, **_kwargs):
            raise ConnectTimeoutError(endpoint_url=private_endpoint)

    storage = S3ObjectStorage(settings(), client=TimeoutClient(b"fixture"))
    with caplog.at_level("WARNING", logger="app.services.storage"):
        with pytest.raises(DocumentInputError) as error:
            await storage.stat_object(STORAGE_KEY)
    assert error.value.code == DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
    assert error.value.retryable is True
    assert private_endpoint not in str(error.value)
    assert private_endpoint not in caplog.text


@pytest.mark.parametrize(
    "unsafe_key",
    ["../secret.pdf", "/absolute.pdf", "folder\\secret.pdf", "folder//secret.pdf"],
)
async def test_download_rejects_unsafe_storage_keys(tmp_path, unsafe_key: str) -> None:
    storage = S3ObjectStorage(settings(), client=DownloadClient(b"fixture"))
    with pytest.raises(DocumentInputError) as error:
        await storage.download_to_path(
            unsafe_key,
            tmp_path / "input.pdf",
            maximum_bytes=1024,
        )
    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
