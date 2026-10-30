import json

import pytest
from chunking_fixtures import CharacterTokenizer, extraction_result

from app.services.ingestion.chunk_types import (
    ChunkingPolicy,
    ChunkWarningCode,
    SourceReferenceRole,
)
from app.services.ingestion.chunking import DocumentChunker
from app.services.ingestion.errors import ChunkingError, ChunkingErrorCode
from app.services.ingestion.types import ConfirmedDocumentFormat, ExtractedBlockType


def policy(**overrides: int) -> ChunkingPolicy:
    values = {
        "target_tokens": 60,
        "overlap_tokens": 12,
        "maximum_content_tokens": 80,
        "formatting_headroom_tokens": 32,
        "model_sequence_length": 512,
        "maximum_chunks": 100,
        "maximum_source_references": 20,
        "maximum_characters": 10_000,
        "maximum_heading_depth": 8,
        "maximum_heading_label_characters": 100,
        "maximum_warnings": 10,
    }
    values.update(overrides)
    return ChunkingPolicy(**values)


def chunker(**overrides: int) -> DocumentChunker:
    return DocumentChunker(tokenizer=CharacterTokenizer(), policy=policy(**overrides))


def test_persisted_hash_contract_remains_compatible_with_existing_chunks() -> None:
    source = extraction_result(
        ConfirmedDocumentFormat.PDF,
        [{"text": "Evidence wraps\nacross lines.", "page_number": 1, "heading_path": ("Scope",)}],
    )
    result = DocumentChunker(tokenizer=CharacterTokenizer(), policy=ChunkingPolicy()).chunk(source)
    assert result.chunks[0].chunk_sha256 == (
        "5ae9b9793fd7bfd825642cb772b7b173bc68240a9bb67ca220a379b352709c87"
    )


def test_small_blocks_group_and_deterministic_output_is_byte_identical() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.DOCX,
        [
            {"text": "REQ-1 Scope remains included.", "heading_path": ("Scope",)},
            {"text": "Constraint: finish by 2026-10-25.", "heading_path": ("Scope",)},
        ],
    )

    first = chunker(target_tokens=75, maximum_content_tokens=90).chunk(result)
    second = chunker(target_tokens=75, maximum_content_tokens=90).chunk(result)

    assert json.dumps(first.to_jsonable(), sort_keys=True) == json.dumps(
        second.to_jsonable(), sort_keys=True
    )
    assert first.chunks[0].primary_source_block_ordinals == (0, 1)
    assert first.chunks[0].token_count <= 80
    assert len(first.chunks[0].chunk_sha256) == 64


def test_heading_transition_creates_boundary_and_overlap_does_not_cross_it() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.DOCX,
        [
            {"text": "A" * 45, "heading_path": ("Scope",)},
            {"text": "B" * 45, "heading_path": ("Risks",)},
        ],
    )

    output = chunker().chunk(result)

    assert len(output.chunks) == 2
    assert output.chunks[1].overlap_source_block_ordinals == ()


def test_glossary_alias_and_table_caption_context_has_explicit_provenance():
    result = extraction_result(
        ConfirmedDocumentFormat.PDF,
        [
            {
                "text": "Power Purchase Agreement or PPA | means the agreement.",
                "block_type": ExtractedBlockType.TABLE_ROW,
                "heading_path": ("GLOSSARY", "Power Purchase Agreement or PPA"),
                "page_number": 1,
                "metadata": {"table_index": 1},
            },
            {
                "text": "Term | means 25 years from PPA execution.",
                "block_type": ExtractedBlockType.TABLE_ROW,
                "heading_path": ("GLOSSARY", "Term"),
                "page_number": 2,
                "metadata": {"table_index": 1},
            },
            {
                "text": "The earnest money deposit is listed below:",
                "page_number": 3,
                "heading_path": ("7. EMD",),
            },
            {
                "text": "One unit | 100 currency units",
                "page_number": 3,
                "block_type": ExtractedBlockType.TABLE_ROW,
                "heading_path": ("7. EMD",),
                "metadata": {"table_index": 2},
            },
        ],
    )
    output = chunker(target_tokens=300, maximum_content_tokens=400).chunk(result)
    term = next(c for c in output.chunks if 1 in c.primary_source_block_ordinals)
    assert "Power Purchase Agreement or PPA" in term.content
    assert term.context_source_block_ordinals == (0,)
    row = next(c for c in output.chunks if 3 in c.primary_source_block_ordinals)
    assert "earnest money deposit" in row.content
    assert row.context_source_block_ordinals == (2,)
    assert all(c.token_count <= 400 for c in output.chunks)
    assert {i for c in output.chunks for i in c.primary_source_block_ordinals} == {0, 1, 2, 3}


def test_oversized_paragraph_splits_without_loss_and_stays_bounded() -> None:
    text = "Requirement one remains. Requirement two remains. Requirement three remains."
    result = extraction_result(ConfirmedDocumentFormat.DOCX, [{"text": text}])

    output = chunker(target_tokens=35, maximum_content_tokens=42).chunk(result)

    assert len(output.chunks) >= 2
    assert all(chunk.token_count <= 42 for chunk in output.chunks)
    assert output.statistics.forced_split_count == 1
    assert all(0 in chunk.primary_source_block_ordinals for chunk in output.chunks)
    assert ChunkWarningCode.FORCED_SPLIT in output.statistics.warning_codes


