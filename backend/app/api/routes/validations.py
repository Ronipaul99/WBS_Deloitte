from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, require_tenant_member
from app.api.routes.helpers import get_tenant_wbs_version
from app.db.session import get_db
from app.models.domain import ValidationRun
from app.schemas.domain import ValidationResponse
from app.services.dispatcher import dispatch_validation

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["validation"])


@router.post(
    "/wbs/{version_id}/validations",
    response_model=ValidationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_validation(
    version_id: UUID,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> ValidationRun:
    await get_tenant_wbs_version(db, context.tenant.id, version_id)
    validation = ValidationRun(tenant_id=context.tenant.id, wbs_version_id=version_id)
    db.add(validation)
    await db.commit()
    await db.refresh(validation)
    dispatch_validation(background_tasks, validation.id)
    return validation


@router.get("/validations/{validation_id}", response_model=ValidationResponse)
async def get_validation(
    validation_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> ValidationRun:
    validation = await db.scalar(
        select(ValidationRun).where(
            ValidationRun.id == validation_id,
            ValidationRun.tenant_id == context.tenant.id,
        )
    )
    if validation is None:
        raise HTTPException(status_code=404, detail="Validation result not found.")
    return validation
