from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode

if TYPE_CHECKING:
    from app.core.config import Settings

_MANIFEST_FILE = "model-manifest.json"
_MAX_MANIFEST_BYTES = 128 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
_MAX_MODEL_BYTES = 2 * 1024 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FILES = frozenset(
    {
        "MODEL-LICENSE.txt",
        "config.json",
        "model_optimized.onnx",
        "ort_config.json",
        "special_tokens_map.json",
        "tokenizer-revision.txt",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    }
)


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedModelManifest:
    root: Path
    provider: str
    model_name: str
    model_revision: str
    dimensions: int
    formatting_version: str
    license_identifier: str
    artifacts: tuple[ModelArtifact, ...]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


def _artifact_from_json(value: object) -> ModelArtifact:
    if not isinstance(value, dict):
        raise ValueError
    path_value = value.get("path")
    size = value.get("size")
    sha256 = value.get("sha256")
    if not isinstance(path_value, str):
        raise ValueError
    path = PurePosixPath(path_value)
    if path.is_absolute() or len(path.parts) != 1 or path_value in {"", ".", ".."}:
        raise ValueError
    if any(ord(character) < 32 or ord(character) == 127 for character in path_value):
        raise ValueError
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or size > _MAX_ARTIFACT_BYTES
    ):
        raise ValueError
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ValueError
    return ModelArtifact(path=path_value, size=size, sha256=sha256)


def verify_model_manifest(
    settings: Settings,
    *,
    require_read_only: bool = False,
) -> VerifiedModelManifest:
    try:
        expected_manifest_sha256 = settings.embedding_model_manifest_sha256
        expected_revision = settings.embedding_model_revision
        if not expected_manifest_sha256 or not expected_revision:
            raise ValueError

        configured_root = Path(settings.embedding_model_path)
        root = configured_root.resolve(strict=True)
        manifest_path = root / _MANIFEST_FILE
        resolved_manifest = manifest_path.resolve(strict=True)
        if (
            _path_has_symlink(configured_root)
            or not root.is_dir()
            or resolved_manifest.parent != root
            or manifest_path.is_symlink()
            or not resolved_manifest.is_file()
            or not os.access(resolved_manifest, os.R_OK)
            or resolved_manifest.stat().st_size > _MAX_MANIFEST_BYTES
        ):
            raise ValueError

        manifest_bytes = resolved_manifest.read_bytes()
        if not hmac.compare_digest(
            hashlib.sha256(manifest_bytes).hexdigest(), expected_manifest_sha256
        ):
            raise ValueError
        payload = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError
        if (
            payload.get("provider") != settings.embedding_provider
            or payload.get("model_name") != settings.embedding_model
            or payload.get("model_revision") != expected_revision
            or payload.get("dimensions") != settings.embedding_dimensions
            or payload.get("formatting_version") != settings.embedding_formatting_version
            or payload.get("license_identifier") != "MIT"
        ):
            raise ValueError

        raw_artifacts = payload.get("files")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise ValueError
        artifacts = tuple(_artifact_from_json(value) for value in raw_artifacts)
        if sum(artifact.size for artifact in artifacts) > _MAX_MODEL_BYTES:
            raise ValueError
        names = tuple(artifact.path for artifact in artifacts)
        if len(names) != len(set(names)) or set(names) != _REQUIRED_FILES:
            raise ValueError

        actual_names = {entry.name for entry in root.iterdir() if entry.name != _MANIFEST_FILE}
        if actual_names != _REQUIRED_FILES:
            raise ValueError
        for artifact in artifacts:
            unresolved = root / artifact.path
            resolved = unresolved.resolve(strict=True)
            if (
                unresolved.is_symlink()
                or resolved.parent != root
                or not resolved.is_file()
                or not os.access(resolved, os.R_OK)
                or resolved.stat().st_size != artifact.size
                or not hmac.compare_digest(_file_sha256(resolved), artifact.sha256)
            ):
                raise ValueError
            if require_read_only and os.access(resolved, os.W_OK):
                raise ValueError
        if require_read_only and os.access(root, os.W_OK):
            raise ValueError
        if require_read_only and os.access(resolved_manifest, os.W_OK):
            raise ValueError

        revision = (root / "tokenizer-revision.txt").read_text(encoding="ascii").strip()
        tokenizer = next(item for item in artifacts if item.path == "tokenizer.json")
        if (
            not hmac.compare_digest(revision, expected_revision)
            or settings.embedding_tokenizer_revision != expected_revision
            or settings.embedding_tokenizer_sha256 != tokenizer.sha256
        ):
            raise ValueError
        return VerifiedModelManifest(
            root=root,
            provider=str(payload["provider"]),
            model_name=str(payload["model_name"]),
            model_revision=str(payload["model_revision"]),
            dimensions=int(payload["dimensions"]),
            formatting_version=str(payload["formatting_version"]),
            license_identifier=str(payload["license_identifier"]),
            artifacts=artifacts,
        )
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError, StopIteration):
        raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_MODEL_INVALID) from None
