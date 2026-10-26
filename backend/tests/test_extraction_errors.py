import logging

import pytest

from app.services.ingestion.errors import (
    ExtractionError,
    ExtractionErrorCode,
    extraction_error_to_job_failure,
    map_unexpected_extraction_failure,
)


@pytest.mark.parametrize("code", list(ExtractionErrorCode))
def test_every_extraction_error_has_stable_safe_job_mapping(
    code: ExtractionErrorCode,
) -> None:
    error = ExtractionError(code)
    failure = extraction_error_to_job_failure(error)

    assert failure.error_code is code
    assert failure.retryable is error.retryable
    assert failure.message == str(error)
    assert failure.message


def test_retry_classification_is_explicit() -> None:
    retryable = {
        ExtractionErrorCode.OCR_UNAVAILABLE,
        ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT,
        ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED,
        ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED,
    }

    for code in ExtractionErrorCode:
        assert ExtractionError(code).retryable is (code in retryable)


def test_unexpected_parser_failure_redacts_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_markers = (
        "private-location-marker",
        "customer-content-marker",
        "uploaded-name-marker",
        "private-storage-marker",
        "private-endpoint-marker",
    )
    exception = RuntimeError(" ".join(sensitive_markers))

    with caplog.at_level(logging.WARNING):
        mapped = map_unexpected_extraction_failure(exception)
    failure = extraction_error_to_job_failure(mapped)
    exposed = f"{mapped} {failure} {caplog.text}"

    assert mapped.code is ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED
    assert all(marker not in exposed for marker in sensitive_markers)
    assert caplog.records[0].error_category == "RuntimeError"
