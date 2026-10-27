from __future__ import annotations

from collections.abc import Sequence

from extraction_fixtures import extraction_limits

from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatistics,
)


class CharacterTokenizer:
    name = "BAAI/bge-small-en-v1.5"
    revision = "synthetic-approved-revision"
    maximum_sequence_length = 512

    def encode(self, text: str) -> tuple[int, ...]:
        return (101, *(ord(character) + 1_000 for character in text), 102)

    def decode(self, token_ids: Sequence[int]) -> str:
        return "".join(chr(token_id - 1_000) for token_id in token_ids if token_id >= 1_000)

    def count(self, text: str) -> int:
        return len(self.encode(text))

    def self_check(self) -> None:
        assert self.count("ready") == 7


def extraction_result(
    confirmed_format: ConfirmedDocumentFormat,
    specs: list[dict[str, object]],
) -> ExtractionResult:
    limits = extraction_limits(
        maximum_extracted_characters=100_000,
        maximum_characters_per_block=50_000,
        maximum_blocks=1_000,
    )
    blocks = []
    for ordinal, spec in enumerate(specs):
        values = dict(spec)
        text = str(values.pop("text"))
        block_type = values.pop("block_type", ExtractedBlockType.PARAGRAPH)
        metadata = values.pop("metadata", {"source_kind": "synthetic"})
        blocks.append(
            ExtractedBlock(
                ordinal=ordinal,
                text=text,
                block_type=block_type,
                limits=limits,
                extraction_method=values.pop("extraction_method", ExtractionMethod.NATIVE),
                metadata=metadata,
                **values,
            )
        )
    pages = {block.page_number for block in blocks if block.page_number is not None}
    sheets = {block.sheet_name for block in blocks if block.sheet_name is not None}
    rows = sum(1 for block in blocks if block.row_start is not None)
    statistics = ExtractionStatistics(
        detected_format=confirmed_format,
        page_count=max(pages, default=0),
        worksheet_count=len(sheets),
        table_count=sum(
            block.block_type in {ExtractedBlockType.TABLE_ROW, ExtractedBlockType.WORKSHEET_ROW}
            for block in blocks
        ),
        row_count=rows,
        block_count=len(blocks),
        character_count=sum(len(block.text) for block in blocks),
        native_page_count=len(pages),
        ocr_page_count=0,
        warning_codes=(),
        extractor_name="synthetic-extractor",
        extractor_version="1.0.0",
        limits=limits,
    )
    return ExtractionResult(
        blocks=blocks,
        statistics=statistics,
        source_content_sha256="b" * 64,
        confirmed_format=confirmed_format,
        limits=limits,
    )
