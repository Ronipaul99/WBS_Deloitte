from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.ingestion.scanning import ClamAVScanner

if TYPE_CHECKING:
    from app.services.ingestion.extractors import OcrRunner
    from app.services.ingestion.registry import ExtractorRegistry

IngestionReadinessCategory = Literal[
    "redis",
    "malware_scanner",
    "embedding_model",
    "ocr_runtime",
    "extractor_registry",
    "tokenizer_runtime",
    "embedding_runtime",
]


class IngestionReadinessError(RuntimeError):
    def __init__(self, category: IngestionReadinessCategory) -> None:
        self.category = category
        super().__init__(f"{category} unavailable")


def application_migration_heads() -> set[str]:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def database_migration_heads(db: AsyncSession) -> set[str]:
    result = await db.execute(text("SELECT version_num FROM alembic_version"))
    return {str(row[0]) for row in result}


async def database_is_at_migration_head(db: AsyncSession) -> bool:
    return await database_migration_heads(db) == application_migration_heads()


async def redis_is_ready(settings: Settings) -> None:
    client: Redis | None = None
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        if not await client.ping():
            raise RuntimeError("Redis ping was not acknowledged")
    except Exception:
        raise IngestionReadinessError("redis") from None
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def clamav_is_ready(settings: Settings) -> None:
    try:
        await ClamAVScanner(settings).check()
    except Exception:
        raise IngestionReadinessError("malware_scanner") from None


def embedding_model_path_is_ready(settings: Settings) -> None:
    path = Path(settings.embedding_model_path)
    try:
        has_readable_file = (
            path.is_dir()
            and os.access(path, os.R_OK)
            and any(entry.is_file() and os.access(entry, os.R_OK) for entry in path.rglob("*"))
        )
    except OSError:
        has_readable_file = False
    if not has_readable_file:
        raise IngestionReadinessError("embedding_model")


def ocr_runtime_is_ready(settings: Settings, runner: OcrRunner | None = None) -> None:
    try:
        from app.services.ingestion.extractors import PdfExtractionPolicy, SubprocessOcrRunner

        policy = PdfExtractionPolicy.from_settings(settings)
        if not (runner or SubprocessOcrRunner()).is_ready(policy):
            raise RuntimeError
    except Exception:
        raise IngestionReadinessError("ocr_runtime") from None


def extractor_registry_is_ready(
    registry: ExtractorRegistry | None = None,
    *,
    settings: Settings | None = None,
) -> None:
    try:
        if registry is None:
            from app.services.ingestion.registry import get_release_extractor_registry

            registry = get_release_extractor_registry(settings)
        registry.validate_release_completeness()
    except Exception:
        raise IngestionReadinessError("extractor_registry") from None


def tokenizer_runtime_is_ready(settings: Settings, tokenizer: object | None = None) -> None:
    try:
        if tokenizer is None:
            from app.services.ingestion.tokenizer import LocalBgeTokenizer

            tokenizer = LocalBgeTokenizer.from_settings(settings)
        if getattr(tokenizer, "name", None) != settings.embedding_model:
            raise RuntimeError
        if getattr(tokenizer, "revision", None) != settings.embedding_tokenizer_revision:
            raise RuntimeError
        if getattr(tokenizer, "maximum_sequence_length", None) != 512:
            raise RuntimeError
        tokenizer.self_check()
    except Exception:
        raise IngestionReadinessError("tokenizer_runtime") from None


def embedding_runtime_is_ready(settings: Settings, provider: object | None = None) -> None:
    try:
        if provider is None:
            from app.services.ingestion.embeddings.fastembed_provider import (
                get_process_embedding_provider,
            )

            provider = get_process_embedding_provider(settings)
        if (
            getattr(provider, "provider_name", None) != settings.embedding_provider
            or getattr(provider, "model_name", None) != settings.embedding_model
            or getattr(provider, "model_revision", None) != settings.embedding_model_revision
            or getattr(provider, "dimensions", None) != settings.embedding_dimensions
            or getattr(provider, "formatting_version", None)
            != settings.embedding_formatting_version
        ):
            raise RuntimeError
        provider.warm_up()
    except Exception:
        raise IngestionReadinessError("embedding_runtime") from None


async def api_ingestion_is_ready(settings: Settings) -> None:
    if settings.document_ingestion_enabled:
        await redis_is_ready(settings)


async def worker_ingestion_is_ready(
    settings: Settings,
    *,
    extractor_registry: ExtractorRegistry | None = None,
    ocr_runner: OcrRunner | None = None,
    tokenizer: object | None = None,
    embedding_provider: object | None = None,
) -> None:
    if not settings.document_ingestion_enabled:
        return
    await redis_is_ready(settings)
    await clamav_is_ready(settings)
    embedding_model_path_is_ready(settings)
    tokenizer_runtime_is_ready(settings, tokenizer)
    embedding_runtime_is_ready(settings, embedding_provider)
    ocr_runtime_is_ready(settings, ocr_runner)
    extractor_registry_is_ready(extractor_registry, settings=settings)
