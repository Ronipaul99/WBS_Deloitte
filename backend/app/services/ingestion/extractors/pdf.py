from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol
from uuid import UUID, uuid4

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError, PyPdfError
from pypdf.generic import ArrayObject, IndirectObject, StreamObject

from app.core.observability import record_pdf_extraction, record_pdf_ocr
from app.services.ingestion.errors import (
    ExtractionError,
    ExtractionErrorCode,
    map_unexpected_extraction_failure,
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

try:
    import resource
except ImportError:  # pragma: no cover - Windows does not expose POSIX resource limits.
    resource = None


OCRMY_PDF_EXECUTABLE = "ocrmypdf"
TESSERACT_EXECUTABLE = "tesseract"
PDF_EXTRACTOR_NAME = "pypdf-ocrmypdf"
PDF_EXTRACTOR_VERSION = "1.0.0"
_INLINE_IMAGE_OPERATOR = re.compile(rb"(?<!\S)BI(?!\S)")
_REPEATED_MARGIN_ARTIFACT = re.compile(
    r"(?:\bheader\b|\bfooter\b|\bconfidential\b|\bcopyright\b|\bpage\s+\d+\b)",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


class PdfPageClassification(StrEnum):
    NATIVE = "native"
    MIXED = "mixed"
    OCR_REQUIRED = "ocr_required"
    BLANK = "blank"


@dataclass(frozen=True, slots=True)
class PdfExtractionPolicy:
    processing_root: Path
    maximum_input_bytes: int
    maximum_content_stream_bytes: int
    native_text_minimum_characters: int
    repeated_margin_minimum_pages: int
    repeated_margin_minimum_ratio: float
    margin_band_ratio: float
    repeated_margin_maximum_characters: int
    parser_timeout_seconds: int
    ocr_languages: tuple[str, ...]
    ocr_timeout_seconds: int
    ocr_maximum_output_bytes: int
    ocr_maximum_temporary_bytes: int
    ocr_process_output_maximum_bytes: int
    ocr_cpu_limit_seconds: int
    ocr_memory_limit_bytes: int
    ocrmypdf_expected_version: str | None
    tesseract_expected_version: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> PdfExtractionPolicy:
        return cls(
            processing_root=Path(settings.document_processing_temp_root),
            maximum_input_bytes=settings.max_upload_bytes,
            maximum_content_stream_bytes=settings.pdf_max_content_stream_bytes,
            native_text_minimum_characters=settings.pdf_native_text_min_characters,
            repeated_margin_minimum_pages=settings.pdf_repeated_margin_min_pages,
            repeated_margin_minimum_ratio=settings.pdf_repeated_margin_min_ratio,
            margin_band_ratio=settings.pdf_margin_band_ratio,
            repeated_margin_maximum_characters=(settings.pdf_repeated_margin_max_characters),
            parser_timeout_seconds=min(
                settings.pdf_parser_timeout_seconds,
                settings.document_processing_timeout_seconds,
            ),
            ocr_languages=(settings.ocr_languages,),
            ocr_timeout_seconds=min(
                settings.ocr_timeout_seconds,
                settings.document_processing_timeout_seconds,
            ),
            ocr_maximum_output_bytes=settings.ocr_max_output_bytes,
            ocr_maximum_temporary_bytes=settings.ocr_max_temporary_bytes,
            ocr_process_output_maximum_bytes=settings.ocr_process_output_max_bytes,
            ocr_cpu_limit_seconds=settings.ocr_cpu_limit_seconds,
            ocr_memory_limit_bytes=settings.ocr_memory_limit_bytes,
            ocrmypdf_expected_version=settings.ocrmypdf_expected_version,
            tesseract_expected_version=settings.tesseract_expected_version,
        )


class OcrRunner(Protocol):
    def run(
        self,
        input_path: Path,
        output_path: Path,
        page_numbers: tuple[int, ...],
        policy: PdfExtractionPolicy,
    ) -> None: ...

    def is_ready(self, policy: PdfExtractionPolicy) -> bool: ...


@dataclass(frozen=True, slots=True)
class _ExtractedLine:
    text: str
    method: ExtractionMethod


@dataclass(frozen=True, slots=True)
class _MarginCandidate:
    text: str
    region: str


@dataclass(frozen=True, slots=True)
class _PageDraft:
    page_number: int
    classification: PdfPageClassification
    lines: tuple[_ExtractedLine, ...]
    margin_candidates: frozenset[_MarginCandidate]


class SubprocessOcrRunner:
    def run(
        self,
        input_path: Path,
        output_path: Path,
        page_numbers: tuple[int, ...],
        policy: PdfExtractionPolicy,
    ) -> None:
        if not page_numbers:
            return
        workspace = input_path.parent.resolve(strict=True)
        if output_path.parent.resolve(strict=True) != workspace or output_path == input_path:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
        if output_path.exists() or output_path.is_symlink():
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
        if not self.is_ready(policy):
            raise ExtractionError(ExtractionErrorCode.OCR_UNAVAILABLE)
        baseline_entries = frozenset(entry.name for entry in workspace.iterdir())

        stdout_path = workspace / f"ocr-stdout-{uuid4().hex}.log"
        stderr_path = workspace / f"ocr-stderr-{uuid4().hex}.log"
        command = self._command(input_path, output_path, page_numbers, policy)
        environment = {
            "HOME": str(workspace),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "OMP_THREAD_LIMIT": "1",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "TMPDIR": str(workspace),
        }
        process: subprocess.Popen[bytes] | None = None
        started = time.monotonic()
        outcome = "failed"
        try:
            with _exclusive_binary_output(stdout_path) as stdout_file:
                with _exclusive_binary_output(stderr_path) as stderr_file:
                    try:
                        process = subprocess.Popen(
                            command,
                            cwd=workspace,
                            env=environment,
                            stdin=subprocess.DEVNULL,
                            stdout=stdout_file,
                            stderr=stderr_file,
                            shell=False,
                            start_new_session=True,
                        )
                    except (FileNotFoundError, PermissionError, OSError):
                        outcome = "unavailable"
                        raise ExtractionError(ExtractionErrorCode.OCR_UNAVAILABLE) from None

                    if not _apply_process_limits(process.pid, policy):
                        outcome = "unavailable"
                        raise ExtractionError(ExtractionErrorCode.OCR_UNAVAILABLE)

                    deadline = started + policy.ocr_timeout_seconds
                    while process.poll() is None:
                        if time.monotonic() >= deadline:
                            outcome = "timeout"
                            raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT)
                        if _file_size(output_path) > policy.ocr_maximum_output_bytes:
                            outcome = "resource_exhausted"
                            raise ExtractionError(
                                ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED
                            )
                        if (
                            _file_size(stdout_path) > policy.ocr_process_output_maximum_bytes
                            or _file_size(stderr_path) > policy.ocr_process_output_maximum_bytes
                            or _workspace_file_bytes(workspace) > policy.ocr_maximum_temporary_bytes
                        ):
                            outcome = "resource_exhausted"
                            raise ExtractionError(
                                ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED
                            )
                        time.sleep(0.05)

                    if process.returncode != 0:
                        raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
                    if (
                        _file_size(stdout_path) > policy.ocr_process_output_maximum_bytes
                        or _file_size(stderr_path) > policy.ocr_process_output_maximum_bytes
                        or _workspace_file_bytes(workspace) > policy.ocr_maximum_temporary_bytes
                    ):
                        outcome = "resource_exhausted"
                        raise ExtractionError(
                            ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED
                        )
                    output_size = _file_size(output_path)
                    if (
                        output_size <= 0
                        or output_size > policy.ocr_maximum_output_bytes
                        or output_path.is_symlink()
                        or not output_path.is_file()
                    ):
                        raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
                    if output_path.resolve(strict=True).parent != workspace:
                        raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
                    outcome = "success"
        finally:
            active_failure = sys.exc_info()[0] is not None
            if process is not None and process.poll() is None:
                _terminate_process(process)
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
            cleanup_failed = False
            try:
                _remove_ocr_artifacts(
                    workspace,
                    baseline_entries=baseline_entries,
                    preserved_output=output_path if outcome == "success" else None,
                )
            except ExtractionError:
                cleanup_failed = True
                logger.error("OCR workspace cleanup failed")
            finally:
                record_pdf_ocr(
                    duration_seconds=time.monotonic() - started,
                    outcome=outcome,
                )
            if cleanup_failed and not active_failure:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED)

    def is_ready(self, policy: PdfExtractionPolicy) -> bool:
        if not policy.ocrmypdf_expected_version or not policy.tesseract_expected_version:
            return False
        ocrmypdf_version = _read_bounded_command_output(
            (OCRMY_PDF_EXECUTABLE, "--version"),
            timeout_seconds=3,
            maximum_bytes=policy.ocr_process_output_maximum_bytes,
        )
        tesseract_version = _read_bounded_command_output(
            (TESSERACT_EXECUTABLE, "--version"),
            timeout_seconds=3,
            maximum_bytes=policy.ocr_process_output_maximum_bytes,
        )
        language_output = _read_bounded_command_output(
            (TESSERACT_EXECUTABLE, "--list-langs"),
            timeout_seconds=3,
            maximum_bytes=policy.ocr_process_output_maximum_bytes,
        )
        if ocrmypdf_version is None or tesseract_version is None or language_output is None:
            return False
        ocrmypdf_line = ocrmypdf_version.splitlines()[0].strip() if ocrmypdf_version else ""
        tesseract_line = tesseract_version.splitlines()[0].strip() if tesseract_version else ""
        installed_languages = {line.strip() for line in language_output.splitlines()[1:]}
        return (
            ocrmypdf_line == policy.ocrmypdf_expected_version
            and tesseract_line == f"tesseract {policy.tesseract_expected_version}"
            and set(policy.ocr_languages).issubset(installed_languages)
        )

    @staticmethod
    def _command(
        input_path: Path,
        output_path: Path,
        page_numbers: tuple[int, ...],
        policy: PdfExtractionPolicy,
    ) -> tuple[str, ...]:
        return (
            OCRMY_PDF_EXECUTABLE,
            "--force-ocr",
            "--output-type",
            "pdf",
            "--optimize",
            "0",
            "--jobs",
            "1",
            "--tesseract-timeout",
            str(policy.ocr_timeout_seconds),
            "--language",
            "+".join(policy.ocr_languages),
            "--pages",
            ",".join(str(page_number) for page_number in page_numbers),
            "--",
            str(input_path),
            str(output_path),
        )


