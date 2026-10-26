from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.config import Settings


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FORBIDDEN_METADATA_KEY_PARTS = frozenset(
    {
        "credential",
        "document",
        "endpoint",
        "error",
        "exception",
        "file",
        "filename",
        "object",
        "path",
        "project",
        "secret",
        "storage",
        "tenant",
        "token",
        "url",
    }
)

ALLOWED_METADATA_KEYS = frozenset(
    {
        "attributes",
        "column_index",
        "column_name",
        "coordinates",
        "is_header",
        "list_level",
        "page_label",
        "source_kind",
        "table_index",
    }
)


class ConfirmedDocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"


class ExtractedBlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE_ROW = "table_row"
    WORKSHEET_ROW = "worksheet_row"


class ExtractionMethod(StrEnum):
    NATIVE = "native"
    OCR = "ocr"


class ExtractionWarningCode(StrEnum):
    EMPTY_PAGE = "empty_page"
    OCR_USED = "ocr_used"
    MIXED_PAGE_OCR_USED = "mixed_page_ocr_used"
    REPEATED_MARGIN_REMOVED = "repeated_margin_removed"
    PARTIAL_ELEMENT_SKIPPED = "partial_element_skipped"
    UNSUPPORTED_ELEMENT_SKIPPED = "unsupported_element_skipped"
    HEADER_FOOTER_EXCLUDED = "header_footer_excluded"
    HIDDEN_SHEET_SKIPPED = "hidden_sheet_skipped"
    WORKSHEET_DIMENSIONS_CORRECTED = "worksheet_dimensions_corrected"
    FORMULA_WITHOUT_CACHED_VALUE = "formula_without_cached_value"
    CSV_HEADER_NORMALIZED = "csv_header_normalized"
    CSV_DUPLICATE_HEADER_NORMALIZED = "csv_duplicate_header_normalized"


