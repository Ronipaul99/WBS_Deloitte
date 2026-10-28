from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import get_tenant_document, require_ready_active_run
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import DocumentSummary, Job, JobType
from app.schemas.domain import JobResponse, SummaryResponse, SummaryUpdate
from app.schemas.external_summary import ExternalSubmissionResponse
from app.schemas.external_summary_result import (
    StructuredSummaryApproval,
    StructuredSummaryPatch,
    StructuredSummaryResponse,
)
from app.schemas.external_summary_tracking import ExternalSummaryStatus
from app.services.dispatcher import dispatch_summary
from app.services.document_workflow_dispatch import enqueue_dispatch, publish_dispatch
from app.services.document_workflow_resume import ensure_workflow, load_workflow, scoped_document
from app.services.external_summary_review import (
    advance_workflows,
    check_revision,
    lock_review,
    patch_structured,
    read_structured,
    revalidate_review_authorization,
)
from app.services.external_summary_submission import create_submission, publish_submission


class SummaryRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def sanitized(request):
            try:
                return await original(request)
            except RequestValidationError:
                if request.method != "PATCH" and not request.url.path.endswith("/approve"):
                    raise
                # Never echo draft content or forbidden metadata through 422 input fields.
                raise HTTPException(
                    422, detail="Invalid summary request fields or bounds."
                ) from None

        return sanitized


router = APIRouter(
    prefix="/tenants/{tenant_id}/documents/{document_id}/summary",
    tags=["summaries"],
    route_class=SummaryRoute,
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


@router.post(
    "",
    response_model=JobResponse | ExternalSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_summary(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_UPDATE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    workflow_id: UUID | None = None,
    idempotency_key: str | None = Header(default=None),
) -> Job | ExternalSubmissionResponse:
    if settings.external_summary_enabled:
        result = await create_submission(
            db, context, document_id, workflow_id, idempotency_key, settings
        )
        await publish_submission(context.tenant.id, result.request_id, background_tasks, settings)
        return result
    document = await get_tenant_document(db, context.tenant.id, document_id)
    workflow = None
    if settings.document_workflow_resume_enabled:
        document = await scoped_document(db, context.tenant.id, document_id, lock=True)
        if workflow_id:
            workflow, owned = await load_workflow(db, context.tenant.id, workflow_id)
            if owned.id != document.id:
                raise HTTPException(409, detail="Workflow does not belong to this document.")
        else:
            workflow = await ensure_workflow(db, document)
        previous = await db.scalar(select(Job).where(
            Job.tenant_id == context.tenant.id, Job.job_type == JobType.DOCUMENT_SUMMARY,
            Job.request_payload["document_id"].as_string() == str(document.id),
        ).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
        if previous is not None:
            if previous.workflow_id is None:
                previous.workflow_id = workflow.id
            workflow.summary_job_id = previous.id
            await db.commit()
            return previous
    await require_ready_active_run(db, context.tenant.id, document)
    job = Job(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        created_by=context.user.id,
        job_type=JobType.DOCUMENT_SUMMARY,
        current_step="Queued for summary generation",
        request_payload={"document_id": str(document.id)},
    )
    db.add(job)
    outbox_id = None
    if workflow:
        await db.flush()
        job.workflow_id = workflow.id
        workflow.summary_job_id = job.id
        workflow.checkpoint_revision += 1
        outbox_id = await enqueue_dispatch(db, workflow, kind="summary", job_id=job.id)
    await db.commit()
    await db.refresh(job)
    if outbox_id:
        await publish_dispatch(context.tenant.id, outbox_id, background_tasks)
    else:
        dispatch_summary(background_tasks, job.id, document.id)
    return job


@router.get("", response_model=StructuredSummaryResponse | SummaryResponse)
async def get_summary(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_READ)),
    db: AsyncSession = Depends(get_db),
) -> SummaryResponse | StructuredSummaryResponse:
    await get_tenant_document(db, context.tenant.id, document_id)
    summary = await _get_summary(db, context.tenant.id, document_id)
    if summary.source_request_id is None:
        return SummaryResponse.model_validate(summary)
    return await read_structured(db, context.tenant.id, document_id, summary)


@router.get("/requests/{request_id}", response_model=ExternalSummaryStatus)
async def external_summary_status(
    document_id: UUID,
    request_id: UUID,
    workflow_id: UUID | None = None,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_READ)),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.exc import SQLAlchemyError

    from app.services.external_summary_tracking import read_status

    try:
        result = await read_status(
            db,
            context.tenant.id,
            document_id,
            request_id,
            context.permissions,
            workflow_id=workflow_id,
            bind=True,
        )
        await db.commit()
        return result
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(503, detail="Summary status is temporarily unavailable.") from None


