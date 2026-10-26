from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from itertools import islice
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from app.core.observability import record_embedding_batch, record_embedding_initialization
from app.services.ingestion.embeddings.base import EmbeddingPolicy, EmbeddingVector
from app.services.ingestion.embeddings.manifest import (
    VerifiedModelManifest,
    verify_model_manifest,
)
from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode

if TYPE_CHECKING:
    from app.core.config import Settings

_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
_READINESS_TEXT = "offline embedding readiness"


class _EmbeddingEngine(Protocol):
    def embed(
        self,
        documents: Iterable[str],
        *,
        batch_size: int,
        parallel: int | None,
    ) -> Iterable[Iterable[object]]: ...


EngineFactory = Callable[[Path, EmbeddingPolicy], _EmbeddingEngine]


def _create_fastembed_engine(root: Path, policy: EmbeddingPolicy) -> _EmbeddingEngine:
    try:
        from fastembed import TextEmbedding
    except (ImportError, OSError):
        raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE) from None
    try:
        return TextEmbedding(
            model_name="BAAI/bge-small-en-v1.5",
            cache_dir=str(root),
            threads=policy.cpu_threads,
            providers=["CPUExecutionProvider"],
            lazy_load=False,
            local_files_only=True,
            specific_model_path=str(root),
        )
    except Exception:
        raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE) from None


class FastEmbedProvider:
    provider_name = "fastembed"
    model_name = "BAAI/bge-small-en-v1.5"
    dimensions = 384

    def __init__(
        self,
        *,
        manifest: VerifiedModelManifest,
        policy: EmbeddingPolicy,
        engine_factory: EngineFactory = _create_fastembed_engine,
    ) -> None:
        if (
            manifest.provider != self.provider_name
            or manifest.model_name != self.model_name
            or manifest.dimensions != self.dimensions
        ):
            raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_MODEL_INVALID)
        self.model_revision = manifest.model_revision
        self.formatting_version = manifest.formatting_version
        self._manifest = manifest
        self._policy = policy
        self._engine_factory = engine_factory
        self._engine: _EmbeddingEngine | None = None
        self._engine_pid: int | None = None
        self._initialization_lock = threading.Lock()
        self._batch_semaphore = threading.BoundedSemaphore(policy.maximum_concurrent_batches)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        engine_factory: EngineFactory = _create_fastembed_engine,
        require_read_only: bool = False,
    ) -> FastEmbedProvider:
        return cls(
            manifest=verify_model_manifest(settings, require_read_only=require_read_only),
            policy=EmbeddingPolicy.from_settings(settings),
            engine_factory=engine_factory,
        )

    @staticmethod
    def format_document(text: str) -> str:
        return text

    @staticmethod
    def format_query(text: str) -> str:
        return _QUERY_INSTRUCTION + text

    def _engine_for_process(self) -> _EmbeddingEngine:
        pid = os.getpid()
        if self._engine is not None and self._engine_pid == pid:
            return self._engine
        with self._initialization_lock:
            if self._engine is not None and self._engine_pid == pid:
                return self._engine
            started = monotonic()
            try:
                engine = self._engine_factory(self._manifest.root, self._policy)
            except EmbeddingError:
                record_embedding_initialization(
                    duration_seconds=monotonic() - started,
                    outcome="unavailable",
                )
                raise
            except Exception:
                record_embedding_initialization(
                    duration_seconds=monotonic() - started,
                    outcome="unavailable",
                )
                raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE) from None
            self._engine = engine
            self._engine_pid = pid
            record_embedding_initialization(
                duration_seconds=monotonic() - started,
                outcome="success",
            )
            return engine

    def _collect_inputs(self, texts: Iterable[str]) -> tuple[str, ...]:
        collected: list[str] = []
        aggregate_characters = 0
        for text in texts:
            if (
                not isinstance(text, str)
                or not text
                or len(text) > self._policy.maximum_text_characters
            ):
                raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED)
            collected.append(text)
            aggregate_characters += len(text)
            if (
                len(collected) > self._policy.maximum_inputs
                or aggregate_characters > self._policy.maximum_aggregate_characters
            ):
                raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED)
        return tuple(collected)

    def _embed_batch(
        self,
        engine: _EmbeddingEngine,
        texts: tuple[str, ...],
    ) -> tuple[EmbeddingVector, ...]:
        started = monotonic()
        try:
            generated: Iterator[Iterable[object]] = iter(
                engine.embed(texts, batch_size=len(texts), parallel=None)
            )
            raw_vectors = tuple(islice(generated, len(texts) + 1))
            if len(raw_vectors) != len(texts):
                raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID)
            vectors = tuple(
                EmbeddingVector(values, dimensions=self.dimensions) for values in raw_vectors
            )
        except EmbeddingError:
            record_embedding_batch(
                duration_seconds=monotonic() - started,
                input_count=len(texts),
                outcome="invalid",
            )
            raise
        except Exception:
            record_embedding_batch(
                duration_seconds=monotonic() - started,
                input_count=len(texts),
                outcome="failed",
            )
            raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED) from None
        record_embedding_batch(
            duration_seconds=monotonic() - started,
            input_count=len(texts),
            outcome="success",
        )
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        collected = self._collect_inputs(texts)
        if not collected:
            return ()
        formatted = tuple(self.format_document(text) for text in collected)
        engine = self._engine_for_process()
        vectors: list[EmbeddingVector] = []
        with self._batch_semaphore:
            for start in range(0, len(formatted), self._policy.batch_size):
                vectors.extend(
                    self._embed_batch(engine, formatted[start : start + self._policy.batch_size])
                )
        if len(vectors) != len(formatted):
            raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID)
        return tuple(vectors)

    def embed_query(self, text: str) -> EmbeddingVector:
        collected = self._collect_inputs((text,))
        engine = self._engine_for_process()
        with self._batch_semaphore:
            return self._embed_batch(engine, (self.format_query(collected[0]),))[0]

    def warm_up(self) -> None:
        vector = self.embed_documents((_READINESS_TEXT,))[0]
        if vector.dimensions != self.dimensions:
            raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID)


_provider_lock = threading.Lock()
_provider_cache: tuple[int, tuple[object, ...], FastEmbedProvider] | None = None


def get_process_embedding_provider(settings: Settings) -> FastEmbedProvider:
    global _provider_cache
    key = (
        settings.embedding_provider,
        settings.embedding_model,
        settings.embedding_dimensions,
        settings.embedding_formatting_version,
        settings.embedding_model_path,
        settings.embedding_model_revision,
        settings.embedding_model_manifest_sha256,
        settings.embedding_tokenizer_revision,
        settings.embedding_tokenizer_sha256,
        settings.embedding_batch_size,
        settings.embedding_max_text_characters,
        settings.embedding_max_concurrent_batches,
        settings.embedding_cpu_threads,
        settings.document_max_chunks,
        settings.document_max_extracted_characters,
    )
    pid = os.getpid()
    if _provider_cache is not None and _provider_cache[:2] == (pid, key):
        return _provider_cache[2]
    with _provider_lock:
        if _provider_cache is not None and _provider_cache[:2] == (pid, key):
            return _provider_cache[2]
        provider = FastEmbedProvider.from_settings(settings, require_read_only=True)
        _provider_cache = (pid, key, provider)
        return provider
