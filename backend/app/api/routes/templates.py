from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, require_tenant_member
from app.api.routes.helpers import get_tenant_template
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.domain import WbsTemplate
from app.schemas.domain import TemplateResponse
from app.services.storage import LocalObjectStorage

router = APIRouter(prefix="/tenants/{tenant_id}/templates", tags=["templates"])
TEMPLATE_EXTENSIONS = {".xls", ".xlsx", ".csv", ".xml"}


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def upload_template(
    file: UploadFile = File(),
    name: str | None = Form(default=None),
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WbsTemplate:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in TEMPLATE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported WBS template format.")

    storage_key, size = await LocalObjectStorage(settings).save(
        context.tenant.id, "templates", file
    )
    template = WbsTemplate(
        tenant_id=context.tenant.id,
        uploaded_by=context.user.id,
        name=(name or Path(file.filename or "Template").stem).strip(),
        file_name=Path(file.filename or "template.bin").name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        storage_key=storage_key,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    context: TenantContext = Depends(require_tenant_member),
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
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> WbsTemplate:
    return await get_tenant_template(db, context.tenant.id, template_id)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_template(
    template_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> Response:
    template = await get_tenant_template(db, context.tenant.id, template_id)
    template.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