class LegacySummaryUpdate(SummaryUpdate):
    model_config = ConfigDict(extra="forbid")


@router.patch("", response_model=StructuredSummaryResponse | SummaryResponse)
async def update_summary(
    document_id: UUID,
    payload: StructuredSummaryPatch | LegacySummaryUpdate,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_UPDATE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SummaryResponse | StructuredSummaryResponse:
    summary, workflows = await lock_review(db, context.tenant.id, document_id)
    if isinstance(payload, StructuredSummaryPatch):
        await revalidate_review_authorization(db, context, Permission.SUMMARY_UPDATE)
        if summary.source_request_id is None:
            raise HTTPException(409, detail="This is a legacy summary.")
        response = await patch_structured(
            db, context.tenant.id, document_id, summary, workflows, payload
        )
        await db.commit()
        return response
    if summary.source_request_id is not None:
        raise HTTPException(409, detail="Use the structured summary edit contract.")
    if payload.model_dump(exclude_unset=True):
        summary.revision += 1
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(summary, field, value)
    summary.is_approved = False
    summary.approved_at = None
    if settings.document_workflow_resume_enabled:
        await db.execute(
            update(DocumentWorkflow)
            .where(
                DocumentWorkflow.tenant_id == context.tenant.id,
                DocumentWorkflow.document_id == document_id,
            )
            .values(checkpoint_revision=DocumentWorkflow.checkpoint_revision + 1)
        )
    await db.commit()
    await db.refresh(summary)
    return SummaryResponse.model_validate(summary)


@router.post("/approve", response_model=StructuredSummaryResponse | SummaryResponse)
async def approve_summary(
    document_id: UUID,
    payload: StructuredSummaryApproval | None = None,
    context: TenantContext = Depends(require_permission(Permission.SUMMARY_APPROVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SummaryResponse | StructuredSummaryResponse:
    summary, workflows = await lock_review(db, context.tenant.id, document_id)
    if summary.source_request_id is not None:
        await revalidate_review_authorization(db, context, Permission.SUMMARY_APPROVE)
        if payload is None:
            raise HTTPException(409, detail="Structured approval requires an expected revision.")
        check_revision(summary, payload.expected_revision)
        response = await read_structured(db, context.tenant.id, document_id, summary)
        if not summary.is_approved:
            summary.is_approved, summary.approved_at = True, datetime.now(UTC)
            advance_workflows(workflows, response)
            await db.flush()
            await db.refresh(summary)
            response = await read_structured(db, context.tenant.id, document_id, summary)
        await db.commit()
        return response
    if payload is not None:
        raise HTTPException(409, detail="This is a legacy summary.")
    summary.is_approved = True
    summary.approved_at = datetime.now(UTC)
    if settings.document_workflow_resume_enabled:
        await db.execute(
            update(DocumentWorkflow)
            .where(
                DocumentWorkflow.tenant_id == context.tenant.id,
                DocumentWorkflow.document_id == document_id,
            )
            .values(checkpoint_revision=DocumentWorkflow.checkpoint_revision + 1)
        )
    await db.commit()
    await db.refresh(summary)
    return SummaryResponse.model_validate(summary)
