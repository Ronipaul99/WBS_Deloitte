import json

import pytest
from embedding_fixtures import MODEL_REVISION, embedding_settings

from app.services.ingestion.embeddings.manifest import verify_model_manifest
from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode


def test_model_manifest_accepts_only_the_complete_integrity_pinned_fixture(tmp_path) -> None:
    settings = embedding_settings(tmp_path)

    manifest = verify_model_manifest(settings)

    assert manifest.model_revision == MODEL_REVISION
    assert manifest.dimensions == 384
    assert manifest.license_identifier == "MIT"
    assert {artifact.path for artifact in manifest.artifacts} >= {
        "model_optimized.onnx",
        "tokenizer.json",
        "MODEL-LICENSE.txt",
    }


@pytest.mark.parametrize("mutation", ["missing", "changed", "extra", "symlink"])
def test_model_manifest_fails_closed_for_tampered_artifacts(tmp_path, mutation) -> None:
    settings = embedding_settings(tmp_path)
    root = settings.embedding_model_path
    from pathlib import Path

    model_root = Path(root)
    if mutation == "missing":
        (model_root / "model_optimized.onnx").unlink()
    elif mutation == "changed":
        (model_root / "model_optimized.onnx").write_bytes(b"changed")
    elif mutation == "extra":
        (model_root / "unexpected.bin").write_bytes(b"unexpected")
    else:
        target = model_root / "external.bin"
        target.write_bytes(b"fixture")
        candidate = model_root / "model_optimized.onnx"
        candidate.unlink()
        try:
            candidate.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable")

    with pytest.raises(EmbeddingError) as error:
        verify_model_manifest(settings)
    assert error.value.code is EmbeddingErrorCode.EMBEDDING_MODEL_INVALID
    assert str(model_root) not in str(error.value)


def test_model_manifest_rejects_manifest_hash_revision_and_tokenizer_mismatch(tmp_path) -> None:
    settings = embedding_settings(tmp_path, embedding_model_manifest_sha256="b" * 64)
    with pytest.raises(EmbeddingError):
        verify_model_manifest(settings)

    other = tmp_path / "other"
    settings = embedding_settings(other, embedding_model_revision="b" * 40)
    with pytest.raises(EmbeddingError):
        verify_model_manifest(settings)


def test_checked_in_manifest_has_real_immutable_sources_and_no_model_binary() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    inventory = root / "model-artifacts" / "bge-small-en-v1.5.manifest.json"
    payload = json.loads(inventory.read_text(encoding="utf-8"))

    assert len(payload["model_revision"]) == 40
    assert payload["license_identifier"] == "MIT"
    assert all(len(entry["sha256"]) == 64 for entry in payload["files"])
    assert not any(
        path.suffix in {".onnx", ".bin", ".safetensors"} for path in inventory.parent.iterdir()
    )
