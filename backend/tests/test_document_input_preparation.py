import asyncio
import hashlib
import os
from pathlib import Path
from uuid import UUID

import pytest

from app.core.config import Settings
from app.models.domain import Document, DocumentKind, Job, JobType, ProcessingStatus
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.ingestion.input_preparation import prepare_document_input
from app.services.ingestion.scanning import MalwareScanResult, MalwareScanStatus
from app.services.storage import DownloadResult, StoredObjectMetadata

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")
DOCUMENT_ID = UUID("00000000-0000-0000-0000-000000000003")
JOB_ID = UUID("00000000-0000-0000-0000-000000000004")
OBJECT_ID = UUID("00000000-0000-0000-0000-000000000005")
USER_ID = UUID("00000000-0000-0000-0000-000000000006")
BODY = b"trusted synthetic document"
SHA256 = hashlib.sha256(BODY).hexdigest()


def ingestion_settings(temp_root: Path, **overrides) -> Settings:
    values = {
        "app_env": "test",
        "document_ingestion_enabled": True,
        "database_url": "postgresql://runtime:test@db.example.test/wbs",
        "direct_database_url": "postgresql://migration:test@db.example.test/wbs",
        "storage_backend": "s3",
        "object_storage_bucket": "assets",
        "aws_endpoint_url_s3": "https://storage.example.test",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "redis_url": "rediss://worker:test@redis.example.test:6380/0",
        "tasks_eager": False,
        "auto_create_tables": False,
        "embedding_model_path": str(temp_root / "model"),
        "embedding_model_revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        "embedding_model_manifest_sha256": "a" * 64,
        "embedding_tokenizer_revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        "embedding_tokenizer_sha256": (
            "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
        ),
        "clamav_host": "scanner.example.test",
        "document_processing_temp_root": str(temp_root),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def persisted_records(*, storage_key: str | None = None, sha256: str | None = SHA256):
    key = storage_key or (f"tenants/{TENANT_ID}/projects/{PROJECT_ID}/documents/{OBJECT_ID}.pdf")
    document = Document(
        id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        uploaded_by=USER_ID,
        kind=DocumentKind.PROJECT,
        file_name="source.pdf",
        content_type="application/pdf",
        size_bytes=len(BODY),
        storage_key=key,
        content_sha256=sha256,
    )
    job = Job(
        id=JOB_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        created_by=USER_ID,
        job_type=JobType.DOCUMENT_INGESTION,
        status=ProcessingStatus.QUEUED,
        request_payload={"document_id": str(DOCUMENT_ID)},
    )
    return document, job


class FakeStorage:
    def __init__(
        self,
        events: list[str],
        *,
        metadata_size: int = len(BODY),
        checksum: str | None = SHA256,
    ) -> None:
        self.events = events
        self.metadata_size = metadata_size
        self.checksum = checksum

    async def stat_object(self, _storage_key: str) -> StoredObjectMetadata:
        self.events.append("stat")
        return StoredObjectMetadata(
            size_bytes=self.metadata_size,
            content_type="application/pdf",
            checksum_sha256=self.checksum,
            entity_tag="diagnostic-only",
        )

    async def download_to_path(
        self,
        _storage_key: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadResult:
        self.events.append("download")
        assert len(BODY) <= maximum_bytes
        destination.write_bytes(BODY)
        if os.name == "posix":
            destination.chmod(0o600)
        return DownloadResult(byte_count=len(BODY), sha256=SHA256)


class FakeScanner:
    def __init__(self, events: list[str], status: MalwareScanStatus) -> None:
        self.events = events
        self.status = status
        self.path: Path | None = None

    async def scan(self, path: Path) -> MalwareScanResult:
        self.events.append("scan")
        self.path = path
        assert path.read_bytes() == BODY
        return MalwareScanResult(self.status)


async def test_clean_document_is_yielded_only_after_stat_download_and_scan(tmp_path) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()
    events: list[str] = []
    storage = FakeStorage(events)
    scanner = FakeScanner(events, MalwareScanStatus.CLEAN)
    trusted_path = None

    async with prepare_document_input(
        document,
        job,
        storage=storage,
        scanner=scanner,
        settings=ingestion_settings(root),
    ) as trusted:
        events.append("handoff")
        trusted_path = trusted.path
        assert trusted.path.exists()
        assert trusted.path.name == "input.pdf"
        assert trusted.size_bytes == len(BODY)
        assert trusted.sha256 == SHA256
        assert trusted.scan_status == MalwareScanStatus.CLEAN

    assert events == ["stat", "download", "scan", "handoff"]
    assert trusted_path is not None and not trusted_path.parent.exists()


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable"),
    [
        (MalwareScanStatus.INFECTED, DocumentInputErrorCode.DOCUMENT_REJECTED_MALWARE, False),
        (
            MalwareScanStatus.UNAVAILABLE,
            DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE,
            True,
        ),
    ],
)
async def test_non_clean_scan_never_yields_trusted_input_and_cleans_up(
    tmp_path,
    status: MalwareScanStatus,
    expected_code: DocumentInputErrorCode,
    retryable: bool,
) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()
    events: list[str] = []
    scanner = FakeScanner(events, status)

    with pytest.raises(DocumentInputError) as error:
        async with prepare_document_input(
            document,
            job,
            storage=FakeStorage(events),
            scanner=scanner,
            settings=ingestion_settings(root),
        ):
            events.append("unexpected-handoff")

    assert error.value.code == expected_code
    assert error.value.retryable is retryable
    assert "unexpected-handoff" not in events
    assert scanner.path is not None and not scanner.path.parent.exists()


