from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.services.ingestion.types import ConfirmedDocumentFormat, ExtractionMethod

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ChunkWarningCode(StrEnum):
    EMPTY_BLOCK_DROPPED = "empty_block_dropped"
    FORCED_SPLIT = "forced_split"
    OVERLAP_APPLIED = "overlap_applied"
    HEADER_CONTEXT_REPEATED = "header_context_repeated"


class SourceReferenceRole(StrEnum):
    PRIMARY = "primary"
    OVERLAP = "overlap"
    HEADER_CONTEXT = "header_context"


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    target_tokens: int = 400
    overlap_tokens: int = 50
    maximum_content_tokens: int = 480
    formatting_headroom_tokens: int = 32
    model_sequence_length: int = 512
    maximum_chunks: int = 100_000
    maximum_source_references: int = 2_048
    maximum_characters: int = 10_000_000
    maximum_heading_depth: int = 16
    maximum_heading_label_characters: int = 500
    maximum_warnings: int = 100

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("chunking policy values must be integers")
        if self.target_tokens <= 0 or self.maximum_content_tokens <= 0:
            raise ValueError("chunk token limits must be positive")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be non-negative and smaller than target_tokens")
        if self.target_tokens > self.maximum_content_tokens:
            raise ValueError("target_tokens cannot exceed maximum_content_tokens")
        if (
            self.maximum_content_tokens + self.formatting_headroom_tokens
            > self.model_sequence_length
        ):
            raise ValueError(
                "chunk content and formatting headroom exceed the model sequence limit"
            )
        if (
            min(
                self.maximum_chunks,
                self.maximum_source_references,
                self.maximum_characters,
                self.maximum_heading_depth,
                self.maximum_heading_label_characters,
            )
            <= 0
        ):
            raise ValueError("chunking collection and string limits must be positive")
        if self.maximum_warnings < 0:
            raise ValueError("maximum_warnings must be non-negative")

    @classmethod
    def from_settings(cls, settings: object) -> ChunkingPolicy:
        return cls(
            target_tokens=settings.document_chunk_target_tokens,
            overlap_tokens=settings.document_chunk_overlap_tokens,
            maximum_content_tokens=settings.document_chunk_max_tokens,
            formatting_headroom_tokens=settings.document_chunk_formatting_headroom_tokens,
            maximum_chunks=settings.document_max_chunks,
            maximum_source_references=settings.document_max_chunk_source_references,
            maximum_characters=settings.document_max_extracted_characters,
            maximum_heading_depth=settings.document_max_heading_depth,
            maximum_heading_label_characters=settings.document_max_heading_label_characters,
            maximum_warnings=settings.document_max_extraction_warnings,
        )


@dataclass(frozen=True, slots=True)
class ChunkSourceReference:
    block_ordinal: int
    role: SourceReferenceRole
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    extraction_method: ExtractionMethod

    def __post_init__(self) -> None:
        if not isinstance(self.block_ordinal, int) or isinstance(self.block_ordinal, bool):
            raise ValueError("block_ordinal must be an integer")
        if self.block_ordinal < 0:
            raise ValueError("block_ordinal must be non-negative")
        if not isinstance(self.role, SourceReferenceRole):
            raise ValueError("role must be a source-reference role")
        if not isinstance(self.extraction_method, ExtractionMethod):
            raise ValueError("extraction_method must be allowlisted")

    def to_jsonable(self) -> dict[str, object]:
        return {
            "block_ordinal": self.block_ordinal,
            "role": self.role.value,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "extraction_method": self.extraction_method.value,
        }


