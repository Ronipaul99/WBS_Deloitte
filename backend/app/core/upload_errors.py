from enum import StrEnum

from fastapi import HTTPException


class UploadErrorCode(StrEnum):
    UNSUPPORTED_DOCUMENT_FORMAT = "UNSUPPORTED_DOCUMENT_FORMAT"
    DOCUMENT_TYPE_MISMATCH = "DOCUMENT_TYPE_MISMATCH"
    DOCUMENT_EMPTY = "DOCUMENT_EMPTY"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    PDF_MALFORMED = "PDF_MALFORMED"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    OBJECT_STORAGE_UNAVAILABLE = "OBJECT_STORAGE_UNAVAILABLE"


UPLOAD_ERROR_SPECS: dict[UploadErrorCode, tuple[int, str]] = {
    UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT: (415, "Document format is not supported."),
    UploadErrorCode.DOCUMENT_TYPE_MISMATCH: (
        415,
        "Uploaded content does not match the declared document type.",
    ),
    UploadErrorCode.DOCUMENT_EMPTY: (400, "The uploaded document is empty."),
    UploadErrorCode.DOCUMENT_TOO_LARGE: (
        413,
        "The uploaded document exceeds the configured size limit.",
    ),
    UploadErrorCode.PDF_MALFORMED: (422, "The PDF structure could not be read."),
    UploadErrorCode.PDF_ENCRYPTED: (422, "Password-protected PDFs are not supported."),
    UploadErrorCode.OBJECT_STORAGE_UNAVAILABLE: (
        503,
        "Document storage is temporarily unavailable.",
    ),
}


def upload_http_error(code: UploadErrorCode) -> HTTPException:
    status_code, message = UPLOAD_ERROR_SPECS[code]
    return HTTPException(
        status_code=status_code,
        detail={"code": code.value, "message": message},
    )


def upload_error_code(error: HTTPException) -> UploadErrorCode | None:
    if not isinstance(error.detail, dict):
        return None
    raw_code = error.detail.get("code")
    try:
        return UploadErrorCode(raw_code)
    except (TypeError, ValueError):
        return None
