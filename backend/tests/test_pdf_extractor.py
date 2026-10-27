import hashlib
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from extraction_fixtures import extraction_limits
from pdf_extraction_fixtures import FakeOcrRunner, pdf_policy
from pdf_fixtures import (
    _pdf_with_content_stream,
    compressed_content_pdf_bytes,
    encrypted_pdf_bytes,
    scanned_pdf_bytes,
    text_pages_pdf_bytes,
    text_pdf_bytes,
)

from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.extractors.pdf import (
    PDF_EXTRACTOR_NAME,
    PDF_EXTRACTOR_VERSION,
    PdfExtractor,
    _text_lines,
)
from app.services.ingestion.types import ExtractionMethod, ExtractionWarningCode


def write_fixture(tmp_path: Path, content: bytes) -> Path:
    workspace = tmp_path / str(uuid4())
    workspace.mkdir()
    path = workspace / "input.pdf"
    path.write_bytes(content)
    return path


def assert_error(
    extractor: PdfExtractor,
    path: Path,
    expected: ExtractionErrorCode,
    **limit_overrides: int,
) -> None:
    with pytest.raises(ExtractionError) as error:
        extractor.extract(path, extraction_limits(**limit_overrides))
    assert error.value.code is expected


def test_native_pdf_is_ordered_page_referenced_and_hashed(tmp_path: Path) -> None:
    content = text_pages_pdf_bytes(
        [
            [("Project 100", 720), ("Cost 2500", 680)],
            [("Delivery scope", 720)],
        ]
    )
    path = write_fixture(tmp_path, content)
    runner = FakeOcrRunner()

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), runner).extract(
        path, extraction_limits()
    )

    assert [block.ordinal for block in result.blocks] == [0, 1, 2]
    assert [block.page_number for block in result.blocks] == [1, 1, 2]
    assert [block.text for block in result.blocks] == ["Project 100", "Cost 2500", "Delivery scope"]
    assert all(block.extraction_method is ExtractionMethod.NATIVE for block in result.blocks)
    assert result.source_content_sha256 == hashlib.sha256(content).hexdigest()
    assert result.statistics.extractor_name == PDF_EXTRACTOR_NAME
    assert result.statistics.extractor_version == PDF_EXTRACTOR_VERSION
    assert result.statistics.page_count == 2
    assert result.statistics.native_page_count == 2
    assert result.statistics.ocr_page_count == 0
    assert runner.calls == []


def test_rotated_page_and_blank_page_are_retained_in_statistics(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path,
        text_pages_pdf_bytes(
            [[("Rotated project scope", 720)], [], [("Final scope", 720)]],
            rotated_pages=frozenset({1}),
        ),
    )

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
        path, extraction_limits()
    )

    assert [block.text for block in result.blocks] == ["Rotated project scope", "Final scope"]
    assert [block.page_number for block in result.blocks] == [1, 3]
    assert result.statistics.page_count == 3
    assert ExtractionWarningCode.EMPTY_PAGE in result.statistics.warning_codes


def test_unicode_and_ligature_text_is_not_semantically_normalized() -> None:
    assert _text_lines("Scope cafe\u0301 \ufb01t\n") == ("Scope cafe\u0301 \ufb01t",)


def test_repeated_top_and_bottom_margins_are_removed_conservatively(tmp_path: Path) -> None:
    pages = [
        [("Synthetic Header", 770), (f"Section {index}", 700), ("Page Footer", 20)]
        for index in range(1, 5)
    ]
    path = write_fixture(tmp_path, text_pages_pdf_bytes(pages))

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
        path, extraction_limits()
    )

    assert [block.text for block in result.blocks] == [
        "Section 1",
        "Section 2",
        "Section 3",
        "Section 4",
    ]
    assert ExtractionWarningCode.REPEATED_MARGIN_REMOVED in result.statistics.warning_codes


def test_short_or_nonrepeating_margin_content_is_retained(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path,
        text_pages_pdf_bytes(
            [
                [("Section Alpha", 770), ("Scope A", 700)],
                [("Section Beta", 770), ("Scope B", 700)],
            ]
        ),
    )

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
        path, extraction_limits()
    )

    assert [block.text for block in result.blocks] == [
        "Section Alpha",
        "Scope A",
        "Section Beta",
        "Scope B",
    ]
    assert ExtractionWarningCode.REPEATED_MARGIN_REMOVED not in result.statistics.warning_codes


