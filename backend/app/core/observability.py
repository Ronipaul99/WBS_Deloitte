from prometheus_client import Counter, Gauge, Histogram

AUTH_EVENTS = Counter(
    "wbs_auth_events_total",
    "Authentication and authorization security events.",
    ("event_type", "outcome"),
)
HTTP_REQUESTS = Counter(
    "wbs_http_requests_total",
    "Completed API requests.",
    ("method", "route", "status_class"),
)
HTTP_REQUEST_DURATION = Histogram(
    "wbs_http_request_duration_seconds",
    "API request duration in seconds.",
    ("method", "route"),
)
MAINTENANCE_RUNS = Counter(
    "wbs_maintenance_runs_total",
    "Maintenance job outcomes.",
    ("outcome",),
)
REFRESH_SESSIONS = Gauge(
    "wbs_refresh_sessions",
    "Refresh session records by state.",
    ("state",),
)
MIGRATION_AT_HEAD = Gauge(
    "wbs_migration_at_head",
    "Whether the database migration revision is at the application head.",
)
DOCUMENT_UPLOADS = Counter(
    "wbs_document_uploads_total",
    "Accepted and rejected project document uploads.",
    ("outcome", "detected_format", "error_code"),
)
DOCUMENT_DOWNLOAD_DURATION = Histogram(
    "wbs_document_download_duration_seconds",
    "Private object inspection and download duration in seconds.",
    ("outcome",),
)
DOCUMENT_DOWNLOAD_BYTES = Histogram(
    "wbs_document_download_bytes",
    "Downloaded document bytes after bounded streaming succeeds.",
)
MALWARE_SCAN_DURATION = Histogram(
    "wbs_malware_scan_duration_seconds",
    "Malware scan duration in seconds.",
    ("outcome",),
)
DOCUMENT_INPUTS = Counter(
    "wbs_document_inputs_total",
    "Trusted and rejected worker document inputs.",
    ("outcome", "error_code"),
)
PDF_EXTRACTION_DURATION = Histogram(
    "wbs_pdf_extraction_duration_seconds",
    "Bounded PDF extraction duration in seconds.",
    ("outcome", "mode"),
)
PDF_EXTRACTED_PAGES = Histogram(
    "wbs_pdf_extracted_pages",
    "Page count for successful PDF extraction.",
    ("mode",),
)
PDF_OCR_DURATION = Histogram(
    "wbs_pdf_ocr_duration_seconds",
    "Controlled OCR subprocess duration in seconds.",
    ("outcome",),
)
DOCUMENT_EXTRACTION_DURATION = Histogram(
    "wbs_document_extraction_duration_seconds",
    "Bounded Office and CSV extraction duration in seconds.",
    ("document_format", "outcome"),
)
DOCUMENT_EXTRACTED_BLOCKS = Histogram(
    "wbs_document_extracted_blocks",
    "Block count for successful Office and CSV extraction.",
    ("document_format",),
)
DOCUMENT_EXTRACTED_ROWS = Histogram(
    "wbs_document_extracted_rows",
    "Row count for successful XLSX and CSV extraction.",
    ("document_format",),
)
DOCUMENT_EXTRACTED_WORKSHEETS = Histogram(
    "wbs_document_extracted_worksheets",
    "Worksheet count for successful XLSX extraction.",
    ("document_format",),
)
DOCUMENT_CHUNKING_DURATION = Histogram(
    "wbs_document_chunking_duration_seconds",
    "Bounded document normalization and chunking duration.",
    ("document_format", "outcome", "error_code"),
)
DOCUMENT_CHUNK_INPUT_BLOCKS = Histogram(
    "wbs_document_chunk_input_blocks",
    "Validated extraction blocks received by the chunker.",
    ("document_format",),
)
DOCUMENT_CHUNK_OUTPUTS = Histogram(
    "wbs_document_chunks",
    "Canonical chunks produced by the chunker.",
    ("document_format",),
)
DOCUMENT_CHUNK_TOKENS = Histogram(
    "wbs_document_chunk_tokens",
    "Aggregate model tokens in canonical chunks.",
    ("document_format",),
)
DOCUMENT_CHUNK_EVENTS = Histogram(
    "wbs_document_chunk_events",
    "Bounded chunk split, overlap, and empty-block event counts.",
    ("document_format", "event_type"),
)
EMBEDDING_INITIALIZATION_DURATION = Histogram(
    "wbs_embedding_initialization_duration_seconds",
    "Offline embedding-model initialization duration.",
    ("outcome",),
)
EMBEDDING_BATCH_DURATION = Histogram(
    "wbs_embedding_batch_duration_seconds",
    "Bounded offline embedding batch duration.",
    ("outcome",),
)
EMBEDDING_BATCH_INPUTS = Histogram(
    "wbs_embedding_batch_inputs",
    "Input count for a completed embedding batch.",
    ("outcome",),
)
VECTOR_PERSISTENCE_BATCH_DURATION = Histogram(
    "wbs_vector_persistence_batch_duration_seconds",
    "Bounded document chunk and vector batch persistence duration.",
    ("outcome",),
)
VECTOR_PERSISTENCE_BATCH_SIZE = Histogram(
    "wbs_vector_persistence_batch_size",
    "Document chunks handled by a persistence batch.",
    ("outcome",),
)
VECTOR_PERSISTENCE_ACTIVATION_DURATION = Histogram(
    "wbs_vector_persistence_activation_duration_seconds",
    "Atomic document processing-run activation duration.",
    ("outcome",),
)
VECTOR_PERSISTENCE_EVENTS = Counter(
    "wbs_vector_persistence_events_total",
    "Bounded vector-persistence operation outcomes.",
    ("operation", "outcome", "error_code"),
)
INGESTION_STAGE_TRANSITIONS = Counter(
    "wbs_ingestion_stage_transitions_total",
    "Durable document-ingestion stage transitions.",
    ("stage", "outcome"),
)
INGESTION_ATTEMPTS = Counter(
    "wbs_ingestion_attempts_total",
    "Document-ingestion attempt outcomes.",
    ("outcome", "error_code"),
)
INGESTION_DISPATCH_EVENTS = Counter(
    "wbs_ingestion_dispatch_events_total",
    "Transactional ingestion-dispatch outcomes.",
    ("outcome",),
)
INGESTION_RECONCILIATION_EVENTS = Counter(
    "wbs_ingestion_reconciliation_events_total",
    "Ingestion state reconciliation outcomes.",
    ("outcome",),
)
INGESTION_QUEUE_AGE = Histogram(
    "wbs_ingestion_queue_age_seconds",
    "Age of a document-ingestion job when a worker claims it.",
)
INGESTION_STAGE_DURATION = Histogram(
    "wbs_ingestion_stage_duration_seconds",
    "Elapsed time between durable document-ingestion stage transitions.",
    ("stage",),
)
INGESTION_RECONCILIATION_BACKLOG = Gauge(
    "wbs_ingestion_reconciliation_backlog",
    "Bounded ingestion dispatch records observed for republication.",
)
DOCUMENT_DELETION_EVENTS = Counter(
    "wbs_document_deletion_events_total",
    "Durable document deletion outcomes.",
    ("outcome",),
)
DOCUMENT_DELETION_DISPATCH_EVENTS = Counter(
    "wbs_document_deletion_dispatch_events_total",
    "Transactional document-deletion dispatch outcomes.",
    ("outcome",),
)
DOCUMENT_RETENTION_EVENTS = Counter(
    "wbs_document_retention_events_total",
    "Bounded document-retention outcomes.",
    ("category", "outcome"),
)
DOCUMENT_RECONCILIATION_FINDINGS = Counter(
    "wbs_document_reconciliation_findings_total",
    "Document lifecycle reconciliation findings by safe category.",
    ("category",),
)
DOCUMENT_RECONCILIATION_REPAIRS = Counter(
    "wbs_document_reconciliation_repairs_total",
    "Document lifecycle reconciliation repair outcomes.",
    ("category", "outcome"),
)

