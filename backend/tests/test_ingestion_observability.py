from app.core.observability import (
    DOCUMENT_CHUNKING_DURATION,
    DOCUMENT_EXTRACTION_DURATION,
    DOCUMENT_INPUTS,
    EMBEDDING_BATCH_DURATION,
    EMBEDDING_INITIALIZATION_DURATION,
    MALWARE_SCAN_DURATION,
    PDF_EXTRACTION_DURATION,
    PDF_OCR_DURATION,
    record_document_chunking,
    record_document_extraction,
    record_document_input,
    record_embedding_batch,
    record_embedding_initialization,
    record_malware_scan,
    record_pdf_extraction,
    record_pdf_ocr,
)


def test_ingestion_metrics_replace_unbounded_labels() -> None:
    sensitive_value = "tenant-document-private-value"

    record_document_input(trusted=False, error_code=sensitive_value)
    record_malware_scan(duration_seconds=0.1, outcome=sensitive_value)

    input_samples = DOCUMENT_INPUTS.collect()[0].samples
    scan_samples = MALWARE_SCAN_DURATION.collect()[0].samples
    assert any(sample.labels.get("error_code") == "INTERNAL_ERROR" for sample in input_samples)
    assert any(sample.labels.get("outcome") == "unavailable" for sample in scan_samples)
    assert sensitive_value not in str(input_samples)
    assert sensitive_value not in str(scan_samples)


def test_pdf_metrics_allow_only_bounded_non_sensitive_labels() -> None:
    sensitive_value = "private-document-and-path-marker"

    record_pdf_extraction(
        duration_seconds=0.1,
        outcome=sensitive_value,
        mode=sensitive_value,
    )
    record_pdf_ocr(duration_seconds=0.1, outcome=sensitive_value)

    extraction_samples = PDF_EXTRACTION_DURATION.collect()[0].samples
    ocr_samples = PDF_OCR_DURATION.collect()[0].samples
    assert any(
        sample.labels == {"outcome": "failed", "mode": "unknown"} for sample in extraction_samples
    )
    assert any(sample.labels == {"outcome": "failed"} for sample in ocr_samples)
    assert sensitive_value not in str(extraction_samples)
    assert sensitive_value not in str(ocr_samples)


def test_office_csv_metrics_allow_only_bounded_non_sensitive_labels() -> None:
    sensitive_value = "private-sheet-path-formula-marker"

    record_document_extraction(
        document_format=sensitive_value,
        duration_seconds=0.1,
        outcome=sensitive_value,
    )

    samples = DOCUMENT_EXTRACTION_DURATION.collect()[0].samples
    assert any(
        sample.labels == {"document_format": "unknown", "outcome": "failed"} for sample in samples
    )
    assert sensitive_value not in str(samples)


def test_chunking_metrics_allow_only_bounded_non_sensitive_labels() -> None:
    sensitive_value = "private-content-sheet-path-hash-marker"

    record_document_chunking(
        document_format=sensitive_value,
        duration_seconds=0.1,
        outcome=sensitive_value,
        error_code=sensitive_value,
    )

    samples = DOCUMENT_CHUNKING_DURATION.collect()[0].samples
    assert any(
        sample.labels
        == {
            "document_format": "unknown",
            "outcome": "failed",
            "error_code": "DOCUMENT_CHUNKING_FAILED",
        }
        for sample in samples
    )
    assert sensitive_value not in str(samples)


def test_embedding_metrics_allow_only_bounded_non_sensitive_labels() -> None:
    sensitive_value = "private-content-vector-path-hash-marker"

    record_embedding_initialization(duration_seconds=0.1, outcome=sensitive_value)
    record_embedding_batch(
        duration_seconds=0.1,
        input_count=2,
        outcome=sensitive_value,
    )

    initialization_samples = EMBEDDING_INITIALIZATION_DURATION.collect()[0].samples
    batch_samples = EMBEDDING_BATCH_DURATION.collect()[0].samples
    assert any(sample.labels == {"outcome": "unavailable"} for sample in initialization_samples)
    assert any(sample.labels == {"outcome": "failed"} for sample in batch_samples)
    assert sensitive_value not in str(initialization_samples)
    assert sensitive_value not in str(batch_samples)
