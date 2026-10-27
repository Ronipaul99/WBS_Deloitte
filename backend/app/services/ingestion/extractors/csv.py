from __future__ import annotations

import csv as csv_module
import io
import time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from app.core.observability import record_document_extraction
from app.services.ingestion.errors import (
    ExtractionError,
    ExtractionErrorCode,
    map_unexpected_extraction_failure,
)
from app.services.ingestion.extractors._common import (
    TrustedExtractionPolicy,
    append_warning_once,
    clean_contract_text,
    sha256_file,
    validate_trusted_input_path,
)
from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionLimits,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatistics,
    ExtractionWarningCode,
)

if TYPE_CHECKING:
    from app.core.config import Settings

CSV_EXTRACTOR_NAME = "python-csv"
CSV_EXTRACTOR_VERSION = "1.0.0"
_ALLOWED_DELIMITERS = ",;\t|"
_DIALECT_SAMPLE_CHARACTERS = 64 * 1024
_FIELD_LIMIT_LOCK = Lock()


class CsvExtractor:
    format_name = ConfirmedDocumentFormat.CSV
    name = CSV_EXTRACTOR_NAME
    version = CSV_EXTRACTOR_VERSION

    def __init__(self, policy: TrustedExtractionPolicy) -> None:
        self._policy = policy

    @classmethod
    def from_settings(cls, settings: Settings) -> CsvExtractor:
        return cls(TrustedExtractionPolicy.from_settings(settings))

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool:
        return confirmed_format is ConfirmedDocumentFormat.CSV

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult:
        started = time.monotonic()
        try:
            trusted_path = validate_trusted_input_path(
                path,
                processing_root=self._policy.processing_root,
                expected_suffix=".csv",
                maximum_bytes=self._policy.maximum_input_bytes,
                allow_empty=True,
            )
            source_sha256 = sha256_file(
                trusted_path,
                maximum_bytes=self._policy.maximum_input_bytes,
            )
            result = _extract_csv(trusted_path, limits=limits, source_sha256=source_sha256)
            record_document_extraction(
                document_format="csv",
                duration_seconds=time.monotonic() - started,
                outcome="success",
                block_count=result.statistics.block_count,
                row_count=result.statistics.row_count,
            )
            return result
        except ExtractionError as exc:
            record_document_extraction(
                document_format="csv",
                duration_seconds=time.monotonic() - started,
                outcome=_outcome(exc.code),
            )
            raise
        except (UnicodeDecodeError, csv_module.Error):
            record_document_extraction(
                document_format="csv",
                duration_seconds=time.monotonic() - started,
                outcome="rejected",
            )
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
        except MemoryError:
            record_document_extraction(
                document_format="csv",
                duration_seconds=time.monotonic() - started,
                outcome="failed",
            )
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None
        except Exception as exc:
            record_document_extraction(
                document_format="csv",
                duration_seconds=time.monotonic() - started,
                outcome="failed",
            )
            raise map_unexpected_extraction_failure(exc) from None


def _extract_csv(
    path: Path,
    *,
    limits: ExtractionLimits,
    source_sha256: str,
) -> ExtractionResult:
    blocks: list[ExtractedBlock] = []
    warnings: list[ExtractionWarningCode] = []
    character_count = 0
    header_seen = False

    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as source:
            sample = source.read(_DIALECT_SAMPLE_CHARACTERS)
            source.seek(0)
            delimiter = _detect_delimiter(sample)
            with _bounded_csv_field_limit(limits.maximum_csv_field_characters):
                reader = csv_module.reader(
                    source,
                    delimiter=delimiter,
                    quotechar='"',
                    doublequote=True,
                    strict=True,
                )
                for record_number, raw_row in enumerate(reader, start=1):
                    if record_number > limits.maximum_rows_per_sheet:
                        raise _limit_error()
                    if len(raw_row) > min(
                        limits.maximum_csv_columns,
                        limits.maximum_spreadsheet_columns,
                    ):
                        raise _limit_error()
                    if any(len(field) > limits.maximum_csv_field_characters for field in raw_row):
                        raise _limit_error()
                    row = [clean_contract_text(field) for field in raw_row]
                    if not row or all(not field for field in row):
                        continue
                    is_header = not header_seen
                    if is_header:
                        row, normalized, duplicates = _normalize_headers(row)
                        if normalized:
                            append_warning_once(
                                warnings,
                                ExtractionWarningCode.CSV_HEADER_NORMALIZED,
                                limits.maximum_warnings,
                            )
                        if duplicates:
                            append_warning_once(
                                warnings,
                                ExtractionWarningCode.CSV_DUPLICATE_HEADER_NORMALIZED,
                                limits.maximum_warnings,
                            )
                        header_seen = True
                    text = " | ".join(row)
                    character_count = _append_csv_block(
                        blocks,
                        text=text,
                        record_number=record_number,
                        is_header=is_header,
                        character_count=character_count,
                        limits=limits,
                    )
    except ExtractionError:
        raise
    except UnicodeDecodeError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
    except csv_module.Error as exc:
        if "field larger" in str(exc).casefold():
            raise _limit_error() from None
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
    except OSError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED) from None

    if not blocks:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT)
    try:
        statistics = ExtractionStatistics(
            detected_format=ConfirmedDocumentFormat.CSV,
            page_count=0,
            worksheet_count=0,
            table_count=1,
            row_count=len(blocks),
            block_count=len(blocks),
            character_count=character_count,
            native_page_count=0,
            ocr_page_count=0,
            warning_codes=warnings,
            extractor_name=CSV_EXTRACTOR_NAME,
            extractor_version=CSV_EXTRACTOR_VERSION,
            limits=limits,
        )
        return ExtractionResult(
            blocks=blocks,
            statistics=statistics,
            source_content_sha256=source_sha256,
            confirmed_format=ConfirmedDocumentFormat.CSV,
            limits=limits,
        )
    except ValueError:
        raise _limit_error() from None