UPLOAD_FORMAT_LABELS = frozenset({"pdf", "docx", "xlsx", "csv", "unknown"})
UPLOAD_ERROR_LABELS = frozenset(
    {
        "none",
        "UNSUPPORTED_DOCUMENT_FORMAT",
        "DOCUMENT_TYPE_MISMATCH",
        "DOCUMENT_EMPTY",
        "DOCUMENT_TOO_LARGE",
        "PDF_MALFORMED",
        "PDF_ENCRYPTED",
        "OBJECT_STORAGE_UNAVAILABLE",
        "INTERNAL_ERROR",
    }
)
DOCUMENT_INPUT_ERROR_LABELS = frozenset(
    {
        "none",
        "DOCUMENT_OBJECT_MISSING",
        "OBJECT_STORAGE_UNAVAILABLE",
        "DOCUMENT_INTEGRITY_FAILED",
        "MALWARE_SCANNER_UNAVAILABLE",
        "DOCUMENT_REJECTED_MALWARE",
        "PROCESSING_STORAGE_UNAVAILABLE",
        "INTERNAL_ERROR",
    }
)
MALWARE_SCAN_OUTCOME_LABELS = frozenset({"clean", "infected", "unavailable"})
PDF_EXTRACTION_OUTCOME_LABELS = frozenset(
    {"success", "rejected", "timeout", "unavailable", "failed"}
)
PDF_EXTRACTION_MODE_LABELS = frozenset({"native", "ocr", "mixed", "unknown"})
PDF_OCR_OUTCOME_LABELS = frozenset(
    {"success", "failed", "timeout", "unavailable", "resource_exhausted"}
)
OFFICE_CSV_FORMAT_LABELS = frozenset({"docx", "xlsx", "csv", "unknown"})
OFFICE_CSV_OUTCOME_LABELS = frozenset({"success", "rejected", "failed"})
CHUNKING_FORMAT_LABELS = frozenset({"pdf", "docx", "xlsx", "csv", "unknown"})
CHUNKING_OUTCOME_LABELS = frozenset({"success", "rejected", "failed"})
CHUNKING_ERROR_LABELS = frozenset(
    {
        "none",
        "TOKENIZER_UNAVAILABLE",
        "TOKENIZER_ARTIFACT_INVALID",
        "DOCUMENT_NORMALIZATION_FAILED",
        "DOCUMENT_CHUNK_LIMIT_EXCEEDED",
        "DOCUMENT_CHUNK_COVERAGE_FAILED",
        "DOCUMENT_CHUNKING_FAILED",
    }
)
CHUNKING_EVENT_LABELS = frozenset({"forced_split", "overlap", "dropped_empty"})
EMBEDDING_INITIALIZATION_OUTCOME_LABELS = frozenset({"success", "unavailable", "invalid"})
EMBEDDING_BATCH_OUTCOME_LABELS = frozenset({"success", "invalid", "failed"})
VECTOR_PERSISTENCE_OPERATION_LABELS = frozenset(
    {"resolve", "batch", "reconcile", "activate", "fail", "delete"}
)
VECTOR_PERSISTENCE_OUTCOME_LABELS = frozenset(
    {"success", "reused", "conflict", "unavailable", "failed"}
)
VECTOR_PERSISTENCE_ERROR_LABELS = frozenset(
    {
        "none",
        "DOCUMENT_PERSISTENCE_INPUT_INVALID",
        "DOCUMENT_PERSISTENCE_SCOPE_MISMATCH",
        "DOCUMENT_PROCESSING_STATE_CONFLICT",
        "DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT",
        "DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED",
        "DOCUMENT_ACTIVATION_CONFLICT",
        "DOCUMENT_PERSISTENCE_UNAVAILABLE",
        "DOCUMENT_PERSISTENCE_FAILED",
    }
)
INGESTION_STAGE_LABELS = frozenset(
    {
        "QUEUED",
        "SCANNING",
        "EXTRACTING",
        "CHUNKING",
        "EMBEDDING",
        "PERSISTING",
        "ACTIVATING",
        "RETRY_WAIT",
        "COMPLETED",
        "FAILED",
    }
)
INGESTION_OUTCOME_LABELS = frozenset(
    {"success", "retry", "failed", "duplicate", "published", "pending", "repaired"}
)
INGESTION_ERROR_LABELS = frozenset(
    {
        "none",
        "DOCUMENT_OBJECT_MISSING",
        "OBJECT_STORAGE_UNAVAILABLE",
        "DOCUMENT_INTEGRITY_FAILED",
        "MALWARE_SCANNER_UNAVAILABLE",
        "DOCUMENT_REJECTED_MALWARE",
        "PROCESSING_STORAGE_UNAVAILABLE",
        "UNSUPPORTED_DOCUMENT_FORMAT",
        "DOCUMENT_ENCRYPTED",
        "DOCUMENT_MALFORMED",
        "DOCUMENT_EXTRACTION_LIMIT_EXCEEDED",
        "DOCUMENT_NO_EXTRACTABLE_CONTENT",
        "OCR_UNAVAILABLE",
        "OCR_FAILED",
        "DOCUMENT_PARSER_TIMEOUT",
        "DOCUMENT_PARSER_RESOURCE_EXHAUSTED",
        "DOCUMENT_EXTRACTION_FAILED",
        "EXTRACTOR_REGISTRY_INVALID",
        "TOKENIZER_UNAVAILABLE",
        "TOKENIZER_ARTIFACT_INVALID",
        "DOCUMENT_NORMALIZATION_FAILED",
        "DOCUMENT_CHUNK_LIMIT_EXCEEDED",
        "DOCUMENT_CHUNK_COVERAGE_FAILED",
        "DOCUMENT_CHUNKING_FAILED",
        "EMBEDDING_RUNTIME_UNAVAILABLE",
        "EMBEDDING_MODEL_INVALID",
        "DOCUMENT_EMBEDDING_LIMIT_EXCEEDED",
        "EMBEDDING_OUTPUT_INVALID",
        "DOCUMENT_EMBEDDING_FAILED",
        "DOCUMENT_PERSISTENCE_INPUT_INVALID",
        "DOCUMENT_PERSISTENCE_SCOPE_MISMATCH",
        "DOCUMENT_PROCESSING_STATE_CONFLICT",
        "DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT",
        "DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED",
        "DOCUMENT_ACTIVATION_CONFLICT",
        "DOCUMENT_PERSISTENCE_UNAVAILABLE",
        "DOCUMENT_PERSISTENCE_FAILED",
        "DOCUMENT_INGESTION_SCOPE_INVALID",
        "DOCUMENT_INGESTION_STATE_CONFLICT",
        "DOCUMENT_INGESTION_STATE_INCONSISTENT",
        "DOCUMENT_INGESTION_TIMEOUT",
        "DOCUMENT_INGESTION_FAILED",
        "DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED",
        "DOCUMENT_DISPATCH_UNAVAILABLE",
        "INTERNAL_ERROR",
    }
)


