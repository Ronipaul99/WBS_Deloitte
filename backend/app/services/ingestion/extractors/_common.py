from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID
from zipfile import BadZipFile, LargeZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as safe_xml_fromstring

from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.types import ExtractionLimits

if TYPE_CHECKING:
    from app.core.config import Settings

_OLE_COMPOUND_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
_MACRO_OR_EMBEDDED_PARTS = (
    "/activex/",
    "/embeddings/",
    "vbaproject.bin",
)


@dataclass(frozen=True, slots=True)
class OfficePackageInspection:
    has_header_or_footer: bool = False
    has_formula_without_cached_value: bool = False
    worksheet_dimensions_need_correction: bool = False


@dataclass(frozen=True, slots=True)
class TrustedExtractionPolicy:
    processing_root: Path
    maximum_input_bytes: int

    @classmethod
    def from_settings(cls, settings: Settings) -> TrustedExtractionPolicy:
        return cls(
            processing_root=Path(settings.document_processing_temp_root),
            maximum_input_bytes=settings.max_upload_bytes,
        )


def validate_trusted_input_path(
    path: Path,
    *,
    processing_root: Path,
    expected_suffix: str,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> Path:
    if not isinstance(path, Path):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)
    try:
        if (
            path.name != f"input{expected_suffix}"
            or path.is_symlink()
            or processing_root.is_symlink()
        ):
            raise OSError
        resolved_root = processing_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        workspace = resolved.parent
        UUID(workspace.name)
        if workspace.is_symlink() or workspace.parent != resolved_root:
            raise OSError
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_size <= 0 and not allow_empty):
            raise OSError
        if metadata.st_size > maximum_bytes:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
    except ExtractionError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED) from None
    return resolved


def sha256_file(path: Path, *, maximum_bytes: int) -> str:
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


def preflight_office_package(
    path: Path,
    *,
    confirmed_suffix: str,
    limits: ExtractionLimits,
) -> OfficePackageInspection:
    try:
        with path.open("rb") as source:
            prefix = source.read(8)
        if prefix == _OLE_COMPOUND_HEADER:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_ENCRYPTED)

        with ZipFile(path, "r") as package:
            entries = package.infolist()
            if not entries or len(entries) > limits.maximum_archive_entries:
                raise _limit_error()
            names = _validate_archive_entries(entries, limits)
            required = "word/document.xml" if confirmed_suffix == ".docx" else "xl/workbook.xml"
            if required not in names or "[Content_Types].xml" not in names:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            _reject_unsupported_parts(names)
            if confirmed_suffix == ".xlsx":
                worksheet_parts = sum(
                    name.startswith("xl/worksheets/") and name.endswith(".xml") for name in names
                )
                if worksheet_parts > limits.maximum_worksheets:
                    raise _limit_error()

            has_header_or_footer = any(
                name.startswith(("word/header", "word/footer")) and name.endswith(".xml")
                for name in names
            )
            formula_without_cache = False
            dimensions_need_correction = False
            total_cells = 0
            total_merged_ranges = 0
            for info in entries:
                if info.is_dir() or not _is_xml_part(info.filename):
                    continue
                xml_root = _read_safe_xml(package, info.filename, limits)
                if info.filename == "[Content_Types].xml":
                    _reject_macro_content_types(xml_root)
                if confirmed_suffix == ".xlsx" and info.filename.startswith("xl/worksheets/"):
                    analysis = _inspect_worksheet_xml(xml_root, limits)
                    total_cells += analysis[0]
                    total_merged_ranges += analysis[1]
                    formula_without_cache = formula_without_cache or analysis[2]
                    dimensions_need_correction = dimensions_need_correction or analysis[3]
                    if total_cells > limits.maximum_spreadsheet_cells:
                        raise _limit_error()
                    if total_merged_ranges > limits.maximum_merged_ranges:
                        raise _limit_error()

            return OfficePackageInspection(
                has_header_or_footer=has_header_or_footer,
                has_formula_without_cached_value=formula_without_cache,
                worksheet_dimensions_need_correction=dimensions_need_correction,
            )
    except ExtractionError:
        raise
    except (BadZipFile, LargeZipFile, DefusedXmlException, OSError, RuntimeError, ValueError):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED) from None
    except MemoryError:
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED) from None


def clean_contract_text(value: object) -> str:
    if not isinstance(value, str):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
    if any(
        (ord(character) < 32 and character not in "\t\n\r") or ord(character) == 127
        for character in value
    ):
        raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def append_warning_once(warnings: list[object], warning: object, maximum_warnings: int) -> None:
    if warning in warnings:
        return
    if len(warnings) >= maximum_warnings:
        raise _limit_error()
    warnings.append(warning)


