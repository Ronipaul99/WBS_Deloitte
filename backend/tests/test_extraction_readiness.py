import pytest
from extraction_fixtures import FakeExtractor, complete_fake_extractors

from app.core.config import Settings
from app.services import readiness
from app.services.ingestion.registry import ExtractorRegistry


def test_complete_injected_registry_passes_worker_registry_readiness() -> None:
    readiness.extractor_registry_is_ready(ExtractorRegistry(complete_fake_extractors()))


def test_missing_format_fails_with_safe_registry_category() -> None:
    registry = ExtractorRegistry(complete_fake_extractors()[:-1])

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.extractor_registry_is_ready(registry)

    assert error.value.category == "extractor_registry"
    assert str(error.value) == "extractor_registry unavailable"


def test_ambiguous_format_fails_with_safe_registry_category() -> None:
    registry = ExtractorRegistry(
        complete_fake_extractors() + (FakeExtractor(complete_fake_extractors()[0].format_name),)
    )

    with pytest.raises(readiness.IngestionReadinessError) as error:
        readiness.extractor_registry_is_ready(registry)

    assert error.value.category == "extractor_registry"
    assert "fake-extractor" not in str(error.value)


async def test_api_readiness_does_not_construct_registry_or_invoke_extractors(
    monkeypatch,
) -> None:
    settings = Settings(_env_file=None, document_ingestion_enabled=False)

    def unexpected_registry_check(*_args, **_kwargs) -> None:
        raise AssertionError("API readiness constructed the extraction registry")

    monkeypatch.setattr(readiness, "extractor_registry_is_ready", unexpected_registry_check)

    await readiness.api_ingestion_is_ready(settings)