def record_auth_event(event_type: str, success: bool) -> None:
    AUTH_EVENTS.labels(event_type=event_type, outcome="success" if success else "failure").inc()


def record_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    status_class = f"{status_code // 100}xx"
    HTTP_REQUESTS.labels(method=method, route=route, status_class=status_class).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration_seconds)


def record_document_upload(
    *,
    accepted: bool,
    detected_format: str,
    error_code: str = "none",
) -> None:
    safe_format = detected_format if detected_format in UPLOAD_FORMAT_LABELS else "unknown"
    safe_error = error_code if error_code in UPLOAD_ERROR_LABELS else "INTERNAL_ERROR"
    DOCUMENT_UPLOADS.labels(
        outcome="accepted" if accepted else "rejected",
        detected_format=safe_format,
        error_code=safe_error,
    ).inc()


def record_document_download(
    *,
    duration_seconds: float,
    byte_count: int | None,
    success: bool,
) -> None:
    DOCUMENT_DOWNLOAD_DURATION.labels(outcome="success" if success else "failure").observe(
        max(duration_seconds, 0)
    )
    if success and byte_count is not None:
        DOCUMENT_DOWNLOAD_BYTES.observe(max(byte_count, 0))


def record_malware_scan(*, duration_seconds: float, outcome: str) -> None:
    safe_outcome = outcome if outcome in MALWARE_SCAN_OUTCOME_LABELS else "unavailable"
    MALWARE_SCAN_DURATION.labels(outcome=safe_outcome).observe(max(duration_seconds, 0))


