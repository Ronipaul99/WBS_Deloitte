"""Bounded, explicit tenant backfill and owned-upload reconciliation.

Dry runs may read stored objects but never mutate application records or permanent objects.
No legacy WBS is attached using project recency alone.
"""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import delete, func, select

from app.core.config import Settings
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.document_workflows import (
    DocumentContentClaim,
    DocumentUploadAttempt,
    DocumentWorkflow,
)
from app.models.domain import (
    Document,
    DocumentSummary,
    Job,
    Project,
    ValidationRun,
    WbsTemplate,
    WbsVersion,
)
from app.services.document_content import database_now, insert_for, record_content_rejection, utc
from app.services.document_workflow_resume import digest_json, ensure_workflow
from app.services.ingestion.errors import DocumentInputError, DocumentInputErrorCode
from app.services.storage import UploadObjectStorage, validate_document_storage_key


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def recover_lineage(db, document: Document, *, apply: bool) -> int:
    """Return ambiguity count. Only explicit job input -> version links are recoverable."""
    summary = await db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.tenant_id == document.tenant_id,
            DocumentSummary.document_id == document.id,
        )
    )
    jobs = list(
        await db.scalars(
            select(Job)
            .where(
                Job.tenant_id == document.tenant_id,
                Job.project_id == document.project_id,
                Job.request_payload["document_id"].as_string() == str(document.id),
            )
            .order_by(Job.created_at, Job.id)
        )
    )
    generations = [job for job in jobs if job.job_type == "WBS_GENERATION"]
    summaries = [job for job in jobs if job.job_type == "DOCUMENT_SUMMARY"]
    ambiguous = 0
    recovered = 0
    for job in generations:
        if job.workflow_id:
            recovered += 1
            continue
        payload = job.request_payload
        if summary is None or _uuid(payload.get("summary_id")) != summary.id:
            ambiguous += 1
            continue
        template_id = _uuid(payload.get("template_id"))
        if payload.get("template_id") and not template_id:
            ambiguous += 1
            continue
        if template_id:
            template = await db.get(WbsTemplate, template_id)
            if template is None or template.tenant_id != document.tenant_id:
                ambiguous += 1
                continue
        versions = list(
            await db.scalars(
                select(WbsVersion).where(
                    WbsVersion.generation_job_id == job.id,
                    WbsVersion.tenant_id == document.tenant_id,
                    WbsVersion.project_id == document.project_id,
                )
            )
        )
        if len(versions) > 1 or (job.status == "COMPLETED" and not versions):
            ambiguous += 1
            continue
        recovered += 1
        if not apply:
            continue
        base = await ensure_workflow(db, document)
        workflow = (
            base
            if not base.generation_job_id
            else DocumentWorkflow(
                tenant_id=document.tenant_id,
                project_id=document.project_id,
                document_id=document.id,
            )
        )
        db.add(workflow)
        await db.flush()
        workflow.summary_id = summary.id
        workflow.processing_run_id = document.current_processing_run_id
        workflow.template_id = template_id
        workflow.generation_job_id = job.id
        snapshot = payload.get("input_snapshot")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("summary_revision"), int):
            workflow.summary_revision = snapshot["summary_revision"]
            workflow.template_identity = snapshot.get("template_identity", {})
            workflow.generation_input_fingerprint = digest_json(snapshot)
        job.workflow_id = workflow.id
        if versions:
            version = versions[0]
            version.workflow_id = workflow.id
            workflow.wbs_version_id = version.id
            validation = await db.scalar(
                select(ValidationRun)
                .where(
                    ValidationRun.tenant_id == document.tenant_id,
                    ValidationRun.wbs_version_id == version.id,
                )
                .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc())
                .limit(1)
            )
            if validation:
                workflow.validation_id = validation.id
    if not generations:
        # A project-only legacy output cannot safely be attributed to this source document.
        orphan = await db.scalar(
            select(WbsVersion.id)
            .where(
                WbsVersion.tenant_id == document.tenant_id,
                WbsVersion.project_id == document.project_id,
                WbsVersion.generation_job_id.is_(None),
            )
            .limit(1)
        )
        if orphan:
            return ambiguous + 1
        if apply:
            workflow = await ensure_workflow(db, document)
            workflow.processing_run_id = document.current_processing_run_id
            if summary:
                workflow.summary_id = summary.id
                workflow.summary_revision = summary.revision
            if summaries:
                workflow.summary_job_id = summaries[-1].id
                if summaries[-1].workflow_id is None:
                    summaries[-1].workflow_id = workflow.id
    return ambiguous


