import hashlib
import json

import pytest

from scripts.package_embedding_model import package_model


def generated_manifest(tmp_path, *, artifact_path: str = "fixture.txt"):
    content = "immutable fixture\n"
    payload = {
        "files": [
            {
                "path": artifact_path,
                "size": len(content.encode("ascii")),
                "sha256": hashlib.sha256(content.encode("ascii")).hexdigest(),
                "generated_content": content,
            }
        ]
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_model_builder_validates_manifest_and_generated_artifact_integrity(tmp_path) -> None:
    manifest, digest = generated_manifest(tmp_path)
    destination = tmp_path / "model"

    package_model(manifest, destination, digest)

    assert (destination / "fixture.txt").read_text(encoding="ascii") == "immutable fixture\n"
    assert (destination / "model-manifest.json").read_bytes() == manifest.read_bytes()


def test_model_builder_rejects_manifest_tampering_before_packaging(tmp_path) -> None:
    manifest, _digest = generated_manifest(tmp_path)

    with pytest.raises(ValueError, match="manifest integrity"):
        package_model(manifest, tmp_path / "model", "a" * 64)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "nested/file"])
def test_model_builder_rejects_unsafe_artifact_paths(tmp_path, path) -> None:
    manifest, digest = generated_manifest(tmp_path, artifact_path=path)

    with pytest.raises(ValueError, match="file path"):
        package_model(manifest, tmp_path / "model", digest)
