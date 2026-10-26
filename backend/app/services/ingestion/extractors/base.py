from pathlib import Path
from typing import Protocol

from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractionLimits,
    ExtractionResult,
)


class DocumentExtractor(Protocol):
    format_name: ConfirmedDocumentFormat
    name: str
    version: str

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool: ...

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult: ...
