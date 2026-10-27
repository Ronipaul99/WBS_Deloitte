import logging
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class DocumentInputErrorCode(StrEnum):
    DOCUMENT_OBJECT_MISSING = "DOCUMENT_OBJECT_MISSING"
    OBJECT_STORAGE_UNAVAILABLE = "OBJECT_STORAGE_UNAVAILABLE"
    DOCUMENT_INTEGRITY_FAILED = "DOCUMENT_INTEGRITY_FAILED"
    MALWARE_SCANNER_UNAVAILABLE = "MALWARE_SCANNER_UNAVAILABLE"
    DOCUMENT_REJECTED_MALWARE = "DOCUMENT_REJECTED_MALWARE"
    PROCESSING_STORAGE_UNAVAILABLE = "PROCESSING_STORAGE_UNAVAILABLE"


_ERROR_DETAILS: dict[DocumentInputErrorCode, tuple[str, bool, bool]] = {
    DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING: (
        "The source document is unavailable.",
        False,
        False,
    ),
    DocumentInputErrorCode.OBJECT_STORAGE_UNAVAILABLE: (
        "Object storage is temporarily unavailable.",
        True,
        False,
    ),
    DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED: (
        "The source document failed integrity validation.",
        False,
        True,
    ),
    DocumentInputErrorCode.MALWARE_SCANNER_UNAVAILABLE: (
        "Malware scanning is temporarily unavailable.",
        True,
        False,
    ),
    DocumentInputErrorCode.DOCUMENT_REJECTED_MALWARE: (
        "The source document was rejected by malware scanning.",
        False,
        True,
    ),
    DocumentInputErrorCode.PROCESSING_STORAGE_UNAVAILABLE: (
        "Temporary processing storage is unavailable.",
        True,
        False,
    ),
}


class DocumentInputError(RuntimeError):
    def __init__(self, code: DocumentInputErrorCode) -> None:
        message, retryable, security_review = _ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        self.security_review = security_review
        super().__init__(message)


class ExtractionErrorCode(StrEnum):
    UNSUPPORTED_DOCUMENT_FORMAT = "UNSUPPORTED_DOCUMENT_FORMAT"
    DOCUMENT_ENCRYPTED = "DOCUMENT_ENCRYPTED"
    DOCUMENT_MALFORMED = "DOCUMENT_MALFORMED"
    DOCUMENT_EXTRACTION_LIMIT_EXCEEDED = "DOCUMENT_EXTRACTION_LIMIT_EXCEEDED"
    DOCUMENT_NO_EXTRACTABLE_CONTENT = "DOCUMENT_NO_EXTRACTABLE_CONTENT"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    OCR_FAILED = "OCR_FAILED"
    DOCUMENT_PARSER_TIMEOUT = "DOCUMENT_PARSER_TIMEOUT"
    DOCUMENT_PARSER_RESOURCE_EXHAUSTED = "DOCUMENT_PARSER_RESOURCE_EXHAUSTED"
    DOCUMENT_EXTRACTION_FAILED = "DOCUMENT_EXTRACTION_FAILED"
    EXTRACTOR_REGISTRY_INVALID = "EXTRACTOR_REGISTRY_INVALID"