def record_document_input(*, trusted: bool, error_code: str = "none") -> None:
    safe_error = error_code if error_code in DOCUMENT_INPUT_ERROR_LABELS else "INTERNAL_ERROR"
    DOCUMENT_INPUTS.labels(
        outcome="trusted" if trusted else "rejected",
        error_code=safe_error,
    ).inc()


def record_pdf_extraction(
    *,
    duration_seconds: float,
    outcome: str,
    mode: str,
    page_count: int | None = None,
) -> None:
    safe_outcome = outcome if outcome in PDF_EXTRACTION_OUTCOME_LABELS else "failed"
    safe_mode = mode if mode in PDF_EXTRACTION_MODE_LABELS else "unknown"
    PDF_EXTRACTION_DURATION.labels(outcome=safe_outcome, mode=safe_mode).observe(
        max(duration_seconds, 0)
    )
    if safe_outcome == "success" and page_count is not None:
        PDF_EXTRACTED_PAGES.labels(mode=safe_mode).observe(max(page_count, 0))


def record_pdf_ocr(*, duration_seconds: float, outcome: str) -> None:
    safe_outcome = outcome if outcome in PDF_OCR_OUTCOME_LABELS else "failed"
    PDF_OCR_DURATION.labels(outcome=safe_outcome).observe(max(duration_seconds, 0))