class FrozenDict(dict[str, Any]):
    """JSON-serializable dictionary that cannot be mutated after construction."""

    def _immutable(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("validated metadata is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True, slots=True)
class ExtractionLimits:
    maximum_pdf_pages: int
    maximum_worksheets: int
    maximum_rows_per_sheet: int
    maximum_extracted_characters: int
    maximum_blocks: int
    maximum_characters_per_block: int
    maximum_heading_depth: int
    maximum_heading_label_characters: int
    maximum_warnings: int
    maximum_metadata_fields: int
    maximum_metadata_depth: int
    maximum_metadata_value_characters: int
    maximum_metadata_list_items: int
    maximum_sheet_name_characters: int
    maximum_archive_entries: int
    maximum_archive_compressed_bytes: int
    maximum_archive_uncompressed_bytes: int
    maximum_archive_entry_bytes: int
    maximum_archive_expansion_ratio: int
    maximum_spreadsheet_columns: int
    maximum_spreadsheet_cells: int
    maximum_merged_ranges: int
    maximum_csv_columns: int
    maximum_csv_field_characters: int

    def __post_init__(self) -> None:
        for field_name, value in self.__dict_values().items():
            if not _is_non_negative_integer(value):
                raise ValueError(f"{field_name} must be a non-negative integer")
        positive_fields = (
            "maximum_pdf_pages",
            "maximum_worksheets",
            "maximum_rows_per_sheet",
            "maximum_extracted_characters",
            "maximum_blocks",
            "maximum_characters_per_block",
            "maximum_heading_depth",
            "maximum_heading_label_characters",
            "maximum_metadata_depth",
            "maximum_metadata_value_characters",
            "maximum_sheet_name_characters",
            "maximum_archive_entries",
            "maximum_archive_compressed_bytes",
            "maximum_archive_uncompressed_bytes",
            "maximum_archive_entry_bytes",
            "maximum_archive_expansion_ratio",
            "maximum_spreadsheet_columns",
            "maximum_spreadsheet_cells",
            "maximum_csv_columns",
            "maximum_csv_field_characters",
        )
        for field_name in positive_fields:
            if getattr(self, field_name) == 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.maximum_characters_per_block > self.maximum_extracted_characters:
            raise ValueError(
                "maximum_characters_per_block cannot exceed maximum_extracted_characters"
            )
        if self.maximum_archive_entry_bytes > self.maximum_archive_uncompressed_bytes:
            raise ValueError(
                "maximum_archive_entry_bytes cannot exceed maximum_archive_uncompressed_bytes"
            )
        if self.maximum_csv_columns > self.maximum_spreadsheet_columns:
            raise ValueError("maximum_csv_columns cannot exceed maximum_spreadsheet_columns")

    def __dict_values(self) -> dict[str, int]:
        return {field_name: getattr(self, field_name) for field_name in self.__dataclass_fields__}

    @classmethod
    def from_settings(cls, settings: Settings) -> ExtractionLimits:
        return cls(
            maximum_pdf_pages=settings.document_max_pdf_pages,
            maximum_worksheets=settings.document_max_worksheets,
            maximum_rows_per_sheet=settings.document_max_rows_per_sheet,
            maximum_extracted_characters=settings.document_max_extracted_characters,
            maximum_blocks=settings.document_max_extracted_blocks,
            maximum_characters_per_block=min(
                settings.document_max_block_characters,
                settings.document_max_extracted_characters,
            ),
            maximum_heading_depth=settings.document_max_heading_depth,
            maximum_heading_label_characters=(settings.document_max_heading_label_characters),
            maximum_warnings=settings.document_max_extraction_warnings,
            maximum_metadata_fields=settings.document_max_metadata_fields,
            maximum_metadata_depth=settings.document_max_metadata_depth,
            maximum_metadata_value_characters=(settings.document_max_metadata_value_characters),
            maximum_metadata_list_items=settings.document_max_metadata_list_items,
            maximum_sheet_name_characters=settings.document_max_sheet_name_characters,
            maximum_archive_entries=settings.document_max_archive_entries,
            maximum_archive_compressed_bytes=settings.document_max_archive_compressed_bytes,
            maximum_archive_uncompressed_bytes=settings.document_max_archive_uncompressed_bytes,
            maximum_archive_entry_bytes=settings.document_max_archive_entry_bytes,
            maximum_archive_expansion_ratio=settings.document_max_archive_expansion_ratio,
            maximum_spreadsheet_columns=settings.document_max_spreadsheet_columns,
            maximum_spreadsheet_cells=settings.document_max_spreadsheet_cells,
            maximum_merged_ranges=settings.document_max_merged_ranges,
            maximum_csv_columns=settings.document_max_csv_columns,
            maximum_csv_field_characters=settings.document_max_csv_field_characters,
        )


@dataclass(frozen=True, slots=True, init=False)
class ExtractedBlock:
    ordinal: int
    text: str
    block_type: ExtractedBlockType
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    heading_path: tuple[str, ...]
    extraction_method: ExtractionMethod
    metadata: FrozenDict

    def __init__(
        self,
        *,
        ordinal: int,
        text: str,
        block_type: ExtractedBlockType,
        limits: ExtractionLimits,
        page_number: int | None = None,
        sheet_name: str | None = None,
        row_start: int | None = None,
        row_end: int | None = None,
        heading_path: Sequence[str] = (),
        extraction_method: ExtractionMethod = ExtractionMethod.NATIVE,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not _is_non_negative_integer(ordinal):
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must contain extractable content")
        if len(text) > limits.maximum_characters_per_block:
            raise ValueError("text exceeds the per-block character limit")
        if not isinstance(block_type, ExtractedBlockType):
            raise ValueError("block_type must be an allowlisted extraction block type")
        if not isinstance(extraction_method, ExtractionMethod):
            raise ValueError("extraction_method must be an allowlisted extraction method")
        if page_number is not None and not _is_positive_integer(page_number):
            raise ValueError("page_number must be one-based when present")
        if (row_start is None) != (row_end is None):
            raise ValueError("row_start and row_end must both be present or absent")
        if row_start is not None:
            if not _is_positive_integer(row_start) or not _is_positive_integer(row_end):
                raise ValueError("row locations must be one-based")
            if row_start > row_end:
                raise ValueError("row_start cannot exceed row_end")
            if row_end > limits.maximum_rows_per_sheet:
                raise ValueError("row location exceeds the row limit")
        if sheet_name is not None:
            _validate_location_label(
                sheet_name,
                maximum_length=limits.maximum_sheet_name_characters,
                field_name="sheet_name",
            )

        frozen_heading_path = tuple(heading_path)
        if len(frozen_heading_path) > limits.maximum_heading_depth:
            raise ValueError("heading_path exceeds the heading-depth limit")
        for heading_label in frozen_heading_path:
            _validate_location_label(
                heading_label,
                maximum_length=limits.maximum_heading_label_characters,
                field_name="heading_path label",
            )

        frozen_metadata = _validate_and_freeze_metadata(metadata or {}, limits)
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "block_type", block_type)
        object.__setattr__(self, "page_number", page_number)
        object.__setattr__(self, "sheet_name", sheet_name)
        object.__setattr__(self, "row_start", row_start)
        object.__setattr__(self, "row_end", row_end)
        object.__setattr__(self, "heading_path", frozen_heading_path)
        object.__setattr__(self, "extraction_method", extraction_method)
        object.__setattr__(self, "metadata", frozen_metadata)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "text": self.text,
            "block_type": self.block_type.value,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "heading_path": list(self.heading_path),
            "extraction_method": self.extraction_method.value,
            "metadata": _thaw_json_value(self.metadata),
        }


@dataclass(frozen=True, slots=True, init=False)
class ExtractionStatistics:
    detected_format: ConfirmedDocumentFormat
    page_count: int
    worksheet_count: int
    table_count: int
    row_count: int
    block_count: int
    character_count: int
    native_page_count: int
    ocr_page_count: int
    warning_codes: tuple[ExtractionWarningCode, ...]
    extractor_name: str
    extractor_version: str

    def __init__(
        self,
        *,
        detected_format: ConfirmedDocumentFormat,
        page_count: int,
        worksheet_count: int,
        table_count: int,
        row_count: int,
        block_count: int,
        character_count: int,
        native_page_count: int,
        ocr_page_count: int,
        warning_codes: Iterable[ExtractionWarningCode],
        extractor_name: str,
        extractor_version: str,
        limits: ExtractionLimits,
    ) -> None:
        if not isinstance(detected_format, ConfirmedDocumentFormat):
            raise ValueError("detected_format must be a confirmed document format")
        counts = {
            "page_count": page_count,
            "worksheet_count": worksheet_count,
            "table_count": table_count,
            "row_count": row_count,
            "block_count": block_count,
            "character_count": character_count,
            "native_page_count": native_page_count,
            "ocr_page_count": ocr_page_count,
        }
        for field_name, value in counts.items():
            if not _is_non_negative_integer(value):
                raise ValueError(f"{field_name} must be a non-negative integer")
        if page_count > limits.maximum_pdf_pages:
            raise ValueError("page_count exceeds the page limit")
        if worksheet_count > limits.maximum_worksheets:
            raise ValueError("worksheet_count exceeds the worksheet limit")
        maximum_rows = limits.maximum_rows_per_sheet * max(1, worksheet_count)
        if row_count > maximum_rows:
            raise ValueError("row_count exceeds the row limit")
        if block_count > limits.maximum_blocks:
            raise ValueError("block_count exceeds the block limit")
        if table_count > limits.maximum_blocks:
            raise ValueError("table_count exceeds the block limit")
        if character_count > limits.maximum_extracted_characters:
            raise ValueError("character_count exceeds the aggregate character limit")
        if native_page_count > page_count or ocr_page_count > page_count:
            raise ValueError("native and OCR page counts cannot exceed page_count")

        frozen_warnings = tuple(warning_codes)
        if len(frozen_warnings) > limits.maximum_warnings:
            raise ValueError("warning_codes exceeds the warning limit")
        if any(not isinstance(code, ExtractionWarningCode) for code in frozen_warnings):
            raise ValueError("warning_codes must contain only stable warning codes")
        if len(set(frozen_warnings)) != len(frozen_warnings):
            raise ValueError("warning_codes must be unique")
        validate_safe_identifier(extractor_name, field_name="extractor_name", maximum_length=80)
        validate_safe_identifier(
            extractor_version,
            field_name="extractor_version",
            maximum_length=40,
        )

        object.__setattr__(self, "detected_format", detected_format)
        for field_name, value in counts.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "warning_codes", frozen_warnings)
        object.__setattr__(self, "extractor_name", extractor_name)
        object.__setattr__(self, "extractor_version", extractor_version)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "detected_format": self.detected_format.value,
            "page_count": self.page_count,
            "worksheet_count": self.worksheet_count,
            "table_count": self.table_count,
            "row_count": self.row_count,
            "block_count": self.block_count,
            "character_count": self.character_count,
            "native_page_count": self.native_page_count,
            "ocr_page_count": self.ocr_page_count,
            "warning_codes": [code.value for code in self.warning_codes],
            "extractor_name": self.extractor_name,
            "extractor_version": self.extractor_version,
        }


