from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import set_local_tenant_context
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    Job,
    Project,
    WbsTemplate,
    WbsVersion,
)


async def get_tenant_project(db: AsyncSession, tenant_id: UUID, project_id: UUID) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.tenant_id == tenant_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def get_tenant_document(db: AsyncSession, tenant_id: UUID, document_id: UUID) -> Document:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


async def require_ready_active_run(
    db: AsyncSession,
    tenant_id: UUID,
    document: Document,
) -> DocumentProcessingRun:
    await set_local_tenant_context(db, tenant_id)
    if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_DELETION_IN_PROGRESS",
                "message": "The document is being deleted and cannot be processed.",
            },
        )
    run = None
    if document.current_processing_run_id is not None:
        run = await db.scalar(
            select(DocumentProcessingRun).where(
                DocumentProcessingRun.id == document.current_processing_run_id,
                DocumentProcessingRun.tenant_id == tenant_id,
                DocumentProcessingRun.project_id == document.project_id,
                DocumentProcessingRun.document_id == document.id,
                DocumentProcessingRun.status == DocumentProcessingStatus.COMPLETED.value,
            )
        )
    chunk_count = 0
    if run is not None:
        chunk_count = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.project_id == document.project_id,
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.processing_run_id == run.id,
                )
            )
            or 0
        )
    if run is None or run.chunk_count < 1 or chunk_count != run.chunk_count:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_INGESTION_REQUIRED",
                "message": "The document must have a ready ingestion run.",
            },
        )
    return run


async def get_tenant_template(db: AsyncSession, tenant_id: UUID, template_id: UUID) -> WbsTemplate:
    template = await db.scalar(
        select(WbsTemplate).where(WbsTemplate.id == template_id, WbsTemplate.tenant_id == tenant_id)
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return template


async def get_tenant_job(db: AsyncSession, tenant_id: UUID, job_id: UUID) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


async def get_tenant_wbs_version(db: AsyncSession, tenant_id: UUID, version_id: UUID) -> WbsVersion:
    version = await db.scalar(
        select(WbsVersion).where(WbsVersion.id == version_id, WbsVersion.tenant_id == tenant_id)
    )
    if version is None:
        raise HTTPException(status_code=404, detail="WBS version not found.")
    return version