class PdfExtractor:
    format_name = ConfirmedDocumentFormat.PDF
    name = PDF_EXTRACTOR_NAME
    version = PDF_EXTRACTOR_VERSION

    def __init__(self, policy: PdfExtractionPolicy, ocr_runner: OcrRunner) -> None:
        self._policy = policy
        self._ocr_runner = ocr_runner

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        ocr_runner: OcrRunner | None = None,
    ) -> PdfExtractor:
        return cls(
            PdfExtractionPolicy.from_settings(settings),
            ocr_runner or SubprocessOcrRunner(),
        )

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool:
        return confirmed_format is ConfirmedDocumentFormat.PDF

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult:
        started = time.monotonic()
        mode = "unknown"
        page_count: int | None = None
        output_path: Path | None = None
        try:
            trusted_path = _validate_input_path(
                path,
                processing_root=self._policy.processing_root,
                maximum_bytes=self._policy.maximum_input_bytes,
            )
            source_sha256 = _sha256_file(
                trusted_path,
                maximum_bytes=self._policy.maximum_input_bytes,
            )
            deadline = started + self._policy.parser_timeout_seconds
            drafts = _extract_pdf_drafts(
                trusted_path,
                limits=limits,
                policy=self._policy,
                deadline=deadline,
            )
            page_count = len(drafts)
            ocr_pages = tuple(
                draft.page_number
                for draft in drafts
                if draft.classification
                in {PdfPageClassification.MIXED, PdfPageClassification.OCR_REQUIRED}
            )
            if ocr_pages:
                output_path = trusted_path.parent / f"ocr-output-{uuid4().hex}.pdf"
                self._ocr_runner.run(
                    trusted_path,
                    output_path,
                    ocr_pages,
                    self._policy,
                )
                _validate_ocr_output(
                    output_path,
                    source_path=trusted_path,
                    maximum_bytes=self._policy.ocr_maximum_output_bytes,
                )
                ocr_drafts = _extract_pdf_drafts(
                    output_path,
                    limits=limits,
                    policy=self._policy,
                    deadline=deadline,
                    expected_page_count=page_count,
                    selected_pages=frozenset(ocr_pages),
                    force_method=ExtractionMethod.OCR,
                )
                drafts = _merge_ocr_drafts(drafts, ocr_drafts, frozenset(ocr_pages))

            drafts, margin_removed = _remove_repeated_margins(drafts, self._policy)
            result = _build_result(
                drafts,
                source_sha256=source_sha256,
                limits=limits,
                margin_removed=margin_removed,
            )
            mode = _extraction_mode(drafts)
            record_pdf_extraction(
                duration_seconds=time.monotonic() - started,
                outcome="success",
                mode=mode,
                page_count=page_count,
            )
            return result
        except ExtractionError as exc:
            record_pdf_extraction(
                duration_seconds=time.monotonic() - started,
                outcome=_error_outcome(exc.code),
                mode=mode,
            )
            raise
        except MemoryError:
            error = ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED)
            record_pdf_extraction(
                duration_seconds=time.monotonic() - started,
                outcome="failed",
                mode=mode,
            )
            raise error from None
        except (PdfReadError, FileNotDecryptedError, PyPdfError):
            error = ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            record_pdf_extraction(
                duration_seconds=time.monotonic() - started,
                outcome="rejected",
                mode=mode,
            )
            raise error from None
        except Exception as exc:
            error = map_unexpected_extraction_failure(exc)
            record_pdf_extraction(
                duration_seconds=time.monotonic() - started,
                outcome="failed",
                mode=mode,
            )
            raise error from None
        finally:
            if output_path is not None:
                output_path.unlink(missing_ok=True)