@dataclass(frozen=True, slots=True, init=False)
class ExtractionResult:
    blocks: tuple[ExtractedBlock, ...]
    statistics: ExtractionStatistics
    source_content_sha256: str
    confirmed_format: ConfirmedDocumentFormat

    def __init__(
        self,
        *,
        blocks: Iterable[ExtractedBlock],
        statistics: ExtractionStatistics,
        source_content_sha256: str,
        confirmed_format: ConfirmedDocumentFormat,
        limits: ExtractionLimits,
    ) -> None:
        frozen_blocks = tuple(blocks)
        if not frozen_blocks:
            raise ValueError("an extraction result must contain at least one block")
        if len(frozen_blocks) > limits.maximum_blocks:
            raise ValueError("blocks exceeds the block limit")
        if not isinstance(statistics, ExtractionStatistics):
            raise ValueError("statistics must be validated extraction statistics")
        if not isinstance(confirmed_format, ConfirmedDocumentFormat):
            raise ValueError("confirmed_format must be a confirmed document format")
        if not isinstance(source_content_sha256, str) or not _SHA256.fullmatch(
            source_content_sha256
        ):
            raise ValueError("source_content_sha256 must be lowercase SHA-256 hexadecimal")
        if statistics.detected_format is not confirmed_format:
            raise ValueError("confirmed_format and detected_format must agree")
        _validate_statistics_against_limits(statistics, limits)

        ordinals = tuple(block.ordinal for block in frozen_blocks)
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("block ordinals must be unique")
        if any(
            current >= following for current, following in zip(ordinals, ordinals[1:], strict=False)
        ):
            raise ValueError("block ordinals must be strictly increasing")
        if statistics.block_count != len(frozen_blocks):
            raise ValueError("block_count does not match the validated blocks")
        character_count = sum(len(block.text) for block in frozen_blocks)
        if statistics.character_count != character_count:
            raise ValueError("character_count does not match the validated block text")
        if character_count > limits.maximum_extracted_characters:
            raise ValueError("aggregate extracted characters exceed the configured limit")

        for block in frozen_blocks:
            _validate_block_against_limits(block, limits)
            _validate_block_location(block, confirmed_format)
        pages = {block.page_number for block in frozen_blocks if block.page_number is not None}
        sheets = {block.sheet_name for block in frozen_blocks if block.sheet_name is not None}
        if pages and max(pages) > statistics.page_count:
            raise ValueError("block page locations exceed page_count")
        if len(sheets) > statistics.worksheet_count:
            raise ValueError("block worksheet locations exceed worksheet_count")

        object.__setattr__(self, "blocks", frozen_blocks)
        object.__setattr__(self, "statistics", statistics)
        object.__setattr__(self, "source_content_sha256", source_content_sha256)
        object.__setattr__(self, "confirmed_format", confirmed_format)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "blocks": [block.to_jsonable() for block in self.blocks],
            "statistics": self.statistics.to_jsonable(),
            "source_content_sha256": self.source_content_sha256,
            "confirmed_format": self.confirmed_format.value,
        }


