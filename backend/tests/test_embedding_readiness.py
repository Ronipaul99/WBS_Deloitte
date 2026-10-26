from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import readiness


class ReadyProvider:
    provider_name = "fastembed"
    model_name = "BAAI/bge-small-en-v1.5"
    model_revision = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
    dimensions = 384
    formatting_version = "bge-small-en-v1.5-format-v1"

    def warm_up(self) -> None:
        return None


def settings() -> Settings:
    return Settings(
        _env_file=None,
        embedding_model_revision=ReadyProvider.model_revision,
        embedding_model_manifest_sha256="a" * 64,
    )


def test_embedding_runtime_readiness_accepts_matching_warmed_provider() -> None:
    readiness.embedding_runtime_is_ready(settings(), ReadyProvider())


@pytest.mark.parametrize("field", ["model_revision", "dimensions", "formatting_version"])
def test_embedding_runtime_readiness_fails_closed_with_safe_category(field) -> None:
    provider = ReadyProvider()
    setattr(provider, field, "wrong" if field != "dimensions" else 768)

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.embedding_runtime_is_ready(settings(), provider)
    assert error.value.category == "embedding_runtime"
    assert "wrong" not in str(error.value)


def test_embedding_runtime_readiness_redacts_warmup_failure() -> None:
    marker = "private-model-path-endpoint-vector-content-marker"

    class FailingProvider(ReadyProvider):
        def warm_up(self) -> None:
            raise RuntimeError(marker)

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.embedding_runtime_is_ready(settings(), FailingProvider())
    assert error.value.category == "embedding_runtime"
    assert marker not in str(error.value)


def test_api_readiness_source_has_no_fastembed_or_onnx_dependency() -> None:
    source = Path(readiness.__file__).read_text(encoding="utf-8")
    api_body = source.split("async def api_ingestion_is_ready", 1)[1].split(
        "async def worker_ingestion_is_ready", 1
    )[0]

    assert "fastembed" not in api_body
    assert "onnx" not in api_body
    assert "embedding_runtime_is_ready" not in api_body
