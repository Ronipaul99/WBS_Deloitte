import logging
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
CHUNK_SIZE = 1024 * 1024
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


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
    ) -> tuple[str, int]: ...

    async def delete_object(self, storage_key: str) -> None: ...

    async def check(self) -> None: ...


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
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="File exceeds the configured upload limit.",
            )
    await upload.seek(0)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty files are not allowed.")
    return size


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
    invalid = False

    if suffix == ".pdf":
        invalid = not sample.startswith(b"%PDF-")
    elif suffix in {".doc", ".xls"}:
        invalid = not sample.startswith(OLE_SIGNATURE)
    elif suffix in {".docx", ".xlsx"}:
        if not sample.startswith(b"PK"):
            invalid = True
        else:
            try:
                await run_in_threadpool(_validate_zip, upload.file, suffix, max_upload_bytes)
            except (BadZipFile, ValueError):
                invalid = True
            finally:
                await upload.seek(0)
    elif suffix == ".xml":
        normalized = sample.lstrip(b"\xef\xbb\xbf\x00\t\r\n ")
        lowered = sample.lower()
        invalid = (
            not normalized.startswith(b"<")
            or b"<!doctype" in lowered
            or b"<!entity" in lowered
        )
    elif suffix == ".csv":
        try:
            sample.decode("utf-8-sig")
        except UnicodeDecodeError:
            invalid = True
        else:
            invalid = b"\x00" in sample

    if invalid:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file content does not match its extension.",
        )
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
    ) -> tuple[str, int]:
        del content_type
        try:
            size = await _validate_content(upload, suffix, self.max_upload_bytes)
        except Exception:
            await upload.close()
            raise
        storage_key = _object_key(tenant_id, category, suffix, project_id)
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

    def absolute_path(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("Storage key resolves outside the upload root.")
        return target


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
    ) -> tuple[str, int]:
        try:
            size = await _validate_content(upload, suffix, self.max_upload_bytes)
        except Exception:
            await upload.close()
            raise
        storage_key = _object_key(tenant_id, category, suffix, project_id)
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


@lru_cache
def get_upload_storage() -> UploadObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings)