def _extract_pdf_drafts(
    path: Path,
    *,
    limits: ExtractionLimits,
    policy: PdfExtractionPolicy,
    deadline: float,
    expected_page_count: int | None = None,
    selected_pages: frozenset[int] | None = None,
    force_method: ExtractionMethod | None = None,
) -> tuple[_PageDraft, ...]:
    try:
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            source.seek(0)
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_ENCRYPTED)
            page_count = len(reader.pages)
            if page_count <= 0:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            if page_count > limits.maximum_pdf_pages:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
            if expected_page_count is not None and page_count != expected_page_count:
                raise ExtractionError(ExtractionErrorCode.OCR_FAILED)

            drafts: list[_PageDraft] = []
            extracted_characters = 0
            extracted_blocks = 0
            for index, page in enumerate(reader.pages, start=1):
                _check_deadline(deadline)
                _, has_inline_image = _bounded_page_streams(
                    page,
                    maximum_bytes=policy.maximum_content_stream_bytes,
                )
                has_image = has_inline_image or _page_has_image_xobject(page)
                if selected_pages is not None and index not in selected_pages:
                    drafts.append(
                        _PageDraft(
                            page_number=index,
                            classification=PdfPageClassification.BLANK,
                            lines=(),
                            margin_candidates=frozenset(),
                        )
                    )
                    continue
                text, candidates = _extract_page_text(
                    page,
                    policy=policy,
                    method=force_method or ExtractionMethod.NATIVE,
                )
                lines = tuple(
                    _ExtractedLine(line, force_method or ExtractionMethod.NATIVE)
                    for line in _text_lines(text)
                )
                if any(len(line.text) > limits.maximum_characters_per_block for line in lines):
                    raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
                extracted_blocks += len(lines)
                extracted_characters += sum(len(line.text) for line in lines)
                if (
                    extracted_blocks > limits.maximum_blocks
                    or extracted_characters > limits.maximum_extracted_characters
                ):
                    raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
                if force_method is ExtractionMethod.OCR:
                    classification = PdfPageClassification.OCR_REQUIRED
                else:
                    classification = _classify_page(lines, has_image, policy)
                drafts.append(
                    _PageDraft(
                        page_number=index,
                        classification=classification,
                        lines=lines,
                        margin_candidates=candidates,
                    )
                )
            return tuple(drafts)
    except ExtractionError:
        raise
    except FileNotDecryptedError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_ENCRYPTED) from None
    except (PdfReadError, PyPdfError, OSError, ValueError, TypeError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None


def _bounded_page_streams(page: object, *, maximum_bytes: int) -> tuple[int, bool]:
    try:
        raw_contents = page.raw_get("/Contents")
    except KeyError:
        return 0, False
    encoded_total = 0
    decoded_total = 0
    has_inline_image = False
    for stream in _iter_streams(raw_contents):
        declared_length = stream.get("/Length")
        if declared_length is not None:
            try:
                declared_length_value = int(declared_length)
            except (TypeError, ValueError, OverflowError):
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
            if declared_length_value < 0:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            if declared_length_value > maximum_bytes:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
        raw_data = getattr(stream, "_data", b"")
        if not isinstance(raw_data, bytes):
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        encoded_total += len(raw_data)
        if encoded_total > maximum_bytes:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
        decoded = stream.get_data()
        if not isinstance(decoded, bytes):
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        decoded_total += len(decoded)
        if decoded_total > maximum_bytes:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
        has_inline_image = has_inline_image or bool(_INLINE_IMAGE_OPERATOR.search(decoded))
    return decoded_total, has_inline_image


def _iter_streams(value: object) -> Iterable[StreamObject]:
    pending = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, IndirectObject):
            current = current.get_object()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if isinstance(current, ArrayObject):
            pending.extend(current)
        elif isinstance(current, StreamObject):
            yield current
        else:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)