def record_document_extraction(
    *,
    document_format: str,
    duration_seconds: float,
    outcome: str,
    block_count: int | None = None,
    row_count: int | None = None,
    worksheet_count: int | None = None,
) -> None:
    safe_format = document_format if document_format in OFFICE_CSV_FORMAT_LABELS else "unknown"
    safe_outcome = outcome if outcome in OFFICE_CSV_OUTCOME_LABELS else "failed"
    DOCUMENT_EXTRACTION_DURATION.labels(
        document_format=safe_format,
        outcome=safe_outcome,
    ).observe(max(duration_seconds, 0))
    if safe_outcome != "success":
        return
    if block_count is not None:
        DOCUMENT_EXTRACTED_BLOCKS.labels(document_format=safe_format).observe(max(block_count, 0))
    if row_count is not None:
        DOCUMENT_EXTRACTED_ROWS.labels(document_format=safe_format).observe(max(row_count, 0))
    if worksheet_count is not None:
        DOCUMENT_EXTRACTED_WORKSHEETS.labels(document_format=safe_format).observe(
            max(worksheet_count, 0)
        )


def record_document_chunking(
    *,
    document_format: str,
    duration_seconds: float,
    outcome: str,
    error_code: str,
    input_blocks: int | None = None,
    output_chunks: int | None = None,
    total_tokens: int | None = None,
    forced_splits: int | None = None,
    overlap_applications: int | None = None,
    dropped_empty_blocks: int | None = None,
) -> None:
    safe_format = document_format if document_format in CHUNKING_FORMAT_LABELS else "unknown"
    safe_outcome = outcome if outcome in CHUNKING_OUTCOME_LABELS else "failed"
    safe_error = error_code if error_code in CHUNKING_ERROR_LABELS else "DOCUMENT_CHUNKING_FAILED"
    DOCUMENT_CHUNKING_DURATION.labels(
        document_format=safe_format,
        outcome=safe_outcome,
        error_code=safe_error,
    ).observe(max(duration_seconds, 0))
    if safe_outcome != "success":
        return
    if input_blocks is not None:
        DOCUMENT_CHUNK_INPUT_BLOCKS.labels(document_format=safe_format).observe(
            max(input_blocks, 0)
        )
    if output_chunks is not None:
        DOCUMENT_CHUNK_OUTPUTS.labels(document_format=safe_format).observe(max(output_chunks, 0))
    if total_tokens is not None:
        DOCUMENT_CHUNK_TOKENS.labels(document_format=safe_format).observe(max(total_tokens, 0))
    for event_type, value in (
        ("forced_split", forced_splits),
        ("overlap", overlap_applications),
        ("dropped_empty", dropped_empty_blocks),
    ):
        if event_type in CHUNKING_EVENT_LABELS and value is not None:
            DOCUMENT_CHUNK_EVENTS.labels(
                document_format=safe_format,
                event_type=event_type,
            ).observe(max(value, 0))