@pytest.mark.parametrize(
    "storage",
    [
        FakeStorage([], metadata_size=len(BODY) + 1),
        FakeStorage([], checksum="0" * 64),
    ],
)
async def test_integrity_mismatch_prevents_scanning(tmp_path, storage: FakeStorage) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()
    scanner = FakeScanner([], MalwareScanStatus.CLEAN)

    with pytest.raises(DocumentInputError) as error:
        async with prepare_document_input(
            document,
            job,
            storage=storage,
            scanner=scanner,
            settings=ingestion_settings(root),
        ):
            pass

    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert scanner.path is None
    assert list(root.iterdir()) == []


async def test_consumer_failure_still_removes_scanned_input(tmp_path) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()
    scanner = FakeScanner([], MalwareScanStatus.CLEAN)
    trusted_path = None

    with pytest.raises(RuntimeError, match="later parser failed"):
        async with prepare_document_input(
            document,
            job,
            storage=FakeStorage([]),
            scanner=scanner,
            settings=ingestion_settings(root),
        ) as trusted:
            trusted_path = trusted.path
            raise RuntimeError("later parser failed")

    assert trusted_path is not None and not trusted_path.parent.exists()


async def test_cancellation_during_scan_removes_temporary_input(tmp_path) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()

    class BlockingScanner:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.path: Path | None = None

        async def scan(self, path: Path) -> MalwareScanResult:
            self.path = path
            self.started.set()
            await asyncio.Event().wait()
            return MalwareScanResult(MalwareScanStatus.CLEAN)

    scanner = BlockingScanner()

    async def prepare() -> None:
        async with prepare_document_input(
            document,
            job,
            storage=FakeStorage([]),
            scanner=scanner,
            settings=ingestion_settings(root),
        ):
            raise AssertionError("cancelled input must not be yielded")

    task = asyncio.create_task(prepare())
    await scanner.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert scanner.path is not None and not scanner.path.parent.exists()


async def test_untrusted_storage_key_is_rejected_before_storage_access(tmp_path) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records(storage_key="../../arbitrary.pdf")
    events: list[str] = []

    with pytest.raises(DocumentInputError) as error:
        async with prepare_document_input(
            document,
            job,
            storage=FakeStorage(events),
            scanner=FakeScanner(events, MalwareScanStatus.CLEAN),
            settings=ingestion_settings(root),
        ):
            pass

    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert events == []


async def test_job_scope_must_authorize_the_persisted_document(tmp_path) -> None:
    root = tmp_path / "processing"
    root.mkdir(mode=0o700)
    document, job = persisted_records()
    job.request_payload = {"document_id": str(UUID(int=99))}

    with pytest.raises(DocumentInputError) as error:
        async with prepare_document_input(
            document,
            job,
            storage=FakeStorage([]),
            scanner=FakeScanner([], MalwareScanStatus.CLEAN),
            settings=ingestion_settings(root),
        ):
            pass
    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