def _page_has_image_xobject(page: object) -> bool:
    try:
        resources = page.get("/Resources")
        if isinstance(resources, IndirectObject):
            resources = resources.get_object()
        if not resources:
            return False
        xobjects = resources.get("/XObject")
        if isinstance(xobjects, IndirectObject):
            xobjects = xobjects.get_object()
        if not xobjects:
            return False
        for candidate in xobjects.values():
            if isinstance(candidate, IndirectObject):
                candidate = candidate.get_object()
            if candidate.get("/Subtype") == "/Image":
                return True
    except (AttributeError, KeyError, TypeError, ValueError, PyPdfError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
    return False


def _extract_page_text(
    page: object,
    *,
    policy: PdfExtractionPolicy,
    method: ExtractionMethod,
) -> tuple[str, frozenset[_MarginCandidate]]:
    candidates: set[_MarginCandidate] = set()
    try:
        height = float(page.mediabox.height)

        def visitor(
            text: str,
            _current_matrix: Sequence[float],
            text_matrix: Sequence[float],
            _font: object,
            _font_size: float,
        ) -> None:
            if not text or len(text_matrix) < 6:
                return
            y_position = float(text_matrix[5])
            if not math.isfinite(y_position):
                return
            if y_position >= height * (1 - policy.margin_band_ratio):
                region = "top"
            elif y_position <= height * policy.margin_band_ratio:
                region = "bottom"
            else:
                return
            for line in _text_lines(text):
                if len(line) <= policy.repeated_margin_maximum_characters:
                    candidates.add(_MarginCandidate(line, region))

        text = page.extract_text(visitor_text=visitor) or ""
    except (PdfReadError, PyPdfError, OSError, ValueError, TypeError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
    if method not in {ExtractionMethod.NATIVE, ExtractionMethod.OCR}:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
    return text, frozenset(candidates)


def _classify_page(
    lines: tuple[_ExtractedLine, ...],
    has_image: bool,
    policy: PdfExtractionPolicy,
) -> PdfPageClassification:
    usable_characters = sum(
        1 for line in lines for character in line.text if not character.isspace()
    )
    if usable_characters == 0:
        return PdfPageClassification.OCR_REQUIRED if has_image else PdfPageClassification.BLANK
    if has_image and usable_characters < policy.native_text_minimum_characters:
        return PdfPageClassification.MIXED
    return PdfPageClassification.NATIVE


def _merge_ocr_drafts(
    native_drafts: tuple[_PageDraft, ...],
    ocr_drafts: tuple[_PageDraft, ...],
    ocr_pages: frozenset[int],
) -> tuple[_PageDraft, ...]:
    merged: list[_PageDraft] = []
    for native, ocr in zip(native_drafts, ocr_drafts, strict=True):
        if native.page_number not in ocr_pages:
            merged.append(native)
            continue
        if not ocr.lines:
            raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
        lines = list(native.lines)
        existing = {_deduplication_key(line.text) for line in lines}
        for line in ocr.lines:
            key = _deduplication_key(line.text)
            if key and key not in existing:
                lines.append(replace(line, method=ExtractionMethod.OCR))
                existing.add(key)
        merged.append(
            _PageDraft(
                page_number=native.page_number,
                classification=native.classification,
                lines=tuple(lines),
                margin_candidates=native.margin_candidates | ocr.margin_candidates,
            )
        )
    return tuple(merged)


def _remove_repeated_margins(
    drafts: tuple[_PageDraft, ...],
    policy: PdfExtractionPolicy,
) -> tuple[tuple[_PageDraft, ...], bool]:
    if len(drafts) < policy.repeated_margin_minimum_pages:
        return drafts, False
    page_counts: Counter[_MarginCandidate] = Counter()
    for draft in drafts:
        page_counts.update(draft.margin_candidates)
    required = max(
        policy.repeated_margin_minimum_pages,
        math.ceil(len(drafts) * policy.repeated_margin_minimum_ratio),
    )
    repeated = {
        candidate
        for candidate, count in page_counts.items()
        if count >= required and _REPEATED_MARGIN_ARTIFACT.search(candidate.text)
    }
    if not repeated:
        return drafts, False
    cleaned: list[_PageDraft] = []
    removed = False
    for draft in drafts:
        lines = list(draft.lines)
        page_repeated = draft.margin_candidates & repeated
        for candidate in sorted(page_repeated, key=lambda item: (item.region, item.text)):
            indexes = range(len(lines))
            if candidate.region == "bottom":
                indexes = range(len(lines) - 1, -1, -1)
            for index in indexes:
                if lines[index].text == candidate.text:
                    lines.pop(index)
                    removed = True
                    break
        cleaned.append(replace(draft, lines=lines))
    return tuple(cleaned), removed


def _build_result(
    drafts: tuple[_PageDraft, ...],
    *,
    source_sha256: str,
    limits: ExtractionLimits,
    margin_removed: bool,
) -> ExtractionResult:
    blocks: list[ExtractedBlock] = []
    warnings: list[ExtractionWarningCode] = []
    native_pages = 0
    ocr_pages = 0
    for draft in drafts:
        if draft.classification is PdfPageClassification.BLANK:
            _append_warning(warnings, ExtractionWarningCode.EMPTY_PAGE)
        if draft.classification is PdfPageClassification.MIXED:
            _append_warning(warnings, ExtractionWarningCode.MIXED_PAGE_OCR_USED)
            _append_warning(warnings, ExtractionWarningCode.OCR_USED)
            ocr_pages += 1
        elif draft.classification is PdfPageClassification.OCR_REQUIRED:
            _append_warning(warnings, ExtractionWarningCode.OCR_USED)
            ocr_pages += 1
        if any(line.method is ExtractionMethod.NATIVE for line in draft.lines):
            native_pages += 1
        for line in draft.lines:
            try:
                blocks.append(
                    ExtractedBlock(
                        ordinal=len(blocks),
                        text=line.text,
                        block_type=ExtractedBlockType.PARAGRAPH,
                        page_number=draft.page_number,
                        extraction_method=line.method,
                        limits=limits,
                    )
                )
            except ValueError:
                raise ExtractionError(
                    ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED
                ) from None
    if margin_removed:
        _append_warning(warnings, ExtractionWarningCode.REPEATED_MARGIN_REMOVED)
    if not blocks:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT)
    try:
        statistics = ExtractionStatistics(
            detected_format=ConfirmedDocumentFormat.PDF,
            page_count=len(drafts),
            worksheet_count=0,
            table_count=0,
            row_count=0,
            block_count=len(blocks),
            character_count=sum(len(block.text) for block in blocks),
            native_page_count=native_pages,
            ocr_page_count=ocr_pages,
            warning_codes=warnings,
            extractor_name=PDF_EXTRACTOR_NAME,
            extractor_version=PDF_EXTRACTOR_VERSION,
            limits=limits,
        )
        return ExtractionResult(
            blocks=blocks,
            statistics=statistics,
            source_content_sha256=source_sha256,
            confirmed_format=ConfirmedDocumentFormat.PDF,
            limits=limits,
        )
    except ValueError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED) from None