async def backfill_workflows(
    *,
    tenant_id: UUID,
    storage: UploadObjectStorage,
    settings: Settings,
    apply: bool = False,
    batch_size: int = 100,
    after: UUID | None = None,
    session_factory=SessionLocal,
) -> dict:
    if not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    report = {
        "mode": "apply" if apply else "dry_run",
        "scanned": 0,
        "verified": 0,
        "missing_objects": 0,
        "integrity_failures": 0,
        "storage_unavailable": 0,
        "ambiguous_histories": 0,
        "changed_during_backfill": 0,
        "next_cursor": None,
    }
    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        query = (
            select(Document)
            .join(Project)
            .where(
                Document.tenant_id == tenant_id,
                Document.lifecycle_status == "ACTIVE",
            )
            .order_by(Document.id)
            .limit(batch_size)
        )
        if after:
            query = query.where(Document.id > after)
        documents = list(await db.scalars(query))
        snapshots = [
            (
                doc.id,
                doc.project_id,
                doc.storage_key,
                doc.size_bytes,
                doc.upload_sha256,
                doc.content_sha256,
            )
            for doc in documents
        ]
    for document_id, project_id, storage_key, size, old_hash, ingestion_hash in snapshots:
        report["scanned"] += 1
        report["next_cursor"] = str(document_id)
        try:
            validate_document_storage_key(storage_key, tenant_id=tenant_id, project_id=project_id)
        except ValueError:
            report["integrity_failures"] += 1
            continue
        try:
            # Network/object reads happen outside the database transaction.
            with TemporaryDirectory(prefix="wbs-content-backfill-") as directory:
                downloaded = await storage.download_to_path(
                    storage_key,
                    Path(directory) / "source.bin",
                    maximum_bytes=settings.max_upload_bytes,
                )
        except DocumentInputError as error:
            key = (
                "missing_objects"
                if error.code == DocumentInputErrorCode.DOCUMENT_OBJECT_MISSING
                else (
                    "integrity_failures"
                    if error.code == DocumentInputErrorCode.DOCUMENT_INTEGRITY_FAILED
                    else "storage_unavailable"
                )
            )
            report[key] += 1
            continue
        except Exception:
            report["storage_unavailable"] += 1
            continue
        if (
            downloaded.byte_count != size
            or (old_hash and old_hash != downloaded.sha256)
            or (ingestion_hash and ingestion_hash != downloaded.sha256)
        ):
            report["integrity_failures"] += 1
            continue
        async with session_factory() as db:
            await set_local_tenant_context(db, tenant_id)
            document = await db.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if (
                document is None
                or document.lifecycle_status != "ACTIVE"
                or document.project_id != project_id
                or document.storage_key != storage_key
                or document.size_bytes != size
                or document.upload_sha256 != old_hash
                or document.content_sha256 != ingestion_hash
            ):
                report["changed_during_backfill"] += 1
                continue
            if apply:
                document.upload_sha256 = downloaded.sha256
                await record_content_rejection(db, document, document.processing_error_code)
                await db.flush()
                canonical = await db.scalar(
                    select(Document)
                    .where(
                        Document.tenant_id == tenant_id,
                        Document.upload_sha256 == downloaded.sha256,
                        Document.lifecycle_status == "ACTIVE",
                    )
                    .order_by(Document.created_at, Document.id)
                    .limit(1)
                )
                await db.execute(
                    insert_for(db, DocumentContentClaim)
                    .values(
                        tenant_id=tenant_id,
                        sha256=downloaded.sha256,
                        size_bytes=size,
                        state="READY",
                        document_id=canonical.id,
                        project_id=canonical.project_id,
                    )
                    .on_conflict_do_nothing()
                )
                claim = await db.get(DocumentContentClaim, (tenant_id, downloaded.sha256))
                if claim.state == "READY":
                    claim.document_id, claim.project_id = canonical.id, canonical.project_id
            report["ambiguous_histories"] += await recover_lineage(db, document, apply=apply)
            if apply:
                await db.commit()
            report["verified"] += 1
    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        report["remaining_unverified"] = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.lifecycle_status != "DELETED",
                Document.upload_sha256.is_(None),
            )
        )
        report["archived_documents"] = await db.scalar(
            select(func.count())
            .select_from(Document)
            .join(Project)
            .where(Document.tenant_id == tenant_id, Project.status == "ARCHIVED")
        )
        for lifecycle in ("DELETING", "DELETED"):
            report[lifecycle.lower() + "_documents"] = await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.tenant_id == tenant_id, Document.lifecycle_status == lifecycle)
            )
        groups = (
            select(Document.upload_sha256)
            .where(
                Document.tenant_id == tenant_id,
                Document.upload_sha256.is_not(None),
                Document.lifecycle_status == "ACTIVE",
            )
            .group_by(Document.upload_sha256)
            .having(func.count() > 1)
        )
        report["duplicate_groups"] = await db.scalar(
            select(func.count()).select_from(groups.subquery())
        )
    return report


