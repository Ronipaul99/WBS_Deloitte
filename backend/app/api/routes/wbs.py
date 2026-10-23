from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_project, get_tenant_wbs_version
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import WbsVersion
from app.schemas.domain import WbsVersionResponse, WbsVersionUpdate

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["wbs"], responses=TENANT_AUTH_RESPONSES)


@router.get("/projects/{project_id}/wbs/latest", response_model=WbsVersionResponse)
async def latest_wbs(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.WBS_READ)),
    db: AsyncSession = Depends(get_db),
) -> WbsVersion:
    await get_tenant_project(db, context.tenant.id, project_id)
    version = await db.scalar(
        select(WbsVersion)
        .where(WbsVersion.tenant_id == context.tenant.id, WbsVersion.project_id == project_id)
        .order_by(WbsVersion.version_number.desc())
        .limit(1)
    )
    if version is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="No WBS version exists for this project.")
    return version


@router.get("/projects/{project_id}/wbs/versions", response_model=list[WbsVersionResponse])
async def list_wbs_versions(
    project_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.WBS_READ)),
    db: AsyncSession = Depends(get_db),
) -> list[WbsVersion]:
    await get_tenant_project(db, context.tenant.id, project_id)
    result = await db.scalars(
        select(WbsVersion)
        .where(WbsVersion.tenant_id == context.tenant.id, WbsVersion.project_id == project_id)
        .order_by(WbsVersion.version_number.desc())
    )
    return list(result)


@router.put("/wbs/{version_id}", response_model=WbsVersionResponse)
async def update_wbs(
    version_id: UUID,
    payload: WbsVersionUpdate,
    context: TenantContext = Depends(require_permission(Permission.WBS_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> WbsVersion:
    version = await get_tenant_wbs_version(db, context.tenant.id, version_id)
    version.tree = payload.tree
    if payload.scope_coverage is not None:
        version.scope_coverage = payload.scope_coverage
    await db.commit()
    await db.refresh(version)
    return version
