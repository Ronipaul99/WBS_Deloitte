import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_document, get_tenant_project
from app.core.observability import record_document_upload
from app.core.permissions import Permission
from app.core.upload_errors import UploadErrorCode, upload_error_code, upload_http_error
from app.db.session import get_db, set_local_tenant_context
from app.models.domain import Document, DocumentKind, DocumentLifecycleStatus, Job
from app.schemas.domain import DocumentDeletionStatusResponse, DocumentResponse, JobResponse
from app.services.dispatcher import publish_deletion_dispatch
from app.services.document_lifecycle import request_document_deletion
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["documents"], responses=TENANT_AUTH_RESPONSES
)
logger = logging.getLogger(__name__)

PROJECT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv"}
PROJECT_CONTENT_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
}
PROJECT_FORMAT_LABELS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".csv": "csv",
}
COMPENSATION_DELETE_ATTEMPTS = 2


async def _cleanup_uploaded_document(
    storage: UploadObjectStorage,
    storage_key: str,
) -> None:
    for _ in range(COMPENSATION_DELETE_ATTEMPTS):
        try:
            await storage.delete_object(storage_key)
            return
        except ObjectStorageUnavailableError:
            continue
    logger.error("Document object cleanup failed after database rollback")


async def _persist_document(
    db: AsyncSession,
    storage: UploadObjectStorage,
    document: Document,
) -> None:
    try:
        db.add(document)
        await db.commit()
    except Exception:
        await db.rollback()
        await _cleanup_uploaded_document(storage, document.storage_key)
        raise


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "kind": {
                                "type": "string",
                                "enum": [kind.value for kind in DocumentKind],
                                "default": DocumentKind.PROJECT.value,
                            },
                        },
                    }
                }
            },
        }
    },
)
async def upload_document(
    request: Request,
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
    storage: UploadObjectStorage = Depends(get_upload_storage),
) -> Document:
    await get_tenant_project(db, context.tenant.id, project_id)
    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise HTTPException(status_code=422, detail="A document file is required.")
    try:
        kind = DocumentKind(str(form.get("kind") or DocumentKind.PROJECT.value))
    except ValueError as exc:
        await file.close()
        raise HTTPException(status_code=422, detail="Invalid document kind.") from exc
    if kind != DocumentKind.PROJECT:
        await file.close()
        raise HTTPException(
            status_code=422,
            detail="WBS templates must be uploaded through the templates endpoint.",
        )
    suffix = Path(file.filename or "").suffix.lower()
    if kind == DocumentKind.PROJECT and suffix not in PROJECT_EXTENSIONS:
        await file.close()
        record_document_upload(
            accepted=False,
            detected_format="unknown",
            error_code=UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT.value,
        )
        raise upload_http_error(UploadErrorCode.UNSUPPORTED_DOCUMENT_FORMAT)
    detected_format = PROJECT_FORMAT_LABELS[suffix]
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if kind == DocumentKind.PROJECT and content_type not in PROJECT_CONTENT_TYPES[suffix]:
        await file.close()
        record_document_upload(
            accepted=False,
            detected_format=detected_format,
            error_code=UploadErrorCode.DOCUMENT_TYPE_MISMATCH.value,
        )
        raise upload_http_error(UploadErrorCode.DOCUMENT_TYPE_MISMATCH)

    normalized_content_type = "application/pdf" if suffix == ".pdf" else content_type

    file_name = Path(file.filename or "upload.bin").name
    try:
        storage_key, size = await storage.save(
            context.tenant.id,
            "documents",
            file,
            suffix=suffix,
            content_type=normalized_content_type,
            project_id=project_id,
        )
    except HTTPException as exc:
        code = upload_error_code(exc)
        if code is not None:
            record_document_upload(
                accepted=False,
                detected_format=(
                    "unknown" if code == UploadErrorCode.DOCUMENT_TYPE_MISMATCH else detected_format
                ),
                error_code=code.value,
            )
        raise
    except ObjectStorageUnavailableError:
        record_document_upload(
            accepted=False,
            detected_format=detected_format,
            error_code=UploadErrorCode.OBJECT_STORAGE_UNAVAILABLE.value,
        )
        raise upload_http_error(UploadErrorCode.OBJECT_STORAGE_UNAVAILABLE) from None
    document = Document(
        tenant_id=context.tenant.id,
        project_id=project_id,
        uploaded_by=context.user.id,
        kind=kind,
        file_name=file_name,
        content_type=normalized_content_type,
        size_bytes=size,
        storage_key=storage_key,
    )
    try:
        await _persist_document(db, storage, document)
    except Exception:
        record_document_upload(
            accepted=False,
            detected_format=detected_format,
            error_code="INTERNAL_ERROR",
        )
        raise
    await db.refresh(document)
    record_document_upload(accepted=True, detected_format=detected_format)
    return document


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    await get_tenant_project(db, context.tenant.id, project_id)
    result = await db.scalars(
        select(Document)
        .where(
            Document.tenant_id == context.tenant.id,
            Document.project_id == project_id,
            Document.lifecycle_status != DocumentLifecycleStatus.DELETED.value,
        )
        .order_by(Document.created_at.desc())
    )
    return list(result)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: AsyncSession = Depends(get_db),
) -> Document:
    return await get_tenant_document(db, context.tenant.id, document_id)


@router.delete(
    "/documents/{document_id}",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_document(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    try:
        job, outbox = await request_document_deletion(
            db,
            tenant_id=context.tenant.id,
            document_id=document_id,
            requested_by=context.user.id,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Document not found.") from None
    except RuntimeError:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_DELETION_STATE_INVALID",
                "message": "The document deletion state could not be verified.",
            },
        ) from None
    if outbox is not None:
        await publish_deletion_dispatch(context.tenant.id, outbox.id)
    return job


@router.get(
    "/documents/{document_id}/deletion",
    response_model=DocumentDeletionStatusResponse,
)
async def get_document_deletion_status(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentDeletionStatusResponse:
    await set_local_tenant_context(db, context.tenant.id)
    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == context.tenant.id,
        )
    )
    if document is None or document.deletion_job_id is None:
        raise HTTPException(status_code=404, detail="Document deletion not found.")
    job = await db.scalar(
        select(Job).where(
            Job.id == document.deletion_job_id,
            Job.tenant_id == context.tenant.id,
            Job.project_id == document.project_id,
        )
    )
    if job is None or document.deletion_requested_at is None or document.vectors_hidden_at is None:
        raise HTTPException(status_code=404, detail="Document deletion not found.")
    return DocumentDeletionStatusResponse(
        document_id=document.id,
        job_id=job.id,
        status=job.status,
        stage=job.current_step or "QUEUED",
        progress=job.progress,
        attempt_count=job.attempt_count,
        lifecycle_status=document.lifecycle_status,
        deletion_requested_at=document.deletion_requested_at,
        vectors_hidden_at=document.vectors_hidden_at,
        deletion_completed_at=document.deletion_completed_at,
        error_code=document.deletion_error_code or job.error_code,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
