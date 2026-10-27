from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import TENANT_AUTH_RESPONSES, require_permission
from app.api.dependencies import (
    TenantContext,
    ensure_document_ingestion_ready,
)
from app.core.config import Settings, get_settings
from app.core.permissions import Permission
from app.db.session import get_db, set_local_tenant_context
from app.models.domain import (
    ACTIVE_DOCUMENT_PROCESSING_STATUSES,
    DispatchStatus,
    Document,
    DocumentKind,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    IngestionStage,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
    Project,
    ProjectStatus,
)
from app.schemas.domain import IngestionStatusResponse, JobResponse
from app.services.dispatcher import INGESTION_TASK_NAME, publish_ingestion_dispatch
from app.services.ingestion.chunk_types import ChunkWarningCode
from app.services.ingestion.release_identity import (
    RELEASE_CHUNKER_VERSION,
    release_extractor_identity,
)
from app.services.ingestion.types import ExtractionWarningCode, confirmed_format_from_suffix

SAFE_WARNING_CODES = frozenset(code.value for code in (*ExtractionWarningCode, *ChunkWarningCode))

router = APIRouter(
    prefix="/tenants/{tenant_id}/documents/{document_id}/ingestions",
    tags=["document-ingestion"],
    responses=TENANT_AUTH_RESPONSES,
)


def _matches_release_identity(
    document: Document,
    run: DocumentProcessingRun,
    settings: Settings,
) -> bool:
    try:
        confirmed_format = confirmed_format_from_suffix(
            PurePosixPath(document.storage_key).suffix.casefold()
        )
        extractor_name, extractor_version = release_extractor_identity(confirmed_format)
    except ValueError:
        return False
    return all(
        (
            document.current_processing_run_id == run.id,
            document.content_sha256 is not None,
            document.content_sha256 == run.document_content_sha256,
            run.status == DocumentProcessingStatus.COMPLETED.value,
            run.chunk_count > 0,
            run.extractor_name == extractor_name,
            run.extractor_version == extractor_version,
            run.chunker_version == RELEASE_CHUNKER_VERSION,
            run.embedding_provider == settings.embedding_provider,
            run.embedding_model == settings.embedding_model,
            run.embedding_model_revision == settings.embedding_model_revision,
            run.embedding_dimensions == settings.embedding_dimensions,
            run.embedding_formatting_version == settings.embedding_formatting_version,
        )
    )


