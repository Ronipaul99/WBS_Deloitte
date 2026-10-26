from __future__ import annotations

import hashlib
from uuid import UUID

from app.services.ingestion.chunk_types import (
    CanonicalChunk,
    ChunkingPolicy,
    ChunkSourceReference,
    SourceReferenceRole,
)
from app.services.ingestion.embeddings.base import (
    EmbeddedChunk,
    EmbeddingBatchResult,
    EmbeddingMetadata,
    EmbeddingVector,
)
from app.services.ingestion.repository import ProcessingCounts, ProcessingIdentity
from app.services.ingestion.types import ExtractionMethod

MODEL_REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
FORMATTING_VERSION = "bge-small-en-v1.5-format-v1"


def processing_identity(*, chunker_version: str = "1.0.0") -> ProcessingIdentity:
    return ProcessingIdentity(
        document_content_sha256="a" * 64,
        extractor_name="synthetic-extractor",
        extractor_version="1.0.0",
        chunker_version=chunker_version,
        embedding_provider="fastembed",
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_model_revision=MODEL_REVISION,
        embedding_dimensions=384,
        embedding_formatting_version=FORMATTING_VERSION,
    )


def embedding_result(count: int = 2) -> EmbeddingBatchResult:
    policy = ChunkingPolicy(
        target_tokens=60,
        overlap_tokens=10,
        maximum_content_tokens=80,
        formatting_headroom_tokens=32,
        maximum_chunks=100,
        maximum_source_references=20,
        maximum_characters=10_000,
        maximum_heading_depth=8,
        maximum_heading_label_characters=100,
        maximum_warnings=10,
    )
    items = []
    for ordinal in range(count):
        content = f"Synthetic persistence scope line {ordinal + 1}."
        reference = ChunkSourceReference(
            block_ordinal=ordinal,
            role=SourceReferenceRole.PRIMARY,
            page_number=ordinal + 1,
            sheet_name=None,
            row_start=None,
            row_end=None,
            extraction_method=ExtractionMethod.NATIVE,
        )
        chunk = CanonicalChunk(
            ordinal=ordinal,
            content=content,
            token_count=8,
            chunk_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            source_references=(reference,),
            heading_path=("Scope",),
            warning_codes=(),
            policy=policy,
        )
        vector_values = [0.0] * 384
        vector_values[ordinal % 384] = 1.0
        items.append(
            EmbeddedChunk(
                chunk=chunk,
                vector=EmbeddingVector(vector_values, dimensions=384),
            )
        )
    return EmbeddingBatchResult(
        items=tuple(items),
        metadata=EmbeddingMetadata(
            provider_name="fastembed",
            model_name="BAAI/bge-small-en-v1.5",
            model_revision=MODEL_REVISION,
            dimensions=384,
            formatting_version=FORMATTING_VERSION,
        ),
    )


def processing_counts(result: EmbeddingBatchResult) -> ProcessingCounts:
    return ProcessingCounts(
        page_count=len(result.items),
        worksheet_count=0,
        block_count=len(result.items),
        chunk_count=len(result.items),
    )


def synthetic_ids() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    return tuple(
        UUID(value)
        for value in (
            "10000000-0000-0000-0000-000000000001",
            "20000000-0000-0000-0000-000000000001",
            "30000000-0000-0000-0000-000000000001",
            "40000000-0000-0000-0000-000000000001",
            "50000000-0000-0000-0000-000000000001",
        )
    )
