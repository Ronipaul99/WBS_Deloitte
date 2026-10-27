from pathlib import Path

from pdf_fixtures import text_pages_pdf_bytes

from app.services.ingestion.extractors.pdf import PdfExtractionPolicy


def pdf_policy(**overrides: object) -> PdfExtractionPolicy:
    values: dict[str, object] = {
        "processing_root": Path("."),
        "maximum_input_bytes": 2 * 1024 * 1024,
        "maximum_content_stream_bytes": 1024 * 1024,
        "native_text_minimum_characters": 32,
        "repeated_margin_minimum_pages": 3,
        "repeated_margin_minimum_ratio": 0.8,
        "margin_band_ratio": 0.12,
        "repeated_margin_maximum_characters": 160,
        "parser_timeout_seconds": 30,
        "ocr_languages": ("eng",),
        "ocr_timeout_seconds": 30,
        "ocr_maximum_output_bytes": 2 * 1024 * 1024,
        "ocr_maximum_temporary_bytes": 4 * 1024 * 1024,
        "ocr_process_output_maximum_bytes": 4096,
        "ocr_cpu_limit_seconds": 30,
        "ocr_memory_limit_bytes": 256 * 1024 * 1024,
        "ocrmypdf_expected_version": "test-ocrmypdf",
        "tesseract_expected_version": "test-tesseract",
    }
    values.update(overrides)
    return PdfExtractionPolicy(**values)


class FakeOcrRunner:
    def __init__(
        self,
        page_text: dict[int, tuple[str, ...]] | None = None,
        *,
        error: BaseException | None = None,
        ready: bool = True,
    ) -> None:
        self.page_text = page_text or {}
        self.error = error
        self.ready = ready
        self.calls: list[tuple[Path, Path, tuple[int, ...]]] = []

    def run(
        self,
        input_path: Path,
        output_path: Path,
        page_numbers: tuple[int, ...],
        policy: PdfExtractionPolicy,
    ) -> None:
        del policy
        self.calls.append((input_path, output_path, page_numbers))
        if self.error is not None:
            raise self.error
        from pypdf import PdfReader

        page_count = len(PdfReader(input_path, strict=True).pages)
        pages: list[list[tuple[str, int]]] = []
        for page_number in range(1, page_count + 1):
            lines = self.page_text.get(page_number, ())
            pages.append([(line, 720 - index * 20) for index, line in enumerate(lines)])
        output_path.write_bytes(text_pages_pdf_bytes(pages))

    def is_ready(self, policy: PdfExtractionPolicy) -> bool:
        del policy
        return self.ready
