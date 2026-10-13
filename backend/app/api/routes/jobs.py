import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import TenantContext, require_tenant_member
from app.api.routes.helpers import get_tenant_job
from app.db.session import SessionLocal, get_db
from app.models.domain import Job, JobType, ProcessingStatus
from app.schemas.domain import JobResponse
from app.services.dispatcher import dispatch_generation, dispatch_summary

router = APIRouter(prefix="/tenants/{tenant_id}/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> Job:
    return await get_tenant_job(db, context.tenant.id, job_id)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> Job:
    job = await get_tenant_job(db, context.tenant.id, job_id)
    if job.status in {ProcessingStatus.COMPLETED, ProcessingStatus.FAILED}:
        raise HTTPException(status_code=409, detail="Completed jobs cannot be cancelled.")
    job.status = ProcessingStatus.CANCELLED
    job.current_step = "Cancelled by user"
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_tenant_member),
    db: AsyncSession = Depends(get_db),
) -> Job:
    job = await get_tenant_job(db, context.tenant.id, job_id)
    if job.status not in {ProcessingStatus.FAILED, ProcessingStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried.")
    if job.job_type not in {JobType.DOCUMENT_SUMMARY, JobType.WBS_GENERATION}:
        raise HTTPException(status_code=409, detail="This job type cannot be retried.")

    job.status = ProcessingStatus.QUEUED
    job.progress = 0
    job.current_step = "Queued for retry"
    job.error_message = None
    await db.commit()
    await db.refresh(job)

    if job.job_type == JobType.DOCUMENT_SUMMARY:
        document_id = UUID(job.request_payload["document_id"])
        dispatch_summary(background_tasks, job.id, document_id)
    elif job.job_type == JobType.WBS_GENERATION:
        dispatch_generation(background_tasks, job.id)
    return job


@router.get("/{job_id}/events")
async def job_events(
    tenant_id: UUID,
    job_id: UUID,
    context: TenantContext = Depends(require_tenant_member),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        last_signature = ""
        for _ in range(60):
            async with SessionLocal() as db:
                job = await get_tenant_job(db, context.tenant.id, job_id)
                payload = JobResponse.model_validate(job).model_dump(mode="json")
                signature = json.dumps(payload, sort_keys=True)
                if signature != last_signature:
                    yield f"event: job\ndata: {json.dumps(payload)}\n\n"
                    last_signature = signature
                if job.status in {
                    ProcessingStatus.COMPLETED,
                    ProcessingStatus.FAILED,
                    ProcessingStatus.CANCELLED,
                }:
                    return
            await asyncio.sleep(1)
        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