def _append_warning(
    warnings: list[ExtractionWarningCode],
    warning: ExtractionWarningCode,
) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _validate_input_path(
    path: Path,
    *,
    processing_root: Path,
    maximum_bytes: int,
) -> Path:
    if not isinstance(path, Path):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
    try:
        if path.name != "input.pdf" or path.is_symlink() or processing_root.is_symlink():
            raise OSError
        resolved_root = processing_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        workspace = resolved.parent
        UUID(workspace.name)
        if workspace.is_symlink() or workspace.parent != resolved_root:
            raise OSError
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            raise OSError
        if metadata.st_size > maximum_bytes:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
    except ExtractionError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED) from None
    return resolved


def _validate_ocr_output(path: Path, *, source_path: Path, maximum_bytes: int) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
        resolved = path.resolve(strict=True)
        if resolved == source_path or resolved.parent != source_path.parent:
            raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
        size = resolved.stat().st_size
        if size <= 0:
            raise ExtractionError(ExtractionErrorCode.OCR_FAILED)
        if size > maximum_bytes:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
    except ExtractionError:
        raise
    except (OSError, RuntimeError):
        raise ExtractionError(ExtractionErrorCode.OCR_FAILED) from None


def _sha256_file(path: Path, *, maximum_bytes: int) -> str:
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                byte_count += len(chunk)
                if byte_count > maximum_bytes:
                    raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
                digest.update(chunk)
    except ExtractionError:
        raise
    except OSError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED) from None
    return digest.hexdigest()