_EXTRACTION_ERROR_DETAILS: dict[ExtractionErrorCode, tuple[str, bool]] = {
    ExtractionErrorCode.UNSUPPORTED_DOCUMENT_FORMAT: (
        "The confirmed document format is not supported.",
        False,
    ),
    ExtractionErrorCode.DOCUMENT_ENCRYPTED: (
        "The document is encrypted and cannot be processed.",
        False,
    ),
    ExtractionErrorCode.DOCUMENT_MALFORMED: (
        "The document structure is invalid.",
        False,
    ),
    ExtractionErrorCode.DOCUMENT_EXTRACTION_LIMIT_EXCEEDED: (
        "The document exceeds an extraction safety limit.",
        False,
    ),
    ExtractionErrorCode.DOCUMENT_NO_EXTRACTABLE_CONTENT: (
        "The document contains no extractable content.",
        False,
    ),
    ExtractionErrorCode.OCR_UNAVAILABLE: (
        "The OCR dependency is unavailable.",
        True,
    ),
    ExtractionErrorCode.OCR_FAILED: (
        "OCR could not extract document content.",
        False,
    ),
    ExtractionErrorCode.DOCUMENT_PARSER_TIMEOUT: (
        "Document extraction exceeded its time limit.",
        True,
    ),
    ExtractionErrorCode.DOCUMENT_PARSER_RESOURCE_EXHAUSTED: (
        "Document extraction exceeded an execution resource limit.",
        True,
    ),
    ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED: (
        "Document extraction failed safely.",
        True,
    ),
    ExtractionErrorCode.EXTRACTOR_REGISTRY_INVALID: (
        "The extractor registry is incomplete or ambiguous.",
        False,
    ),
}


class ExtractionError(RuntimeError):
    def __init__(self, code: ExtractionErrorCode) -> None:
        message, retryable = _EXTRACTION_ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ExtractionJobFailure:
    error_code: ExtractionErrorCode
    retryable: bool
    message: str


def extraction_error_to_job_failure(error: ExtractionError) -> ExtractionJobFailure:
    return ExtractionJobFailure(
        error_code=error.code,
        retryable=error.retryable,
        message=str(error),
    )


def map_unexpected_extraction_failure(error: BaseException) -> ExtractionError:
    logger.warning(
        "Document extraction failed safely",
        extra={"error_category": type(error).__name__},
    )
    return ExtractionError(ExtractionErrorCode.DOCUMENT_EXTRACTION_FAILED)


class ChunkingErrorCode(StrEnum):
    TOKENIZER_UNAVAILABLE = "TOKENIZER_UNAVAILABLE"
    TOKENIZER_ARTIFACT_INVALID = "TOKENIZER_ARTIFACT_INVALID"
    DOCUMENT_NORMALIZATION_FAILED = "DOCUMENT_NORMALIZATION_FAILED"
    DOCUMENT_CHUNK_LIMIT_EXCEEDED = "DOCUMENT_CHUNK_LIMIT_EXCEEDED"
    DOCUMENT_CHUNK_COVERAGE_FAILED = "DOCUMENT_CHUNK_COVERAGE_FAILED"
    DOCUMENT_CHUNKING_FAILED = "DOCUMENT_CHUNKING_FAILED"


_CHUNKING_ERROR_DETAILS: dict[ChunkingErrorCode, tuple[str, bool]] = {
    ChunkingErrorCode.TOKENIZER_UNAVAILABLE: (
        "The approved tokenizer dependency is unavailable.",
        True,
    ),
    ChunkingErrorCode.TOKENIZER_ARTIFACT_INVALID: (
        "The packaged tokenizer artifact is invalid.",
        False,
    ),
    ChunkingErrorCode.DOCUMENT_NORMALIZATION_FAILED: (
        "Document normalization failed safely.",
        False,
    ),
    ChunkingErrorCode.DOCUMENT_CHUNK_LIMIT_EXCEEDED: (
        "The document exceeds a chunking safety limit.",
        False,
    ),
    ChunkingErrorCode.DOCUMENT_CHUNK_COVERAGE_FAILED: (
        "Document chunk source coverage validation failed.",
        False,
    ),
    ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED: (
        "Document chunking failed safely.",
        True,
    ),
}


class ChunkingError(RuntimeError):
    def __init__(self, code: ChunkingErrorCode) -> None:
        message, retryable = _CHUNKING_ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ChunkingJobFailure:
    error_code: ChunkingErrorCode
    retryable: bool
    message: str


def chunking_error_to_job_failure(error: ChunkingError) -> ChunkingJobFailure:
    return ChunkingJobFailure(
        error_code=error.code,
        retryable=error.retryable,
        message=str(error),
    )


