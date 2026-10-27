from __future__ import annotations

from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

from app.services.ingestion.types import ConfirmedDocumentFormat, confirmed_format_from_suffix

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.models.domain import Document, DocumentProcessingRun

RELEASE_CHUNKER_VERSION = "1.1.0"
RELEASE_EXTRACTOR_IDENTITIES = MappingProxyType(
    {
        ConfirmedDocumentFormat.PDF: ("pypdf-ocrmypdf", "1.1.0"),
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


def matches_release_identity(
    document: Document,
    run: DocumentProcessingRun,
    settings: Settings,
) -> bool:
    try:
        confirmed_format = confirmed_format_from_suffix(
            PurePosixPath(document.storage_key).suffix.casefold()
        )
        extractor_name, extractor_version = release_extractor_identity(confirmed_format)
    except ValueError:
        return False
    return all(
        (
            document.current_processing_run_id == run.id,
            document.content_sha256 is not None,
            document.content_sha256 == run.document_content_sha256,
            run.status == "COMPLETED",
            run.chunk_count > 0,
            run.extractor_name == extractor_name,
            run.extractor_version == extractor_version,
            run.chunker_version == RELEASE_CHUNKER_VERSION,
            run.embedding_provider == settings.embedding_provider,
            run.embedding_model == settings.embedding_model,
            run.embedding_model_revision == settings.embedding_model_revision,
            run.embedding_dimensions == settings.embedding_dimensions,
            run.embedding_formatting_version == settings.embedding_formatting_version,
        )
    )
