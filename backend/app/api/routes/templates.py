import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_template
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import WbsTemplate
from app.schemas.domain import TemplateResponse
from app.services.storage import (
    ObjectStorageUnavailableError,
    UploadObjectStorage,
    get_upload_storage,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/templates",
    tags=["templates"],
    responses=TENANT_AUTH_RESPONSES,
)
logger = logging.getLogger(__name__)
TEMPLATE_EXTENSIONS = {".xlsx", ".csv", ".xml"}
TEMPLATE_CONTENT_TYPES = {
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    ".xml": {"application/xml", "text/xml"},
}


@router.post(
    "",
    response_model=TemplateResponse,
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
                            "name": {"type": "string"},
                        },
                    }
                }
            },
        }
    },
)
async def upload_template(
    request: Request,
    context: TenantContext = Depends(require_permission(Permission.TEMPLATE_MANAGE)),
    db: AsyncSession = Depends(get_db),
    storage: UploadObjectStorage = Depends(get_upload_storage),
) -> WbsTemplate:
    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise HTTPException(status_code=422, detail="A template file is required.")
    raw_name = form.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in TEMPLATE_EXTENSIONS:
        await file.close()
        raise HTTPException(status_code=400, detail="Unsupported WBS template format.")
    content_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if content_type not in TEMPLATE_CONTENT_TYPES[suffix]:
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded content type does not match the WBS template extension.",
        )

    file_name = Path(file.filename or "template.bin").name
    try:
        storage_key, size = await storage.save(
            context.tenant.id,
            "templates",
            file,
            suffix=suffix,
            content_type=content_type,
        )
    except ObjectStorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Template storage is temporarily unavailable.",
        ) from None
    template = WbsTemplate(
        tenant_id=context.tenant.id,
        uploaded_by=context.user.id,
        name=(name or Path(file.filename or "Template").stem).strip(),
        file_name=file_name,
        content_type=content_type,
        size_bytes=size,
        storage_key=storage_key,
    )
    try:
        db.add(template)
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await storage.delete_object(storage_key)
        except ObjectStorageUnavailableError:
            logger.exception("Failed to compensate template upload after database error")
        raise
    await db.refresh(template)
    return template


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    context: TenantContext = Depends(require_permission(Permission.TEMPLATE_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[WbsTemplate]:
    result = await db.scalars(
        select(WbsTemplate)
        .where(WbsTemplate.tenant_id == context.tenant.id, WbsTemplate.is_active.is_(True))
        .order_by(WbsTemplate.created_at.desc())
    )
    return list(result)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.TEMPLATE_READ)),
    db: AsyncSession = Depends(get_db),
) -> WbsTemplate:
    return await get_tenant_template(db, context.tenant.id, template_id)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_template(
    template_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.TEMPLATE_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    template = await get_tenant_template(db, context.tenant.id, template_id)
    template.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
