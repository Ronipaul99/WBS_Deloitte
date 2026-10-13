from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Document, Job, Project, WbsTemplate, WbsVersion


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