def test_repeated_meaningful_heading_is_retained(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path,
        text_pages_pdf_bytes(
            [[("Requirements", 770), (f"Scope {index}", 700)] for index in range(1, 5)]
        ),
    )

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
        path, extraction_limits()
    )

    assert [block.text for block in result.blocks].count("Requirements") == 4
    assert ExtractionWarningCode.REPEATED_MARGIN_REMOVED not in result.statistics.warning_codes


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (encrypted_pdf_bytes(), ExtractionErrorCode.DOCUMENT_ENCRYPTED),
        (b"not-a-pdf", ExtractionErrorCode.DOCUMENT_MALFORMED),
        (b"%PDF-1.7\nmalformed", ExtractionErrorCode.DOCUMENT_MALFORMED),
    ],
)
def test_encrypted_and_malformed_pdfs_fail_with_stable_errors(
    tmp_path: Path, content: bytes, code: ExtractionErrorCode
) -> None:
    extractor = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner())
    assert_error(extractor, write_fixture(tmp_path, content), code)


def test_page_stream_block_and_aggregate_limits_fail_closed(tmp_path: Path) -> None:
    extractor = PdfExtractor(
        pdf_policy(processing_root=tmp_path, maximum_content_stream_bytes=4096),
        FakeOcrRunner(),
    )
    too_many_pages = write_fixture(
        tmp_path,
        text_pages_pdf_bytes([[("Scope", 720)], [("More scope", 720)]]),
    )
    assert_error(
        extractor,
        too_many_pages,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        maximum_pdf_pages=1,
    )

    oversized_stream = write_fixture(tmp_path, _pdf_with_content_stream(b"%" + b"x" * 5000))
    assert_error(
        extractor,
        oversized_stream,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
    )

    compressed_stream = write_fixture(tmp_path, compressed_content_pdf_bytes(5000))
    assert_error(
        extractor,
        compressed_stream,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
    )

    oversized_block = write_fixture(
        tmp_path,
        text_pages_pdf_bytes([[("A" * 40, 720)]]),
    )
    assert_error(
        PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()),
        oversized_block,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        maximum_characters_per_block=20,
    )
    assert_error(
        PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()),
        oversized_block,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        maximum_extracted_characters=30,
        maximum_characters_per_block=30,
    )


def test_parser_deadline_maps_to_retryable_timeout(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, text_pdf_bytes())
    assert_error(
        PdfExtractor(
            pdf_policy(processing_root=tmp_path, parser_timeout_seconds=-1),
            FakeOcrRunner(),
        ),
        path,
        ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT,
    )


def test_blank_pdf_maps_to_no_extractable_content(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, text_pages_pdf_bytes([[]]))
    assert_error(
        PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()),
        path,
        ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT,
    )


def test_non_regular_and_symlink_inputs_fail_without_path_disclosure(tmp_path: Path) -> None:
    extractor = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner())
    assert_error(extractor, tmp_path, ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
    if hasattr(Path, "symlink_to"):
        source = write_fixture(tmp_path, text_pdf_bytes())
        link = tmp_path / "link.pdf"
        try:
            link.symlink_to(source)
        except OSError:
            pytest.skip("Symlinks are unavailable for this test account")
        assert_error(extractor, link, ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)


def test_regular_file_outside_controlled_uuid_workspace_is_rejected(tmp_path: Path) -> None:
    content = text_pdf_bytes()
    outside = tmp_path / "input.pdf"
    outside.write_bytes(content)
    wrong_name_workspace = tmp_path / str(uuid4())
    wrong_name_workspace.mkdir()
    wrong_name = wrong_name_workspace / "customer.pdf"
    wrong_name.write_bytes(content)
    extractor = PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner())

    assert_error(extractor, outside, ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
    assert_error(extractor, wrong_name, ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)


def test_unexpected_parser_error_is_redacted(tmp_path: Path, caplog) -> None:
    marker = "private-marker /tmp/customer.pdf storage-key endpoint"
    runner = FakeOcrRunner(error=RuntimeError(marker))
    path = write_fixture(tmp_path, scanned_pdf_bytes())

    with caplog.at_level(logging.WARNING):
        assert_error(
            PdfExtractor(pdf_policy(processing_root=tmp_path), runner),
            path,
            ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED,
        )

    assert marker not in caplog.text
    assert str(path) not in caplog.text
