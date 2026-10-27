import asyncio
import logging
import os
import shutil
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from starlette.concurrency import run_in_threadpool

from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode

logger = logging.getLogger(__name__)
ALLOWED_DOCUMENT_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".csv"})


@dataclass(frozen=True, slots=True)
class TemporaryDocumentWorkspace:
    directory: Path
    input_path: Path
    suffix: str


@dataclass(frozen=True, slots=True)
class StaleWorkspaceCleanupResult:
    candidates: int
    removed: int
    failed: int


def validate_document_suffix(suffix: str) -> str:
    normalized = suffix.casefold()
    if suffix != normalized or normalized not in ALLOWED_DOCUMENT_SUFFIXES:
        raise DocumentInputError(DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED)
    return normalized


def _validated_root(configured_root: str | Path) -> Path:
    root = Path(configured_root)
    try:
        if root.is_symlink():
            raise OSError("unsafe temporary root")
        absolute = root.absolute()
        resolved = root.resolve(strict=True)
        if absolute != resolved or not resolved.is_dir() or resolved.parent == resolved:
            raise OSError("unsafe temporary root")
        root_stat = resolved.stat()
        if os.name == "posix":
            if root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) & 0o077:
                raise OSError("temporary root permissions are unsafe")
    except (OSError, RuntimeError):
        raise DocumentInputError(DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE) from None
    return resolved


def _create_workspace(configured_root: str | Path, suffix: str) -> TemporaryDocumentWorkspace:
    root = _validated_root(configured_root)
    for _ in range(3):
        directory = root / str(uuid4())
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            continue
        except OSError:
            raise DocumentInputError(
                DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
            ) from None

        resolved_directory = directory.resolve(strict=True)
        if resolved_directory.parent != root or resolved_directory.is_symlink():
            directory.rmdir()
            raise DocumentInputError(DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE)
        return TemporaryDocumentWorkspace(
            directory=resolved_directory,
            input_path=resolved_directory / f"input{suffix}",
            suffix=suffix,
        )
    raise DocumentInputError(DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE)


def _cleanup_workspace(configured_root: str | Path, directory: Path) -> None:
    root = _validated_root(configured_root)
    try:
        UUID(directory.name)
    except (TypeError, ValueError, AttributeError):
        raise OSError("unsafe temporary workspace") from None

    if directory.parent.resolve(strict=True) != root or directory == root:
        raise OSError("unsafe temporary workspace")
    if directory.is_symlink():
        directory.unlink(missing_ok=True)
        return
    if directory.exists():
        resolved = directory.resolve(strict=True)
        if resolved.parent != root:
            raise OSError("unsafe temporary workspace")
        shutil.rmtree(resolved)


def cleanup_stale_workspaces(
    configured_root: str | Path,
    *,
    cutoff: datetime,
    maximum_items: int,
    apply_changes: bool,
) -> StaleWorkspaceCleanupResult:
    if maximum_items < 1 or maximum_items > 1_000:
        raise OSError("workspace cleanup limit is outside the approved bound")
    root = _validated_root(configured_root)
    candidates = removed = failed = 0
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if candidates >= maximum_items:
            break
        try:
            UUID(directory.name)
            if directory.is_symlink() or not directory.is_dir():
                continue
            modified = datetime.fromtimestamp(directory.stat().st_mtime, tz=cutoff.tzinfo)
            if modified > cutoff:
                continue
            candidates += 1
            if apply_changes:
                _cleanup_workspace(root, directory)
                removed += 1
        except (OSError, RuntimeError, ValueError):
            failed += 1
    return StaleWorkspaceCleanupResult(candidates, removed, failed)


@asynccontextmanager
async def temporary_document_workspace(
    configured_root: str | Path,
    suffix: str,
) -> AsyncIterator[TemporaryDocumentWorkspace]:
    safe_suffix = validate_document_suffix(suffix)
    workspace = await run_in_threadpool(_create_workspace, configured_root, safe_suffix)
    active_exception = False
    try:
        yield workspace
    except BaseException:
        active_exception = True
        raise
    finally:
        cleanup = asyncio.create_task(
            run_in_threadpool(_cleanup_workspace, configured_root, workspace.directory)
        )
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            try:
                await cleanup
            except Exception:
                logger.error("Temporary document workspace cleanup failed")
            raise
        except Exception:
            logger.error("Temporary document workspace cleanup failed")
            if not active_exception:
                raise DocumentInputError(
                    DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
                ) from None