async def reconcile_uploads(
    *,
    tenant_id: UUID,
    storage: UploadObjectStorage,
    apply: bool = False,
    minimum_age_seconds: int = 3600,
    batch_size: int = 100,
    session_factory=SessionLocal,
) -> dict:
    if minimum_age_seconds < 300 or not 1 <= batch_size <= 1000:
        raise ValueError("Cleanup needs a grace period of at least 300 seconds and a bounded batch")
    report = {"mode": "apply" if apply else "dry_run", "eligible": 0, "cleaned": 0, "deferred": 0}
    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        now = await database_now(db)
        attempts = list(
            await db.scalars(
                select(DocumentUploadAttempt)
                .where(
                    DocumentUploadAttempt.tenant_id == tenant_id,
                    DocumentUploadAttempt.state.in_(["RESERVED", "ABANDONED"]),
                    DocumentUploadAttempt.updated_at < now - timedelta(seconds=minimum_age_seconds),
                )
                .order_by(DocumentUploadAttempt.updated_at)
                .limit(batch_size)
            )
        )
        candidates = [(a.id, a.sha256, a.storage_key) for a in attempts]
    for token, sha256, key in candidates:
        async with session_factory() as db:
            await set_local_tenant_context(db, tenant_id)
            now = await database_now(db)
            attempt = await db.get(DocumentUploadAttempt, token)
            claim = await db.get(DocumentContentClaim, (tenant_id, sha256), with_for_update=True)
            referenced = await db.scalar(select(Document.id).where(Document.storage_key == key))
            if attempt.state == "COMMITTED" or referenced:
                continue
            if claim and claim.owner_token == token:
                if claim.state != "RESERVED" or utc(claim.lease_expires_at) > now:
                    continue
                if apply:
                    await db.execute(
                        delete(DocumentContentClaim).where(
                            DocumentContentClaim.tenant_id == tenant_id,
                            DocumentContentClaim.sha256 == sha256,
                            DocumentContentClaim.owner_token == token,
                            DocumentContentClaim.state == "RESERVED",
                            DocumentContentClaim.lease_expires_at <= now,
                        )
                    )
            report["eligible"] += 1
            if not apply:
                continue
            attempt.state = "ABANDONED"
            await db.commit()
        try:
            await storage.delete_object(key)
        except Exception:
            report["deferred"] += 1
            continue
        async with session_factory() as db:
            await set_local_tenant_context(db, tenant_id)
            attempt = await db.get(DocumentUploadAttempt, token)
            if attempt.state == "ABANDONED":
                attempt.state = "CLEANED"
                await db.commit()
                report["cleaned"] += 1
    return report