def confirmed_format_from_suffix(suffix: str) -> ConfirmedDocumentFormat:
    mapping = {
        ".pdf": ConfirmedDocumentFormat.PDF,
        ".docx": ConfirmedDocumentFormat.DOCX,
        ".xlsx": ConfirmedDocumentFormat.XLSX,
        ".csv": ConfirmedDocumentFormat.CSV,
    }
    if not isinstance(suffix, str) or suffix not in mapping:
        raise ValueError("confirmed suffix is unsupported or malformed")
    return mapping[suffix]


def _validate_block_against_limits(block: ExtractedBlock, limits: ExtractionLimits) -> None:
    if not isinstance(block, ExtractedBlock):
        raise ValueError("blocks must contain only validated ExtractedBlock values")
    if len(block.text) > limits.maximum_characters_per_block:
        raise ValueError("block text exceeds the per-block character limit")
    if len(block.heading_path) > limits.maximum_heading_depth:
        raise ValueError("heading_path exceeds the heading-depth limit")
    if any(len(label) > limits.maximum_heading_label_characters for label in block.heading_path):
        raise ValueError("heading_path label exceeds the configured limit")
    if (
        block.sheet_name is not None
        and len(block.sheet_name) > limits.maximum_sheet_name_characters
    ):
        raise ValueError("sheet_name exceeds the configured limit")
    if block.row_end is not None and block.row_end > limits.maximum_rows_per_sheet:
        raise ValueError("row location exceeds the configured limit")
    _validate_and_freeze_metadata(block.metadata, limits)


