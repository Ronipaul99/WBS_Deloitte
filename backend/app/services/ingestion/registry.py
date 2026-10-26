from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.extractors.base import DocumentExtractor
from app.services.ingestion.types import ConfirmedDocumentFormat, validate_safe_identifier

if TYPE_CHECKING:
    from app.services.ingestion.extractors.pdf import OcrRunner

REQUIRED_RELEASE_FORMATS = tuple(ConfirmedDocumentFormat)


class ExtractorRegistry:
    def __init__(self, extractors: Iterable[DocumentExtractor]) -> None:
        registrations = tuple(extractors)
        if len({id(extractor) for extractor in registrations}) != len(registrations):
            raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)
        for extractor in registrations:
            self._validate_registration(extractor)
        self._extractors = registrations

    @property
    def extractors(self) -> tuple[DocumentExtractor, ...]:
        return self._extractors

    def select(self, confirmed_format: ConfirmedDocumentFormat) -> DocumentExtractor:
        if not isinstance(confirmed_format, ConfirmedDocumentFormat):
            raise ExtractionError(ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)
        matches = self._matching_extractors(confirmed_format)
        if not matches:
            raise ExtractionError(ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)
        if len(matches) != 1:
            raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)
        return matches[0]

    def validate_release_completeness(
        self,
        required_formats: Iterable[ConfirmedDocumentFormat] = REQUIRED_RELEASE_FORMATS,
    ) -> None:
        for confirmed_format in tuple(required_formats):
            if not isinstance(confirmed_format, ConfirmedDocumentFormat):
                raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)
            if len(self._matching_extractors(confirmed_format)) != 1:
                raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)

    def _matching_extractors(
        self,
        confirmed_format: ConfirmedDocumentFormat,
    ) -> tuple[DocumentExtractor, ...]:
        matches: list[DocumentExtractor] = []
        for extractor in self._extractors:
            try:
                supported = extractor.supports(confirmed_format)
            except Exception as exc:
                raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID) from exc
            if not isinstance(supported, bool):
                raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)
            if supported:
                matches.append(extractor)
        return tuple(matches)

    @staticmethod
    def _validate_registration(extractor: DocumentExtractor) -> None:
        if not isinstance(getattr(extractor, "format_name", None), ConfirmedDocumentFormat):
            raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID)
        try:
            validate_safe_identifier(
                getattr(extractor, "name", None),
                field_name="extractor_name",
                maximum_length=80,
            )
            validate_safe_identifier(
                getattr(extractor, "version", None),
                field_name="extractor_version",
                maximum_length=40,
            )
        except ValueError as exc:
            raise ExtractionError(ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID) from exc


def get_release_extractor_registry(
    settings: Settings | None = None,
    *,
    ocr_runner: OcrRunner | None = None,
) -> ExtractorRegistry:
    from app.services.ingestion.extractors.csv import CsvExtractor
    from app.services.ingestion.extractors.docx import DocxExtractor
    from app.services.ingestion.extractors.pdf import PdfExtractor
    from app.services.ingestion.extractors.xlsx import XlsxExtractor

    effective_settings = settings or Settings(_env_file=None)
    return ExtractorRegistry(
        (
            PdfExtractor.from_settings(effective_settings, ocr_runner=ocr_runner),
            DocxExtractor.from_settings(effective_settings),
            XlsxExtractor.from_settings(effective_settings),
            CsvExtractor.from_settings(effective_settings),
        )
    )