def _validate_archive_entries(entries: list[object], limits: ExtractionLimits) -> frozenset[str]:
    names: set[str] = set()
    casefolded_names: set[str] = set()
    compressed_total = 0
    uncompressed_total = 0
    for entry in entries:
        name = entry.filename
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        pure_name = PurePosixPath(name)
        if (
            pure_name.is_absolute()
            or ".." in pure_name.parts
            or any(":" in part for part in pure_name.parts)
        ):
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        folded = name.casefold()
        if name in names or folded in casefolded_names:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        names.add(name)
        casefolded_names.add(folded)
        if entry.flag_bits & 0x1:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_ENCRYPTED)
        mode = (entry.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR} or stat.S_ISLNK(mode):
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        if entry.file_size < 0 or entry.compress_size < 0:
            raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
        if entry.file_size > limits.maximum_archive_entry_bytes:
            raise _limit_error()
        compressed_total += entry.compress_size
        uncompressed_total += entry.file_size
        if compressed_total > limits.maximum_archive_compressed_bytes:
            raise _limit_error()
        if uncompressed_total > limits.maximum_archive_uncompressed_bytes:
            raise _limit_error()
        if (
            entry.file_size > 0
            and entry.file_size / max(1, entry.compress_size)
            > limits.maximum_archive_expansion_ratio
        ):
            raise _limit_error()
    if uncompressed_total / max(1, compressed_total) > limits.maximum_archive_expansion_ratio:
        raise _limit_error()
    return frozenset(names)


def _reject_unsupported_parts(names: frozenset[str]) -> None:
    for name in names:
        normalized = f"/{name.casefold()}"
        if any(part in normalized for part in _MACRO_OR_EMBEDDED_PARTS):
            raise ExtractionError(ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)
        if normalized.endswith((".exe", ".dll", ".com", ".msi")):
            raise ExtractionError(ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)


def _is_xml_part(name: str) -> bool:
    return name.endswith((".xml", ".rels")) or name == "[Content_Types].xml"


def _read_safe_xml(package: ZipFile, name: str, limits: ExtractionLimits) -> object:
    info = package.getinfo(name)
    if info.file_size > limits.maximum_archive_entry_bytes:
        raise _limit_error()
    with package.open(info, "r") as source:
        data = source.read(limits.maximum_archive_entry_bytes + 1)
    if len(data) > limits.maximum_archive_entry_bytes:
        raise _limit_error()
    return safe_xml_fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def _reject_macro_content_types(root: object) -> None:
    for element in root.iter():
        content_type = element.attrib.get("ContentType", "").casefold()
        if "macroenabled" in content_type or "vba" in content_type:
            raise ExtractionError(ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)


def _inspect_worksheet_xml(
    root: object,
    limits: ExtractionLimits,
) -> tuple[int, int, bool, bool]:
    cells = 0
    merged_ranges = 0
    formula_without_cache = False
    dimensions_need_correction = False
    declared_end: tuple[int, int] | None = None
    maximum_actual_column = 0
    maximum_actual_row = 0
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name == "dimension":
            reference = element.attrib.get("ref", "")
            end_reference = reference.split(":")[-1]
            parsed = _parse_cell_reference(end_reference)
            declared_end = parsed
            if parsed and (
                parsed[0] > limits.maximum_spreadsheet_columns
                or parsed[1] > limits.maximum_rows_per_sheet
            ):
                dimensions_need_correction = True
        elif local_name == "mergeCell":
            merged_ranges += 1
        elif local_name == "c":
            cells += 1
            parsed = _parse_cell_reference(element.attrib.get("r", ""))
            if parsed is None:
                raise ExtractionError(ExtractionErrorCode.DOCUMENT_MALFORMED)
            if (
                parsed[0] > limits.maximum_spreadsheet_columns
                or parsed[1] > limits.maximum_rows_per_sheet
            ):
                raise _limit_error()
            maximum_actual_column = max(maximum_actual_column, parsed[0])
            maximum_actual_row = max(maximum_actual_row, parsed[1])
            child_names = {child.tag.rsplit("}", 1)[-1]: child for child in element}
            if "f" in child_names:
                cached = child_names.get("v")
                if cached is None or cached.text is None:
                    formula_without_cache = True
    if merged_ranges > limits.maximum_merged_ranges:
        raise _limit_error()
    if declared_end is not None and (
        maximum_actual_column > declared_end[0] or maximum_actual_row > declared_end[1]
    ):
        dimensions_need_correction = True
    return cells, merged_ranges, formula_without_cache, dimensions_need_correction


def _parse_cell_reference(value: str) -> tuple[int, int] | None:
    match = _CELL_REFERENCE.fullmatch(value.replace("$", ""))
    if match is None:
        return None
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return column, int(match.group(2))


def _limit_error() -> ExtractionError:
    return ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED)
