from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_project, get_tenant_wbs_version
from app.core.permissions import Permission
from app.db.session import get_db, set_local_tenant_context
from app.models.document_workflows import DocumentWorkflow
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


@router.get("/wbs/{version_id}", response_model=WbsVersionResponse)
async def get_wbs_version(
    version_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.WBS_READ)),
    db: AsyncSession = Depends(get_db),
) -> WbsVersion:
    return await get_tenant_wbs_version(db, context.tenant.id, version_id)


@router.put("/wbs/{version_id}", response_model=WbsVersionResponse)
async def update_wbs(
    version_id: UUID,
    payload: WbsVersionUpdate,
    context: TenantContext = Depends(require_permission(Permission.WBS_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> WbsVersion:
    version = await get_tenant_wbs_version(db, context.tenant.id, version_id)
    await db.refresh(version, with_for_update=True)
    version.tree = payload.tree
    version.revision += 1
    if payload.scope_coverage is not None:
        version.scope_coverage = payload.scope_coverage
    if version.workflow_id:
        await set_local_tenant_context(db, context.tenant.id)
        await db.execute(update(DocumentWorkflow).where(
            DocumentWorkflow.id == version.workflow_id,
            DocumentWorkflow.tenant_id == context.tenant.id,
        ).values(checkpoint_revision=DocumentWorkflow.checkpoint_revision + 1))
    await db.commit()
    await db.refresh(version)
    return version
