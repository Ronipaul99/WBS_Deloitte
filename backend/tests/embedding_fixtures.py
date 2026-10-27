from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.core.config import Settings
from app.services.ingestion.embeddings.manifest import VerifiedModelManifest

MODEL_REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
MODEL_FILES = {
    "MODEL-LICENSE.txt": b"synthetic MIT license fixture",
    "config.json": b"{}",
    "model_optimized.onnx": b"synthetic onnx fixture",
    "ort_config.json": b"{}",
    "special_tokens_map.json": b"{}",
    "tokenizer-revision.txt": f"{MODEL_REVISION}\n".encode("ascii"),
    "tokenizer.json": b"{}",
    "tokenizer_config.json": b"{}",
    "vocab.txt": b"[UNK]\n",
}


def create_model_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "bge-small-en-v1.5"
    root.mkdir(parents=True)
    entries = []
    for name, content in MODEL_FILES.items():
        (root / name).write_bytes(content)
        entries.append(
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    payload = {
        "schema_version": 1,
        "provider": "fastembed",
        "model_name": "BAAI/bge-small-en-v1.5",
        "artifact_repository": "synthetic/test",
        "model_revision": MODEL_REVISION,
        "upstream_model_revision": MODEL_REVISION,
        "dimensions": 384,
        "formatting_version": "bge-small-en-v1.5-format-v1",
        "license_identifier": "MIT",
        "files": entries,
    }
    manifest = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (root / "model-manifest.json").write_bytes(manifest)
    return (
        root,
        hashlib.sha256(manifest).hexdigest(),
        hashlib.sha256(MODEL_FILES["tokenizer.json"]).hexdigest(),
    )


def embedding_settings(tmp_path: Path, **overrides: object) -> Settings:
    root, manifest_sha256, tokenizer_sha256 = create_model_fixture(tmp_path)
    values: dict[str, object] = {
        "embedding_model_path": str(root),
        "embedding_model_revision": MODEL_REVISION,
        "embedding_model_manifest_sha256": manifest_sha256,
        "embedding_tokenizer_revision": MODEL_REVISION,
        "embedding_tokenizer_sha256": tokenizer_sha256,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def verified_manifest(root: Path) -> VerifiedModelManifest:
    return VerifiedModelManifest(
        root=root,
        provider="fastembed",
        model_name="BAAI/bge-small-en-v1.5",
        model_revision=MODEL_REVISION,
        dimensions=384,
        formatting_version="bge-small-en-v1.5-format-v1",
        license_identifier="MIT",
        artifacts=(),
    )
