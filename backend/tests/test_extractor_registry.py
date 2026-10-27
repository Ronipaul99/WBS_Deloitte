import pytest
from extraction_fixtures import FakeExtractor, complete_fake_extractors

from app.services.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.services.ingestion.registry import (
    ExtractorRegistry,
    get_release_extractor_registry,
)
from app.services.ingestion.types import ConfirmedDocumentFormat


@pytest.mark.parametrize("confirmed_format", list(ConfirmedDocumentFormat))
def test_registry_selects_exactly_one_explicit_fake_extractor(
    confirmed_format: ConfirmedDocumentFormat,
) -> None:
    extractors = complete_fake_extractors()
    registry = ExtractorRegistry(extractors)

    selected = registry.select(confirmed_format)

    assert selected.format_name is confirmed_format
    assert selected.version == "1.0.0"
    assert all(extractor.extract_calls == 0 for extractor in extractors)


def test_missing_registration_fails_safely() -> None:
    registry = ExtractorRegistry(())

    with pytest.raises(ExtractionError) as error:
        registry.select(ConfirmedDocumentFormat.PDF)

    assert error.value.code is ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT


def test_ambiguous_registration_fails_safely() -> None:
    registry = ExtractorRegistry(
        (
            FakeExtractor(ConfirmedDocumentFormat.PDF),
            FakeExtractor(ConfirmedDocumentFormat.PDF),
        )
    )

    with pytest.raises(ExtractionError) as error:
        registry.select(ConfirmedDocumentFormat.PDF)

    assert error.value.code is ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID


def test_duplicate_object_registration_is_rejected() -> None:
    extractor = FakeExtractor(ConfirmedDocumentFormat.PDF)

    with pytest.raises(ExtractionError) as error:
        ExtractorRegistry((extractor, extractor))

    assert error.value.code is ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID


def test_registry_contents_are_immutable_and_copied() -> None:
    source = [FakeExtractor(ConfirmedDocumentFormat.PDF)]
    registry = ExtractorRegistry(source)
    source.clear()

    assert len(registry.extractors) == 1
    with pytest.raises(AttributeError):
        registry.extractors.append(FakeExtractor(ConfirmedDocumentFormat.DOCX))


def test_registry_selection_rejects_non_enum_values() -> None:
    registry = ExtractorRegistry(complete_fake_extractors())

    for untrusted_value in ("pdf", "application/pdf", "../pdf", ".PDF"):
        with pytest.raises(ExtractionError) as error:
            registry.select(untrusted_value)
        assert error.value.code is ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT


def test_complete_registry_passes_and_missing_or_ambiguous_registry_fails() -> None:
    ExtractorRegistry(complete_fake_extractors()).validate_release_completeness()

    with pytest.raises(ExtractionError):
        ExtractorRegistry(complete_fake_extractors()[:-1]).validate_release_completeness()
    with pytest.raises(ExtractionError):
        ExtractorRegistry(
            complete_fake_extractors() + (FakeExtractor(ConfirmedDocumentFormat.PDF),)
        ).validate_release_completeness()


def test_production_registry_contains_no_stub_or_test_fake() -> None:
    registry = get_release_extractor_registry()

    assert tuple(extractor.format_name for extractor in registry.extractors) == tuple(
        ConfirmedDocumentFormat
    )
    assert tuple(extractor.name for extractor in registry.extractors) == (
        "pypdf-ocrmypdf",
        "python-docx",
        "openpyxl",
        "python-csv",
    )
    assert all(not isinstance(extractor, FakeExtractor) for extractor in registry.extractors)
    registry.validate_release_completeness()
