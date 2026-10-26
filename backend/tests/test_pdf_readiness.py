from pathlib import Path

import pytest
from extraction_fixtures import complete_fake_extractors
from pdf_extraction_fixtures import FakeOcrRunner

from app.core.config import Settings
from app.services import readiness
from app.services.ingestion.registry import ExtractorRegistry, get_release_extractor_registry
from app.services.ingestion.types import ConfirmedDocumentFormat


def settings_for_readiness(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        embedding_model_path=str(tmp_path),
        ocrmypdf_expected_version="approved-ocr-version",
        tesseract_expected_version="approved-tesseract-version",
    )


def test_release_registry_contains_all_real_extractors(tmp_path: Path) -> None:
    settings = settings_for_readiness(tmp_path)
    registry = get_release_extractor_registry(settings, ocr_runner=FakeOcrRunner())

    assert tuple(extractor.format_name for extractor in registry.extractors) == (
        ConfirmedDocumentFormat.PDF,
        ConfirmedDocumentFormat.DOCX,
        ConfirmedDocumentFormat.XLSX,
        ConfirmedDocumentFormat.CSV,
    )
    readiness.extractor_registry_is_ready(registry, settings=settings)


def test_ocr_runtime_readiness_accepts_injected_ready_runner_and_fails_safely(
    tmp_path: Path,
) -> None:
    settings = settings_for_readiness(tmp_path)
    readiness.ocr_runtime_is_ready(settings, FakeOcrRunner(ready=True))

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.ocr_runtime_is_ready(settings, FakeOcrRunner(ready=False))
    assert error.value.category == "ocr_runtime"
    assert str(error.value) == "ocr_runtime unavailable"
    assert str(tmp_path) not in str(error.value)


def test_complete_registry_remains_injectable_for_worker_readiness(tmp_path: Path) -> None:
    settings = settings_for_readiness(tmp_path)
    readiness.extractor_registry_is_ready(
        ExtractorRegistry(complete_fake_extractors()),
        settings=settings,
    )
