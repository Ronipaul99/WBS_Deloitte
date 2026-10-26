from __future__ import annotations

import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from docx import Document
from docx.document import Document as DocumentObject
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

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
    preflight_office_package,
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

DOCX_EXTRACTOR_NAME = "python-docx"
DOCX_EXTRACTOR_VERSION = "1.0.0"
_HEADING_STYLE = re.compile(r"^Heading ([1-9][0-9]*)$")


class DocxExtractor:
    format_name = ConfirmedDocumentFormat.DOCX
    name = DOCX_EXTRACTOR_NAME
    version = DOCX_EXTRACTOR_VERSION

    def __init__(self, policy: TrustedExtractionPolicy) -> None:
        self._policy = policy

    @classmethod
    def from_settings(cls, settings: Settings) -> DocxExtractor:
        return cls(TrustedExtractionPolicy.from_settings(settings))

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool:
        return confirmed_format is ConfirmedDocumentFormat.DOCX

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult:
        started = time.monotonic()
        try:
            trusted_path = validate_trusted_input_path(
                path,
                processing_root=self._policy.processing_root,
                expected_suffix=".docx",
                maximum_bytes=self._policy.maximum_input_bytes,
            )
            inspection = preflight_office_package(
                trusted_path,
                confirmed_suffix=".docx",
                limits=limits,
            )
            source_sha256 = sha256_file(
                trusted_path,
                maximum_bytes=self._policy.maximum_input_bytes,
            )
            document = Document(trusted_path)
            result = _extract_document(
                document,
                limits=limits,
                source_sha256=source_sha256,
                has_header_or_footer=inspection.has_header_or_footer,
            )
            record_document_extraction(
                document_format="docx",
                duration_seconds=time.monotonic() - started,
                outcome="success",
                block_count=result.statistics.block_count,
                row_count=result.statistics.row_count,
            )
            return result
        except ExtractionError as exc:
            record_document_extraction(
                document_format="docx",
                duration_seconds=time.monotonic() - started,
                outcome=_outcome(exc.code),
            )
            raise
        except (PackageNotFoundError, KeyError):
            record_document_extraction(
                document_format="docx",
                duration_seconds=time.monotonic() - started,
                outcome="rejected",
            )
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
        except MemoryError:
            record_document_extraction(
                document_format="docx",
                duration_seconds=time.monotonic() - started,
                outcome="failed",
            )
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None
        except Exception as exc:
            record_document_extraction(
                document_format="docx",
                duration_seconds=time.monotonic() - started,
                outcome="failed",
            )
            raise map_unexpected_extraction_failure(exc) from None


def _extract_document(
    document: DocumentObject,
    *,
    limits: ExtractionLimits,
    source_sha256: str,
    has_header_or_footer: bool,
) -> ExtractionResult:
    blocks: list[ExtractedBlock] = []
    warnings: list[ExtractionWarningCode] = []
    heading_path: list[str] = []
    table_count = 0
    table_row_count = 0
    character_count = 0

    if has_header_or_footer:
        append_warning_once(
            warnings,
            ExtractionWarningCode.HEADER_FOOTER_EXCLUDED,
            limits.maximum_warnings,
        )

    for item in _iter_document_body(document):
        if isinstance(item, Paragraph):
            text = clean_contract_text(item.text)
            if not text:
                continue
            heading_level = _heading_level(item)
            if heading_level is not None:
                if heading_level > limits.maximum_heading_depth:
                    raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
                heading_path = heading_path[: max(0, heading_level - 1)]
                heading_path.append(text)
                block_type = ExtractedBlockType.HEADING
                metadata = {"source_kind": "document_body"}
            elif _is_list_paragraph(item):
                block_type = ExtractedBlockType.LIST_ITEM
                metadata = {
                    "source_kind": "document_body",
                    "list_level": _list_level(item),
                }
            else:
                block_type = ExtractedBlockType.PARAGRAPH
                metadata = {"source_kind": "document_body"}
            character_count = _append_docx_block(
                blocks,
                text=text,
                block_type=block_type,
                heading_path=tuple(heading_path),
                metadata=metadata,
                character_count=character_count,
                limits=limits,
            )
            continue

        table_count += 1
        for row_index, row in enumerate(item.rows, start=1):
            cells: list[str] = []
            seen_cells: set[int] = set()
            for cell in row.cells:
                cell_identity = id(cell._tc)
                if cell_identity in seen_cells:
                    continue
                seen_cells.add(cell_identity)
                cells.append(clean_contract_text(cell.text))
            while cells and not cells[-1]:
                cells.pop()
            text = " | ".join(cells)
            if not text.strip(" |"):
                continue
            table_row_count += 1
            character_count = _append_docx_block(
                blocks,
                text=text,
                block_type=ExtractedBlockType.TABLE_ROW,
                heading_path=tuple(heading_path),
                metadata={
                    "source_kind": "table",
                    "table_index": table_count - 1,
                    "is_header": row_index == 1,
                },
                character_count=character_count,
                limits=limits,
            )

    if not blocks:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT)
    try:
        statistics = ExtractionStatistics(
            detected_format=ConfirmedDocumentFormat.DOCX,
            page_count=0,
            worksheet_count=0,
            table_count=table_count,
            row_count=table_row_count,
            block_count=len(blocks),
            character_count=character_count,
            native_page_count=0,
            ocr_page_count=0,
            warning_codes=warnings,
            extractor_name=DOCX_EXTRACTOR_NAME,
            extractor_version=DOCX_EXTRACTOR_VERSION,
            limits=limits,
        )
        return ExtractionResult(
            blocks=blocks,
            statistics=statistics,
            source_content_sha256=source_sha256,
            confirmed_format=ConfirmedDocumentFormat.DOCX,
            limits=limits,
        )
    except ValueError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED) from None


def _iter_document_body(document: DocumentObject) -> Iterator[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int | None:
    style_name = paragraph.style.name if paragraph.style is not None else ""
    match = _HEADING_STYLE.fullmatch(style_name)
    return int(match.group(1)) if match else None


def _is_list_paragraph(paragraph: Paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style is not None else ""
    properties = paragraph._p.pPr
    return "list" in style_name.casefold() or (
        properties is not None and properties.numPr is not None
    )


def _list_level(paragraph: Paragraph) -> int:
    properties = paragraph._p.pPr
    if properties is None or properties.numPr is None or properties.numPr.ilvl is None:
        return 0
    return max(0, int(properties.numPr.ilvl.val))


def _append_docx_block(
    blocks: list[ExtractedBlock],
    *,
    text: str,
    block_type: ExtractedBlockType,
    heading_path: tuple[str, ...],
    metadata: dict[str, object],
    character_count: int,
    limits: ExtractionLimits,
) -> int:
    if len(blocks) >= limits.maximum_blocks:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
    new_character_count = character_count + len(text)
    if new_character_count > limits.maximum_extracted_characters:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
    try:
        blocks.append(
            ExtractedBlock(
                ordinal=len(blocks),
                text=text,
                block_type=block_type,
                heading_path=heading_path,
                extraction_method=ExtractionMethod.NATIVE,
                metadata=metadata,
                limits=limits,
            )
        )
    except ValueError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED) from None
    return new_character_count


def _outcome(code: ExtractionErrorCode) -> str:
    if code in {
        ExtractionErrorCode.DOCUMENT_ENCRYPTED,
        ExtractionErrorCode.DOCUMENT_MALFORMED,
        ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED,
        ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT,
    }:
        return "rejected"
    return "failed"
