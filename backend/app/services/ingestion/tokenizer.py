from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.services.ingestion.errors import ChunkingError, ChunkingErrorCode
from app.services.ingestion.types import validate_safe_identifier

if TYPE_CHECKING:
    from app.core.config import Settings

_TOKENIZER_FILE = "tokenizer.json"
_REVISION_FILE = "tokenizer-revision.txt"
_MAX_TOKENIZER_BYTES = 32 * 1024 * 1024


@runtime_checkable
class TokenizerAdapter(Protocol):
    name: str
    revision: str
    maximum_sequence_length: int

    def encode(self, text: str) -> tuple[int, ...]: ...

    def decode(self, token_ids: Sequence[int]) -> str: ...

    def count(self, text: str) -> int: ...

    def self_check(self) -> None: ...


class LocalBgeTokenizer:
    """Offline adapter for one integrity-pinned tokenizer artifact."""

    name = "BAAI/bge-small-en-v1.5"
    maximum_sequence_length = 512

    def __init__(self, *, tokenizer: object, revision: str) -> None:
        self._tokenizer = tokenizer
        self.revision = revision

    @classmethod
    def from_settings(cls, settings: Settings) -> LocalBgeTokenizer:
        revision = settings.embedding_tokenizer_revision
        expected_sha256 = settings.embedding_tokenizer_sha256
        if not revision or not expected_sha256:
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID)
        try:
            validate_safe_identifier(revision, field_name="tokenizer_revision", maximum_length=128)
        except ValueError:
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID) from None

        root = Path(settings.embedding_model_path)
        tokenizer_path = root / _TOKENIZER_FILE
        revision_path = root / _REVISION_FILE
        try:
            resolved_root = root.resolve(strict=True)
            resolved_tokenizer = tokenizer_path.resolve(strict=True)
            resolved_revision = revision_path.resolve(strict=True)
            if (
                not resolved_root.is_dir()
                or root.is_symlink()
                or resolved_tokenizer.parent != resolved_root
                or resolved_revision.parent != resolved_root
                or tokenizer_path.is_symlink()
                or revision_path.is_symlink()
                or not resolved_tokenizer.is_file()
                or not resolved_revision.is_file()
                or not os.access(resolved_tokenizer, os.R_OK)
                or not os.access(resolved_revision, os.R_OK)
            ):
                raise OSError
            if (
                resolved_tokenizer.stat().st_size > _MAX_TOKENIZER_BYTES
                or resolved_revision.stat().st_size > 256
            ):
                raise OSError
            artifact = resolved_tokenizer.read_bytes()
            if len(artifact) > _MAX_TOKENIZER_BYTES:
                raise OSError
            packaged_revision = resolved_revision.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID) from None

        actual_sha256 = hashlib.sha256(artifact).hexdigest()
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID)
        if not hmac.compare_digest(packaged_revision, revision):
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID)

        try:
            from tokenizers import Tokenizer
        except (ImportError, OSError):
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_UNAVAILABLE) from None
        try:
            tokenizer = Tokenizer.from_file(str(resolved_tokenizer))
        except Exception:
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID) from None
        adapter = cls(tokenizer=tokenizer, revision=revision)
        adapter.self_check()
        return adapter

    def encode(self, text: str) -> tuple[int, ...]:
        if not isinstance(text, str):
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED)
        try:
            return tuple(self._tokenizer.encode(text, add_special_tokens=True).ids)
        except Exception:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED) from None

    def decode(self, token_ids: Sequence[int]) -> str:
        if any(
            not isinstance(token_id, int) or isinstance(token_id, bool) for token_id in token_ids
        ):
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED)
        try:
            return str(self._tokenizer.decode(list(token_ids), skip_special_tokens=True))
        except Exception:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED) from None

    def count(self, text: str) -> int:
        return len(self.encode(text))

    def self_check(self) -> None:
        token_ids = self.encode("bounded tokenizer readiness")
        if not token_ids or len(token_ids) >= self.maximum_sequence_length:
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID)
