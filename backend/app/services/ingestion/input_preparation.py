import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from secrets import compare_digest
from uuid import UUID

from app.core.config import Settings
from app.core.observability import (
    record_document_download,
    record_document_input,
    record_malware_scan,
)
from app.models.domain import (
    Document,
    DocumentKind,
    DocumentProcessingRun,
    Job,
    JobType,
    ProcessingStatus,
)
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.ingestion.scanning import (
    MalwareScanner,
    MalwareScanStatus,
    ScannerInputReadError,
)
from app.services.ingestion.workspace import temporary_document_workspace
from app.services.storage import DownloadResult, StoredObjectMetadata, UploadObjectStorage

CONTENT_TYPES_BY_SUFFIX = {
    ".pdf": frozenset({"application/pdf"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    ".csv": frozenset({"text/csv", "application/csv", "application/vnd.ms-excel"}),
}


@dataclass(frozen=True, slots=True)
class TrustedDocumentInput:
    path: Path
    suffix: str
    size_bytes: int
    sha256: str
    scan_status: MalwareScanStatus


def _fail_integrity() -> None:
    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)


def _confirmed_document_suffix(document: Document) -> str:
    key = document.storage_key
    parts = key.split("/") if isinstance(key, str) else []
    if (
        len(parts) != 6
        or parts[0] != "tenants"
        or parts[2] != "projects"
        or parts[4] != "documents"
        or parts[1] != str(document.tenant_id)
        or parts[3] != str(document.project_id)
        or not isinstance(document.content_type, str)
    ):
        _fail_integrity()
    filename = parts[5]
    if PurePosixPath(filename).name != filename:
        _fail_integrity()
    try:
        UUID(PurePosixPath(filename).stem)
    except (TypeError, ValueError, AttributeError):
        _fail_integrity()
    suffix = PurePosixPath(filename).suffix.casefold()
    allowed_content_types = CONTENT_TYPES_BY_SUFFIX.get(suffix)
    if (
        allowed_content_types is None
        or document.content_type.casefold() not in allowed_content_types
    ):
        _fail_integrity()
    return suffix


def _validate_persisted_context(
    document: Document,
    job: Job,
    processing_run: DocumentProcessingRun | None,
) -> str:
    identifiers = (
        document.id,
        document.tenant_id,
        document.project_id,
        job.id,
        job.tenant_id,
        job.project_id,
    )
    if not all(isinstance(identifier, UUID) for identifier in identifiers):
        _fail_integrity()
    if (
        document.kind != DocumentKind.PROJECT
        or job.job_type != JobType.DOCUMENT_INGESTION
        or job.status not in {ProcessingStatus.QUEUED, ProcessingStatus.IN_PROGRESS}
        or document.tenant_id != job.tenant_id
        or document.project_id != job.project_id
        or not isinstance(job.request_payload, dict)
        or str(job.request_payload.get("document_id", "")) != str(document.id)
        or not isinstance(document.size_bytes, int)
        or document.size_bytes < 1
    ):
        _fail_integrity()
    if processing_run is not None and (
        processing_run.document_id != document.id
        or processing_run.tenant_id != document.tenant_id
        or processing_run.project_id != document.project_id
        or processing_run.job_id != job.id
    ):
        _fail_integrity()
    return _confirmed_document_suffix(document)


def _validated_expected_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        _fail_integrity()
    return value.casefold()


def _validate_metadata(document: Document, metadata: StoredObjectMetadata, maximum: int) -> None:
    if (
        metadata.size_bytes < 1
        or metadata.size_bytes > maximum
        or metadata.size_bytes != document.size_bytes
    ):
        _fail_integrity()
    if (
        metadata.content_type is not None
        and metadata.content_type != document.content_type.casefold()
    ):
        _fail_integrity()


def _validate_download(
    document: Document,
    metadata: StoredObjectMetadata,
    result: DownloadResult,
) -> None:
    if (
        result.byte_count != document.size_bytes
        or result.byte_count != metadata.size_bytes
        or not re.fullmatch(r"[0-9a-f]{64}", result.sha256)
    ):
        _fail_integrity()
    expected_hashes = (
        _validated_expected_sha256(document.content_sha256),
        metadata.checksum_sha256,
    )
    for expected in expected_hashes:
        if expected is not None and not compare_digest(expected, result.sha256):
            _fail_integrity()


@asynccontextmanager
async def prepare_document_input(
    document: Document,
    job: Job,
    *,
    storage: UploadObjectStorage,
    scanner: MalwareScanner,
    settings: Settings,
    processing_run: DocumentProcessingRun | None = None,
) -> AsyncIterator[TrustedDocumentInput]:
    try:
        suffix = _validate_persisted_context(document, job, processing_run)
        if not settings.document_ingestion_enabled or not settings.malware_scan_required:
            raise DocumentInputError(DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE)

        async with temporary_document_workspace(
            settings.document_processing_temp_root,
            suffix,
        ) as workspace:
            download_started = time.monotonic()
            download_result: DownloadResult | None = None
            download_succeeded = False
            try:
                metadata = await storage.stat_object(document.storage_key)
                _validate_metadata(document, metadata, settings.max_upload_bytes)
                download_result = await storage.download_to_path(
                    document.storage_key,
                    workspace.input_path,
                    maximum_bytes=settings.max_upload_bytes,
                )
                _validate_download(document, metadata, download_result)
                download_succeeded = True
            finally:
                record_document_download(
                    duration_seconds=time.monotonic() - download_started,
                    byte_count=(download_result.byte_count if download_result else None),
                    success=download_succeeded,
                )

            scan_started = time.monotonic()
            scan_outcome = MalwareScanStatus.UNAVAILABLE
            try:
                scan_result = await scanner.scan(workspace.input_path)
                if not isinstance(scan_result.status, MalwareScanStatus):
                    raise DocumentInputError(DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE)
                scan_outcome = scan_result.status
            except ScannerInputReadError:
                raise DocumentInputError(
                    DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
                ) from None
            except DocumentInputError:
                raise
            except Exception:
                raise DocumentInputError(
                    DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE
                ) from None
            finally:
                record_malware_scan(
                    duration_seconds=time.monotonic() - scan_started,
                    outcome=scan_outcome.value,
                )

            if scan_result.status == MalwareScanStatus.INFECTED:
                raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_REJECTED_MALWARE)
            if scan_result.status != MalwareScanStatus.CLEAN:
                raise DocumentInputError(DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE)

            trusted = TrustedDocumentInput(
                path=workspace.input_path,
                suffix=suffix,
                size_bytes=download_result.byte_count,
                sha256=download_result.sha256,
                scan_status=scan_result.status,
            )
            record_document_input(trusted=True)
            yield trusted
    except DocumentInputError as exc:
        record_document_input(trusted=False, error_code=exc.code.value)
        raise
