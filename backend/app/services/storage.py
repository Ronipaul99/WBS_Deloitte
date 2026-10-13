from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings


class LocalObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = settings.upload_root.resolve()
        self.max_upload_bytes = settings.max_upload_bytes

    async def save(self, tenant_id: UUID, category: str, upload: UploadFile) -> tuple[str, int]:
        safe_name = Path(upload.filename or "upload.bin").name
        relative = Path(str(tenant_id)) / category / str(uuid4()) / safe_name
        destination = (self.root / relative).resolve()
        if self.root not in destination.parents:
            raise HTTPException(status_code=400, detail="Invalid upload file name.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with destination.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="File exceeds the configured upload limit.",
                        )
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        if size == 0:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Empty files are not allowed.")

        return relative.as_posix(), size

    def delete(self, storage_key: str) -> None:
        target = (self.root / storage_key).resolve()
        if self.root in target.parents:
            target.unlink(missing_ok=True)

    def absolute_path(self, storage_key: str) -> Path:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("Storage key resolves outside the upload root.")
        return target
