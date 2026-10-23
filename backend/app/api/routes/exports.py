from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_project, get_tenant_wbs_version
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import ExportFile
from app.schemas.domain import ExportCreate, ExportResponse
from app.services.dispatcher import dispatch_export

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["exports"], responses=TENANT_AUTH_RESPONSES)


def _to_response(export: ExportFile) -> ExportResponse:
    download_url = (
        f"/api/v1/tenants/{export.tenant_id}/exports/{export.id}/download"
        if export.storage_key
        else None
    )
    return ExportResponse.model_validate(export).model_copy(update={"download_url": download_url})


@router.post(
    "/wbs/{version_id}/exports",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_export(
    version_id: UUID,
    payload: ExportCreate,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.EXPORT_CREATE)),
    db: AsyncSession = Depends(get_db),
) -> ExportResponse:
    version = await get_tenant_wbs_version(db, context.tenant.id, version_id)
    export = ExportFile(
        tenant_id=context.tenant.id,
        project_id=version.project_id,
        wbs_version_id=version.id,
        format=payload.format,
    )
    db.add(export)
    await db.commit()
    await db.refresh(export)
    dispatch_export(background_tasks, export.id)
    return _to_response(export)


@router.get("/exports/{export_id}", response_model=ExportResponse)
async def get_export(
    export_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.EXPORT_READ)),
    db: AsyncSession = Depends(get_db),
) -> ExportResponse:
    export = await db.scalar(
        select(ExportFile).where(
            ExportFile.id == export_id,
            ExportFile.tenant_id == context.tenant.id,
        )
    )
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    return _to_response(export)


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.EXPORT_READ)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    export = await db.scalar(
        select(ExportFile).where(
            ExportFile.id == export_id,
            ExportFile.tenant_id == context.tenant.id,
        )
    )
    if export is None or export.storage_key is None or export.file_name is None:
        raise HTTPException(status_code=404, detail="Export file is not ready.")
    from app.services.storage import LocalObjectStorage

    path = LocalObjectStorage(settings).absolute_path(export.storage_key)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file is missing from storage.")
    return FileResponse(path, filename=export.file_name)


@router.get("/projects/{project_id}/exports", response_model=list[ExportResponse])
async def list_exports(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.EXPORT_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[ExportResponse]:
    await get_tenant_project(db, context.tenant.id, project_id)
    result = await db.scalars(
        select(ExportFile)
        .where(
            ExportFile.tenant_id == context.tenant.id,
            ExportFile.project_id == project_id,
        )
        .order_by(ExportFile.created_at.desc())
    )
    return [_to_response(export) for export in result]
