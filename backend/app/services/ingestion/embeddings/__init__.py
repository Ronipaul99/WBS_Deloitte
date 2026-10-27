"""Offline, worker-only document embedding contracts."""

from app.services.ingestion.embeddings.base import (
    EmbeddedChunk,
    EmbeddingBatchResult,
    EmbeddingMetadata,
    EmbeddingPolicy,
    EmbeddingProvider,
    EmbeddingVector,
    embed_canonical_chunks,
)

__all__ = [
    "EmbeddedChunk",
    "EmbeddingBatchResult",
    "EmbeddingMetadata",
    "EmbeddingPolicy",
    "EmbeddingProvider",
    "EmbeddingVector",
    "embed_canonical_chunks",
]
