import hashlib
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_worker_dependencies_are_exactly_pinned_without_changing_httpx() -> None:
    pyproject = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    constraints = (BACKEND_ROOT / "worker-constraints.txt").read_text(encoding="utf-8")

    for dependency in (
        '"fastembed==0.9.0"',
        '"onnxruntime==1.31.0"',
        '"numpy==2.5.4"',
        '"tokenizers==0.22.2"',
        '"huggingface-hub==1.33.0"',
    ):
        assert dependency in pyproject
    assert '"httpx>=0.28,<1"' in pyproject
    assert "httpx2" not in pyproject
    for dependency in (
        "fastembed==0.9.0",
        "onnxruntime==1.31.0",
        "numpy==2.5.4",
        "pillow==12.3.0",
        "tokenizers==0.22.2",
        "huggingface-hub==1.33.0",
        "httpx==0.28.1",
        "certifi==2026.7.22",
    ):
        assert dependency in constraints


def test_model_inventory_checksum_matches_release_configuration() -> None:
    manifest_path = BACKEND_ROOT / "model-artifacts" / "bge-small-en-v1.5.manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    environment = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")

    assert payload["model_revision"] == "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
    assert payload["dimensions"] == 384
    assert payload["license_identifier"] == "MIT"
    assert f"EMBEDDING_MODEL_MANIFEST_SHA256={manifest_sha256}" in environment


def test_worker_image_packages_model_offline_but_api_runtime_does_not() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    worker = dockerfile.split("FROM runtime-base AS ocr-worker", 1)[1].split(
        "FROM runtime-base AS runtime", 1
    )[0]
    api = dockerfile.split("FROM runtime-base AS runtime", 1)[1]

    assert "embedding-model-builder" in dockerfile
    assert "package_embedding_model.py" in dockerfile
    assert "--constraint worker-constraints.txt" in dockerfile
    assert "--constraint /tmp/worker-constraints.txt" in worker
    assert (
        "--manifest-sha256 609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0"
        in dockerfile
    )
    assert "COPY --from=embedding-model-builder /opt/wbs-models" in worker
    assert "HF_HUB_OFFLINE=1" in worker
    assert "local_files_only=True" in worker
    assert "USER wbs" in worker
    assert "chmod 0444" in worker
    assert "fastembed" not in api.casefold()
    assert "/opt/wbs-models" not in api


def test_model_builder_uses_fixed_sources_and_no_shell_execution() -> None:
    source = (BACKEND_ROOT / "scripts" / "package_embedding_model.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "shell=True" not in source
    assert "eval(" not in source
    assert "exec(" not in source
    assert "_ALLOWED_HOSTS" in source
