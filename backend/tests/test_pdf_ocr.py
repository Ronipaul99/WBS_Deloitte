from pathlib import Path
from uuid import uuid4

import pytest
from extraction_fixtures import extraction_limits
from pdf_extraction_fixtures import FakeOcrRunner, pdf_policy
from pdf_fixtures import scanned_pdf_bytes, text_pages_pdf_bytes

from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.extractors.pdf import PdfExtractor
from app.services.ingestion.types import ExtractionMethod, ExtractionWarningCode


def write_fixture(tmp_path: Path, content: bytes) -> Path:
    workspace = tmp_path / str(uuid4())
    workspace.mkdir()
    path = workspace / "input.pdf"
    path.write_bytes(content)
    return path


def test_scanned_pdf_uses_ocr_and_preserves_page_number(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, scanned_pdf_bytes())
    runner = FakeOcrRunner({1: ("OCR project scope",)})

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), runner).extract(
        path, extraction_limits()
    )

    assert runner.calls[0][2] == (1,)
    locations = [
        (block.text, block.page_number, block.extraction_method) for block in result.blocks
    ]
    assert locations == [("OCR project scope", 1, ExtractionMethod.OCR)]
    assert result.statistics.native_page_count == 0
    assert result.statistics.ocr_page_count == 1
    assert ExtractionWarningCode.OCR_USED in result.statistics.warning_codes
    assert not list(tmp_path.rglob("ocr-output-*.pdf"))


def test_mixed_pdf_ocr_removes_exact_duplicate_and_retains_distinct_text(tmp_path: Path) -> None:
    path = write_fixture(
        tmp_path,
        text_pages_pdf_bytes(
            [[("A", 720)]],
            image_pages=frozenset({1}),
        ),
    )
    runner = FakeOcrRunner({1: ("A", "Distinct scanned requirement")})

    result = PdfExtractor(pdf_policy(processing_root=tmp_path), runner).extract(
        path, extraction_limits()
    )

    assert [block.text for block in result.blocks] == ["A", "Distinct scanned requirement"]
    assert [block.extraction_method for block in result.blocks] == [
        ExtractionMethod.NATIVE,
        ExtractionMethod.OCR,
    ]
    assert result.statistics.native_page_count == 1
    assert result.statistics.ocr_page_count == 1
    assert ExtractionWarningCode.MIXED_PAGE_OCR_USED in result.statistics.warning_codes


def test_only_classified_pages_are_requested_from_ocr(tmp_path: Path) -> None:
    source = text_pages_pdf_bytes(
        [[("Complete native page content", 720)], []],
        image_pages=frozenset({2}),
    )
    path = write_fixture(tmp_path, source)
    runner = FakeOcrRunner({2: ("Scanned second page",)})

    result = PdfExtractor(
        pdf_policy(processing_root=tmp_path, native_text_minimum_characters=10), runner
    ).extract(path, extraction_limits())

    assert runner.calls[0][2] == (2,)
    assert [block.page_number for block in result.blocks] == [1, 2]


def test_empty_or_page_mismatched_ocr_output_fails_and_is_cleaned(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, scanned_pdf_bytes())
    with pytest.raises(ExtractionError) as empty_error:
        PdfExtractor(pdf_policy(processing_root=tmp_path), FakeOcrRunner()).extract(
            path, extraction_limits()
        )
    assert empty_error.value.code is ExtractionErrorCode.OCR_FAILED
    assert not list(tmp_path.rglob("ocr-output-*.pdf"))

    class WrongPageCountRunner(FakeOcrRunner):
        def run(self, input_path, output_path, page_numbers, policy) -> None:
            del input_path, page_numbers, policy
            output_path.write_bytes(
                text_pages_pdf_bytes([[("Page one", 720)], [("Unexpected page", 720)]])
            )

    with pytest.raises(ExtractionError) as mismatch_error:
        PdfExtractor(pdf_policy(processing_root=tmp_path), WrongPageCountRunner()).extract(
            path, extraction_limits()
        )
    assert mismatch_error.value.code is ExtractionErrorCode.OCR_FAILED
    assert not list(tmp_path.rglob("ocr-output-*.pdf"))


@pytest.mark.parametrize(
    "code",
    [
        ExtractionErrorCode.OCR_UNAVAILABLE,
        ExtractionErrorCode.OCR_FAILED,
        ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT,
        ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED,
    ],
)
def test_ocr_failures_keep_stable_classification_and_cleanup(
    tmp_path: Path, code: ExtractionErrorCode
) -> None:
    path = write_fixture(tmp_path, scanned_pdf_bytes())
    runner = FakeOcrRunner(error=ExtractionError(code))

    with pytest.raises(ExtractionError) as error:
        PdfExtractor(pdf_policy(processing_root=tmp_path), runner).extract(
            path, extraction_limits()
        )

    assert error.value.code is code
    assert not list(tmp_path.rglob("ocr-output-*.pdf"))


def test_forced_interruption_cleans_ocr_output(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, scanned_pdf_bytes())

    class InterruptedRunner(FakeOcrRunner):
        def run(self, input_path, output_path, page_numbers, policy) -> None:
            del input_path, page_numbers, policy
            output_path.write_bytes(b"partial")
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        PdfExtractor(pdf_policy(processing_root=tmp_path), InterruptedRunner()).extract(
            path, extraction_limits()
        )

    assert not list(tmp_path.rglob("ocr-output-*.pdf"))


def test_oversized_ocr_output_is_rejected_even_for_injected_runner(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, scanned_pdf_bytes())

    class OversizedRunner(FakeOcrRunner):
        def run(self, input_path, output_path, page_numbers, policy) -> None:
            del input_path, page_numbers
            output_path.write_bytes(b"%PDF-" + b"x" * policy.ocr_maximum_output_bytes)

    with pytest.raises(ExtractionError) as error:
        PdfExtractor(
            pdf_policy(processing_root=tmp_path, ocr_maximum_output_bytes=4096),
            OversizedRunner(),
        ).extract(path, extraction_limits())

    assert error.value.code is ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED
    assert not list(tmp_path.rglob("ocr-output-*.pdf"))