@dataclass(frozen=True, slots=True, init=False)
class CanonicalChunk:
    ordinal: int
    content: str
    token_count: int
    chunk_sha256: str
    source_references: tuple[ChunkSourceReference, ...]
    primary_source_block_ordinals: tuple[int, ...]
    overlap_source_block_ordinals: tuple[int, ...]
    context_source_block_ordinals: tuple[int, ...]
    source_block_ordinal_start: int
    source_block_ordinal_end: int
    page_numbers: tuple[int, ...]
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    heading_path: tuple[str, ...]
    extraction_methods: tuple[ExtractionMethod, ...]
    warning_codes: tuple[ChunkWarningCode, ...]

    def __init__(
        self,
        *,
        ordinal: int,
        content: str,
        token_count: int,
        chunk_sha256: str,
        source_references: Iterable[ChunkSourceReference],
        heading_path: Sequence[str],
        warning_codes: Iterable[ChunkWarningCode],
        policy: ChunkingPolicy,
    ) -> None:
        references = tuple(source_references)
        warnings = tuple(dict.fromkeys(warning_codes))
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise ValueError("chunk ordinal must be non-negative")
        if not isinstance(content, str) or not content:
            raise ValueError("chunk content must not be empty")
        if len(content) > policy.maximum_characters:
            raise ValueError("chunk content exceeds the character limit")
        if not isinstance(token_count, int) or isinstance(token_count, bool) or token_count <= 0:
            raise ValueError("token_count must be positive")
        if token_count > policy.maximum_content_tokens:
            raise ValueError("token_count exceeds the chunk ceiling")
        if not _SHA256.fullmatch(chunk_sha256):
            raise ValueError("chunk_sha256 must be lowercase SHA-256 hexadecimal")
        if not references or len(references) > policy.maximum_source_references:
            raise ValueError("source references are missing or exceed the configured limit")
        if len(warnings) > policy.maximum_warnings:
            raise ValueError("chunk warning count exceeds the configured limit")
        if any(not isinstance(code, ChunkWarningCode) for code in warnings):
            raise ValueError("chunk warnings must use stable codes")
        headings = tuple(heading_path)
        if len(headings) > policy.maximum_heading_depth or any(
            not label or len(label) > policy.maximum_heading_label_characters for label in headings
        ):
            raise ValueError("chunk heading path exceeds configured bounds")

        primary = _unique_ordinals(references, SourceReferenceRole.PRIMARY)
        if not primary:
            raise ValueError("a chunk must contain primary source coverage")
        overlap = _unique_ordinals(references, SourceReferenceRole.OVERLAP)
        context = _unique_ordinals(references, SourceReferenceRole.HEADER_CONTEXT)
        pages = tuple(
            sorted({ref.page_number for ref in references if ref.page_number is not None})
        )
        sheets = {ref.sheet_name for ref in references if ref.sheet_name is not None}
        if len(sheets) > 1:
            raise ValueError("a chunk cannot mix worksheets")
        rows = [
            value
            for ref in references
            if ref.role is SourceReferenceRole.PRIMARY
            for value in (ref.row_start, ref.row_end)
            if value is not None
        ]
        methods = tuple(dict.fromkeys(ref.extraction_method for ref in references))
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "token_count", token_count)
        object.__setattr__(self, "chunk_sha256", chunk_sha256)
        object.__setattr__(self, "source_references", references)
        object.__setattr__(self, "primary_source_block_ordinals", primary)
        object.__setattr__(self, "overlap_source_block_ordinals", overlap)
        object.__setattr__(self, "context_source_block_ordinals", context)
        object.__setattr__(self, "source_block_ordinal_start", min(primary))
        object.__setattr__(self, "source_block_ordinal_end", max(primary))
        object.__setattr__(self, "page_numbers", pages)
        object.__setattr__(self, "sheet_name", next(iter(sheets), None))
        object.__setattr__(self, "row_start", min(rows) if rows else None)
        object.__setattr__(self, "row_end", max(rows) if rows else None)
        object.__setattr__(self, "heading_path", headings)
        object.__setattr__(self, "extraction_methods", methods)
        object.__setattr__(self, "warning_codes", warnings)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "content": self.content,
            "token_count": self.token_count,
            "chunk_sha256": self.chunk_sha256,
            "source_references": [ref.to_jsonable() for ref in self.source_references],
            "primary_source_block_ordinals": list(self.primary_source_block_ordinals),
            "overlap_source_block_ordinals": list(self.overlap_source_block_ordinals),
            "context_source_block_ordinals": list(self.context_source_block_ordinals),
            "source_block_ordinal_start": self.source_block_ordinal_start,
            "source_block_ordinal_end": self.source_block_ordinal_end,
            "page_numbers": list(self.page_numbers),
            "sheet_name": self.sheet_name,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "heading_path": list(self.heading_path),
            "extraction_methods": [method.value for method in self.extraction_methods],
            "warning_codes": [code.value for code in self.warning_codes],
        }


