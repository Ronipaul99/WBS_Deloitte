from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_wbs_version
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db, set_local_tenant_context
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import ValidationRun
from app.schemas.domain import ValidationResponse
from app.services.dispatcher import dispatch_validation
from app.services.document_workflow_dispatch import enqueue_dispatch, publish_dispatch

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["validation"], responses=TENANT_AUTH_RESPONSES
)


@router.post(
    "/wbs/{version_id}/validations",
    response_model=ValidationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_validation(
    version_id: UUID,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.VALIDATION_RUN)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    rerun: bool = False,
) -> ValidationRun:
    version = await get_tenant_wbs_version(db, context.tenant.id, version_id)
    workflow = None
    if settings.document_workflow_resume_enabled:
        from app.models.domain import WbsVersion

        version = await db.scalar(select(WbsVersion).where(
            WbsVersion.id == version_id, WbsVersion.tenant_id == context.tenant.id,
        ).with_for_update())
        previous = await db.scalar(
            select(ValidationRun)
            .where(
                ValidationRun.tenant_id == context.tenant.id,
                ValidationRun.wbs_version_id == version_id,
                ValidationRun.wbs_revision == version.revision,
            )
            .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc())
            .limit(1)
        )
        if previous and (not rerun or previous.status in {"QUEUED", "IN_PROGRESS"}):
            return previous
        if version.workflow_id:
            await set_local_tenant_context(db, context.tenant.id)
            workflow = await db.get(DocumentWorkflow, version.workflow_id)
    validation = ValidationRun(
        tenant_id=context.tenant.id,
        wbs_version_id=version_id,
        wbs_revision=version.revision,
        wbs_snapshot={"tree": version.tree, "scope_coverage": version.scope_coverage},
    )
    db.add(validation)
    outbox_id = None
    if workflow:
        await db.flush()
        workflow.validation_id = validation.id
        workflow.checkpoint_revision += 1
        outbox_id = await enqueue_dispatch(db, workflow, kind="validation", validation=validation)
    await db.commit()
    await db.refresh(validation)
    if outbox_id:
        await publish_dispatch(context.tenant.id, outbox_id, background_tasks)
    else:
        dispatch_validation(background_tasks, validation.id)
    return validation


@router.get("/validations/{validation_id}", response_model=ValidationResponse)
async def get_validation(
    validation_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.VALIDATION_READ)),
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