def record_embedding_initialization(*, duration_seconds: float, outcome: str) -> None:
    safe_outcome = outcome if outcome in EMBEDDING_INITIALIZATION_OUTCOME_LABELS else "unavailable"
    EMBEDDING_INITIALIZATION_DURATION.labels(outcome=safe_outcome).observe(max(duration_seconds, 0))


def record_embedding_batch(
    *,
    duration_seconds: float,
    input_count: int,
    outcome: str,
) -> None:
    safe_outcome = outcome if outcome in EMBEDDING_BATCH_OUTCOME_LABELS else "failed"
    EMBEDDING_BATCH_DURATION.labels(outcome=safe_outcome).observe(max(duration_seconds, 0))
    EMBEDDING_BATCH_INPUTS.labels(outcome=safe_outcome).observe(max(input_count, 0))


def record_vector_persistence_event(
    *,
    operation: str,
    outcome: str,
    error_code: str = "none",
) -> None:
    safe_operation = operation if operation in VECTOR_PERSISTENCE_OPERATION_LABELS else "reconcile"
    safe_outcome = outcome if outcome in VECTOR_PERSISTENCE_OUTCOME_LABELS else "failed"
    safe_error = (
        error_code
        if error_code in VECTOR_PERSISTENCE_ERROR_LABELS
        else "DOCUMENT_PERSISTENCE_FAILED"
    )
    VECTOR_PERSISTENCE_EVENTS.labels(
        operation=safe_operation,
        outcome=safe_outcome,
        error_code=safe_error,
    ).inc()


def record_vector_persistence_batch(
    *,
    duration_seconds: float,
    batch_size: int,
    outcome: str,
) -> None:
    safe_outcome = outcome if outcome in VECTOR_PERSISTENCE_OUTCOME_LABELS else "failed"
    VECTOR_PERSISTENCE_BATCH_DURATION.labels(outcome=safe_outcome).observe(max(duration_seconds, 0))
    VECTOR_PERSISTENCE_BATCH_SIZE.labels(outcome=safe_outcome).observe(max(batch_size, 0))


def record_vector_persistence_activation(*, duration_seconds: float, outcome: str) -> None:
    safe_outcome = outcome if outcome in VECTOR_PERSISTENCE_OUTCOME_LABELS else "failed"
    VECTOR_PERSISTENCE_ACTIVATION_DURATION.labels(outcome=safe_outcome).observe(
        max(duration_seconds, 0)
    )