@dataclass(frozen=True, slots=True)
class ChunkingStatistics:
    input_block_count: int
    retained_block_count: int
    dropped_empty_block_count: int
    chunk_count: int
    forced_split_count: int
    overlap_application_count: int
    repeated_header_context_count: int
    total_token_count: int
    warning_codes: tuple[ChunkWarningCode, ...]

    def __post_init__(self) -> None:
        warnings = tuple(dict.fromkeys(self.warning_codes))
        if any(not isinstance(code, ChunkWarningCode) for code in warnings):
            raise ValueError("warning_codes must contain stable chunk warning codes")
        object.__setattr__(self, "warning_codes", warnings)
        for field_name in self.__dataclass_fields__:
            if field_name == "warning_codes":
                continue
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.retained_block_count + self.dropped_empty_block_count != self.input_block_count:
            raise ValueError("retained and dropped block counts must equal input_block_count")
        if self.chunk_count == 0 or self.forced_split_count > self.retained_block_count:
            raise ValueError("chunking statistics contain inconsistent counts")

    def to_jsonable(self) -> dict[str, object]:
        return {
            field_name: (
                [code.value for code in self.warning_codes]
                if field_name == "warning_codes"
                else getattr(self, field_name)
            )
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    chunks: tuple[CanonicalChunk, ...]
    statistics: ChunkingStatistics
    source_content_sha256: str
    confirmed_format: ConfirmedDocumentFormat
    chunker_version: str
    tokenizer_name: str
    tokenizer_revision: str

    def __post_init__(self) -> None:
        chunks = tuple(self.chunks)
        object.__setattr__(self, "chunks", chunks)
        if not chunks:
            raise ValueError("chunking result must contain chunks")
        if tuple(chunk.ordinal for chunk in chunks) != tuple(range(len(chunks))):
            raise ValueError("chunk ordinals must be contiguous and zero-based")
        if self.statistics.chunk_count != len(chunks):
            raise ValueError("chunk statistics do not match the chunk collection")
        if not _SHA256.fullmatch(self.source_content_sha256):
            raise ValueError("source_content_sha256 must be lowercase SHA-256 hexadecimal")
        if not isinstance(self.confirmed_format, ConfirmedDocumentFormat):
            raise ValueError("confirmed_format must be a confirmed document format")
        for field_name, value, maximum in (
            ("chunker_version", self.chunker_version, 40),
            ("tokenizer_name", self.tokenizer_name, 160),
            ("tokenizer_revision", self.tokenizer_revision, 128),
        ):
            if (
                not isinstance(value, str)
                or not value
                or len(value) > maximum
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError(f"{field_name} is invalid")

    def to_jsonable(self) -> dict[str, object]:
        return {
            "chunks": [chunk.to_jsonable() for chunk in self.chunks],
            "statistics": self.statistics.to_jsonable(),
            "source_content_sha256": self.source_content_sha256,
            "confirmed_format": self.confirmed_format.value,
            "chunker_version": self.chunker_version,
            "tokenizer_name": self.tokenizer_name,
            "tokenizer_revision": self.tokenizer_revision,
        }


def _unique_ordinals(
    references: tuple[ChunkSourceReference, ...], role: SourceReferenceRole
) -> tuple[int, ...]:
    return tuple(dict.fromkeys(ref.block_ordinal for ref in references if ref.role is role))