def _text_lines(text: str) -> tuple[str, ...]:
    sanitized = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return tuple(line.strip() for line in sanitized.split("\n") if line.strip())


def _deduplication_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _extraction_mode(drafts: tuple[_PageDraft, ...]) -> str:
    has_ocr = any(
        draft.classification in {PdfPageClassification.MIXED, PdfPageClassification.OCR_REQUIRED}
        for draft in drafts
    )
    has_native = any(
        any(line.method is ExtractionMethod.NATIVE for line in draft.lines) for draft in drafts
    )
    if has_ocr and has_native:
        return "mixed"
    if has_ocr:
        return "ocr"
    return "native"


def _error_outcome(code: ExtractionErrorCode) -> str:
    if code is ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT:
        return "timeout"
    if code is ExtractionErrorCode.OCR_UNAVAILABLE:
        return "unavailable"
    if code in {
        ExtractionErrorCode.DOCUMENT_ENCRYPTED,
        ExtractionErrorCode.DOCUMENT_MALFORMED,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT,
    }:
        return "rejected"
    return "failed"


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT)


def _exclusive_binary_output(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, "wb")


def _apply_process_limits(process_id: int, policy: PdfExtractionPolicy) -> bool:
    if os.name != "posix" or resource is None or not hasattr(resource, "prlimit"):
        return os.name != "posix"
    try:
        resource.prlimit(
            process_id,
            resource.RLIMIT_CPU,
            (policy.ocr_cpu_limit_seconds, policy.ocr_cpu_limit_seconds),
        )
        resource.prlimit(
            process_id,
            resource.RLIMIT_AS,
            (policy.ocr_memory_limit_bytes, policy.ocr_memory_limit_bytes),
        )
    except (OSError, ValueError):
        return False
    return True


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=2)
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.exists() else 0
    except OSError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None


