"""Read-only workflow recovery and shared provenance helpers.

No resolver in this module dispatches work. Domain records, not a cached screen name, determine
the recoverable state. Writers use the document lock to serialize attempt creation.
"""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from prometheus_client import Counter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.permissions import Permission
from app.db.session import set_local_tenant_context
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentSummary,
    Job,
    JobType,
    Project,
    ValidationRun,
    WbsTemplate,
    WbsVersion,
)
from app.schemas.document_workflows import WorkflowState
from app.schemas.domain import DocumentResponse, JobResponse, ProjectResponse, TemplateResponse
from app.services.ingestion.release_identity import matches_release_identity

RESUME_EVENTS = Counter(
    "wbs_workflow_resumes_total", "Authoritative workflow resume stages", ["stage"]
)

ACTIVE = {"QUEUED", "IN_PROGRESS"}
STOPPED = {"FAILED", "CANCELLED"}
PIPELINE_VERSION = "wbs-generation-v1"


def digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def inconsistent() -> HTTPException:
    RESUME_EVENTS.labels("INCONSISTENT").inc()
    return HTTPException(
        409,
        detail={
            "code": "WORKFLOW_STATE_INCONSISTENT",
            "message": "The saved workflow references could not be verified.",
        },
    )


async def scoped_document(
    db: AsyncSession,
    tenant_id: UUID,
    document_id: UUID,
    *,
    lock: bool = False,
    read_lock: bool = False,
) -> Document:
    await set_local_tenant_context(db, tenant_id)
    query = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    if lock or read_lock:
        query = query.with_for_update(read=read_lock)
    document = await db.scalar(query)
    if document is None:
        raise HTTPException(404, detail="Document not found.")
    project = await db.scalar(
        select(Project).where(
            Project.id == document.project_id,
            Project.tenant_id == tenant_id,
        )
    )
    if project is None or project.status != "ACTIVE":
        raise HTTPException(404, detail="The original project is unavailable.")
    if document.lifecycle_status != "ACTIVE":
        raise HTTPException(
            410 if document.lifecycle_status == "DELETED" else 409,
            detail={
                "code": "DOCUMENT_UNAVAILABLE",
                "message": "The document is unavailable for reuse.",
            },
        )
    if document.processing_error_code in {
        "DOCUMENT_REJECTED_MALWARE",
        "DOCUMENT_INTEGRITY_FAILED",
        "DOCUMENT_OBJECT_MISSING",
    }:
        raise HTTPException(
            409,
            detail={
                "code": "DOCUMENT_UNAVAILABLE",
                "message": "The source document is unavailable for reuse.",
            },
        )
    return document


async def ensure_workflow(db: AsyncSession, document: Document) -> DocumentWorkflow:
    # Caller holds the document row lock before creating or changing an attempt.
    workflow = await db.scalar(
        select(DocumentWorkflow).where(
            DocumentWorkflow.tenant_id == document.tenant_id,
            DocumentWorkflow.document_id == document.id,
            DocumentWorkflow.is_base.is_(True),
        )
    )
    if workflow is None:
        workflow = DocumentWorkflow(
            tenant_id=document.tenant_id,
            project_id=document.project_id,
            document_id=document.id,
            is_base=True,
        )
        db.add(workflow)
        await db.flush()
    return workflow


async def load_workflow(
    db: AsyncSession, tenant_id: UUID, workflow_id: UUID, *, lock: bool = False
) -> tuple[DocumentWorkflow, Document]:
    await set_local_tenant_context(db, tenant_id)
    workflow = await db.scalar(
        select(DocumentWorkflow).where(
            DocumentWorkflow.id == workflow_id,
            DocumentWorkflow.tenant_id == tenant_id,
        )
    )
    if workflow is None:
        raise HTTPException(404, detail="Workflow not found.")
    document = await scoped_document(
        db, tenant_id, workflow.document_id, lock=lock, read_lock=not lock
    )
    if workflow.project_id != document.project_id:
        raise inconsistent()
    workflow = await db.scalar(
        select(DocumentWorkflow)
        .where(
            DocumentWorkflow.id == workflow_id,
            DocumentWorkflow.tenant_id == tenant_id,
        )
        .with_for_update(read=not lock)
        .execution_options(populate_existing=True)
    )
    if workflow is None:
        raise HTTPException(404, detail="Workflow not found.")
    return workflow, document