def map_unexpected_chunking_failure(error: BaseException) -> ChunkingError:
    logger.warning(
        "Document chunking failed safely",
        extra={"error_category": type(error).__name__},
    )
    return ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED)


class EmbeddingErrorCode(StrEnum):
    EMBEDDING_RUNTIME_UNAVAILABLE = "EMBEDDING_RUNTIME_UNAVAILABLE"
    EMBEDDING_MODEL_INVALID = "EMBEDDING_MODEL_INVALID"
    DOCUMENT_EMBEDDING_LIMIT_EXCEEDED = "DOCUMENT_EMBEDDING_LIMIT_EXCEEDED"
    EMBEDDING_OUTPUT_INVALID = "EMBEDDING_OUTPUT_INVALID"
    DOCUMENT_EMBEDDING_FAILED = "DOCUMENT_EMBEDDING_FAILED"


_EMBEDDING_ERROR_DETAILS: dict[EmbeddingErrorCode, tuple[str, bool]] = {
    EmbeddingErrorCode.EMBEDDING_RUNTIME_UNAVAILABLE: (
        "The approved embedding runtime is unavailable.",
        True,
    ),
    EmbeddingErrorCode.EMBEDDING_MODEL_INVALID: (
        "The packaged embedding model failed integrity validation.",
        False,
    ),
    EmbeddingErrorCode.DOCUMENT_EMBEDDING_LIMIT_EXCEEDED: (
        "The document exceeds an embedding safety limit.",
        False,
    ),
    EmbeddingErrorCode.EMBEDDING_OUTPUT_INVALID: (
        "The embedding runtime returned invalid output.",
        True,
    ),
    EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED: (
        "Document embedding failed safely.",
        True,
    ),
}


class EmbeddingError(RuntimeError):
    def __init__(self, code: EmbeddingErrorCode) -> None:
        message, retryable = _EMBEDDING_ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EmbeddingJobFailure:
    error_code: EmbeddingErrorCode
    retryable: bool
    message: str


def embedding_error_to_job_failure(error: EmbeddingError) -> EmbeddingJobFailure:
    return EmbeddingJobFailure(
        error_code=error.code,
        retryable=error.retryable,
        message=str(error),
    )


def map_unexpected_embedding_failure(error: BaseException) -> EmbeddingError:
    logger.warning(
        "Document embedding failed safely",
        extra={"error_category": type(error).__name__},
    )
    return EmbeddingError(EmbeddingErrorCode.DOCUMENT_EMBEDDING_FAILED)


class PersistenceErrorCode(StrEnum):
    DOCUMENT_PERSISTENCE_INPUT_INVALID = "DOCUMENT_PERSISTENCE_INPUT_INVALID"
    DOCUMENT_PERSISTENCE_SCOPE_MISMATCH = "DOCUMENT_PERSISTENCE_SCOPE_MISMATCH"
    DOCUMENT_PROCESSING_STATE_CONFLICT = "DOCUMENT_PROCESSING_STATE_CONFLICT"
    DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT = "DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT"
    DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED = "DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED"
    DOCUMENT_ACTIVATION_CONFLICT = "DOCUMENT_ACTIVATION_CONFLICT"
    DOCUMENT_PERSISTENCE_UNAVAILABLE = "DOCUMENT_PERSISTENCE_UNAVAILABLE"
    DOCUMENT_PERSISTENCE_FAILED = "DOCUMENT_PERSISTENCE_FAILED"


_PERSISTENCE_ERROR_DETAILS: dict[PersistenceErrorCode, tuple[str, bool]] = {
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_INPUT_INVALID: (
        "The document persistence input is invalid.",
        False,
    ),
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH: (
        "The document persistence scope is invalid.",
        False,
    ),
    PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT: (
        "The document processing state does not permit this operation.",
        False,
    ),
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT: (
        "The persisted document data conflicts with this processing attempt.",
        False,
    ),
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED: (
        "The persisted document data failed reconciliation.",
        False,
    ),
    PersistenceErrorCode.DOCUMENT_ACTIVATION_CONFLICT: (
        "The document processing run could not be activated consistently.",
        True,
    ),
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_UNAVAILABLE: (
        "Document persistence is temporarily unavailable.",
        True,
    ),
    PersistenceErrorCode.DOCUMENT_PERSISTENCE_FAILED: (
        "Document persistence failed safely.",
        True,
    ),
}


class PersistenceError(RuntimeError):
    def __init__(self, code: PersistenceErrorCode) -> None:
        message, retryable = _PERSISTENCE_ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PersistenceJobFailure:
    error_code: PersistenceErrorCode
    retryable: bool
    message: str


def persistence_error_to_job_failure(error: PersistenceError) -> PersistenceJobFailure:
    return PersistenceJobFailure(
        error_code=error.code,
        retryable=error.retryable,
        message=str(error),
    )


def map_unexpected_persistence_failure(error: BaseException) -> PersistenceError:
    logger.warning(
        "Document persistence failed safely",
        extra={"error_category": type(error).__name__},
    )
    return PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_FAILED)


class IngestionErrorCode(StrEnum):
    DOCUMENT_INGESTION_SCOPE_INVALID = "DOCUMENT_INGESTION_SCOPE_INVALID"
    DOCUMENT_INGESTION_STATE_CONFLICT = "DOCUMENT_INGESTION_STATE_CONFLICT"
    DOCUMENT_INGESTION_STATE_INCONSISTENT = "DOCUMENT_INGESTION_STATE_INCONSISTENT"
    DOCUMENT_INGESTION_TIMEOUT = "DOCUMENT_INGESTION_TIMEOUT"
    DOCUMENT_INGESTION_FAILED = "DOCUMENT_INGESTION_FAILED"
    DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED = "DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED"
    DOCUMENT_DISPATCH_UNAVAILABLE = "DOCUMENT_DISPATCH_UNAVAILABLE"


_INGESTION_ERROR_DETAILS: dict[IngestionErrorCode, tuple[str, bool]] = {
    IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID: (
        "The document ingestion scope is invalid.",
        False,
    ),
    IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT: (
        "The document ingestion state does not permit this operation.",
        False,
    ),
    IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT: (
        "The document ingestion state requires reconciliation.",
        False,
    ),
    IngestionErrorCode.DOCUMENT_INGESTION_TIMEOUT: (
        "Document ingestion exceeded its execution time limit.",
        True,
    ),
    IngestionErrorCode.DOCUMENT_INGESTION_FAILED: (
        "Document ingestion failed safely.",
        True,
    ),
    IngestionErrorCode.DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED: (
        "Document ingestion exhausted its retry attempts.",
        False,
    ),
    IngestionErrorCode.DOCUMENT_DISPATCH_UNAVAILABLE: (
        "Document ingestion dispatch is temporarily unavailable.",
        True,
    ),
}


class IngestionError(RuntimeError):
    def __init__(self, code: IngestionErrorCode) -> None:
        message, retryable = _INGESTION_ERROR_DETAILS[code]
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class IngestionJobFailure:
    error_code: str
    retryable: bool
    message: str


def ingestion_error_to_job_failure(error: BaseException) -> IngestionJobFailure:
    if isinstance(error, TimeoutError) or type(error).__name__ == "SoftTimeLimitExceeded":
        error = IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_TIMEOUT)
    supported = (
        DocumentInputError,
        ExtractionError,
        ChunkingError,
        EmbeddingError,
        PersistenceError,
        IngestionError,
    )
    if isinstance(error, supported):
        return IngestionJobFailure(
            error_code=error.code.value,
            retryable=error.retryable,
            message=str(error),
        )
    logger.warning(
        "Document ingestion failed safely",
        extra={"error_category": type(error).__name__},
    )
    mapped = IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_FAILED)
    return IngestionJobFailure(
        error_code=mapped.code.value,
        retryable=mapped.retryable,
        message=str(mapped),
    )
