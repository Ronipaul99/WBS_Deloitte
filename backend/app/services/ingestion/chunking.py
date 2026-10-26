from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, replace

from app.core.observability import record_document_chunking
from app.services.ingestion.chunk_types import (
    CanonicalChunk,
    ChunkingPolicy,
    ChunkingResult,
    ChunkingStatistics,
    ChunkSourceReference,
    ChunkWarningCode,
    SourceReferenceRole,
)
from app.services.ingestion.errors import (
    ChunkingError,
    ChunkingErrorCode,
    map_unexpected_chunking_failure,
)
from app.services.ingestion.normalization import normalize_extracted_text
from app.services.ingestion.tokenizer import TokenizerAdapter
from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionResult,
)

CHUNKER_VERSION = "1.0.0"
_HASH_DOMAIN = "wbs-canonical-chunk-v1"
_TABLE_TYPES = frozenset({ExtractedBlockType.TABLE_ROW, ExtractedBlockType.WORKSHEET_ROW})


@dataclass(frozen=True, slots=True)
class _NormalizedBlock:
    block: ExtractedBlock
    text: str
    scope: tuple[object, ...]
    is_header: bool
    header: _NormalizedBlock | None = None


@dataclass(frozen=True, slots=True)
class _Segment:
    source: _NormalizedBlock
    text: str
    role: SourceReferenceRole = SourceReferenceRole.PRIMARY
    forced_split: bool = False


