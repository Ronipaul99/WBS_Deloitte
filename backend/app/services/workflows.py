import csv
import json
from datetime import UTC, datetime
from io import StringIO
from typing import Any
from uuid import UUID
from xml.etree import ElementTree

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import (
    Document,
    DocumentSummary,
    ExportFile,
    Job,
    ProcessingStatus,
    Project,
    ValidationRun,
    WbsVersion,
)
from app.services.storage import LocalObjectStorage


async def _set_job(
    job: Job,
    *,
    status: ProcessingStatus,
    progress: int,
    step: str,
    result_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.progress = progress
    job.current_step = step
    job.error_message = error_message
    if result_payload is not None:
        job.result_payload = result_payload


async def process_document_summary(job_id: UUID, document_id: UUID) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != ProcessingStatus.QUEUED:
            return
        document = await db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == job.tenant_id,
            )
        )
        if document is None:
            return
        try:
            await _set_job(
                job,
                status=ProcessingStatus.IN_PROGRESS,
                progress=20,
                step="Extracting project document",
            )
            await db.commit()

            summary = await db.scalar(
                select(DocumentSummary).where(
                    DocumentSummary.document_id == document.id,
                    DocumentSummary.tenant_id == job.tenant_id,
                )
            )
            await db.refresh(job, with_for_update=True)
            if job.status != ProcessingStatus.IN_PROGRESS:
                await db.rollback()
                return
            if summary is None:
                summary = DocumentSummary(tenant_id=document.tenant_id, document_id=document.id)
                db.add(summary)
            else:
                summary.revision += 1

            summary.summary_text = (
                f"Placeholder summary for {document.file_name}. Replace the summary processor "
                "with the selected document extraction and LLM implementation."
            )
            summary.key_points = [
                "Project scope document uploaded successfully",
                "Document extraction integration is ready to be connected",
                "Review and approve this summary before WBS generation",
            ]
            summary.requirements = [
                {
                    "id": "REQ-001",
                    "title": "Example extracted requirement",
                    "source": document.file_name,
                    "status": "REVIEW_REQUIRED",
                }
            ]
            summary.is_approved = False
            summary.approved_at = None
            await db.flush()

            if job.workflow_id:
                await set_local_tenant_context(db, job.tenant_id)
                workflow = await db.get(DocumentWorkflow, job.workflow_id)
                if workflow is None or workflow.summary_job_id != job.id:
                    raise RuntimeError("Summary attempt was superseded")
                workflow.summary_id = summary.id
                workflow.summary_revision = summary.revision
                workflow.checkpoint_revision += 1

            await _set_job(
                job,
                status=ProcessingStatus.COMPLETED,
                progress=100,
                step="Summary ready for review",
                result_payload={"summary_id": str(summary.id)},
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            job = await db.get(Job, job_id)
            if job is not None:
                await _set_job(
                    job,
                    status=ProcessingStatus.FAILED,
                    progress=100,
                    step="Summary generation failed",
                    error_message=str(exc),
                )
                await db.commit()
            raise


async def process_wbs_generation(job_id: UUID) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.project_id is None or job.status != ProcessingStatus.QUEUED:
            return
        project = await db.scalar(
            select(Project).where(
                Project.id == job.project_id,
                Project.tenant_id == job.tenant_id,
            )
        )
        if project is None:
            return
        try:
            await _set_job(
                job,
                status=ProcessingStatus.IN_PROGRESS,
                progress=35,
                step="Mapping approved requirements to template",
            )
            await db.commit()

            await db.refresh(project, with_for_update=True)
            await db.refresh(job, with_for_update=True)
            if job.status != ProcessingStatus.IN_PROGRESS:
                await db.rollback()
                return

            last_version = await db.scalar(
                select(func.max(WbsVersion.version_number)).where(
                    WbsVersion.tenant_id == job.tenant_id,
                    WbsVersion.project_id == project.id,
                )
            )
            version = WbsVersion(
                tenant_id=job.tenant_id,
                project_id=project.id,
                generation_job_id=job.id,
                workflow_id=job.workflow_id,
                version_number=(last_version or 0) + 1,
                tree=[
                    {
                        "id": "phase-1",
                        "code": "1.0",
                        "name": project.name,
                        "type": "Phase",
                        "parent": "Root",
                        "description": "Generated WBS placeholder root",
                        "children": [
                            {
                                "id": "package-1",
                                "code": "1.1",
                                "name": "Review approved project requirements",
                                "type": "Work Package",
                                "parent": "phase-1",
                                "description": "Replace with AI-generated work packages",
                                "children": [],
                            }
                        ],
                    }
                ],
                scope_coverage={
                    "overallScore": 0,
                    "totalRequirements": 1,
                    "mappedCount": 0,
                    "gapCount": 1,
                },
            )
            db.add(version)
            await db.flush()
            if job.workflow_id:
                await set_local_tenant_context(db, job.tenant_id)
                workflow = await db.get(DocumentWorkflow, job.workflow_id)
                if workflow is None or workflow.generation_job_id != job.id:
                    raise RuntimeError("Generation attempt was superseded")
                workflow.wbs_version_id = version.id
                workflow.checkpoint_revision += 1
            await _set_job(
                job,
                status=ProcessingStatus.COMPLETED,
                progress=100,
                step="Draft WBS generated",
                result_payload={"wbs_version_id": str(version.id)},
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            job = await db.get(Job, job_id)
            if job is not None:
                await _set_job(
                    job,
                    status=ProcessingStatus.FAILED,
                    progress=100,
                    step="WBS generation failed",
                    error_message=str(exc),
                )
                await db.commit()
            raise


def _flatten_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(_flatten_tree(node.get("children", [])))
    return flattened


async def process_validation(validation_id: UUID) -> None:
    async with SessionLocal() as db:
        validation = await db.scalar(select(ValidationRun).where(
            ValidationRun.id == validation_id,
        ).with_for_update())
        if validation is None or validation.status != ProcessingStatus.QUEUED:
            return
        version = await db.scalar(
            select(WbsVersion).where(
                WbsVersion.id == validation.wbs_version_id,
                WbsVersion.tenant_id == validation.tenant_id,
            )
        )
        if version is None:
            return

        snapshot = validation.wbs_snapshot
        nodes = _flatten_tree(snapshot["tree"] if snapshot is not None else version.tree)
        codes = [str(node.get("code", "")) for node in nodes]
        duplicate_codes = sorted({code for code in codes if code and codes.count(code) > 1})
        blank_names = [node.get("id") for node in nodes if not str(node.get("name", "")).strip()]
        validation.result = {
            "summary": {
                "wbsItems": len(nodes),
                "duplicateCodes": len(duplicate_codes),
                "blankNames": len(blank_names),
            },
            "checks": [
                {
                    "code": "UNIQUE_WBS_CODES",
                    "status": "PASSED" if not duplicate_codes else "FAILED",
                    "details": duplicate_codes,
                },
                {
                    "code": "NON_EMPTY_NAMES",
                    "status": "PASSED" if not blank_names else "FAILED",
                    "details": blank_names,
                },
            ],
            "scopeCoverage": snapshot["scope_coverage"]
            if snapshot is not None
            else version.scope_coverage,
        }
        validation.status = ProcessingStatus.COMPLETED
        if version.workflow_id:
            await set_local_tenant_context(db, validation.tenant_id)
            workflow = await db.get(DocumentWorkflow, version.workflow_id)
            if workflow and workflow.validation_id == validation.id:
                workflow.checkpoint_revision += 1
        await db.commit()


async def process_export(export_id: UUID) -> None:
    settings = get_settings()
    storage = LocalObjectStorage(settings)
    async with SessionLocal() as db:
        export = await db.get(ExportFile, export_id)
        if export is None:
            return
        version = await db.scalar(
            select(WbsVersion).where(
                WbsVersion.id == export.wbs_version_id,
                WbsVersion.tenant_id == export.tenant_id,
            )
        )
        if version is None:
            return

        target_dir = storage.root / str(export.tenant_id) / "exports" / str(export.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"wbs-v{version.version_number}.{export.format.replace('p6_xml', 'xml')}"
        target = target_dir / file_name

        if export.format == "json":
            target.write_text(json.dumps(version.tree, indent=2), encoding="utf-8")
        elif export.format == "csv":
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(["code", "name", "type", "parent", "description"])
            for node in _flatten_tree(version.tree):
                writer.writerow(
                    [
                        node.get("code", ""),
                        node.get("name", ""),
                        node.get("type", ""),
                        node.get("parent", ""),
                        node.get("description", ""),
                    ]
                )
            target.write_text(stream.getvalue(), encoding="utf-8-sig")
        else:
            root = ElementTree.Element("WBSList")
            for node in _flatten_tree(version.tree):
                item = ElementTree.SubElement(root, "WBS")
                ElementTree.SubElement(item, "Code").text = str(node.get("code", ""))
                ElementTree.SubElement(item, "Name").text = str(node.get("name", ""))
            ElementTree.ElementTree(root).write(
                target,
                encoding="utf-8",
                xml_declaration=True,
            )

        export.file_name = file_name
        export.storage_key = target.relative_to(storage.root).as_posix()
        export.status = ProcessingStatus.COMPLETED
        export.updated_at = datetime.now(UTC)
        await db.commit()
