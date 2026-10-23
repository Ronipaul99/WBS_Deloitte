from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_document, get_tenant_project, get_tenant_template
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import DocumentSummary, Job, JobType
from app.schemas.domain import GenerationCreate, JobResponse
from app.services.dispatcher import dispatch_generation

router = APIRouter(
    prefix="/tenants/{tenant_id}/projects/{project_id}/generations",
    tags=["generation"],
    responses=TENANT_AUTH_RESPONSES,
)


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    project_id: UUID,
    payload: GenerationCreate,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.WBS_GENERATE)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    await get_tenant_project(db, context.tenant.id, project_id)
    document = await get_tenant_document(db, context.tenant.id, payload.document_id)
    if payload.template_id is not None:
        await get_tenant_template(db, context.tenant.id, payload.template_id)
    summary = await db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.id == payload.summary_id,
            DocumentSummary.tenant_id == context.tenant.id,
        )
    )
    if document.project_id != project_id:
        raise HTTPException(status_code=400, detail="Document does not belong to this project.")
    if summary is None:
        raise HTTPException(status_code=404, detail="Approved summary not found.")
    if summary.document_id != document.id or not summary.is_approved:
        raise HTTPException(status_code=409, detail="The document summary must be approved first.")

    job = Job(
        tenant_id=context.tenant.id,
        project_id=project_id,
        created_by=context.user.id,
        job_type=JobType.WBS_GENERATION,
        current_step="Queued for WBS generation",
        request_payload={
            "document_id": str(payload.document_id),
            "template_id": str(payload.template_id) if payload.template_id else None,
            "summary_id": str(payload.summary_id),
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    dispatch_generation(background_tasks, job.id)
    return job
