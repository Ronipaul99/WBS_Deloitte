"""Step 7 bounded evidence artifacts. No model-selected scope or executable content."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.contracts import SourceScope
from app.services.llm.contracts import Contract, Identity, Sha256

Index = Annotated[int, Field(strict=True, ge=0, le=100000)]
Names = Annotated[
    tuple[Annotated[str, Field(min_length=1, max_length=500)], ...], Field(max_length=16)
]


def digest(value):
    if isinstance(value, Contract):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


class EvidenceError(ValueError):
    """Stable metadata-only error; never include source text or raw SQL."""


class ProcessingVersion(Contract):
    extractor_name: str = Field(min_length=1, max_length=80)
    extractor_version: str = Field(min_length=1, max_length=40)
    chunker_version: str = Field(min_length=1, max_length=40)
    embedding_provider: str = Field(min_length=1, max_length=40)
    embedding_model: str = Field(min_length=1, max_length=160)
    embedding_model_revision: str = Field(min_length=1, max_length=128)
    embedding_dimensions: Literal[384] = 384
    embedding_formatting_version: str = Field(min_length=1, max_length=80)


class EvidencePin(Contract):
    version: Literal["evidence_pin.v1"] = "evidence_pin.v1"
    scope: SourceScope
    processing: ProcessingVersion
    chunk_count: Index
    page_count: Annotated[int, Field(strict=True, ge=0, le=100000)]
    warning_codes: Annotated[
        tuple[Annotated[str, Field(max_length=160)], ...], Field(max_length=100)
    ] = ()


class SourceRef(Contract):
    block_ordinal: Index
    role: Literal["primary", "overlap", "header_context"]
    page_number: Annotated[int, Field(strict=True, ge=1, le=100000)] | None = None
    sheet_name: str | None = Field(default=None, max_length=160)
    row_start: Annotated[int, Field(strict=True, ge=1)] | None = None
    row_end: Annotated[int, Field(strict=True, ge=1)] | None = None
    extraction_method: Literal["native", "ocr"]
    table_index: Index | None = None
    row_index: Index | None = None


class ChunkDescriptor(Contract):
    chunk_id: Identity
    ordinal: Index
    chunk_sha256: Sha256
    text_sha256: Sha256
    metadata_sha256: Sha256
    characters: Annotated[int, Field(strict=True, ge=1, le=100000)]
    section_id: Sha256
    heading_path: Names = ()
    physical_pages: Annotated[
        tuple[Annotated[int, Field(strict=True, ge=1)], ...], Field(max_length=500)
    ] = ()
    source_references: Annotated[tuple[SourceRef, ...], Field(min_length=1, max_length=2048)]
    warning_codes: Annotated[
        tuple[Annotated[str, Field(max_length=160)], ...], Field(max_length=100)
    ] = ()
    printed_page_label: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def primary(self):
        if not any(r.role == "primary" for r in self.source_references):
            raise ValueError("chunk has no primary source")
        if tuple(sorted(set(self.physical_pages))) != self.physical_pages:
            raise ValueError("pages must be unique and ordered")
        return self


class CanonicalEvidenceChunk(Contract):
    descriptor: ChunkDescriptor
    content: Annotated[str, Field(min_length=1, max_length=100000)] = Field(repr=False)

    @model_validator(mode="after")
    def identity(self):
        if (
            len(self.content) != self.descriptor.characters
            or hashlib.sha256(self.content.encode()).hexdigest() != self.descriptor.text_sha256
        ):
            raise ValueError("canonical text identity mismatch")
        return self


class InventoryPage(Contract):
    pin_sha256: Sha256
    index: Index
    previous_sha256: Sha256 | None = None
    entries: Annotated[tuple[ChunkDescriptor, ...], Field(min_length=1, max_length=64)]


class InventoryManifest(Contract):
    version: Literal["inventory.v1"] = "inventory.v1"
    pin: EvidencePin
    root_sha256: Sha256
    page_count: Index
    chunk_count: Index


class ChunkPage(Contract):
    pin_sha256: Sha256
    after_ordinal: Annotated[int, Field(strict=True, ge=-1, le=100000)]
    chunks: Annotated[tuple[CanonicalEvidenceChunk, ...], Field(max_length=64)]
    next_ordinal: Index | None = None


class ReadingBatch(Contract):
    version: Literal["reading_batch.v1"] = "reading_batch.v1"
    inventory_sha256: Sha256
    budget_sha256: Sha256
    index: Index
    primary_chunk_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=64)]
    context_chunk_ids: Annotated[tuple[Identity, ...], Field(max_length=4)] = ()
    section_id: Sha256
    input_estimate: Annotated[int, Field(strict=True, ge=1)]
    accounting: Literal["approved_tokenizer", "utf8_upper_estimate"]
    blocked_reason: Literal["oversized_context", "run_budget_exhausted"] | None = None

    @model_validator(mode="after")
    def distinct(self):
        ids = self.primary_chunk_ids + self.context_chunk_ids
        if len(set(ids)) != len(ids):
            raise ValueError("primary and contextual chunk identities must be distinct")
        return self


class BatchOutcome(Contract):
    batch_sha256: Sha256
    state: Literal["assigned", "retrieved", "delivered", "processed", "failed", "blocked"]
    # Identity of a validated completed artifact, supplied by trusted controller.
    completion_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def completion(self):
        if (self.state == "processed") != (self.completion_sha256 is not None):
            raise ValueError("processed coverage requires a completed artifact")
        return self


class BatchCompletion(Contract):
    """Trusted controller receipt for a validated artifact, never a model assertion."""

    inventory_sha256: Sha256
    batch_sha256: Sha256
    primary_chunk_ids: Annotated[tuple[Identity, ...], Field(min_length=1, max_length=64)]
    artifact_sha256: Sha256
    truncated: Literal[False] = False


class CoveragePage(Contract):
    version: Literal["coverage_page.v1"] = "coverage_page.v1"
    inventory_sha256: Sha256
    index: Index
    outcomes: Annotated[tuple[BatchOutcome, ...], Field(max_length=128)]


class ToolPolicy(Contract):
    max_calls: Annotated[int, Field(strict=True, ge=1, le=120)] = 40
    max_repeats: Annotated[int, Field(strict=True, ge=1, le=5)] = 3
    response_bytes: Annotated[int, Field(strict=True, ge=512, le=48000)] = 16000
    response_tokens: Annotated[int, Field(strict=True, ge=128, le=48000)] = 16000
    total_bytes: Annotated[int, Field(strict=True, ge=512, le=2000000)] = 640000
    total_tokens: Annotated[int, Field(strict=True, ge=128, le=2000000)] = 640000


class RequestCount(Contract):
    request_sha256: Sha256
    count: Annotated[int, Field(strict=True, ge=1, le=5)]


class ToolUsage(Contract):
    binding: Sha256
    policy: ToolPolicy
    calls: Annotated[int, Field(strict=True, ge=0, le=120)] = 0
    reserved_bytes: Annotated[int, Field(strict=True, ge=0, le=6000000)] = 0
    reserved_tokens: Annotated[int, Field(strict=True, ge=0, le=6000000)] = 0
    requests: Annotated[tuple[RequestCount, ...], Field(max_length=120)] = ()


class EvidenceArtifact(Contract):
    """Allowed only nested inside the existing fenced orchestration artifact."""

    kind: Literal[
        "inventory_manifest.v1", "inventory_page.v1", "reading_batch.v1", "coverage_page.v1"
    ]
    payload: InventoryManifest | InventoryPage | ReadingBatch | CoveragePage

    @model_validator(mode="after")
    def correct_kind(self):
        expected = {
            "inventory_manifest.v1": InventoryManifest,
            "inventory_page.v1": InventoryPage,
            "reading_batch.v1": ReadingBatch,
            "coverage_page.v1": CoveragePage,
        }[self.kind]
        if not isinstance(self.payload, expected):
            raise ValueError("evidence artifact kind mismatch")
        if len(self.model_dump_json().encode()) > 300000:
            raise ValueError("evidence artifact must be paged")
        return self
