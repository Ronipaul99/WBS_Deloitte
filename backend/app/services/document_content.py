"""Verified, tenant-scoped content claims with fenced upload ownership."""

import asyncio
import hashlib
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from prometheus_client import Counter, Histogram
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import UploadFile

from app.core.config import Settings
from app.core.permissions import Permission, permissions_for_role
from app.db.session import ensure_tenant_transaction
from app.models.document_workflows import (
    DocumentContentClaim,
    DocumentContentRejection,
    DocumentUploadAttempt,
    DocumentWorkflow,
    WorkflowRequestKey,
)
from app.models.domain import Document, Project, Tenant, TenantMembership, User
from app.schemas.document_workflows import ResolveResponse, WorkflowCandidate
from app.services.document_workflow_resume import digest_json, ensure_workflow, resume_state
from app.services.storage import PreparedUpload, UploadObjectStorage, prepare_upload

logger = logging.getLogger(__name__)
LOOKUP_DURATION = Histogram("wbs_document_content_lookup_seconds", "Tenant content lookup duration")
CONTENT_EVENTS = Counter("wbs_document_content_total", "Document content outcomes", ["outcome"])


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def conflict(code: str, message: str, **extra) -> HTTPException:
    return HTTPException(409, detail={"code": code, "message": message, **extra})


async def database_now(db: AsyncSession) -> datetime:
    return utc(
        await db.scalar(
            select(
                func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.now()
            )
        )
    )


def insert_for(db: AsyncSession, model):
    return (pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert)(model)