def _validate_statistics_against_limits(
    statistics: ExtractionStatistics,
    limits: ExtractionLimits,
) -> None:
    if statistics.page_count > limits.maximum_pdf_pages:
        raise ValueError("page_count exceeds the configured limit")
    if statistics.worksheet_count > limits.maximum_worksheets:
        raise ValueError("worksheet_count exceeds the configured limit")
    maximum_rows = limits.maximum_rows_per_sheet * max(1, statistics.worksheet_count)
    if statistics.row_count > maximum_rows:
        raise ValueError("row_count exceeds the configured limit")
    if statistics.block_count > limits.maximum_blocks:
        raise ValueError("block_count exceeds the configured limit")
    if statistics.table_count > limits.maximum_blocks:
        raise ValueError("table_count exceeds the configured limit")
    if statistics.character_count > limits.maximum_extracted_characters:
        raise ValueError("character_count exceeds the configured limit")
    if len(statistics.warning_codes) > limits.maximum_warnings:
        raise ValueError("warning_codes exceeds the configured limit")


def _validate_block_location(
    block: ExtractedBlock,
    confirmed_format: ConfirmedDocumentFormat,
) -> None:
    has_rows = block.row_start is not None and block.row_end is not None
    if confirmed_format is ConfirmedDocumentFormat.PDF:
        if block.page_number is None or block.sheet_name is not None or has_rows:
            raise ValueError("PDF blocks require only a one-based page location")
    elif confirmed_format is ConfirmedDocumentFormat.DOCX:
        if block.page_number is not None or block.sheet_name is not None or has_rows:
            raise ValueError("DOCX blocks cannot contain page or spreadsheet locations")
        if block.extraction_method is ExtractionMethod.OCR:
            raise ValueError("DOCX blocks cannot report OCR extraction")
    elif confirmed_format is ConfirmedDocumentFormat.XLSX:
        if block.page_number is not None or block.sheet_name is None or not has_rows:
            raise ValueError("XLSX blocks require worksheet and row locations")
        if block.extraction_method is ExtractionMethod.OCR:
            raise ValueError("XLSX blocks cannot report OCR extraction")
    elif confirmed_format is ConfirmedDocumentFormat.CSV:
        if block.page_number is not None or block.sheet_name is not None or not has_rows:
            raise ValueError("CSV blocks require row locations without a worksheet")
        if block.extraction_method is ExtractionMethod.OCR:
            raise ValueError("CSV blocks cannot report OCR extraction")


