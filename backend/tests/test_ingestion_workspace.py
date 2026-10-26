import asyncio
import os
from contextlib import AsyncExitStack

import pytest

from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.ingestion.workspace import (
    _cleanup_workspace,
    temporary_document_workspace,
)


def secure_root(path):
    path.mkdir()
    if os.name == "posix":
        path.chmod(0o700)
    return path


async def test_workspace_is_unique_private_and_removed_after_success(tmp_path) -> None:
    root = secure_root(tmp_path / "processing")
    async with AsyncExitStack() as stack:
        first = await stack.enter_async_context(temporary_document_workspace(root, ".pdf"))
        second = await stack.enter_async_context(temporary_document_workspace(root, ".pdf"))
        first.input_path.write_bytes(b"one")
        second.input_path.write_bytes(b"two")
        assert first.directory != second.directory
        assert first.input_path.name == "input.pdf"
        assert first.input_path.parent.parent == root.resolve()
        if os.name == "posix":
            assert first.directory.stat().st_mode & 0o077 == 0
    assert list(root.iterdir()) == []


async def test_workspace_cleans_up_after_consumer_failure(tmp_path) -> None:
    root = secure_root(tmp_path / "processing")
    directory = None
    with pytest.raises(RuntimeError, match="consumer failed"):
        async with temporary_document_workspace(root, ".xlsx") as workspace:
            directory = workspace.directory
            workspace.input_path.write_bytes(b"fixture")
            raise RuntimeError("consumer failed")
    assert directory is not None and not directory.exists()


async def test_workspace_cleans_up_after_cancellation(tmp_path) -> None:
    root = secure_root(tmp_path / "processing")
    entered = asyncio.Event()
    release = asyncio.Event()
    directory = None

    async def run() -> None:
        nonlocal directory
        async with temporary_document_workspace(root, ".csv") as workspace:
            directory = workspace.directory
            workspace.input_path.write_bytes(b"fixture")
            entered.set()
            await release.wait()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert directory is not None and not directory.exists()


async def test_workspace_cleans_up_after_hard_timeout(tmp_path) -> None:
    root = secure_root(tmp_path / "processing")
    directory = None
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.5):
            async with temporary_document_workspace(root, ".docx") as workspace:
                directory = workspace.directory
                workspace.input_path.write_bytes(b"fixture")
                await asyncio.sleep(5)
    assert directory is not None and not directory.exists()


@pytest.mark.parametrize("suffix", ["../secret.pdf", ".exe", "PDF", ""])
async def test_workspace_rejects_untrusted_suffixes(tmp_path, suffix: str) -> None:
    root = secure_root(tmp_path / "processing")
    with pytest.raises(DocumentInputError) as error:
        async with temporary_document_workspace(root, suffix):
            pass
    assert error.value.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
    assert list(root.iterdir()) == []


def test_cleanup_refuses_root_or_unrelated_directory(tmp_path) -> None:
    root = secure_root(tmp_path / "processing")
    unrelated = secure_root(tmp_path / "unrelated")

    with pytest.raises(OSError):
        _cleanup_workspace(root, root)
    with pytest.raises(OSError):
        _cleanup_workspace(root, unrelated)

    assert root.exists()
    assert unrelated.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires privileges")
async def test_workspace_rejects_symlink_root(tmp_path) -> None:
    actual = secure_root(tmp_path / "actual")
    link = tmp_path / "processing"
    link.symlink_to(actual, target_is_directory=True)

    with pytest.raises(DocumentInputError) as error:
        async with temporary_document_workspace(link, ".pdf"):
            pass
    assert error.value.code == DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE
