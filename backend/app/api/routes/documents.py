from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_document, get_tenant_project
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import Document, DocumentKind
from app.schemas.domain import DocumentResponse
from app.services.storage import LocalObjectStorage

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["documents"], responses=TENANT_AUTH_RESPONSES
)

PROJECT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv"}
PROJECT_CONTENT_TYPES = {
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
}


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
    settings: Settings = Depends(get_settings),
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
        raise HTTPException(status_code=400, detail="Unsupported project document format.")
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if kind == DocumentKind.PROJECT and content_type not in PROJECT_CONTENT_TYPES[suffix]:
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded content type does not match the project document extension.",
        )

    storage_key, size = await LocalObjectStorage(settings).save(
        context.tenant.id, "documents", file
    )
    document = Document(
        tenant_id=context.tenant.id,
        project_id=project_id,
        uploaded_by=context.user.id,
        kind=kind,
        file_name=Path(file.filename or "upload.bin").name,
        content_type=content_type,
        size_bytes=size,
        storage_key=storage_key,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
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
        .where(Document.tenant_id == context.tenant.id, Document.project_id == project_id)
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


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    document = await get_tenant_document(db, context.tenant.id, document_id)
    LocalObjectStorage(settings).delete(document.storage_key)
    await db.delete(document)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
