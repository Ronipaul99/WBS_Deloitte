from pathlib import Path

from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionLimits,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatistics,
)


def extraction_limits(**overrides: int) -> ExtractionLimits:
    values = {
        "maximum_pdf_pages": 10,
        "maximum_worksheets": 5,
        "maximum_rows_per_sheet": 100,
        "maximum_extracted_characters": 5_000,
        "maximum_blocks": 100,
        "maximum_characters_per_block": 1_000,
        "maximum_heading_depth": 5,
        "maximum_heading_label_characters": 100,
        "maximum_warnings": 10,
        "maximum_metadata_fields": 10,
        "maximum_metadata_depth": 3,
        "maximum_metadata_value_characters": 200,
        "maximum_metadata_list_items": 10,
        "maximum_sheet_name_characters": 100,
        "maximum_archive_entries": 1_000,
        "maximum_archive_compressed_bytes": 5_000_000,
        "maximum_archive_uncompressed_bytes": 20_000_000,
        "maximum_archive_entry_bytes": 5_000_000,
        "maximum_archive_expansion_ratio": 100,
        "maximum_spreadsheet_columns": 100,
        "maximum_spreadsheet_cells": 1_000,
        "maximum_merged_ranges": 100,
        "maximum_csv_columns": 100,
        "maximum_csv_field_characters": 1_000,
    }
    values.update(overrides)
    return ExtractionLimits(**values)


def block_for_format(
    confirmed_format: ConfirmedDocumentFormat,
    *,
    limits: ExtractionLimits | None = None,
    ordinal: int = 0,
    text: str = "Synthetic project scope",
) -> ExtractedBlock:
    limits = limits or extraction_limits()
    locations: dict[str, object] = {}
    block_type = ExtractedBlockType.PARAGRAPH
    if confirmed_format is ConfirmedDocumentFormat.PDF:
        locations["page_number"] = 1
    elif confirmed_format is ConfirmedDocumentFormat.XLSX:
        locations.update(sheet_name="Scope", row_start=1, row_end=1)
        block_type = ExtractedBlockType.WORKSHEET_ROW
    elif confirmed_format is ConfirmedDocumentFormat.CSV:
        locations.update(row_start=1, row_end=1)
        block_type = ExtractedBlockType.TABLE_ROW
    return ExtractedBlock(
        ordinal=ordinal,
        text=text,
        block_type=block_type,
        extraction_method=ExtractionMethod.NATIVE,
        limits=limits,
        metadata={"source_kind": "synthetic"},
        **locations,
    )


def result_for_format(
    confirmed_format: ConfirmedDocumentFormat,
    *,
    limits: ExtractionLimits | None = None,
) -> ExtractionResult:
    limits = limits or extraction_limits()
    block = block_for_format(confirmed_format, limits=limits)
    page_count = 1 if confirmed_format is ConfirmedDocumentFormat.PDF else 0
    worksheet_count = 1 if confirmed_format is ConfirmedDocumentFormat.XLSX else 0
    row_count = (
        1
        if confirmed_format
        in {
            ConfirmedDocumentFormat.XLSX,
            ConfirmedDocumentFormat.CSV,
        }
        else 0
    )
    statistics = ExtractionStatistics(
        detected_format=confirmed_format,
        page_count=page_count,
        worksheet_count=worksheet_count,
        table_count=0,
        row_count=row_count,
        block_count=1,
        character_count=len(block.text),
        native_page_count=page_count,
        ocr_page_count=0,
        warning_codes=(),
        extractor_name="fake-extractor",
        extractor_version="1.0.0",
        limits=limits,
    )
    return ExtractionResult(
        blocks=(block,),
        statistics=statistics,
        source_content_sha256="a" * 64,
        confirmed_format=confirmed_format,
        limits=limits,
    )


class FakeExtractor:
    name = "fake-extractor"
    version = "1.0.0"

    def __init__(self, confirmed_format: ConfirmedDocumentFormat) -> None:
        self.format_name = confirmed_format
        self.extract_calls = 0

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool:
        return confirmed_format is self.format_name

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult:
        del path
        self.extract_calls += 1
        return result_for_format(self.format_name, limits=limits)


def complete_fake_extractors() -> tuple[FakeExtractor, ...]:
    return tuple(FakeExtractor(format_name) for format_name in ConfirmedDocumentFormat)
