import math
from dataclasses import FrozenInstanceError

import pytest
from chunking_fixtures import CharacterTokenizer, extraction_result

from app.services.ingestion.chunk_types import ChunkingPolicy
from app.services.ingestion.chunking import DocumentChunker
from app.services.ingestion.embeddings.base import (
    EmbeddingPolicy,
    EmbeddingVector,
    embed_canonical_chunks,
)
from app.services.ingestion.errors import EmbeddingError, EmbeddingErrorCode
from app.services.ingestion.types import ConfirmedDocumentFormat


def vector(value: float = 0.25) -> EmbeddingVector:
    return EmbeddingVector((value for _ in range(384)), dimensions=384)


def canonical_chunks():
    source = extraction_result(
        ConfirmedDocumentFormat.DOCX,
        [{"text": "private synthetic scope content", "heading_path": ("Scope",)}],
    )
    policy = ChunkingPolicy(
        target_tokens=60,
        overlap_tokens=12,
        maximum_content_tokens=80,
        formatting_headroom_tokens=32,
        maximum_chunks=100,
        maximum_source_references=20,
        maximum_characters=10_000,
        maximum_heading_depth=8,
        maximum_heading_label_characters=100,
        maximum_warnings=10,
    )
    return DocumentChunker(tokenizer=CharacterTokenizer(), policy=policy).chunk(source).chunks


def test_embedding_vector_is_finite_dimensioned_immutable_and_redacted() -> None:
    result = vector()

    assert result.dimensions == 384
    assert all(math.isfinite(value) for value in result.values)
    assert "0.25" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.values = ()


@pytest.mark.parametrize(
    "values",
    [
        [0.0] * 383,
        [0.0] * 385,
        [0.0] * 383 + [float("nan")],
        [0.0] * 383 + [float("inf")],
        [0.0] * 383 + [True],
        [0.0] * 383 + ["0.1"],
        [0.0] * 383 + [1 + 2j],
    ],
)
def test_embedding_vector_rejects_invalid_runtime_output(values) -> None:
    with pytest.raises(EmbeddingError) as error:
        EmbeddingVector(values, dimensions=384)
    assert error.value.code is EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID


def test_canonical_chunk_handoff_preserves_order_identity_and_hides_payloads() -> None:
    chunks = canonical_chunks()

    class Provider:
        provider_name = "fastembed"
        model_name = "BAAI/bge-small-en-v1.5"
        model_revision = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
        dimensions = 384
        formatting_version = "bge-small-en-v1.5-format-v1"

        def embed_documents(self, texts):
            assert tuple(texts) == tuple(chunk.content for chunk in chunks)
            return tuple(vector(index / 100) for index, _ in enumerate(texts))

        def embed_query(self, text):
            return vector()

    result = embed_canonical_chunks(
        chunks,
        provider=Provider(),
        policy=EmbeddingPolicy(),
    )

    assert tuple(item.ordinal for item in result.items) == tuple(chunk.ordinal for chunk in chunks)
    assert tuple(item.chunk_sha256 for item in result.items) == tuple(
        chunk.chunk_sha256 for chunk in chunks
    )
    assert result.metadata.model_revision == Provider.model_revision
    rendered = repr(result)
    assert all(chunk.content not in rendered for chunk in chunks)
    assert "0.01" not in rendered


def test_canonical_handoff_rejects_missing_vectors_without_partial_result() -> None:
    chunks = canonical_chunks()

    class MissingProvider:
        provider_name = "fastembed"
        model_name = "BAAI/bge-small-en-v1.5"
        model_revision = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
        dimensions = 384
        formatting_version = "bge-small-en-v1.5-format-v1"

        def embed_documents(self, texts):
            return ()

        def embed_query(self, text):
            return vector()

    with pytest.raises(EmbeddingError) as error:
        embed_canonical_chunks(
            chunks,
            provider=MissingProvider(),
            policy=EmbeddingPolicy(),
        )
    assert error.value.code is EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID
