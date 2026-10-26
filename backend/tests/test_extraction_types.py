import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from extraction_fixtures import block_for_format, extraction_limits, result_for_format

from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionLimits,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatistics,
    ExtractionWarningCode,
    confirmed_format_from_suffix,
)


def test_heading_and_paragraph_blocks_are_immutable() -> None:
    limits = extraction_limits()
    heading_source = ["Delivery", "Planning"]
    metadata_source = {"attributes": {"label": "synthetic"}}
    heading = ExtractedBlock(
        ordinal=0,
        text="Planning",
        block_type=ExtractedBlockType.HEADING,
        heading_path=heading_source,
        extraction_method=ExtractionMethod.NATIVE,
        metadata=metadata_source,
        limits=limits,
    )
    paragraph = ExtractedBlock(
        ordinal=1,
        text="Synthetic paragraph",
        block_type=ExtractedBlockType.PARAGRAPH,
        heading_path=heading_source,
        limits=limits,
    )

    heading_source.append("Changed")
    metadata_source["attributes"]["label"] = "changed"

    assert heading.heading_path == ("Delivery", "Planning")
    assert heading.metadata["attributes"]["label"] == "synthetic"
    assert paragraph.text == "Synthetic paragraph"
    with pytest.raises(TypeError):
        heading.metadata["source_kind"] = "changed"
    with pytest.raises(FrozenInstanceError):
        heading.text = "changed"


@pytest.mark.parametrize("confirmed_format", list(ConfirmedDocumentFormat))
def test_valid_result_for_each_confirmed_format(
    confirmed_format: ConfirmedDocumentFormat,
) -> None:
    result = result_for_format(confirmed_format)
    serialized = json.dumps(result.to_jsonable())

    assert result.confirmed_format is confirmed_format
    assert "temporary_path" not in serialized
    assert "storage_key" not in serialized
    assert result.statistics.extractor_name == "fake-extractor"
    assert result.statistics.extractor_version == "1.0.0"


def test_result_defensively_copies_the_ordered_block_collection() -> None:
    limits = extraction_limits()
    block = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits)
    source_blocks = [block]
    result = ExtractionResult(
        blocks=source_blocks,
        statistics=_statistics((block,), limits=limits),
        source_content_sha256="a" * 64,
        confirmed_format=ConfirmedDocumentFormat.DOCX,
        limits=limits,
    )

    source_blocks.clear()

    assert result.blocks == (block,)


@pytest.mark.parametrize("suffix", ["PDF", ".PDF", "application/pdf", "../pdf", ".exe", ""])
def test_confirmed_format_adapter_rejects_untrusted_values(suffix: str) -> None:
    with pytest.raises(ValueError, match="unsupported or malformed"):
        confirmed_format_from_suffix(suffix)


def test_confirmed_format_adapter_accepts_exact_server_suffix() -> None:
    assert confirmed_format_from_suffix(".pdf") is ConfirmedDocumentFormat.PDF


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ordinal": -1}, "ordinal"),
        ({"page_number": 0}, "page_number"),
        ({"row_start": 1}, "both be present"),
        ({"row_start": 2, "row_end": 1}, "row_start"),
        ({"sheet_name": "bad\x00name"}, "control"),
        ({"block_type": "heading"}, "block_type"),
        ({"extraction_method": "native"}, "extraction_method"),
        ({"text": "   "}, "extractable"),
    ],
)
def test_invalid_block_values_are_rejected(overrides: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "ordinal": 0,
        "text": "Synthetic text",
        "block_type": ExtractedBlockType.PARAGRAPH,
        "extraction_method": ExtractionMethod.NATIVE,
        "limits": extraction_limits(),
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        ExtractedBlock(**values)


def test_block_string_and_collection_limits_are_enforced() -> None:
    limits = extraction_limits(
        maximum_characters_per_block=5,
        maximum_heading_depth=1,
        maximum_heading_label_characters=3,
        maximum_sheet_name_characters=3,
    )
    with pytest.raises(ValueError, match="per-block"):
        ExtractedBlock(
            ordinal=0,
            text="too long",
            block_type=ExtractedBlockType.PARAGRAPH,
            limits=limits,
        )
    with pytest.raises(ValueError, match="heading-depth"):
        ExtractedBlock(
            ordinal=0,
            text="valid",
            block_type=ExtractedBlockType.HEADING,
            heading_path=("one", "two"),
            limits=limits,
        )
    with pytest.raises(ValueError, match="heading_path label"):
        ExtractedBlock(
            ordinal=0,
            text="valid",
            block_type=ExtractedBlockType.HEADING,
            heading_path=("four",),
            limits=limits,
        )
    with pytest.raises(ValueError, match="sheet_name"):
        ExtractedBlock(
            ordinal=0,
            text="valid",
            block_type=ExtractedBlockType.WORKSHEET_ROW,
            sheet_name="four",
            row_start=1,
            row_end=1,
            limits=limits,
        )


def test_allowlisted_metadata_shapes_are_json_serializable() -> None:
    limits = extraction_limits(maximum_metadata_fields=20)
    metadata = {
        "attributes": {"label": "synthetic", "count": 1},
        "column_index": 2,
        "column_name": "Scope",
        "coordinates": [1, 2.5],
        "is_header": True,
        "list_level": 1,
        "page_label": "A-1",
        "source_kind": "table",
        "table_index": 0,
    }
    block = ExtractedBlock(
        ordinal=0,
        text="Synthetic",
        block_type=ExtractedBlockType.PARAGRAPH,
        metadata=metadata,
        limits=limits,
    )

    assert json.loads(json.dumps(block.metadata))["source_kind"] == "table"


@pytest.mark.parametrize(
    "metadata",
    [
        {"unknown": "value"},
        {"attributes": {"path": "redacted"}},
        {"attributes": Path("synthetic")},
        {"attributes": b"bytes"},
        {"attributes": object()},
        {"attributes": float("nan")},
        {"attributes": float("inf")},
    ],
)
def test_unsafe_metadata_is_rejected(metadata: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ExtractedBlock(
            ordinal=0,
            text="Synthetic",
            block_type=ExtractedBlockType.PARAGRAPH,
            metadata=metadata,
            limits=extraction_limits(),
        )


def test_metadata_bounds_are_enforced() -> None:
    limits = extraction_limits(
        maximum_metadata_fields=1,
        maximum_metadata_depth=2,
        maximum_metadata_list_items=1,
        maximum_metadata_value_characters=3,
    )
    invalid_values = (
        {"source_kind": "four"},
        {"list_level": 10_000},
        {"coordinates": [1, 2]},
        {"attributes": {"one": {"two": 2}}},
        {"attributes": {"one": 1, "two": 2}},
    )
    for metadata in invalid_values:
        with pytest.raises(ValueError):
            ExtractedBlock(
                ordinal=0,
                text="Synthetic",
                block_type=ExtractedBlockType.PARAGRAPH,
                metadata=metadata,
                limits=limits,
            )


@pytest.mark.parametrize(
    "reserved_key",
    ["temporary_path", "storage_key", "filename", "endpoint", "credential", "parser_error"],
)
def test_reserved_metadata_keys_are_rejected_at_every_depth(reserved_key: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        ExtractedBlock(
            ordinal=0,
            text="Synthetic",
            block_type=ExtractedBlockType.PARAGRAPH,
            metadata={"attributes": {reserved_key: "redacted"}},
            limits=extraction_limits(),
        )


def _statistics(
    blocks: tuple[ExtractedBlock, ...],
    *,
    limits: ExtractionLimits,
    confirmed_format: ConfirmedDocumentFormat = ConfirmedDocumentFormat.DOCX,
    **overrides: object,
) -> ExtractionStatistics:
    values: dict[str, object] = {
        "detected_format": confirmed_format,
        "page_count": 0,
        "worksheet_count": 0,
        "table_count": 0,
        "row_count": 0,
        "block_count": len(blocks),
        "character_count": sum(len(block.text) for block in blocks),
        "native_page_count": 0,
        "ocr_page_count": 0,
        "warning_codes": (),
        "extractor_name": "fake-extractor",
        "extractor_version": "1.0.0",
        "limits": limits,
    }
    values.update(overrides)
    return ExtractionStatistics(**values)


def test_result_rejects_duplicate_and_out_of_order_ordinals() -> None:
    limits = extraction_limits()
    first = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits, ordinal=1)
    duplicate = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits, ordinal=1)
    second = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits, ordinal=0)

    with pytest.raises(ValueError, match="unique"):
        ExtractionResult(
            blocks=(first, duplicate),
            statistics=_statistics((first, duplicate), limits=limits),
            source_content_sha256="a" * 64,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=limits,
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        ExtractionResult(
            blocks=(first, second),
            statistics=_statistics((first, second), limits=limits),
            source_content_sha256="a" * 64,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=limits,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"block_count": 2},
        {"character_count": 999},
        {"detected_format": ConfirmedDocumentFormat.PDF},
    ],
)
def test_result_rejects_inconsistent_statistics(overrides: dict[str, object]) -> None:
    limits = extraction_limits()
    block = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits)
    statistics = _statistics((block,), limits=limits, **overrides)

    with pytest.raises(ValueError):
        ExtractionResult(
            blocks=(block,),
            statistics=statistics,
            source_content_sha256="a" * 64,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=limits,
        )


def test_result_revalidates_blocks_and_statistics_against_its_limits() -> None:
    loose_limits = extraction_limits()
    tight_limits = extraction_limits(
        maximum_pdf_pages=1,
        maximum_worksheets=1,
        maximum_rows_per_sheet=1,
        maximum_extracted_characters=10,
        maximum_blocks=1,
        maximum_characters_per_block=10,
        maximum_heading_label_characters=3,
        maximum_warnings=0,
        maximum_metadata_fields=0,
    )
    block = ExtractedBlock(
        ordinal=0,
        text="Synthetic",
        block_type=ExtractedBlockType.PARAGRAPH,
        heading_path=("Planning",),
        metadata={"source_kind": "synthetic"},
        limits=loose_limits,
    )
    statistics = _statistics((block,), limits=loose_limits)

    with pytest.raises(ValueError):
        ExtractionResult(
            blocks=(block,),
            statistics=statistics,
            source_content_sha256="a" * 64,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=tight_limits,
        )


def test_result_enforces_aggregate_character_limit() -> None:
    block_limits = extraction_limits(
        maximum_extracted_characters=100,
        maximum_characters_per_block=100,
    )
    result_limits = extraction_limits(
        maximum_extracted_characters=10,
        maximum_characters_per_block=10,
    )
    blocks = (
        block_for_format(
            ConfirmedDocumentFormat.DOCX,
            limits=block_limits,
            ordinal=0,
            text="First!",
        ),
        block_for_format(
            ConfirmedDocumentFormat.DOCX,
            limits=block_limits,
            ordinal=1,
            text="Second",
        ),
    )
    statistics = _statistics(blocks, limits=block_limits)

    with pytest.raises(ValueError, match="character_count"):
        ExtractionResult(
            blocks=blocks,
            statistics=statistics,
            source_content_sha256="a" * 64,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=result_limits,
        )