def _workspace_file_bytes(workspace: Path) -> int:
    total = 0
    try:
        for root, directories, filenames in os.walk(workspace, followlinks=False):
            root_path = Path(root)
            for directory in directories:
                if (root_path / directory).is_symlink():
                    raise OSError
            for filename in filenames:
                entry = root_path / filename
                if entry.is_symlink():
                    raise OSError
                total += entry.stat().st_size
    except OSError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None
    return total


def _remove_ocr_artifacts(
    workspace: Path,
    *,
    baseline_entries: frozenset[str],
    preserved_output: Path | None,
) -> None:
    try:
        for entry in workspace.iterdir():
            if entry.name in baseline_entries or entry == preserved_output:
                continue
            if entry.is_symlink():
                entry.unlink(missing_ok=True)
                continue
            resolved = entry.resolve(strict=True)
            if resolved.parent != workspace:
                raise OSError
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink(missing_ok=True)
    except OSError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None


def _read_bounded_command_output(
    command: tuple[str, ...],
    *,
    timeout_seconds: int,
    maximum_bytes: int,
) -> str | None:
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                shell=False,
                env={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                },
                start_new_session=True,
            )
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process(process)
                return None
            if process.returncode != 0 or output.tell() > maximum_bytes:
                return None
            output.seek(0)
            return output.read(maximum_bytes + 1).decode("utf-8", errors="strict")
    except (FileNotFoundError, PermissionError, OSError, UnicodeError):
        return None
