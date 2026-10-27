from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Protocol, runtime_checkable

from app.services.ingestion.chunk_types import CanonicalChunk
from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True, slots=True)
class EmbeddingPolicy:
    dimensions: int = 384
    batch_size: int = 32
    maximum_inputs: int = 100_000
    maximum_text_characters: int = 100_000
    maximum_aggregate_characters: int = 10_000_000
    maximum_concurrent_batches: int = 1
    cpu_threads: int = 2

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.dimensions != 384:
            raise ValueError("dimensions must be 384")
        if self.batch_size > 256:
            raise ValueError("batch_size exceeds the approved maximum")
        if self.maximum_concurrent_batches > 8:
            raise ValueError("maximum_concurrent_batches exceeds the approved maximum")
        if self.cpu_threads > 32:
            raise ValueError("cpu_threads exceeds the approved maximum")

    @classmethod
    def from_settings(cls, settings: object) -> EmbeddingPolicy:
        return cls(
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            maximum_inputs=settings.document_max_chunks,
            maximum_text_characters=settings.embedding_max_text_characters,
            maximum_aggregate_characters=settings.document_max_extracted_characters,
            maximum_concurrent_batches=settings.embedding_max_concurrent_batches,
            cpu_threads=settings.embedding_cpu_threads,
        )


@dataclass(frozen=True, slots=True, init=False)
class EmbeddingVector:
    values: tuple[float, ...] = field(repr=False)

    def __init__(self, values: Iterable[object], *, dimensions: int) -> None:
        collected: list[float] = []
        try:
            for value in values:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise ValueError
                converted = float(value)
                if not math.isfinite(converted):
                    raise ValueError
                collected.append(converted)
                if len(collected) > dimensions:
                    raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID) from None
        if len(collected) != dimensions:
            raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID)
        object.__setattr__(self, "values", tuple(collected))

    @property
    def dimensions(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    provider_name: str
    model_name: str
    model_revision: str
    dimensions: int
    formatting_version: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("provider_name", self.provider_name, 40),
            ("model_name", self.model_name, 160),
            ("model_revision", self.model_revision, 128),
            ("formatting_version", self.formatting_version, 80),
        ):
            if not isinstance(value, str) or not value or len(value) > maximum:
                raise ValueError(f"{name} is invalid")
            if not _SAFE_NAME.fullmatch(value):
                raise ValueError(f"{name} is invalid")
        if self.dimensions != 384:
            raise ValueError("embedding metadata dimensions must be 384")


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    chunk: CanonicalChunk = field(repr=False)
    vector: EmbeddingVector = field(repr=False)

    @property
    def ordinal(self) -> int:
        return self.chunk.ordinal

    @property
    def chunk_sha256(self) -> str:
        return self.chunk.chunk_sha256


@dataclass(frozen=True, slots=True)
class EmbeddingBatchResult:
    items: tuple[EmbeddedChunk, ...]
    metadata: EmbeddingMetadata

    def __post_init__(self) -> None:
        items = tuple(self.items)
        object.__setattr__(self, "items", items)
        if tuple(item.ordinal for item in items) != tuple(range(len(items))):
            raise ValueError("embedded chunk ordinals must be contiguous and zero-based")
        if any(
            not _SHA256.fullmatch(item.chunk_sha256)
            or item.vector.dimensions != self.metadata.dimensions
            for item in items
        ):
            raise ValueError("embedded chunk identity or vector dimensions are invalid")


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    model_revision: str
    dimensions: int
    formatting_version: str

    def embed_documents(self, texts: Sequence[str]) -> Sequence[EmbeddingVector]: ...

    def embed_query(self, text: str) -> EmbeddingVector: ...


def embed_canonical_chunks(
    chunks: Iterable[CanonicalChunk],
    *,
    provider: EmbeddingProvider,
    policy: EmbeddingPolicy,
) -> EmbeddingBatchResult:
    collected: list[CanonicalChunk] = []
    for chunk in chunks:
        if not isinstance(chunk, CanonicalChunk):
            raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED)
        collected.append(chunk)
        if len(collected) > policy.maximum_inputs:
            raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED)
    if tuple(chunk.ordinal for chunk in collected) != tuple(range(len(collected))):
        raise EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED)

    vectors = tuple(provider.embed_documents(tuple(chunk.content for chunk in collected)))
    if len(vectors) != len(collected):
        raise EmbeddingError(EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID)
    metadata = EmbeddingMetadata(
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        model_revision=provider.model_revision,
        dimensions=provider.dimensions,
        formatting_version=provider.formatting_version,
    )
    return EmbeddingBatchResult(
        items=tuple(
            EmbeddedChunk(chunk=chunk, vector=vector)
            for chunk, vector in zip(collected, vectors, strict=True)
        ),
        metadata=metadata,
    )