async def generation_inputs(
    db: AsyncSession,
    document: Document,
    summary: DocumentSummary,
    template_id: UUID | None,
    *,
    require_active: bool = True,
) -> dict:
    template = None
    if template_id:
        template = await db.scalar(
            select(WbsTemplate).where(
                WbsTemplate.id == template_id,
                WbsTemplate.tenant_id == document.tenant_id,
            )
        )
        if template is None or (require_active and not template.is_active):
            raise HTTPException(404, detail="Template not found.")
    # Snapshot mutable inputs; workers must not infer identity from the latest project rows.
    return {
        "document_id": str(document.id),
        "document_sha256": document.upload_sha256,
        "processing_run_id": str(document.current_processing_run_id),
        "summary_id": str(summary.id),
        "summary_revision": summary.revision,
        "summary_digest": digest_json(
            {
                "summary_text": summary.summary_text,
                "key_points": summary.key_points,
                "requirements": summary.requirements,
            }
        ),
        "summary_snapshot": {
            "summary_text": summary.summary_text,
            "key_points": summary.key_points,
            "requirements": summary.requirements,
        },
        "template_id": str(template_id) if template_id else None,
        "template_identity": (
            {
                "id": str(template.id),
                "updated_at": template.updated_at.isoformat(),
                "is_active": template.is_active,
                "storage_key_digest": digest_json(template.storage_key),
            }
            if template
            else {}
        ),
        "pipeline_version": PIPELINE_VERSION,
    }


async def _linked_job(
    db: AsyncSession, workflow: DocumentWorkflow, job_id: UUID | None, kind: str
) -> Job | None:
    if job_id is None:
        return None
    job = await db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.tenant_id == workflow.tenant_id,
            Job.project_id == workflow.project_id,
            Job.job_type == kind,
        )
    )
    if (
        job is None
        or job.request_payload.get("document_id") != str(workflow.document_id)
        or (
            kind == JobType.WBS_GENERATION
            and job.workflow_id is not None
            and job.workflow_id != workflow.id
        )
    ):
        raise inconsistent()
    return job