def _validate_and_freeze_metadata(
    metadata: Mapping[str, object],
    limits: ExtractionLimits,
) -> FrozenDict:
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    field_counter = [0]
    frozen = _freeze_mapping(
        metadata,
        limits=limits,
        depth=1,
        field_counter=field_counter,
        top_level=True,
    )
    try:
        json.dumps(frozen, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    return frozen


def _freeze_mapping(
    value: Mapping[str, object],
    *,
    limits: ExtractionLimits,
    depth: int,
    field_counter: list[int],
    top_level: bool,
) -> FrozenDict:
    if depth > limits.maximum_metadata_depth:
        raise ValueError("metadata exceeds the nesting limit")
    frozen_items: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _METADATA_KEY.fullmatch(key):
            raise ValueError("metadata keys must use the documented safe format")
        if top_level and key not in ALLOWED_METADATA_KEYS:
            raise ValueError("metadata key is not allowlisted")
        if any(part in _FORBIDDEN_METADATA_KEY_PARTS for part in key.split("_")):
            raise ValueError("metadata key is reserved")
        field_counter[0] += 1
        if field_counter[0] > limits.maximum_metadata_fields:
            raise ValueError("metadata exceeds the field-count limit")
        frozen_items[key] = _freeze_json_value(
            item,
            limits=limits,
            depth=depth,
            field_counter=field_counter,
        )
    return FrozenDict(frozen_items)


def _freeze_json_value(
    value: object,
    *,
    limits: ExtractionLimits,
    depth: int,
    field_counter: list[int],
) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if len(str(value)) > limits.maximum_metadata_value_characters:
            raise ValueError("metadata number exceeds the value-size limit")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("metadata numbers must be finite")
        if len(repr(value)) > limits.maximum_metadata_value_characters:
            raise ValueError("metadata number exceeds the value-size limit")
        return value
    if isinstance(value, str):
        if len(value) > limits.maximum_metadata_value_characters:
            raise ValueError("metadata string exceeds the value-size limit")
        if _contains_forbidden_control(value):
            raise ValueError("metadata strings cannot contain control characters")
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(
            value,
            limits=limits,
            depth=depth + 1,
            field_counter=field_counter,
            top_level=False,
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if depth >= limits.maximum_metadata_depth:
            raise ValueError("metadata exceeds the nesting limit")
        if len(value) > limits.maximum_metadata_list_items:
            raise ValueError("metadata collection exceeds the item limit")
        return tuple(
            _freeze_json_value(
                item,
                limits=limits,
                depth=depth + 1,
                field_counter=field_counter,
            )
            for item in value
        )
    raise ValueError("metadata contains an unsupported value type")


def _thaw_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def validate_safe_identifier(value: object, *, field_name: str, maximum_length: int) -> None:
    if (
        not isinstance(value, str)
        or len(value) > maximum_length
        or not _SAFE_IDENTIFIER.fullmatch(value)
    ):
        raise ValueError(f"{field_name} must use the documented safe character set")


def _validate_location_label(value: str, *, maximum_length: int, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum_length:
        raise ValueError(f"{field_name} is empty or exceeds its limit")
    if _contains_forbidden_control(value):
        raise ValueError(f"{field_name} cannot contain control characters")


def _contains_forbidden_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _is_non_negative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: object) -> bool:
    return _is_non_negative_integer(value) and value > 0