@pytest.mark.parametrize(
    ("confirmed_format", "location"),
    [
        (ConfirmedDocumentFormat.PDF, {}),
        (ConfirmedDocumentFormat.DOCX, {"page_number": 1}),
        (ConfirmedDocumentFormat.XLSX, {"row_start": 1, "row_end": 1}),
        (
            ConfirmedDocumentFormat.CSV,
            {"sheet_name": "Scope", "row_start": 1, "row_end": 1},
        ),
    ],
)
def test_result_rejects_format_incompatible_source_locations(
    confirmed_format: ConfirmedDocumentFormat,
    location: dict[str, object],
) -> None:
    limits = extraction_limits()
    block = ExtractedBlock(
        ordinal=0,
        text="Synthetic",
        block_type=ExtractedBlockType.PARAGRAPH,
        limits=limits,
        **location,
    )
    statistics = _statistics(
        (block,),
        limits=limits,
        confirmed_format=confirmed_format,
        page_count=1 if confirmed_format is ConfirmedDocumentFormat.PDF else 0,
        worksheet_count=1 if confirmed_format is ConfirmedDocumentFormat.XLSX else 0,
        row_count=1
        if confirmed_format in {ConfirmedDocumentFormat.XLSX, ConfirmedDocumentFormat.CSV}
        else 0,
    )

    with pytest.raises(ValueError):
        ExtractionResult(
            blocks=(block,),
            statistics=statistics,
            source_content_sha256="a" * 64,
            confirmed_format=confirmed_format,
            limits=limits,
        )


@pytest.mark.parametrize("source_hash", ["A" * 64, "a" * 63, "g" * 64])
def test_result_rejects_invalid_source_hash(source_hash: str) -> None:
    limits = extraction_limits()
    block = block_for_format(ConfirmedDocumentFormat.DOCX, limits=limits)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        ExtractionResult(
            blocks=(block,),
            statistics=_statistics((block,), limits=limits),
            source_content_sha256=source_hash,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=limits,
        )


def test_statistics_enforces_counts_warnings_and_identity() -> None:
    limits = extraction_limits(maximum_pdf_pages=1, maximum_warnings=1)
    values = {
        "detected_format": ConfirmedDocumentFormat.PDF,
        "page_count": 1,
        "worksheet_count": 0,
        "table_count": 0,
        "row_count": 0,
        "block_count": 1,
        "character_count": 1,
        "native_page_count": 1,
        "ocr_page_count": 0,
        "warning_codes": (ExtractionWarningCode.EMPTY_PAGE,),
        "extractor_name": "safe-name",
        "extractor_version": "1.0.0",
        "limits": limits,
    }
    assert ExtractionStatistics(**values).warning_codes == (ExtractionWarningCode.EMPTY_PAGE,)

    for overrides in (
        {"page_count": -1},
        {"page_count": 2},
        {"native_page_count": 2},
        {"warning_codes": (ExtractionWarningCode.EMPTY_PAGE,) * 2},
        {"extractor_name": "unsafe name"},
        {"extractor_version": "../version"},
    ):
        invalid = values | overrides
        with pytest.raises(ValueError):
            ExtractionStatistics(**invalid)


@pytest.mark.parametrize(
    "overrides",
    [
        {"worksheet_count": 6},
        {"worksheet_count": 1, "row_count": 101},
        {"block_count": 101},
        {"table_count": 101},
        {"character_count": 5_001},
    ],
)
def test_statistics_enforces_all_configured_count_limits(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "detected_format": ConfirmedDocumentFormat.XLSX,
        "page_count": 0,
        "worksheet_count": 1,
        "table_count": 0,
        "row_count": 1,
        "block_count": 1,
        "character_count": 1,
        "native_page_count": 0,
        "ocr_page_count": 0,
        "warning_codes": (),
        "extractor_name": "safe-name",
        "extractor_version": "1.0.0",
        "limits": extraction_limits(),
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        ExtractionStatistics(**values)


def test_limits_adapter_uses_validated_settings() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, document_max_extracted_blocks=321)
    limits = ExtractionLimits.from_settings(settings)

    assert limits.maximum_blocks == 321
    assert limits.maximum_pdf_pages == settings.document_max_pdf_pages


def test_limits_adapter_caps_per_block_limit_at_aggregate_limit() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        document_max_block_characters=2_000,
        document_max_extracted_characters=1_000,
    )

    assert ExtractionLimits.from_settings(settings).maximum_characters_per_block == 1_000