async def _check_destination(db, context, project_id):
    await ensure_tenant_transaction(db, context.tenant.id)
    project = await db.scalar(
        select(Project)
        .where(
            Project.id == project_id,
            Project.tenant_id == context.tenant.id,
            Project.status == "ACTIVE",
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if project is None:
        raise conflict("PROJECT_UNAVAILABLE", "The selected project is unavailable.")
    role = await db.scalar(
        select(TenantMembership.role)
        .join(User)
        .join(
            Tenant,
            Tenant.id == TenantMembership.tenant_id,
        )
        .where(
            TenantMembership.tenant_id == context.tenant.id,
            TenantMembership.user_id == context.user.id,
            User.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
    )
    if role is None or Permission.DOCUMENT_UPLOAD not in permissions_for_role(role):
        raise HTTPException(
            403, detail="You no longer have permission to upload to this workspace."
        )


async def matching_documents(db: AsyncSession, tenant_id: UUID, sha256: str) -> list[Document]:
    return list(
        await db.scalars(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.upload_sha256 == sha256,
                Document.lifecycle_status != "DELETED",
            )
            .order_by(Document.created_at, Document.id)
        )
    )


async def missing_fingerprints(db: AsyncSession, tenant_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(Document.id)
            .where(
                Document.tenant_id == tenant_id,
                Document.lifecycle_status != "DELETED",
                Document.upload_sha256.is_(None),
            )
            .limit(1)
        )
    )


async def resolve_content(db: AsyncSession, **kwargs) -> ResolveResponse:
    with LOOKUP_DURATION.time():
        result = await _resolve_content(db, **kwargs)
    if result.disposition == "UPLOAD_PENDING":
        CONTENT_EVENTS.labels("pending").inc()
    return result


async def _resolve_content(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    sha256: str,
    size_bytes: int,
    selected_project_id: UUID,
    permissions,
) -> ResolveResponse:
    await ensure_tenant_transaction(db, tenant_id)
    if await db.get(DocumentContentRejection, (tenant_id, sha256)):
        return ResolveResponse(disposition="TEMPORARILY_UNAVAILABLE")
    docs = await matching_documents(db, tenant_id, sha256)
    candidates = []
    unavailable = False
    for document in docs:
        if document.size_bytes != size_bytes:
            raise conflict("CONTENT_SIZE_CONFLICT", "The content identity could not be verified.")
        project = await db.get(Project, document.project_id)
        if (
            document.lifecycle_status != "ACTIVE"
            or project is None
            or project.status != "ACTIVE"
            or document.processing_error_code == "DOCUMENT_REJECTED_MALWARE"
        ):
            unavailable = True
            continue
        workflows = list(
            await db.scalars(
                select(DocumentWorkflow)
                .where(
                    DocumentWorkflow.tenant_id == tenant_id,
                    DocumentWorkflow.document_id == document.id,
                )
                .order_by(DocumentWorkflow.created_at.desc(), DocumentWorkflow.id)
            )
        )
        if not workflows:
            unavailable = True  # Explicit backfill is needed; GET must not invent legacy lineage.
        for workflow in workflows:
            state = await resume_state(db, tenant_id, workflow.id, permissions)
            candidates.append(
                WorkflowCandidate(
                    workflow_id=workflow.id,
                    document_id=document.id,
                    project_id=document.project_id,
                    project_name=project.name,
                    file_name=document.file_name,
                    stage=state.stage,
                    updated_at=workflow.updated_at,
                    requires_project_switch=selected_project_id != document.project_id,
                )
            )
    if candidates:
        CONTENT_EVENTS.labels("match").inc()
        return ResolveResponse(
            disposition="MATCH" if len(candidates) == 1 else "MULTIPLE_MATCHES",
            candidates=candidates,
        )
    claim = await db.get(DocumentContentClaim, (tenant_id, sha256))
    if claim and claim.size_bytes != size_bytes:
        raise conflict("CONTENT_SIZE_CONFLICT", "The content identity could not be verified.")
    if claim and claim.state == "RESERVED":
        if claim.lease_expires_at and utc(claim.lease_expires_at) > await database_now(db):
            return ResolveResponse(disposition="UPLOAD_PENDING", upload_handle=claim.owner_token)
    if unavailable or (claim and claim.state in {"READY", "DELETING"}):
        return ResolveResponse(disposition="TEMPORARILY_UNAVAILABLE")
    if await missing_fingerprints(db, tenant_id):
        return ResolveResponse(disposition="TEMPORARILY_UNAVAILABLE")
    return ResolveResponse(disposition="NEW")


async def _renew(factory, tenant_id: UUID, sha256: str, token: UUID, seconds: int) -> None:
    while True:
        await asyncio.sleep(seconds / 3)
        async with factory() as db:
            await ensure_tenant_transaction(db, tenant_id)
            now = await database_now(db)
            result = await db.execute(
                update(DocumentContentClaim)
                .execution_options(synchronize_session=False)
                .where(
                    DocumentContentClaim.tenant_id == tenant_id,
                    DocumentContentClaim.sha256 == sha256,
                    DocumentContentClaim.owner_token == token,
                    DocumentContentClaim.state == "RESERVED",
                    DocumentContentClaim.lease_expires_at > now,
                )
                .values(lease_expires_at=now + timedelta(seconds=seconds))
            )
            await db.commit()
            if result.rowcount != 1:
                return


async def _abandon(
    db: AsyncSession,
    storage: UploadObjectStorage,
    tenant_id: UUID,
    prepared: PreparedUpload,
    token: UUID,
) -> None:
    await db.rollback()
    await ensure_tenant_transaction(db, tenant_id)
    attempt = await db.scalar(
        select(DocumentUploadAttempt)
        .where(
            DocumentUploadAttempt.id == token,
            DocumentUploadAttempt.tenant_id == tenant_id,
            DocumentUploadAttempt.storage_key == prepared.storage_key,
            DocumentUploadAttempt.sha256 == prepared.sha256,
        )
        .with_for_update()
    )
    if attempt is None or attempt.state == "COMMITTED":
        await db.rollback()
        return
    referenced = await db.scalar(
        select(Document.id).where(
            Document.tenant_id == tenant_id, Document.storage_key == prepared.storage_key
        )
    )
    other_owner = await db.scalar(
        select(DocumentContentClaim.tenant_id).where(
            DocumentContentClaim.tenant_id == tenant_id,
            DocumentContentClaim.pending_storage_key == prepared.storage_key,
            DocumentContentClaim.owner_token != token,
        )
    )
    if referenced or other_owner:
        await db.rollback()
        return
    attempt.state = "ABANDONED"
    await db.execute(
        delete(DocumentContentClaim)
        .execution_options(synchronize_session=False)
        .where(
            DocumentContentClaim.tenant_id == tenant_id,
            DocumentContentClaim.sha256 == prepared.sha256,
            DocumentContentClaim.owner_token == token,
            DocumentContentClaim.state == "RESERVED",
        )
    )
    await db.commit()
    try:
        await storage.delete_object(prepared.storage_key)
    except Exception:
        CONTENT_EVENTS.labels("cleanup_pending").inc()
        logger.warning("Document upload cleanup deferred to ownership reconciliation")
    else:
        await ensure_tenant_transaction(db, tenant_id)
        await db.execute(
            update(DocumentUploadAttempt)
            .where(
                DocumentUploadAttempt.id == token,
                DocumentUploadAttempt.tenant_id == tenant_id,
                DocumentUploadAttempt.storage_key == prepared.storage_key,
                DocumentUploadAttempt.state == "ABANDONED",
            )
            .values(state="CLEANED")
        )
        await db.commit()


async def upload_or_reuse(
    db: AsyncSession,
    *,
    context,
    project_id: UUID,
    file: UploadFile,
    suffix: str,
    content_type: str,
    storage: UploadObjectStorage,
    settings: Settings,
    client_sha256: str | None = None,
    idempotency_key: str | None = None,
):
    await _check_destination(db, context, project_id)
    prepared = await prepare_upload(
        file, suffix=suffix, settings=settings, tenant_id=context.tenant.id, project_id=project_id
    )
    if client_sha256 and client_sha256 != prepared.sha256:
        raise HTTPException(
            422,
            detail={
                "code": "CONTENT_FINGERPRINT_MISMATCH",
                "message": "The selected file changed. Select it again.",
            },
        )
    tenant_id = context.tenant.id
    await ensure_tenant_transaction(db, tenant_id)
    if idempotency_key:
        if len(idempotency_key) > 200:
            raise HTTPException(422, detail="Invalid idempotency key.")
        key_digest = hashlib.sha256(("upload:" + idempotency_key).encode()).hexdigest()
        request_digest = digest_json([str(project_id), prepared.sha256, prepared.size_bytes])
        await db.execute(
            insert_for(db, WorkflowRequestKey)
            .values(
                tenant_id=tenant_id,
                user_id=context.user.id,
                key_digest=key_digest,
                request_digest=request_digest,
            )
            .on_conflict_do_nothing()
        )
        request = await db.get(WorkflowRequestKey, (tenant_id, context.user.id, key_digest))
        if request.request_digest != request_digest:
            raise conflict("IDEMPOTENCY_KEY_REUSED", "This request key belongs to another upload.")
        if request.attempt_id:
            attempt = await db.get(DocumentUploadAttempt, request.attempt_id)
            if attempt and attempt.document_id:
                old = await db.get(Document, attempt.document_id)
                if old is None or old.lifecycle_status != "ACTIVE":
                    raise HTTPException(410, detail="The original upload is no longer available.")
                base = await db.scalar(
                    select(DocumentWorkflow).where(
                        DocumentWorkflow.document_id == old.id,
                        DocumentWorkflow.tenant_id == tenant_id,
                        DocumentWorkflow.is_base.is_(True),
                    )
                )
                if base is not None and old.project_id == project_id:
                    await db.commit()
                    return "REUSED", old, base.id, None
    resolved = await resolve_content(
        db,
        tenant_id=tenant_id,
        sha256=prepared.sha256,
        size_bytes=prepared.size_bytes,
        selected_project_id=project_id,
        permissions=context.permissions,
    )
    if resolved.candidates:
        same = [c for c in resolved.candidates if c.project_id == project_id]
        if not same:
            raise conflict(
                "EXISTING_DOCUMENT_IN_OTHER_PROJECT",
                "This document already exists. Continue its previous work.",
                candidates=[c.model_dump(mode="json") for c in resolved.candidates],
            )
        # An API caller must choose explicitly if this document has several generation histories.
        if len(same) > 1:
            raise conflict(
                "MULTIPLE_DOCUMENT_WORKFLOWS",
                "Choose an existing workflow.",
                candidates=[c.model_dump(mode="json") for c in same],
            )
        await db.commit()
        CONTENT_EVENTS.labels("reused").inc()
        return "REUSED", await db.get(Document, same[0].document_id), same[0].workflow_id, None
    if resolved.disposition == "UPLOAD_PENDING":
        await db.commit()
        return "UPLOAD_PENDING", None, None, resolved.upload_handle
    if resolved.disposition != "NEW":
        raise conflict(
            "CONTENT_INDEX_UNAVAILABLE",
            "Existing documents must be indexed or made available before uploading.",
        )
    token = uuid4()
    now = await database_now(db)
    reservation = dict(
        tenant_id=tenant_id,
        sha256=prepared.sha256,
        size_bytes=prepared.size_bytes,
        state="RESERVED",
        owner_token=token,
        lease_expires_at=now + timedelta(seconds=settings.document_upload_lease_seconds),
        pending_storage_key=prepared.storage_key,
    )
    acquired = await db.execute(
        insert_for(db, DocumentContentClaim).values(**reservation).on_conflict_do_nothing()
    )
    if acquired.rowcount != 1:
        old_claim = await db.get(
            DocumentContentClaim, (tenant_id, prepared.sha256), populate_existing=True
        )
        if old_claim is None:
            raise conflict(
                "UPLOAD_RESERVATION_CHANGED", "The upload changed. Check existing work again."
            )
        old_token = old_claim.owner_token
        taken = await db.execute(
            update(DocumentContentClaim)
            .execution_options(synchronize_session=False)
            .where(
                DocumentContentClaim.tenant_id == tenant_id,
                DocumentContentClaim.sha256 == prepared.sha256,
                DocumentContentClaim.state == "RESERVED",
                DocumentContentClaim.lease_expires_at <= now,
                DocumentContentClaim.owner_token == old_token,
            )
            .values(**reservation)
        )
        if taken.rowcount != 1:
            await db.rollback()
            # The winner may have published after our lookup; resolve before asking to retry.
            return await _after_conflict(db, tenant_id, context.permissions, project_id, prepared)
        await db.execute(
            update(DocumentUploadAttempt)
            .where(
                DocumentUploadAttempt.id == old_token,
                DocumentUploadAttempt.state == "RESERVED",
            )
            .values(state="ABANDONED")
        )
        CONTENT_EVENTS.labels("lease_takeover").inc()
    db.add(
        DocumentUploadAttempt(
            id=token,
            tenant_id=tenant_id,
            project_id=project_id,
            sha256=prepared.sha256,
            storage_key=prepared.storage_key,
            state="RESERVED",
        )
    )
    await db.flush()
    if idempotency_key:
        await db.execute(
            update(WorkflowRequestKey)
            .where(
                WorkflowRequestKey.tenant_id == tenant_id,
                WorkflowRequestKey.user_id == context.user.id,
                WorkflowRequestKey.key_digest == key_digest,
            )
            .values(attempt_id=token)
        )
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    heartbeat = asyncio.create_task(
        _renew(factory, tenant_id, prepared.sha256, token, settings.document_upload_lease_seconds)
    )
    committed = False
    try:
        storage_key, size = await storage.save(
            tenant_id,
            "documents",
            file,
            suffix=suffix,
            content_type=content_type,
            project_id=project_id,
            prepared=prepared,
        )
        if storage_key != prepared.storage_key or size != prepared.size_bytes:
            raise RuntimeError("Storage publication did not match the verified upload")
        if heartbeat.done():
            # A failed renewer or lost lease cannot be treated as healthy ownership.
            raise conflict("UPLOAD_LEASE_LOST", "The upload expired. Check existing work again.")
        await ensure_tenant_transaction(db, tenant_id)
        await _check_destination(db, context, project_id)
        now = await database_now(db)
        # Lock/renew only if this request still owns an unexpired lease.
        fenced = await db.execute(
            update(DocumentContentClaim)
            .execution_options(synchronize_session=False)
            .where(
                DocumentContentClaim.tenant_id == tenant_id,
                DocumentContentClaim.sha256 == prepared.sha256,
                DocumentContentClaim.owner_token == token,
                DocumentContentClaim.state == "RESERVED",
                DocumentContentClaim.lease_expires_at > now,
            )
            .values(
                lease_expires_at=now + timedelta(seconds=settings.document_upload_lease_seconds)
            )
        )
        if fenced.rowcount != 1:
            raise conflict("UPLOAD_LEASE_LOST", "The upload expired. Check existing work again.")
        document = Document(
            tenant_id=tenant_id,
            project_id=project_id,
            uploaded_by=context.user.id,
            kind="PROJECT",
            file_name=Path(file.filename or "upload.bin").name,
            content_type=content_type,
            size_bytes=size,
            storage_key=storage_key,
            upload_sha256=prepared.sha256,
        )
        db.add(document)
        await db.flush()
        workflow = await ensure_workflow(db, document)
        await db.execute(
            update(DocumentContentClaim)
            .execution_options(synchronize_session=False)
            .where(
                DocumentContentClaim.tenant_id == tenant_id,
                DocumentContentClaim.sha256 == prepared.sha256,
                DocumentContentClaim.owner_token == token,
            )
            .values(
                state="READY", project_id=project_id, document_id=document.id, lease_expires_at=None
            )
        )
        await db.execute(
            update(DocumentUploadAttempt)
            .where(
                DocumentUploadAttempt.id == token,
            )
            .values(state="COMMITTED", document_id=document.id)
        )
        await db.commit()
        committed = True
        CONTENT_EVENTS.labels("created").inc()
        return "CREATED", document, workflow.id, None
    except BaseException:
        if not committed:
            # Retain the task and finish it before the request session can close,
            # including cancellation during compensation. Preserve the primary error.
            cleanup = asyncio.create_task(_abandon(db, storage, tenant_id, prepared, token))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                try:
                    await cleanup
                except (Exception, asyncio.CancelledError):
                    CONTENT_EVENTS.labels("cleanup_pending").inc()
                    logger.warning("Document upload cleanup interrupted; reconciliation required")
            except Exception:
                CONTENT_EVENTS.labels("cleanup_pending").inc()
                logger.warning("Document upload cleanup failed; ownership reconciliation required")
        raise
    finally:
        if heartbeat.done() and not heartbeat.cancelled() and heartbeat.exception() is not None:
            CONTENT_EVENTS.labels("heartbeat_failed").inc()
            logger.warning("Document upload lease renewal failed; ownership requires revalidation")
        heartbeat.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await heartbeat


async def _after_conflict(db, tenant_id, permissions, project_id, prepared):
    resolved = await resolve_content(
        db,
        tenant_id=tenant_id,
        sha256=prepared.sha256,
        size_bytes=prepared.size_bytes,
        selected_project_id=project_id,
        permissions=permissions,
    )
    if len(resolved.candidates) == 1 and resolved.candidates[0].project_id == project_id:
        candidate = resolved.candidates[0]
        return "REUSED", await db.get(Document, candidate.document_id), candidate.workflow_id, None
    if resolved.candidates:
        raise conflict(
            "EXISTING_DOCUMENT_IN_OTHER_PROJECT",
            "Choose the existing workflow.",
            candidates=[c.model_dump(mode="json") for c in resolved.candidates],
        )
    if resolved.disposition == "TEMPORARILY_UNAVAILABLE":
        raise conflict("CONTENT_INDEX_UNAVAILABLE", "The existing document is unavailable.")
    return "UPLOAD_PENDING", None, None, resolved.upload_handle


async def mark_content_deleting(db: AsyncSession, document: Document) -> None:
    if document.upload_sha256:
        await db.execute(
            update(DocumentContentClaim)
            .execution_options(synchronize_session=False)
            .where(
                DocumentContentClaim.tenant_id == document.tenant_id,
                DocumentContentClaim.sha256 == document.upload_sha256,
                DocumentContentClaim.document_id == document.id,
            )
            .values(state="DELETING")
        )


async def release_deleted_content(db: AsyncSession, document: Document) -> None:
    if not document.upload_sha256:
        return
    claim = await db.get(DocumentContentClaim, (document.tenant_id, document.upload_sha256))
    if claim is None or claim.document_id != document.id:
        return
    replacement = await db.scalar(
        select(Document)
        .join(Project)
        .where(
            Document.tenant_id == document.tenant_id,
            Document.upload_sha256 == document.upload_sha256,
            Document.id != document.id,
            Document.lifecycle_status == "ACTIVE",
            Project.status == "ACTIVE",
        )
        .order_by(Document.created_at, Document.id)
        .limit(1)
    )
    if replacement:
        claim.state = "READY"
        claim.document_id, claim.project_id = replacement.id, replacement.project_id
        claim.size_bytes = replacement.size_bytes
    else:
        await db.delete(claim)


async def record_content_rejection(db: AsyncSession, document: Document, code: str) -> None:
    if code == "DOCUMENT_REJECTED_MALWARE" and document.upload_sha256:
        await db.execute(
            insert_for(db, DocumentContentRejection)
            .values(
                tenant_id=document.tenant_id,
                sha256=document.upload_sha256,
                reason=code,
            )
            .on_conflict_do_nothing()
        )