class DocumentChunker:
    name = "deterministic-source-chunker"
    version = CHUNKER_VERSION

    def __init__(self, *, tokenizer: TokenizerAdapter, policy: ChunkingPolicy) -> None:
        if not isinstance(policy, ChunkingPolicy):
            raise ValueError("policy must be a validated ChunkingPolicy")
        if not isinstance(tokenizer, TokenizerAdapter):
            raise ValueError("tokenizer must implement TokenizerAdapter")
        if tokenizer.maximum_sequence_length != policy.model_sequence_length:
            raise ChunkingError(ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID)
        self._tokenizer = tokenizer
        self._policy = policy

    def chunk(self, extraction: ExtractionResult) -> ChunkingResult:
        started = time.monotonic()
        try:
            result = self._chunk(extraction)
        except ChunkingError as exc:
            record_document_chunking(
                document_format=_safe_format(extraction),
                duration_seconds=time.monotonic() - started,
                outcome="rejected",
                error_code=exc.code.value,
            )
            raise
        except Exception as exc:
            mapped = map_unexpected_chunking_failure(exc)
            record_document_chunking(
                document_format=_safe_format(extraction),
                duration_seconds=time.monotonic() - started,
                outcome="failed",
                error_code=mapped.code.value,
            )
            raise mapped from exc
        record_document_chunking(
            document_format=result.confirmed_format.value,
            duration_seconds=time.monotonic() - started,
            outcome="success",
            error_code="none",
            input_blocks=result.statistics.input_block_count,
            output_chunks=result.statistics.chunk_count,
            total_tokens=result.statistics.total_token_count,
            forced_splits=result.statistics.forced_split_count,
            overlap_applications=result.statistics.overlap_application_count,
            dropped_empty_blocks=result.statistics.dropped_empty_block_count,
        )
        return result

    def _chunk(self, extraction: ExtractionResult) -> ChunkingResult:
        if not isinstance(extraction, ExtractionResult):
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED)
        normalized, dropped = self._normalize_blocks(extraction)
        if not normalized:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_NORMALIZATION_FAILED)
        if sum(len(item.text) for item in normalized) > self._policy.maximum_characters:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)

        segments: list[_Segment] = []
        forced_split_blocks = 0
        for item in normalized:
            block_segments = self._split_block(item)
            if len(block_segments) > 1:
                forced_split_blocks += 1
            segments.extend(block_segments)

        groups = self._group_primary_segments(segments)
        if len(groups) > self._policy.maximum_chunks:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        chunks: list[CanonicalChunk] = []
        overlap_applications = 0
        repeated_headers = 0
        for ordinal, primary_group in enumerate(groups):
            rendered = self._add_header_context(primary_group)
            if any(segment.role is SourceReferenceRole.HEADER_CONTEXT for segment in rendered):
                repeated_headers += 1
            if (
                ordinal
                and self._policy.overlap_tokens
                and self._overlap_compatible(groups[ordinal - 1], primary_group)
            ):
                overlap = self._overlap_segment(groups[ordinal - 1], rendered)
                if overlap is not None:
                    insert_at = 1 if rendered[0].role is SourceReferenceRole.HEADER_CONTEXT else 0
                    rendered.insert(insert_at, overlap)
                    overlap_applications += 1
            chunks.append(
                self._build_chunk(
                    ordinal=ordinal,
                    segments=rendered,
                    extraction=extraction,
                )
            )

        retained_ordinals = {item.block.ordinal for item in normalized}
        covered_ordinals = {
            ordinal for chunk in chunks for ordinal in chunk.primary_source_block_ordinals
        }
        if retained_ordinals != covered_ordinals:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_COVERAGE_FAILED)

        result_warnings: list[ChunkWarningCode] = []
        if dropped:
            result_warnings.append(ChunkWarningCode.EMPTY_BLOCK_DROPPED)
        if forced_split_blocks:
            result_warnings.append(ChunkWarningCode.FORCED_SPLIT)
        if overlap_applications:
            result_warnings.append(ChunkWarningCode.OVERLAP_APPLIED)
        if repeated_headers:
            result_warnings.append(ChunkWarningCode.HEADER_CONTEXT_REPEATED)
        if len(result_warnings) > self._policy.maximum_warnings:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)

        statistics = ChunkingStatistics(
            input_block_count=len(extraction.blocks),
            retained_block_count=len(normalized),
            dropped_empty_block_count=dropped,
            chunk_count=len(chunks),
            forced_split_count=forced_split_blocks,
            overlap_application_count=overlap_applications,
            repeated_header_context_count=repeated_headers,
            total_token_count=sum(chunk.token_count for chunk in chunks),
            warning_codes=tuple(result_warnings),
        )
        return ChunkingResult(
            chunks=tuple(chunks),
            statistics=statistics,
            source_content_sha256=extraction.source_content_sha256,
            confirmed_format=extraction.confirmed_format,
            chunker_version=self.version,
            tokenizer_name=self._tokenizer.name,
            tokenizer_revision=self._tokenizer.revision,
        )

    def _normalize_blocks(self, extraction: ExtractionResult) -> tuple[list[_NormalizedBlock], int]:
        normalized: list[_NormalizedBlock] = []
        dropped = 0
        region_by_sheet: dict[str | None, int] = {}
        headers: dict[tuple[object, ...], _NormalizedBlock] = {}
        for block in extraction.blocks:
            text = normalize_extracted_text(block.text)
            if not text:
                dropped += 1
                continue
            is_table = block.block_type in _TABLE_TYPES
            is_header = is_table and block.metadata.get("is_header") is True
            table_index = block.metadata.get("table_index")
            if is_table and table_index is None:
                sheet_key = block.sheet_name
                current_region = region_by_sheet.get(sheet_key, 0)
                if is_header:
                    current_region += 1
                    region_by_sheet[sheet_key] = current_region
                table_index = current_region
            scope = (
                extraction.confirmed_format.value,
                block.sheet_name,
                block.heading_path,
                "table" if is_table else "text",
                table_index if is_table else None,
            )
            item = _NormalizedBlock(
                block=block,
                text=text,
                scope=scope,
                is_header=is_header,
                header=headers.get(scope),
            )
            if is_header:
                headers[scope] = item
            elif is_table and scope in headers:
                item = replace(item, header=headers[scope])
            normalized.append(item)
        return normalized, dropped

    def _split_block(self, item: _NormalizedBlock) -> list[_Segment]:
        maximum_tokens = self._policy.maximum_content_tokens
        if item.header is not None and item.header.block.ordinal != item.block.ordinal:
            header_tokens = self._tokenizer.count(item.header.text + "\n")
            maximum_tokens -= header_tokens
            if maximum_tokens <= 0:
                raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        if self._tokenizer.count(item.text) <= maximum_tokens:
            return [_Segment(source=item, text=item.text)]

        if item.block.block_type in _TABLE_TYPES and " | " in item.text:
            pieces = self._split_table_row(item, maximum_tokens)
        else:
            pieces = self._split_text(item.text, maximum_tokens)
        if not pieces or any(self._tokenizer.count(piece) > maximum_tokens for piece in pieces):
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        return [_Segment(source=item, text=piece, forced_split=True) for piece in pieces if piece]

    def _split_table_row(self, item: _NormalizedBlock, maximum_tokens: int) -> list[str]:
        values = item.text.split(" | ")
        headers = item.header.text.split(" | ") if item.header is not None else []
        labelled = [
            f"{headers[index]}: {value}" if index < len(headers) and headers[index] else value
            for index, value in enumerate(values)
        ]
        pieces: list[str] = []
        current: list[str] = []
        for cell in labelled:
            if self._tokenizer.count(cell) > maximum_tokens:
                if current:
                    pieces.append(" | ".join(current))
                    current = []
                pieces.extend(self._split_labelled_cell(cell, maximum_tokens))
                continue
            candidate = " | ".join((*current, cell))
            if current and self._tokenizer.count(candidate) > maximum_tokens:
                pieces.append(" | ".join(current))
                current = [cell]
            else:
                current.append(cell)
        if current:
            pieces.append(" | ".join(current))
        return pieces

    def _split_labelled_cell(self, cell: str, maximum_tokens: int) -> list[str]:
        label, separator, value = cell.partition(": ")
        if not separator or not label or not value:
            return self._split_text(cell, maximum_tokens)
        prefix = f"{label}: "
        if self._tokenizer.count(prefix) >= maximum_tokens:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        value_budget = maximum_tokens - self._tokenizer.count(prefix)
        if value_budget <= 0:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        value_parts = self._split_text(value, value_budget)
        labelled_parts = [prefix + part for part in value_parts]
        if any(self._tokenizer.count(part) > maximum_tokens for part in labelled_parts):
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        return labelled_parts

    def _split_text(self, text: str, maximum_tokens: int) -> list[str]:
        remaining = text
        pieces: list[str] = []
        while remaining:
            if self._tokenizer.count(remaining) <= maximum_tokens:
                pieces.append(remaining)
                break
            fit = self._maximum_prefix_length(remaining, maximum_tokens)
            if fit <= 0:
                raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
            boundary = self._preferred_boundary(remaining, fit)
            piece = remaining[:boundary].strip()
            if not piece:
                boundary = fit
                piece = remaining[:boundary].strip()
            if not piece or self._tokenizer.count(piece) > maximum_tokens:
                raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
            pieces.append(piece)
            remaining = remaining[boundary:].lstrip()
        return pieces

    def _maximum_prefix_length(self, text: str, maximum_tokens: int) -> int:
        low, high, best = 1, len(text), 0
        while low <= high:
            middle = (low + high) // 2
            if self._tokenizer.count(text[:middle]) <= maximum_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    @staticmethod
    def _preferred_boundary(text: str, fit: int) -> int:
        minimum = max(1, fit // 2)
        for marker in ("\n\n", ". ", "? ", "! ", "\n", " "):
            position = text.rfind(marker, minimum, fit)
            if position >= minimum:
                return position + (len(marker) if marker != " " else 0)
        return fit

    def _group_primary_segments(self, segments: list[_Segment]) -> list[list[_Segment]]:
        groups: list[list[_Segment]] = []
        current: list[_Segment] = []
        for segment in segments:
            if not current:
                current = [segment]
                continue
            candidate = [*current, segment]
            candidate_count = self._tokenizer.count(self._render(candidate))
            compatible = self._segments_compatible(current[-1], segment)
            keep_small_group_together = self._tokenizer.count(self._render(current)) < max(
                1, self._policy.target_tokens // 4
            )
            if compatible and (
                candidate_count <= self._policy.target_tokens
                or (
                    keep_small_group_together
                    and candidate_count <= self._policy.maximum_content_tokens
                )
            ):
                current.append(segment)
            else:
                groups.append(current)
                current = [segment]
        if current:
            groups.append(current)
        return groups

    def _segments_compatible(self, previous: _Segment, current: _Segment) -> bool:
        if previous.source.scope != current.source.scope:
            return False
        previous_page = previous.source.block.page_number
        current_page = current.source.block.page_number
        return not (
            previous_page is not None
            and current_page is not None
            and current_page - previous_page > 1
        )

    def _add_header_context(self, primary_group: list[_Segment]) -> list[_Segment]:
        first = primary_group[0]
        header = first.source.header
        if header is None or header.block.ordinal in {
            segment.source.block.ordinal for segment in primary_group
        }:
            return list(primary_group)
        context = _Segment(
            source=header,
            text=header.text,
            role=SourceReferenceRole.HEADER_CONTEXT,
        )
        rendered = [context, *primary_group]
        if self._tokenizer.count(self._render(rendered)) > self._policy.maximum_content_tokens:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        return rendered

    def _overlap_compatible(
        self, previous_group: list[_Segment], current_group: list[_Segment]
    ) -> bool:
        previous = previous_group[-1]
        current = current_group[0]
        return (
            previous.source.block.block_type not in _TABLE_TYPES
            and current.source.block.block_type not in _TABLE_TYPES
            and self._segments_compatible(previous, current)
        )

    def _overlap_segment(
        self, previous_group: list[_Segment], rendered_current: list[_Segment]
    ) -> _Segment | None:
        source = previous_group[-1]
        available = self._policy.maximum_content_tokens - self._tokenizer.count(
            self._render(rendered_current)
        )
        budget = min(self._policy.overlap_tokens, available)
        if budget <= 0:
            return None
        text = source.text
        if self._tokenizer.count(text) > budget:
            text = self._maximum_suffix(text, budget)
        if not text:
            return None
        overlap = replace(source, text=text, role=SourceReferenceRole.OVERLAP)
        if (
            self._tokenizer.count(self._render([overlap, *rendered_current]))
            > self._policy.maximum_content_tokens
        ):
            return None
        return overlap

    def _maximum_suffix(self, text: str, maximum_tokens: int) -> str:
        low, high, best = 0, len(text) - 1, ""
        while low <= high:
            middle = (low + high) // 2
            candidate = text[middle:].lstrip()
            if candidate and self._tokenizer.count(candidate) <= maximum_tokens:
                best = candidate
                high = middle - 1
            else:
                low = middle + 1
        if not best:
            return ""
        first_space = best.find(" ")
        if 0 < first_space < len(best) // 3:
            bounded = best[first_space + 1 :].lstrip()
            if bounded:
                best = bounded
        return best

    def _build_chunk(
        self,
        *,
        ordinal: int,
        segments: list[_Segment],
        extraction: ExtractionResult,
    ) -> CanonicalChunk:
        content = self._render(segments)
        token_count = self._tokenizer.count(content)
        if token_count > self._policy.maximum_content_tokens:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        references = self._references(segments)
        if len(references) > self._policy.maximum_source_references:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED)
        warnings: list[ChunkWarningCode] = []
        if any(segment.forced_split for segment in segments):
            warnings.append(ChunkWarningCode.FORCED_SPLIT)
        if any(segment.role is SourceReferenceRole.OVERLAP for segment in segments):
            warnings.append(ChunkWarningCode.OVERLAP_APPLIED)
        if any(segment.role is SourceReferenceRole.HEADER_CONTEXT for segment in segments):
            warnings.append(ChunkWarningCode.HEADER_CONTEXT_REPEATED)
        primary = next(
            segment for segment in segments if segment.role is SourceReferenceRole.PRIMARY
        )
        chunk_hash = self._hash_chunk(
            content=content,
            references=references,
            heading_path=primary.source.block.heading_path,
            extraction=extraction,
        )
        try:
            return CanonicalChunk(
                ordinal=ordinal,
                content=content,
                token_count=token_count,
                chunk_sha256=chunk_hash,
                source_references=references,
                heading_path=primary.source.block.heading_path,
                warning_codes=warnings,
                policy=self._policy,
            )
        except ValueError:
            raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED) from None

    @staticmethod
    def _references(segments: list[_Segment]) -> tuple[ChunkSourceReference, ...]:
        references: list[ChunkSourceReference] = []
        seen: set[tuple[int, SourceReferenceRole]] = set()
        for segment in segments:
            key = (segment.source.block.ordinal, segment.role)
            if key in seen:
                continue
            seen.add(key)
            block = segment.source.block
            references.append(
                ChunkSourceReference(
                    block_ordinal=block.ordinal,
                    role=segment.role,
                    page_number=block.page_number,
                    sheet_name=block.sheet_name,
                    row_start=block.row_start,
                    row_end=block.row_end,
                    extraction_method=block.extraction_method,
                )
            )
        return tuple(references)

    def _hash_chunk(
        self,
        *,
        content: str,
        references: tuple[ChunkSourceReference, ...],
        heading_path: tuple[str, ...],
        extraction: ExtractionResult,
    ) -> str:
        payload = {
            "domain": _HASH_DOMAIN,
            "chunker_version": self.version,
            "tokenizer_name": self._tokenizer.name,
            "tokenizer_revision": self._tokenizer.revision,
            "source_content_sha256": extraction.source_content_sha256,
            "confirmed_format": extraction.confirmed_format.value,
            "content": content,
            "heading_path": list(heading_path),
            "source_references": [reference.to_jsonable() for reference in references],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def _render(segments: list[_Segment]) -> str:
        rendered = ""
        previous: _Segment | None = None
        for segment in segments:
            separator = "\n"
            if previous is not None and (
                previous.source.block.block_type not in _TABLE_TYPES
                or segment.source.block.block_type not in _TABLE_TYPES
            ):
                separator = "\n\n"
            rendered = segment.text if not rendered else rendered + separator + segment.text
            previous = segment
        return rendered


def _safe_format(extraction: object) -> str:
    confirmed_format = getattr(extraction, "confirmed_format", None)
    return (
        confirmed_format.value
        if isinstance(confirmed_format, ConfirmedDocumentFormat)
        else "unknown"
    )