async def resume_state(
    db: AsyncSession, tenant_id: UUID, workflow_id: UUID, permissions: frozenset[Permission]
) -> WorkflowState:
    workflow, document = await load_workflow(db, tenant_id, workflow_id)
    project = await db.get(Project, workflow.project_id)
    assert project is not None
    summary = await db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.tenant_id == tenant_id,
            DocumentSummary.document_id == document.id,
        )
    )
    if workflow.summary_id and (summary is None or summary.id != workflow.summary_id):
        raise inconsistent()
    template = None
    if workflow.template_id:
        template = await db.scalar(
            select(WbsTemplate).where(
                WbsTemplate.id == workflow.template_id,
                WbsTemplate.tenant_id == tenant_id,
            )
        )
        if template is None:
            raise inconsistent()
    # Keep original run lineage for a generated workflow; otherwise observe the document's run.
    run_id = workflow.processing_run_id if workflow.generation_job_id else None
    run_query = select(DocumentProcessingRun).where(
        DocumentProcessingRun.tenant_id == tenant_id,
        DocumentProcessingRun.document_id == document.id,
        DocumentProcessingRun.project_id == document.project_id,
    )
    if run_id:
        run_query = run_query.where(DocumentProcessingRun.id == run_id)
    else:
        run_query = run_query.order_by(
            DocumentProcessingRun.created_at.desc(), DocumentProcessingRun.id.desc()
        ).limit(1)
    run = await db.scalar(run_query)
    if run_id and run is None:
        raise inconsistent()
    ingestion_compatible = bool(run and matches_release_identity(document, run, get_settings()))
    if ingestion_compatible:
        chunk_count = await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == document.id,
                DocumentChunk.processing_run_id == run.id,
            )
        )
        ingestion_compatible = chunk_count == run.chunk_count
    summary_job = await _linked_job(db, workflow, workflow.summary_job_id, JobType.DOCUMENT_SUMMARY)
    generation = await _linked_job(db, workflow, workflow.generation_job_id, JobType.WBS_GENERATION)
    version = None
    if workflow.wbs_version_id:
        version = await db.scalar(
            select(WbsVersion).where(
                WbsVersion.id == workflow.wbs_version_id,
                WbsVersion.tenant_id == tenant_id,
                WbsVersion.project_id == workflow.project_id,
            )
        )
        if (
            version is None
            or generation is None
            or version.generation_job_id != generation.id
            or (version.workflow_id is not None and version.workflow_id != workflow.id)
        ):
            raise inconsistent()
    validation = None
    if workflow.validation_id:
        validation = await db.scalar(
            select(ValidationRun).where(
                ValidationRun.id == workflow.validation_id,
                ValidationRun.tenant_id == tenant_id,
            )
        )
        if version is None or validation is None or validation.wbs_version_id != version.id:
            raise inconsistent()
    stale = bool(validation and version and validation.wbs_revision != version.revision)
    stage, screen, active_job, failed_stage = "DOCUMENT_READY", "checkpoint", None, None
    if run:
        stage, screen = "INGESTING", "doc_processing"
        if run.status == "COMPLETED":
            stage, screen = "INGESTED", "checkpoint"
        elif run.status in STOPPED:
            stage, screen, failed_stage = run.status, "checkpoint", "ingestion"
    if summary:
        stage = "SUMMARY_APPROVED" if summary.is_approved else "SUMMARY_REVIEW"
        screen = "doc_summary"
    if summary_job and summary_job.status in ACTIVE | STOPPED:
        stage = "SUMMARIZING" if summary_job.status in ACTIVE else summary_job.status
        screen, active_job = "checkpoint", summary_job
        failed_stage = "summary" if summary_job.status in STOPPED else None
    if version:
        stage, screen = "WBS_READY", "results"
    if generation and generation.status in ACTIVE | STOPPED:
        stage = "GENERATING" if generation.status in ACTIVE else generation.status
        screen = "analyzing" if generation.status in ACTIVE else "checkpoint"
        active_job = generation
        failed_stage = "generation" if generation.status in STOPPED else None
    elif generation and generation.status == "COMPLETED" and version is None:
        raise inconsistent()
    if validation and not stale and not (generation and generation.status in ACTIVE | STOPPED):
        stage = (
            "VALIDATING"
            if validation.status in ACTIVE
            else "VALIDATED"
            if validation.status == "COMPLETED"
            else validation.status
        )
        screen = "validation" if validation.status not in STOPPED else "checkpoint"
        failed_stage = "validation" if validation.status in STOPPED else None
    # A newer source-processing attempt takes precedence over an older saved summary.
    # Generated output keeps its original lineage and remains viewable as history.
    if not generation and run and (run.status != "COMPLETED" or not ingestion_compatible):
        active_job = await db.scalar(
            select(Job).where(
                Job.id == run.job_id,
                Job.tenant_id == tenant_id,
                Job.project_id == workflow.project_id,
            )
        )
        if run.status in ACTIVE:
            stage, screen, failed_stage = "INGESTING", "doc_processing", None
        elif run.status in STOPPED:
            stage, screen, failed_stage = run.status, "checkpoint", "ingestion"
        else:
            stage, screen, failed_stage = "DOCUMENT_READY", "checkpoint", None
    compatibility = "UNKNOWN"
    if summary and workflow.generation_input_fingerprint:
        inputs = await generation_inputs(
            db, document, summary, workflow.template_id, require_active=False
        )
        compatibility = (
            "CURRENT"
            if ingestion_compatible
            and summary.is_approved
            and digest_json(inputs) == workflow.generation_input_fingerprint
            else "CHANGED"
        )
    actions = []
    if Permission.DOCUMENT_PROCESS in permissions and stage == "DOCUMENT_READY":
        actions.append("start_ingestion")
    if Permission.SUMMARY_UPDATE in permissions and stage == "INGESTED":
        actions.append("start_summary")
    if Permission.WBS_GENERATE in permissions and stage == "SUMMARY_APPROVED":
        actions.append("start_generation")
    if Permission.JOB_MANAGE in permissions and failed_stage:
        actions.append("retry")
    if version and Permission.WBS_READ in permissions:
        actions.append("view_wbs")
    if version and Permission.WBS_UPDATE in permissions:
        actions.append("edit_wbs")
    if version and Permission.VALIDATION_RUN in permissions:
        actions.append("start_validation")
    RESUME_EVENTS.labels(stage).inc()
    return WorkflowState(
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        document_id=document.id,
        checkpoint_revision=workflow.checkpoint_revision,
        stage=stage,
        resume_screen=screen,
        project=ProjectResponse.model_validate(project),
        document=DocumentResponse.model_validate(document),
        template=TemplateResponse.model_validate(template) if template else None,
        processing_run_id=run.id if run else None,
        ingestion_job_id=run.job_id if run else None,
        summary_id=summary.id if summary else None,
        summary_revision=summary.revision if summary else None,
        summary_job_id=workflow.summary_job_id,
        generation_job_id=workflow.generation_job_id,
        wbs_version_id=workflow.wbs_version_id,
        validation_id=workflow.validation_id,
        validation_stale=stale,
        input_compatibility=compatibility,
        source_requires_processing=bool(
            run and run.status == "COMPLETED" and not ingestion_compatible
        ),
        job=JobResponse.model_validate(active_job) if active_job else None,
        failed_stage=failed_stage,
        allowed_actions=actions,
    )
