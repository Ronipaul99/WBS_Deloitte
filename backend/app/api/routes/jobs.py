import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_job
from app.core.permissions import Permission
from app.db.session import SessionLocal, get_db
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Job, JobType, ProcessingStatus
from app.schemas.domain import JobResponse
from app.services.dispatcher import dispatch_generation, dispatch_summary
from app.services.document_workflow_dispatch import enqueue_dispatch, publish_dispatch
from app.services.document_workflow_resume import scoped_document
from app.services.external_summary_tracking import reject_generic_external_access

router = APIRouter(
    prefix="/tenants/{tenant_id}/jobs", tags=["jobs"], responses=TENANT_AUTH_RESPONSES
)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.JOB_READ)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    await reject_generic_external_access(db, context.tenant.id, job_id)
    return await get_tenant_job(db, context.tenant.id, job_id)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.JOB_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    await reject_generic_external_access(db, context.tenant.id, job_id)
    job = await get_tenant_job(db, context.tenant.id, job_id)
    await db.refresh(job, with_for_update=True)
    if job.job_type == JobType.DOCUMENT_INGESTION:
        raise HTTPException(
            status_code=409,
            detail="Document ingestion cancellation is not enabled.",
        )
    if job.job_type == JobType.DOCUMENT_DELETION:
        raise HTTPException(
            status_code=409,
            detail="Document deletion cancellation is not enabled.",
        )
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
    context: TenantContext = Depends(require_permission(Permission.JOB_MANAGE)),
    db: AsyncSession = Depends(get_db),
) -> Job:
    await reject_generic_external_access(db, context.tenant.id, job_id)
    job = await get_tenant_job(db, context.tenant.id, job_id)
    if job.status not in {ProcessingStatus.FAILED, ProcessingStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried.")
    if job.job_type not in {JobType.DOCUMENT_SUMMARY, JobType.WBS_GENERATION}:
        raise HTTPException(status_code=409, detail="This job type cannot be retried.")

    outbox_id = None
    if job.workflow_id:
        await scoped_document(db, context.tenant.id, UUID(job.request_payload["document_id"]),
                              lock=True)
        retried = await db.scalar(select(Job).where(
            Job.tenant_id == context.tenant.id, Job.workflow_id == job.workflow_id,
            Job.request_payload["retry_of"].as_string() == str(job.id),
        ).order_by(Job.created_at.desc()).limit(1))
        if retried:
            return retried
        workflow = await db.get(DocumentWorkflow, job.workflow_id)
        current_id = (workflow.summary_job_id if job.job_type == JobType.DOCUMENT_SUMMARY
                      else workflow.generation_job_id)
        if current_id != job.id:
            raise HTTPException(409, detail="A newer workflow attempt already exists.")
        replacement = Job(
            tenant_id=job.tenant_id, project_id=job.project_id, created_by=context.user.id,
            workflow_id=job.workflow_id, job_type=job.job_type,
            request_payload={**job.request_payload, "retry_of": str(job.id)},
            attempt_count=job.attempt_count + 1, current_step="Queued for retry",
        )
        db.add(replacement)
        await db.flush()
        if job.job_type == JobType.DOCUMENT_SUMMARY:
            workflow.summary_job_id = replacement.id
        else:
            workflow.generation_job_id = replacement.id
            # Historical output remains attached to its original attempt/workflow.
            workflow.wbs_version_id = None
            workflow.validation_id = None
        workflow.checkpoint_revision += 1
        job = replacement
        outbox_id = await enqueue_dispatch(
            db,
            workflow,
            kind="summary" if job.job_type == JobType.DOCUMENT_SUMMARY else "generation",
            job_id=job.id,
        )

    job.status = ProcessingStatus.QUEUED
    job.progress = 0
    job.current_step = "Queued for retry"
    job.error_message = None
    await db.commit()
    await db.refresh(job)

    if outbox_id:
        await publish_dispatch(context.tenant.id, outbox_id, background_tasks)
    elif job.job_type == JobType.DOCUMENT_SUMMARY:
        document_id = UUID(job.request_payload["document_id"])
        dispatch_summary(background_tasks, job.id, document_id)
    elif job.job_type == JobType.WBS_GENERATION:
        dispatch_generation(background_tasks, job.id)
    return job


@router.get("/{job_id}/events")
async def job_events(
    tenant_id: UUID,
    job_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.JOB_READ)),
) -> StreamingResponse:
    async with SessionLocal() as db:
        await reject_generic_external_access(db, context.tenant.id, job_id)

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