def record_ingestion_stage(*, stage: str, outcome: str = "success") -> None:
    safe_stage = stage if stage in INGESTION_STAGE_LABELS else "FAILED"
    safe_outcome = outcome if outcome in INGESTION_OUTCOME_LABELS else "failed"
    INGESTION_STAGE_TRANSITIONS.labels(stage=safe_stage, outcome=safe_outcome).inc()


def record_ingestion_queue_age(*, duration_seconds: float) -> None:
    INGESTION_QUEUE_AGE.observe(max(duration_seconds, 0))


def record_ingestion_stage_duration(*, stage: str, duration_seconds: float) -> None:
    safe_stage = stage if stage in INGESTION_STAGE_LABELS else "FAILED"
    INGESTION_STAGE_DURATION.labels(stage=safe_stage).observe(max(duration_seconds, 0))


def record_ingestion_attempt(*, outcome: str, error_code: str = "none") -> None:
    safe_outcome = outcome if outcome in INGESTION_OUTCOME_LABELS else "failed"
    safe_error = error_code if error_code in INGESTION_ERROR_LABELS else "INTERNAL_ERROR"
    INGESTION_ATTEMPTS.labels(outcome=safe_outcome, error_code=safe_error).inc()


def record_ingestion_dispatch(*, outcome: str) -> None:
    safe_outcome = outcome if outcome in INGESTION_OUTCOME_LABELS else "failed"
    INGESTION_DISPATCH_EVENTS.labels(outcome=safe_outcome).inc()


def record_ingestion_reconciliation(*, outcome: str) -> None:
    safe_outcome = outcome if outcome in INGESTION_OUTCOME_LABELS else "failed"
    INGESTION_RECONCILIATION_EVENTS.labels(outcome=safe_outcome).inc()


def record_ingestion_reconciliation_backlog(*, count: int) -> None:
    INGESTION_RECONCILIATION_BACKLOG.set(max(count, 0))


def record_document_deletion(*, outcome: str) -> None:
    safe_outcome = (
        outcome
        if outcome
        in {
            "requested",
            "completed",
            "failed",
            "retrying",
        }
        else "failed"
    )
    DOCUMENT_DELETION_EVENTS.labels(outcome=safe_outcome).inc()


def record_document_deletion_dispatch(*, outcome: str) -> None:
    safe_outcome = (
        outcome
        if outcome
        in {
            "published",
            "pending",
            "duplicate",
            "failed",
        }
        else "failed"
    )
    DOCUMENT_DELETION_DISPATCH_EVENTS.labels(outcome=safe_outcome).inc()


def record_document_retention(*, category: str, outcome: str) -> None:
    safe_category = (
        category
        if category
        in {
            "failed_run",
            "cancelled_run",
            "superseded_run",
            "malware_event",
            "job",
            "tombstone",
            "workspace",
        }
        else "unknown"
    )
    safe_outcome = outcome if outcome in {"candidate", "removed", "skipped", "failed"} else "failed"
    DOCUMENT_RETENTION_EVENTS.labels(category=safe_category, outcome=safe_outcome).inc()


def record_document_reconciliation(*, category: str, outcome: str | None = None) -> None:
    safe_category = (
        category
        if category
        in {
            "missing_object",
            "orphan_object",
            "missing_dispatch",
            "stale_processing",
            "invalid_counts",
            "invalid_active_run",
            "deleting_vectors",
            "deleting_object",
            "expired_run",
            "stale_workspace",
            "ownership",
        }
        else "unknown"
    )
    DOCUMENT_RECONCILIATION_FINDINGS.labels(category=safe_category).inc()
    if outcome is not None:
        safe_outcome = (
            outcome if outcome in {"repaired", "reported", "skipped", "failed"} else "failed"
        )
        DOCUMENT_RECONCILIATION_REPAIRS.labels(
            category=safe_category,
            outcome=safe_outcome,
        ).inc()
