from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_document
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.domain import DocumentSummary, Job, JobType
from app.schemas.domain import JobResponse, SummaryResponse, SummaryUpdate
from app.services.dispatcher import dispatch_summary

router = APIRouter(
    prefix="/tenants/{tenant_id}/documents/{document_id}/summary",
    tags=["summaries"],
    responses=TENANT_AUTH_RESPONSES,
)


async def _get_summary(db: AsyncSession, tenant_id: UUID, document_id: UUID) -> DocumentSummary:
    summary = await db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.tenant_id == tenant_id,
            DocumentSummary.document_id == document_id,
        )
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Document summary not found.")
    return summary


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_summary(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    document = await get_tenant_document(db, context.tenant.id, document_id)
    job = Job(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        created_by=context.user.id,
        job_type=JobType.DOCUMENT_SUMMARY,
        current_step="Queued for document extraction",
        request_payload={"document_id": str(document.id)},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    dispatch_summary(background_tasks, job.id, document.id)
    return job


@router.get("", response_model=SummaryResponse)
async def get_summary(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_READ)),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummary:
    await get_tenant_document(db, context.tenant.id, document_id)
    return await _get_summary(db, context.tenant.id, document_id)


@router.patch("", response_model=SummaryResponse)
async def update_summary(
    document_id: UUID,
    payload: SummaryUpdate,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_UPDATE)),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummary:
    await get_tenant_document(db, context.tenant.id, document_id)
    summary = await _get_summary(db, context.tenant.id, document_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(summary, field, value)
    summary.is_approved = False
    summary.approved_at = None
    await db.commit()
    await db.refresh(summary)
    return summary


@router.post("/approve", response_model=SummaryResponse)
async def approve_summary(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_APPROVE)),
    db: AsyncSession = Depends(get_db),
) -> DocumentSummary:
    await get_tenant_document(db, context.tenant.id, document_id)
    summary = await _get_summary(db, context.tenant.id, document_id)
    summary.is_approved = True
    summary.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(summary)
    return summary
