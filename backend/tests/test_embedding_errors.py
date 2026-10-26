from app.services.ingestion.errors import (
    EmbeddingError,
    EmbeddingErrorCode,
    embedding_error_to_job_failure,
    map_unexpected_embedding_failure,
)


def test_embedding_errors_have_stable_safe_retry_classification(caplog) -> None:
    expected_retryability = {
        EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE: True,
        EmbeddingErrorCode.EMBEDDING_MODEL_INVALID: False,
        EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED: False,
        EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID: True,
        EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED: True,
    }
    for code, retryable in expected_retryability.items():
        failure = embedding_error_to_job_failure(EmbeddingError(code))
        assert failure.error_code is code
        assert failure.retryable is retryable
        assert failure.message == str(EmbeddingError(code))

    marker = "private-text-vector-path-object-key-endpoint-marker"
    mapped = map_unexpected_embedding_failure(RuntimeError(marker))
    failure = embedding_error_to_job_failure(mapped)
    assert failure.error_code is EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED
    assert marker not in str(mapped)
    assert marker not in repr(failure)
    assert marker not in caplog.text
