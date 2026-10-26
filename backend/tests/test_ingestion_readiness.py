from unittest.mock import AsyncMock

import pytest
from extraction_fixtures import complete_fake_extractors
from fastapi import HTTPException

from app.api.dependencies import require_document_ingestion_enabled
from app.core.config import Settings
from app.services import readiness
from app.services.ingestion.registry import ExtractorRegistry


def ingestion_settings(model_path: str, **overrides) -> Settings:
    values = {
        "app_env": "test",
        "document_ingestion_enabled": True,
        "database_url": "postgresql://runtime:secret@db.example.test/wbs",
        "direct_database_url": "postgresql://migration:secret@db.example.test/wbs",
        "storage_backend": "s3",
        "object_storage_bucket": "assets",
        "aws_endpoint_url_s3": "https://storage.example.test",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "redis_url": "rediss://worker:redis-secret@redis.internal.example.test:6380/0",
        "tasks_eager": False,
        "auto_create_tables": False,
        "embedding_model_path": model_path,
        "embedding_model_revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        "embedding_model_manifest_sha256": "a" * 64,
        "embedding_tokenizer_revision": "aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        "embedding_tokenizer_sha256": (
            "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
        ),
        "clamav_host": "clamav.internal.example.test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def test_api_readiness_checks_dispatch_dependency_without_loading_model(
    tmp_path, monkeypatch
) -> None:
    settings = ingestion_settings(str(tmp_path / "model-not-in-api-image"))
    redis_check = AsyncMock()

    def unexpected_model_check(_settings: Settings) -> None:
        raise AssertionError("API readiness attempted to inspect the worker model")

    async def unexpected_scanner_check(_settings: Settings) -> None:
        raise AssertionError("API readiness attempted to contact the malware scanner")

    def unexpected_registry_check(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness attempted to construct the extractor registry")

    def unexpected_ocr_check(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness attempted to inspect the OCR runtime")

    def unexpected_tokenizer_check(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness attempted to inspect the tokenizer runtime")

    def unexpected_embedding_check(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness attempted to construct the embedding runtime")

    monkeypatch.setattr(readiness, "redis_is_ready", redis_check)
    monkeypatch.setattr(readiness, "embedding_model_path_is_ready", unexpected_model_check)
    monkeypatch.setattr(readiness, "clamav_is_ready", unexpected_scanner_check)
    monkeypatch.setattr(readiness, "extractor_registry_is_ready", unexpected_registry_check)
    monkeypatch.setattr(readiness, "ocr_runtime_is_ready", unexpected_ocr_check)
    monkeypatch.setattr(readiness, "tokenizer_runtime_is_ready", unexpected_tokenizer_check)
    monkeypatch.setattr(readiness, "embedding_runtime_is_ready", unexpected_embedding_check)

    await readiness.api_ingestion_is_ready(settings)

    redis_check.assert_awaited_once_with(settings)


async def test_worker_readiness_accepts_readable_packaged_model(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "bge-small-en-v1.5"
    model_path.mkdir()
    (model_path / "model.onnx").write_bytes(b"model-fixture")
    settings = ingestion_settings(str(model_path))
    redis_check = AsyncMock()
    scanner_check = AsyncMock()
    monkeypatch.setattr(readiness, "redis_is_ready", redis_check)
    monkeypatch.setattr(readiness, "clamav_is_ready", scanner_check)
    monkeypatch.setattr(readiness, "ocr_runtime_is_ready", lambda *_args, **_kwargs: None)

    class ReadyTokenizer:
        name = "BAAI/bge-small-en-v1.5"
        revision = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
        maximum_sequence_length = 512

        def self_check(self) -> None:
            return None

    tokenizer = ReadyTokenizer()

    class ReadyEmbeddingProvider:
        provider_name = "fastembed"
        model_name = "BAAI/bge-small-en-v1.5"
        model_revision = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
        dimensions = 384
        formatting_version = "bge-small-en-v1.5-format-v1"

        def warm_up(self) -> None:
            return None

    provider = ReadyEmbeddingProvider()

    await readiness.worker_ingestion_is_ready(
        settings,
        extractor_registry=ExtractorRegistry(complete_fake_extractors()),
        tokenizer=tokenizer,
        embedding_provider=provider,
    )

    redis_check.assert_awaited_once_with(settings)
    scanner_check.assert_awaited_once_with(settings)

    await readiness.worker_ingestion_is_ready(
        settings,
        tokenizer=tokenizer,
        embedding_provider=provider,
    )


def test_worker_readiness_rejects_unreadable_model_path(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "bge-small-en-v1.5"
    model_path.mkdir()
    (model_path / "model.onnx").write_bytes(b"model-fixture")
    settings = ingestion_settings(str(model_path))
    monkeypatch.setattr(readiness.os, "access", lambda *_args: False)

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.embedding_model_path_is_ready(settings)

    assert error.value.category == "embedding_model"
    assert str(model_path) not in str(error.value)


async def test_redis_readiness_error_hides_secret_and_private_endpoint(
    tmp_path, monkeypatch
) -> None:
    redis_secret = "redis-release-secret"
    private_endpoint = "private-redis.internal.example.test"
    settings = ingestion_settings(
        str(tmp_path),
        redis_url=f"rediss://worker:{redis_secret}@{private_endpoint}:6380/0",
    )

    class FailingRedis:
        async def ping(self):
            raise RuntimeError(f"failed {settings.redis_url}")

        async def aclose(self):
            return None

    monkeypatch.setattr(
        readiness.Redis,
        "from_url",
        lambda *_args, **_kwargs: FailingRedis(),
    )

    with pytest.raises(readiness.IngestionReadinessError) as error:
        await readiness.redis_is_ready(settings)

    safe_error = str(error.value)
    assert error.value.category == "redis"
    assert redis_secret not in safe_error
    assert private_endpoint not in safe_error


async def test_clamav_readiness_uses_scanner_check_and_hides_dependency_details(
    tmp_path, monkeypatch
) -> None:
    settings = ingestion_settings(str(tmp_path))

    class FailingScanner:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def check(self) -> None:
            raise RuntimeError("sensitive scanner dependency detail")

    monkeypatch.setattr(readiness, "ClamAVScanner", FailingScanner)

    with pytest.raises(readiness.IngestionReadinessError) as error:
        await readiness.clamav_is_ready(settings)

    assert error.value.category == "malware_scanner"
    assert "sensitive scanner dependency detail" not in str(error.value)


def test_disabled_ingestion_guard_returns_stable_service_unavailable() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(HTTPException) as error:
        require_document_ingestion_enabled(settings)

    assert error.value.status_code == 503
    assert error.value.detail == {
        "code": "DOCUMENT_INGESTION_DISABLED",
        "message": "Document ingestion is unavailable.",
    }
