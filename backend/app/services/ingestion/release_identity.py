from __future__ import annotations

from types import MappingProxyType

from app.services.ingestion.types import ConfirmedDocumentFormat

RELEASE_CHUNKER_VERSION = "1.0.0"
RELEASE_EXTRACTOR_IDENTITIES = MappingProxyType(
    {
        ConfirmedDocumentFormat.PDF: ("pypdf-ocrmypdf", "1.0.0"),
        ConfirmedDocumentFormat.DOCX: ("python-docx", "1.0.0"),
        ConfirmedDocumentFormat.XLSX: ("openpyxl", "1.0.0"),
        ConfirmedDocumentFormat.CSV: ("python-csv", "1.0.0"),
    }
)


def release_extractor_identity(
    confirmed_format: ConfirmedDocumentFormat,
) -> tuple[str, str]:
    try:
        return RELEASE_EXTRACTOR_IDENTITIES[confirmed_format]
    except (KeyError, TypeError):
        raise ValueError("Unsupported release document format") from None
