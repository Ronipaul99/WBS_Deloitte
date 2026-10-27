import base64
import binascii
import hashlib
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache, partial
from pathlib import Path, PurePosixPath
from secrets import compare_digest
from typing import Any, Protocol
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from pypdf import PdfReader
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core.config import Settings, get_settings
from app.core.upload_errors import UploadErrorCode, upload_http_error
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1024 * 1024
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
SAFE_ENTITY_TAG = re.compile(r"^[A-Za-z0-9-]{1,128}$")


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    size_bytes: int
    content_type: str | None
    checksum_sha256: str | None
    entity_tag: str | None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    sha256: str
    size_bytes: int
    storage_key: str


@dataclass(frozen=True, slots=True)
class StoredObjectEntry:
    storage_key: str
    updated_at: datetime


class ObjectStorageUnavailableError(RuntimeError):
    pass


class UploadObjectStorage(Protocol):
    async def save(
        self,
        tenant_id: UUID,
        category: str,
        upload: UploadFile,
        *,
        suffix: str,
        content_type: str,
        project_id: UUID | None = None,
        prepared: PreparedUpload | None = None,
    ) -> tuple[str, int]: ...

    async def delete_object(self, storage_key: str) -> None: ...

    async def check(self) -> None: ...

    async def stat_object(self, storage_key: str) -> StoredObjectMetadata: ...

    async def download_to_path(
        self,
        storage_key: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadResult: ...

    async def list_objects(
        self,
        prefix: str,
        *,
        maximum_items: int,
    ) -> tuple[StoredObjectEntry, ...]: ...


def _validated_storage_key(storage_key: str) -> str:
    if (
        not storage_key
        or len(storage_key) > 600
        or "\\" in storage_key
        or "\x00" in storage_key
        or storage_key.startswith("/")
        or any(part in {"", ".", ".."} for part in storage_key.split("/"))
    ):
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    path = PurePosixPath(storage_key)
    if path.is_absolute() or path.as_posix() != storage_key:
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    return storage_key


def validate_document_storage_key(
    storage_key: str,
    *,
    tenant_id: UUID,
    project_id: UUID,
) -> str:
    try:
        safe_key = _validated_storage_key(storage_key)
    except DocumentInputError:
        raise ValueError("Document object key is invalid.") from None
    path = PurePosixPath(safe_key)
    expected_prefix = (
        "tenants",
        str(tenant_id),
        "projects",
        str(project_id),
        "documents",
    )
    if path.parts[:-1] != expected_prefix:
        raise ValueError("Document object does not match the persisted ownership scope.")
    if path.suffix.casefold() not in {".pdf", ".docx", ".xlsx", ".csv"}:
        raise ValueError("Document object has an unsupported persisted suffix.")
    try:
        UUID(path.stem)
    except ValueError:
        raise ValueError("Document object name is not server generated.") from None
    return safe_key


def _normalized_sha256(value: object) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", candidate):
        return candidate.casefold()
    try:
        decoded = base64.b64decode(candidate, validate=True)
    except (ValueError, binascii.Error):
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED) from None
    if len(decoded) != hashlib.sha256().digest_size:
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    return decoded.hex()


def _safe_content_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().casefold()
    if not candidate or len(candidate) > 160 or any(ord(char) < 32 for char in candidate):
        return None
    return candidate


