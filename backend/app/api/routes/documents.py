from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, require_tenant_member
from app.api.routes.helpers import get_tenant_document, get_tenant_project
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.domain import Document, DocumentKind
from app.schemas.domain import DocumentResponse
from app.services.storage import LocalObjectStorage

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["documents"])

PROJECT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv"}


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: UUID,
    kind: DocumentKind = Form(default=DocumentKind.PROJECT),
    file: UploadFile = File(),
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    await get_tenant_project(db, context.tenant.id, project_id)
    suffix = Path(file.filename or "").suffix.lower()
    if kind == DocumentKind.PROJECT and suffix not in PROJECT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported project document format.")

    storage_key, size = await LocalObjectStorage(settings).save(
        context.tenant.id, "documents", file
    )
    document = Document(
        tenant_id=context.tenant.id,
        project_id=project_id,
        uploaded_by=context.user.id,
        kind=kind,
        file_name=Path(file.filename or "upload.bin").name,
        content_type=file.content_type or "application/octet-stream",
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
    context: TenantContext = Depends(require_tenant_member),
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
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> Document:
    return await get_tenant_document(db, context.tenant.id, document_id)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    document = await get_tenant_document(db, context.tenant.id, document_id)
    LocalObjectStorage(settings).delete(document.storage_key)
    await db.delete(document)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