async def _scoped_document_for_update(
    db: AsyncSession,
    context: TenantContext,
    document_id: UUID,
) -> Document:
    await set_local_tenant_context(db, context.tenant.id)
    document = await db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.tenant_id == context.tenant.id,
            Document.kind == DocumentKind.PROJECT.value,
            Document.lifecycle_status == DocumentLifecycleStatus.ACTIVE.value,
        )
        .with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    project = await db.scalar(
        select(Project).where(
            Project.id == document.project_id,
            Project.tenant_id == context.tenant.id,
            Project.status == ProjectStatus.ACTIVE.value,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_ingestion(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_PROCESS)),
    _: None = Depends(ensure_document_ingestion_ready),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Job:
    document = await _scoped_document_for_update(db, context, document_id)
    active_run = await db.scalar(
        select(DocumentProcessingRun)
        .where(
            DocumentProcessingRun.tenant_id == context.tenant.id,
            DocumentProcessingRun.project_id == document.project_id,
            DocumentProcessingRun.document_id == document.id,
            DocumentProcessingRun.status.in_(ACTIVE_DOCUMENT_PROCESSING_STATUSES),
        )
        .with_for_update()
    )
    if active_run is not None:
        existing_job = await db.scalar(
            select(Job).where(
                Job.id == active_run.job_id,
                Job.tenant_id == context.tenant.id,
                Job.project_id == document.project_id,
                Job.job_type == JobType.DOCUMENT_INGESTION.value,
            )
        )
        if existing_job is None:
            raise HTTPException(status_code=409, detail="Document ingestion state is inconsistent.")
        return existing_job

    if document.current_processing_run_id is not None:
        completed_run = await db.scalar(
            select(DocumentProcessingRun).where(
                DocumentProcessingRun.id == document.current_processing_run_id,
                DocumentProcessingRun.tenant_id == context.tenant.id,
                DocumentProcessingRun.project_id == document.project_id,
                DocumentProcessingRun.document_id == document.id,
            )
        )
        if completed_run is not None and _matches_release_identity(
            document, completed_run, settings
        ):
            completed_job = await db.scalar(
                select(Job).where(
                    Job.id == completed_run.job_id,
                    Job.tenant_id == context.tenant.id,
                    Job.project_id == document.project_id,
                    Job.job_type == JobType.DOCUMENT_INGESTION.value,
                )
            )
            if completed_job is not None:
                return completed_job

    now = datetime.now(UTC)
    job = Job(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        created_by=context.user.id,
        job_type=JobType.DOCUMENT_INGESTION.value,
        status=ProcessingStatus.QUEUED.value,
        progress=0,
        current_step=IngestionStage.QUEUED.value,
        request_payload={"document_id": str(document.id)},
        result_payload={},
    )
    db.add(job)
    await db.flush()
    run = DocumentProcessingRun(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        document_id=document.id,
        job_id=job.id,
        status=DocumentProcessingStatus.QUEUED.value,
        current_stage=IngestionStage.QUEUED.value,
        page_count=0,
        worksheet_count=0,
        block_count=0,
        chunk_count=0,
        warning_codes=[],
    )
    db.add(run)
    await db.flush()
    outbox = JobDispatchOutbox(
        tenant_id=context.tenant.id,
        project_id=document.project_id,
        document_id=document.id,
        job_id=job.id,
        processing_run_id=run.id,
        task_name=INGESTION_TASK_NAME,
        status=DispatchStatus.PENDING.value,
        attempt_count=0,
        available_at=now,
    )
    db.add(outbox)
    document.processing_status = DocumentProcessingStatus.QUEUED.value
    document.processing_error_code = None
    await db.commit()
    await db.refresh(job)
    await publish_ingestion_dispatch(context.tenant.id, outbox.id)
    return job


@router.get("/current", response_model=IngestionStatusResponse)
async def get_current_ingestion(
    document_id: UUID,
    context: TenantContext = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IngestionStatusResponse:
    document = await _scoped_document_for_update(db, context, document_id)
    run = await db.scalar(
        select(DocumentProcessingRun)
        .where(
            DocumentProcessingRun.tenant_id == context.tenant.id,
            DocumentProcessingRun.project_id == document.project_id,
            DocumentProcessingRun.document_id == document.id,
        )
        .order_by(DocumentProcessingRun.created_at.desc(), DocumentProcessingRun.id.desc())
        .limit(1)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Document ingestion not found.")
    job = await db.scalar(
        select(Job).where(
            Job.id == run.job_id,
            Job.tenant_id == context.tenant.id,
            Job.project_id == document.project_id,
            Job.job_type == JobType.DOCUMENT_INGESTION.value,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Document ingestion not found.")
    return IngestionStatusResponse(
        job_id=job.id,
        processing_run_id=run.id,
        document_id=document.id,
        status=run.status,
        stage=run.current_stage or IngestionStage.QUEUED.value,
        progress=job.progress,
        attempt_count=run.attempt_count,
        maximum_attempts=settings.document_ingestion_max_attempts,
        page_count=run.page_count,
        worksheet_count=run.worksheet_count,
        block_count=run.block_count,
        chunk_count=run.chunk_count,
        extractor_name=run.extractor_name,
        extractor_version=run.extractor_version,
        embedding_provider=run.embedding_provider,
        embedding_model=run.embedding_model,
        embedding_model_revision=run.embedding_model_revision,
        warning_codes=[code for code in run.warning_codes if code in SAFE_WARNING_CODES],
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