def _safe_entity_tag(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().strip('"')
    return candidate if SAFE_ENTITY_TAG.fullmatch(candidate) else None


def _is_missing_object_error(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    metadata = exc.response.get("ResponseMetadata", {})
    return (
        str(error.get("Code", "")) in {"404", "NoSuchKey", "NotFound"}
        or metadata.get("HTTPStatusCode") == 404
    )


def _open_private_destination(destination: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination, flags, 0o600)
    return os.fdopen(descriptor, "wb")


def _stream_to_destination(
    source: Any,
    destination: Path,
    maximum_bytes: int,
) -> DownloadResult:
    if maximum_bytes < 1:
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with _open_private_destination(destination) as output:
            while True:
                try:
                    chunk = source.read(CHUNK_SIZE)
                except OSError:
                    raise DocumentInputError(
                        DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
                    ) from None
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
                byte_count += len(chunk)
                if byte_count > maximum_bytes:
                    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
                try:
                    output.write(chunk)
                except OSError:
                    raise DocumentInputError(
                        DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
                    ) from None
                digest.update(chunk)
            try:
                output.flush()
            except OSError:
                raise DocumentInputError(
                    DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
                ) from None
    except DocumentInputError:
        destination.unlink(missing_ok=True)
        raise
    except OSError:
        destination.unlink(missing_ok=True)
        raise DocumentInputError(DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE) from None
    if byte_count == 0:
        destination.unlink(missing_ok=True)
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    return DownloadResult(byte_count=byte_count, sha256=digest.hexdigest())


def _object_key(
    tenant_id: UUID,
    category: str,
    suffix: str,
    project_id: UUID | None,
) -> str:
    if category not in {"documents", "templates"}:
        raise ValueError("Unsupported upload category.")
    if suffix != suffix.lower() or not suffix.startswith(".") or not suffix[1:].isalnum():
        raise ValueError("Invalid upload suffix.")

    parts = ["tenants", str(tenant_id)]
    if category == "documents":
        if project_id is None:
            raise ValueError("Project uploads require a project ID.")
        parts.extend(("projects", str(project_id)))
    parts.extend((category, f"{uuid4()}{suffix}"))
    return "/".join(parts)


async def _measure_upload(upload: UploadFile, max_upload_bytes: int) -> int:
    await upload.seek(0)
    size = 0
    while chunk := await upload.read(CHUNK_SIZE):
        size += len(chunk)
        if size > max_upload_bytes:
            await upload.seek(0)
            raise upload_http_error(UploadErrorCode.DOCUMENT_TOO_LARGE)
    await upload.seek(0)
    if size == 0:
        raise upload_http_error(UploadErrorCode.DOCUMENT_EMPTY)
    return size


async def prepare_upload(
    upload: UploadFile, *, suffix: str, settings: Settings,
    tenant_id: UUID, project_id: UUID,
) -> PreparedUpload:
    """Validate and hash a bounded spooled upload before any permanent object write."""
    size = await _validate_content(upload, suffix, settings.max_upload_bytes)
    digest = hashlib.sha256()
    await upload.seek(0)
    while chunk := await upload.read(CHUNK_SIZE):
        digest.update(chunk)
    await upload.seek(0)
    return PreparedUpload(
        digest.hexdigest(), size, _object_key(tenant_id, "documents", suffix, project_id)
    )


def _validate_pdf(file: Any) -> None:
    try:
        reader = PdfReader(file, strict=True)
        if reader.is_encrypted:
            raise upload_http_error(UploadErrorCode.PDF_ENCRYPTED)
        if len(reader.pages) == 0:
            raise upload_http_error(UploadErrorCode.PDF_MALFORMED)
    except HTTPException:
        raise
    except Exception:
        raise upload_http_error(UploadErrorCode.PDF_MALFORMED) from None


def _validate_zip(file: Any, suffix: str, max_upload_bytes: int) -> None:
    with ZipFile(file) as archive:
        entries = archive.infolist()
        if len(entries) > 10_000:
            raise ValueError("Archive contains too many entries.")
        total_uncompressed = 0
        for entry in entries:
            if entry.flag_bits & 0x1:
                raise ValueError("Encrypted office documents are not supported.")
            total_uncompressed += entry.file_size
            if total_uncompressed > max_upload_bytes * 10:
                raise ValueError("Archive expands beyond the allowed limit.")
            if (
                entry.file_size > CHUNK_SIZE
                and entry.compress_size > 0
                and entry.file_size / entry.compress_size > 100
            ):
                raise ValueError("Archive compression ratio is unsafe.")

        names = {entry.filename.replace("\\", "/").lower() for entry in entries}
        required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
        if "[content_types].xml" not in names or required not in names:
            raise ValueError("Office document structure does not match its extension.")


async def _validate_content(upload: UploadFile, suffix: str, max_upload_bytes: int) -> int:
    size = await _measure_upload(upload, max_upload_bytes)
    sample = await upload.read(min(size, 64 * 1024))
    await upload.seek(0)
    if suffix == ".pdf":
        if not sample.startswith(b"%PDF-"):
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
        try:
            await run_in_threadpool(_validate_pdf, upload.file)
        finally:
            await upload.seek(0)
    elif suffix in {".doc", ".xls"}:
        if not sample.startswith(OLE_SIGNATURE):
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
    elif suffix in {".docx", ".xlsx"}:
        if not sample.startswith(b"PK"):
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
        else:
            try:
                await run_in_threadpool(_validate_zip, upload.file, suffix, max_upload_bytes)
            except (BadZipFile, ValueError):
                raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH) from None
            finally:
                await upload.seek(0)
    elif suffix == ".xml":
        normalized = sample.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
        lowered = sample.lower()
        invalid = (
            not normalized.startswith(b"<") or b"<!doctype" in lowered or b"<!entity" in lowered
        )
        if invalid:
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
    elif suffix == ".csv":
        try:
            sample.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH) from None
        else:
            if b"\x00" in sample:
                raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)
    return size


class LocalObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = settings.upload_root.resolve()
        self.max_upload_bytes = settings.max_upload_bytes

    async def save(
        self,
        tenant_id: UUID,
        category: str,
        upload: UploadFile,
        *,
        suffix: str,
        content_type: str,
        project_id: UUID | None = None,
        prepared: PreparedUpload | None = None,
    ) -> tuple[str, int]:
        del content_type
        try:
            size = (prepared.size_bytes if prepared else
                    await _validate_content(upload, suffix, self.max_upload_bytes))
        except Exception:
            await upload.close()
            raise
        storage_key = (prepared.storage_key if prepared else
                       _object_key(tenant_id, category, suffix, project_id))
        destination = (self.root / storage_key).resolve()
        if self.root not in destination.parents:
            await upload.close()
            raise HTTPException(status_code=400, detail="Invalid upload path.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("wb") as output:
                while chunk := await upload.read(CHUNK_SIZE):
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
        return storage_key, size

    async def delete_object(self, storage_key: str) -> None:
        self.delete(storage_key)

    def delete(self, storage_key: str) -> None:
        target = (self.root / storage_key).resolve()
        if self.root in target.parents:
            target.unlink(missing_ok=True)

    async def check(self) -> None:
        try:
            await run_in_threadpool(self.root.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise ObjectStorageUnavailableError("Local object storage is unavailable.") from exc

    async def stat_object(self, storage_key: str) -> StoredObjectMetadata:
        target = self.absolute_path(_validated_storage_key(storage_key))
        try:
            size_bytes = await run_in_threadpool(lambda: target.stat().st_size)
        except FileNotFoundError:
            raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING) from None
        except OSError:
            raise DocumentInputError(DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE) from None
        content_type, _ = mimetypes.guess_type(target.name)
        return StoredObjectMetadata(
            size_bytes=size_bytes,
            content_type=content_type,
            checksum_sha256=None,
            entity_tag=None,
        )

    async def download_to_path(
        self,
        storage_key: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadResult:
        target = self.absolute_path(_validated_storage_key(storage_key))

        def download() -> DownloadResult:
            try:
                with target.open("rb") as source:
                    return _stream_to_destination(source, destination, maximum_bytes)
            except FileNotFoundError:
                raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING) from None
            except DocumentInputError:
                raise
            except OSError:
                raise DocumentInputError(
                    DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
                ) from None

        return await run_in_threadpool(download)

    def absolute_path(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("Storage key resolves outside the upload root.")
        return target

    async def list_objects(
        self,
        prefix: str,
        *,
        maximum_items: int,
    ) -> tuple[StoredObjectEntry, ...]:
        if maximum_items < 1 or maximum_items > 1_000:
            raise ValueError("Object listing limit is outside the approved bound.")
        safe_prefix = _validated_storage_key(f"{prefix.rstrip('/')}/placeholder")
        prefix_path = (self.root / PurePosixPath(safe_prefix).parent).resolve()
        if self.root not in prefix_path.parents:
            raise ValueError("Object prefix resolves outside the upload root.")

        def collect() -> tuple[StoredObjectEntry, ...]:
            if not prefix_path.exists():
                return ()
            entries: list[StoredObjectEntry] = []
            for candidate in sorted(prefix_path.rglob("*")):
                if len(entries) >= maximum_items:
                    break
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if self.root not in resolved.parents:
                    continue
                relative = resolved.relative_to(self.root).as_posix()
                entries.append(
                    StoredObjectEntry(
                        storage_key=relative,
                        updated_at=datetime.fromtimestamp(
                            resolved.stat().st_mtime,
                            tz=UTC,
                        ),
                    )
                )
            return tuple(entries)

        return await run_in_threadpool(collect)


class S3ObjectStorage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.aws_secret_access_key or not settings.aws_endpoint_url_s3:
            raise ValueError("S3 object storage settings are incomplete.")
        self.bucket = settings.object_storage_bucket
        self.max_upload_bytes = settings.max_upload_bytes
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.aws_endpoint_url_s3,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
            region_name=settings.aws_region,
            config=Config(
                signature_version="s3v4",
                connect_timeout=settings.object_storage_connect_timeout_seconds,
                read_timeout=settings.object_storage_read_timeout_seconds,
                retries={
                    "max_attempts": settings.object_storage_max_attempts,
                    "mode": "standard",
                },
                s3={"addressing_style": "path"},
            ),
        )

    async def save(
        self,
        tenant_id: UUID,
        category: str,
        upload: UploadFile,
        *,
        suffix: str,
        content_type: str,
        project_id: UUID | None = None,
        prepared: PreparedUpload | None = None,
    ) -> tuple[str, int]:
        try:
            size = (prepared.size_bytes if prepared else
                    await _validate_content(upload, suffix, self.max_upload_bytes))
        except Exception:
            await upload.close()
            raise
        storage_key = (prepared.storage_key if prepared else
                       _object_key(tenant_id, category, suffix, project_id))
        try:
            await run_in_threadpool(
                partial(
                    self.client.upload_fileobj,
                    upload.file,
                    self.bucket,
                    storage_key,
                    ExtraArgs={"ContentType": content_type},
                )
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "Object storage upload failed provider=s3 error_type=%s",
                type(exc).__name__,
            )
            raise ObjectStorageUnavailableError("Object storage upload failed.") from None
        finally:
            await upload.close()
        return storage_key, size

    async def delete_object(self, storage_key: str) -> None:
        try:
            await run_in_threadpool(
                partial(self.client.delete_object, Bucket=self.bucket, Key=storage_key)
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "Object storage delete failed provider=s3 error_type=%s",
                type(exc).__name__,
            )
            raise ObjectStorageUnavailableError("Object storage delete failed.") from None

    async def check(self) -> None:
        try:
            await run_in_threadpool(partial(self.client.head_bucket, Bucket=self.bucket))
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "Object storage readiness check failed provider=s3 error_type=%s",
                type(exc).__name__,
            )
            raise ObjectStorageUnavailableError("Object storage is unavailable.") from None

    async def stat_object(self, storage_key: str) -> StoredObjectMetadata:
        safe_key = _validated_storage_key(storage_key)
        try:
            response = await run_in_threadpool(
                partial(self.client.head_object, Bucket=self.bucket, Key=safe_key)
            )
            size_bytes = int(response["ContentLength"])
            if size_bytes < 0 or size_bytes > self.max_upload_bytes:
                raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
            metadata = response.get("Metadata") or {}
            checksum = response.get("ChecksumSHA256") or metadata.get("sha256")
            return StoredObjectMetadata(
                size_bytes=size_bytes,
                content_type=_safe_content_type(response.get("ContentType")),
                checksum_sha256=_normalized_sha256(checksum),
                entity_tag=_safe_entity_tag(response.get("ETag")),
            )
        except DocumentInputError:
            raise
        except ClientError as exc:
            if _is_missing_object_error(exc):
                raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING) from None
            logger.warning(
                "Object storage metadata request failed provider=s3 error_type=%s",
                type(exc).__name__,
            )
            raise DocumentInputError(DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE) from None
        except Exception as exc:
            logger.warning(
                "Object storage metadata request failed provider=s3 error_type=%s",
                type(exc).__name__,
            )
            raise DocumentInputError(DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE) from None

    async def download_to_path(
        self,
        storage_key: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadResult:
        safe_key = _validated_storage_key(storage_key)

        def download() -> DownloadResult:
            body: Any | None = None
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=safe_key)
                body = response["Body"]
                declared_size = int(response["ContentLength"])
                if declared_size < 0 or declared_size > maximum_bytes:
                    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
                result = _stream_to_destination(body, destination, maximum_bytes)
                if result.byte_count != declared_size:
                    destination.unlink(missing_ok=True)
                    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
                checksum = _normalized_sha256(response.get("ChecksumSHA256"))
                if checksum is not None and not compare_digest(checksum, result.sha256):
                    destination.unlink(missing_ok=True)
                    raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
                return result
            except DocumentInputError:
                destination.unlink(missing_ok=True)
                raise
            except ClientError as exc:
                destination.unlink(missing_ok=True)
                if _is_missing_object_error(exc):
                    raise DocumentInputError(
                        DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING
                    ) from None
                logger.warning(
                    "Object storage download failed provider=s3 error_type=%s",
                    type(exc).__name__,
                )
                raise DocumentInputError(
                    DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
                ) from None
            except Exception as exc:
                destination.unlink(missing_ok=True)
                logger.warning(
                    "Object storage download failed provider=s3 error_type=%s",
                    type(exc).__name__,
                )
                raise DocumentInputError(
                    DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE
                ) from None
            finally:
                if body is not None:
                    try:
                        body.close()
                    except Exception:
                        pass

        return await run_in_threadpool(download)

    async def list_objects(
        self,
        prefix: str,
        *,
        maximum_items: int,
    ) -> tuple[StoredObjectEntry, ...]:
        if maximum_items < 1 or maximum_items > 1_000:
            raise ValueError("Object listing limit is outside the approved bound.")
        safe_prefix = _validated_storage_key(f"{prefix.rstrip('/')}/placeholder")
        normalized_prefix = f"{PurePosixPath(safe_prefix).parent.as_posix()}/"
        try:
            response = await run_in_threadpool(
                partial(
                    self.client.list_objects_v2,
                    Bucket=self.bucket,
                    Prefix=normalized_prefix,
                    MaxKeys=maximum_items,
                )
            )
        except (BotoCoreError, ClientError, OSError):
            raise ObjectStorageUnavailableError("Object storage listing failed.") from None
        entries: list[StoredObjectEntry] = []
        for item in response.get("Contents") or ():
            key = item.get("Key")
            modified = item.get("LastModified")
            if not isinstance(key, str) or not isinstance(modified, datetime):
                continue
            entries.append(
                StoredObjectEntry(
                    storage_key=_validated_storage_key(key),
                    updated_at=modified.astimezone(UTC),
                )
            )
        return tuple(entries)


@lru_cache
def get_upload_storage() -> UploadObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings)