def test_compatible_chunks_carry_bounded_overlap_with_separate_provenance() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.DOCX,
        [
            {
                "text": "First paragraph contains retained scope details.",
                "heading_path": ("Scope",),
            },
            {"text": "Second paragraph contains delivery assumptions.", "heading_path": ("Scope",)},
        ],
    )

    output = chunker(target_tokens=45, maximum_content_tokens=70, overlap_tokens=10).chunk(result)

    assert len(output.chunks) == 2
    assert output.chunks[1].overlap_source_block_ordinals == (0,)
    assert output.chunks[1].primary_source_block_ordinals == (1,)
    assert any(
        reference.role is SourceReferenceRole.OVERLAP
        for reference in output.chunks[1].source_references
    )
    assert output.chunks[1].token_count <= 70


def test_worksheet_header_is_repeated_as_context_without_distorting_rows() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.XLSX,
        [
            {
                "text": "Item | Quantity | Unit",
                "block_type": ExtractedBlockType.WORKSHEET_ROW,
                "sheet_name": "Scope",
                "row_start": 1,
                "row_end": 1,
                "metadata": {"source_kind": "worksheet", "is_header": True},
            },
            {
                "text": "Desk | 25 | each",
                "block_type": ExtractedBlockType.WORKSHEET_ROW,
                "sheet_name": "Scope",
                "row_start": 2,
                "row_end": 2,
                "metadata": {"source_kind": "worksheet", "is_header": False},
            },
            {
                "text": "Chair | 40 | each",
                "block_type": ExtractedBlockType.WORKSHEET_ROW,
                "sheet_name": "Scope",
                "row_start": 3,
                "row_end": 3,
                "metadata": {"source_kind": "worksheet", "is_header": False},
            },
        ],
    )

    output = chunker(target_tokens=35, maximum_content_tokens=62, overlap_tokens=0).chunk(result)

    dependent = next(chunk for chunk in output.chunks if 2 in chunk.primary_source_block_ordinals)
    assert dependent.content.startswith("Item | Quantity | Unit")
    assert dependent.context_source_block_ordinals == (0,)
    assert dependent.row_start >= 2
    assert dependent.row_end == 3
    assert dependent.sheet_name == "Scope"


def test_different_worksheets_never_mix() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.XLSX,
        [
            {
                "text": "A | 1",
                "block_type": ExtractedBlockType.WORKSHEET_ROW,
                "sheet_name": "One",
                "row_start": 1,
                "row_end": 1,
            },
            {
                "text": "B | 2",
                "block_type": ExtractedBlockType.WORKSHEET_ROW,
                "sheet_name": "Two",
                "row_start": 1,
                "row_end": 1,
            },
        ],
    )

    output = chunker().chunk(result)

    assert [chunk.sheet_name for chunk in output.chunks] == ["One", "Two"]


def test_csv_rows_retain_rows_without_inventing_worksheet() -> None:
    result = extraction_result(
        ConfirmedDocumentFormat.CSV,
        [
            {
                "text": "Code | Value",
                "block_type": ExtractedBlockType.TABLE_ROW,
                "row_start": 1,
                "row_end": 1,
                "metadata": {"source_kind": "csv", "is_header": True},
            },
            {
                "text": "REQ-1 | 25%",
                "block_type": ExtractedBlockType.TABLE_ROW,
                "row_start": 2,
                "row_end": 2,
                "metadata": {"source_kind": "csv", "is_header": False},
            },
        ],
    )

    output = chunker().chunk(result)

    assert all(chunk.sheet_name is None for chunk in output.chunks)
    assert {row for chunk in output.chunks for row in (chunk.row_start, chunk.row_end)} >= {1, 2}


def test_policy_and_chunk_limits_fail_closed() -> None:
    with pytest.raises(ValueError):
        policy(target_tokens=50, overlap_tokens=50)
    with pytest.raises(ValueError):
        policy(maximum_content_tokens=500, formatting_headroom_tokens=13)

    result = extraction_result(ConfirmedDocumentFormat.DOCX, [{"text": "A" * 100}])
    with pytest.raises(ChunkingError) as error:
        chunker(maximum_chunks=1, target_tokens=25, maximum_content_tokens=30).chunk(result)
    assert error.value.code is ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED


def test_hash_changes_when_stable_source_identity_changes() -> None:
    first = extraction_result(ConfirmedDocumentFormat.DOCX, [{"text": "Same content"}])
    second = extraction_result(
        ConfirmedDocumentFormat.DOCX,
        [{"text": "Prefix"}, {"text": "Same content", "heading_path": ("Different",)}],
    )

    first_hash = chunker().chunk(first).chunks[0].chunk_sha256
    second_hash = chunker().chunk(second).chunks[-1].chunk_sha256

    assert first_hash != second_hash


def test_result_collections_are_defensively_frozen() -> None:
    result = extraction_result(ConfirmedDocumentFormat.DOCX, [{"text": "Stable content"}])
    output = chunker().chunk(result)

    assert isinstance(output.chunks, tuple)
    assert isinstance(output.statistics.warning_codes, tuple)
    with pytest.raises(AttributeError):
        output.chunks.append(output.chunks[0])
