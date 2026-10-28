import hashlib
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import TenantContext
from app.api.routes.helpers import (
    get_tenant_document,
    get_tenant_project,
    get_tenant_template,
    require_ready_active_run,
)
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db
from app.models.document_workflows import DocumentWorkflow, WorkflowRequestKey
from app.models.domain import DocumentSummary, Job, JobType
from app.schemas.domain import GenerationCreate, JobResponse
from app.services.dispatcher import dispatch_generation
from app.services.document_content import conflict, insert_for
from app.services.document_workflow_dispatch import enqueue_dispatch, publish_dispatch
from app.services.document_workflow_resume import (
    digest_json,
    ensure_workflow,
    generation_inputs,
    load_workflow,
    scoped_document,
)

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
    settings: Settings = Depends(get_settings),
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
    await require_ready_active_run(db, context.tenant.id, document)
    if summary is None:
        raise HTTPException(status_code=404, detail="Approved summary not found.")
    if summary.source_request_id is not None:
        raise HTTPException(
            409,
            detail="Structured review and a supported requirements register "
            "are required before WBS generation.",
        )
    if summary.document_id != document.id or not summary.is_approved:
        raise HTTPException(status_code=409, detail="The document summary must be approved first.")

    workflow = None
    inputs = None
    regeneration_request = None
    if settings.document_workflow_resume_enabled:
        document = await scoped_document(db, context.tenant.id, document.id, lock=True)
        await db.refresh(summary)
        if not summary.is_approved:
            raise HTTPException(409, detail="The document summary must be approved first.")
        if payload.workflow_id:
            workflow, owned = await load_workflow(db, context.tenant.id, payload.workflow_id)
            if owned.id != document.id:
                raise HTTPException(409, detail="Workflow does not belong to this document.")
        else:
            workflow = await ensure_workflow(db, document)
        if payload.regenerate:
            if payload.request_key is None:
                raise HTTPException(422, detail="A request key is required for regeneration.")
            key_digest = hashlib.sha256(
                ("generation:" + str(payload.request_key)).encode()
            ).hexdigest()
            request_digest = digest_json(payload.model_dump(mode="json", exclude={"request_key"}))
            await db.execute(insert_for(db, WorkflowRequestKey).values(
                tenant_id=context.tenant.id, user_id=context.user.id, key_digest=key_digest,
                request_digest=request_digest,
            ).on_conflict_do_nothing())
            regeneration_request = await db.get(WorkflowRequestKey, (
                context.tenant.id, context.user.id, key_digest,
            ))
            if regeneration_request.request_digest != request_digest:
                raise conflict("IDEMPOTENCY_KEY_REUSED", "The generation request key was reused.")
            if regeneration_request.result_workflow_id:
                previous_workflow = await db.get(
                    DocumentWorkflow, regeneration_request.result_workflow_id
                )
                if previous_workflow and previous_workflow.generation_job_id:
                    return await db.get(Job, previous_workflow.generation_job_id)
        if (payload.expected_revision is not None
                and payload.expected_revision != workflow.checkpoint_revision):
            raise conflict("WORKFLOW_CHANGED", "The saved workflow changed. Refresh first.")
        inputs = await generation_inputs(db, document, summary, payload.template_id)
        fingerprint = digest_json(inputs)
        if workflow.generation_job_id:
            previous = await db.get(Job, workflow.generation_job_id)
            if previous is None:
                raise conflict("WORKFLOW_STATE_INCONSISTENT", "Generation history is unavailable.")
            if previous.status in {"QUEUED", "IN_PROGRESS"}:
                return previous
            if not payload.regenerate:
                if workflow.generation_input_fingerprint != fingerprint:
                    raise conflict(
                        "GENERATION_INPUTS_CHANGED",
                        "The inputs changed. Start a new generation workflow explicitly.",
                    )
                return previous
            workflow = DocumentWorkflow(
                tenant_id=document.tenant_id, project_id=document.project_id,
                document_id=document.id, template_id=payload.template_id,
            )
            db.add(workflow)
            await db.flush()

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
    outbox_id = None
    if workflow and inputs:
        await db.flush()
        job.workflow_id = workflow.id
        job.request_payload = {**job.request_payload, "input_snapshot": inputs}
        workflow.generation_job_id = job.id
        workflow.processing_run_id = document.current_processing_run_id
        workflow.summary_id = summary.id
        workflow.summary_revision = summary.revision
        workflow.template_id = payload.template_id
        workflow.template_identity = inputs["template_identity"]
        workflow.generation_input_fingerprint = digest_json(inputs)
        workflow.checkpoint_revision += 1
        outbox_id = await enqueue_dispatch(db, workflow, kind="generation", job_id=job.id)
        if regeneration_request:
            regeneration_request.result_workflow_id = workflow.id
    await db.commit()
    await db.refresh(job)
    if outbox_id:
        await publish_dispatch(context.tenant.id, outbox_id, background_tasks)
    else:
        dispatch_generation(background_tasks, job.id)
    return job