def _detect_delimiter(sample: str) -> str:
    if not sample:
        return ","
    best_delimiter = ","
    best_score = (0, 0, 0)
    for position, delimiter in enumerate(_ALLOWED_DELIMITERS):
        try:
            rows = tuple(
                csv_module.reader(
                    io.StringIO(sample),
                    delimiter=delimiter,
                    quotechar='"',
                    doublequote=True,
                    strict=True,
                )
            )
        except csv_module.Error:
            continue
        nonempty_widths = [len(row) for row in rows if row and any(field for field in row)]
        multi_column_rows = sum(width > 1 for width in nonempty_widths)
        if not multi_column_rows:
            continue
        most_common_width = max(set(nonempty_widths), key=nonempty_widths.count)
        consistent_rows = nonempty_widths.count(most_common_width)
        score = (multi_column_rows, consistent_rows, -position)
        if score > best_score:
            best_delimiter = delimiter
            best_score = score
    return best_delimiter


def _normalize_headers(headers: list[str]) -> tuple[list[str], bool, bool]:
    normalized = False
    duplicates = False
    seen_counts: dict[str, int] = {}
    used: set[str] = set()
    result: list[str] = []
    for index, header in enumerate(headers, start=1):
        candidate = header
        if not candidate:
            candidate = f"column_{index}"
            normalized = True
        base = candidate
        key = base.casefold()
        count = seen_counts.get(key, 0) + 1
        if count > 1:
            candidate = f"{base}_{count}"
            normalized = True
            duplicates = True
        while candidate.casefold() in used:
            count += 1
            candidate = f"{base}_{count}"
            normalized = True
            duplicates = True
        seen_counts[key] = count
        result.append(candidate)
        used.add(candidate.casefold())
    return result, normalized, duplicates


def _append_csv_block(
    blocks: list[ExtractedBlock],
    *,
    text: str,
    record_number: int,
    is_header: bool,
    character_count: int,
    limits: ExtractionLimits,
) -> int:
    if len(blocks) >= limits.maximum_blocks:
        raise _limit_error()
    new_character_count = character_count + len(text)
    if new_character_count > limits.maximum_extracted_characters:
        raise _limit_error()
    try:
        blocks.append(
            ExtractedBlock(
                ordinal=len(blocks),
                text=text,
                block_type=ExtractedBlockType.TABLE_ROW,
                row_start=record_number,
                row_end=record_number,
                extraction_method=ExtractionMethod.NATIVE,
                metadata={"source_kind": "csv", "is_header": is_header},
                limits=limits,
            )
        )
    except ValueError:
        raise _limit_error() from None
    return new_character_count


class _bounded_csv_field_limit:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._previous = 0

    def __enter__(self) -> None:
        _FIELD_LIMIT_LOCK.acquire()
        self._previous = csv_module.field_size_limit()
        csv_module.field_size_limit(self._limit + 1)

    def __exit__(self, *_args: object) -> None:
        csv_module.field_size_limit(self._previous)
        _FIELD_LIMIT_LOCK.release()


def _limit_error() -> ExtractionError:
    return ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)


def _outcome(code: ExtractionErrorCode) -> str:
    if code in {
        ExtractionErrorCode.DOCUMENT_MALFORMED,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT,
    }:
        return "rejected"
    return "failed"
