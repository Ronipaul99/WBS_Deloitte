"""Submission intents and delivery only. Never reads the external jobs table."""

import asyncio
import logging
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import TenantContext
from app.api.routes.helpers import require_ready_active_run
from app.core.config import Settings, get_settings
from app.core.permissions import Permission, permissions_for_role
from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.domain import DocumentSummary, Tenant, TenantMembership, User
from app.models.external_summary import SummaryApiRequest, SummarySubmissionKey
from app.schemas.external_summary import ExternalSubmissionResponse
from app.services.document_content import database_now, utc
from app.services.document_workflow_resume import (
    digest_json,
    ensure_workflow,
    load_workflow,
    scoped_document,
)
from app.services.external_summary_transport import (
    SubmissionFailure,
    submission_configuration,
    submit_document,
)
from app.services.ingestion.release_identity import matches_release_identity

logger = logging.getLogger(__name__)
TASK = "wbs.submit_external_summary"


_CURRENT_REVISION = object()


async def authorized_inputs(
    db, tenant_id, user_id, document_id, workflow_id, *, fingerprint_revision=_CURRENT_REVISION
):
    document = await scoped_document(db, tenant_id, document_id, lock=True)
    user = await db.get(User, user_id, populate_existing=True)
    tenant = await db.get(Tenant, tenant_id, populate_existing=True)
    role = await db.scalar(
        select(TenantMembership.role).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
        )
    )
    if (
        not user
        or not user.is_active
        or not tenant
        or not tenant.is_active
        or Permission.SUMMARY_UPDATE not in permissions_for_role(role or "")
    ):
        raise HTTPException(403, detail="Summary submission is no longer authorized.")
    if workflow_id:
        workflow, owned = await load_workflow(db, tenant_id, workflow_id)
        if owned.id != document_id:
            raise HTTPException(409, detail="Workflow does not belong to this document.")
    else:
        workflow = await ensure_workflow(db, document)
    run = await require_ready_active_run(db, tenant_id, document)
    if not matches_release_identity(document, run, get_settings()):
        raise HTTPException(409, detail="The document ingestion identity is no longer current.")
    summary_revision = await db.scalar(
        select(DocumentSummary.revision).where(
            DocumentSummary.tenant_id == tenant_id,
            DocumentSummary.document_id == document_id,
        )
    )
    fingerprint = source_fingerprint(
        document,
        run,
        summary_revision if fingerprint_revision is _CURRENT_REVISION else fingerprint_revision,
    )
    return document, workflow, run, user, summary_revision, fingerprint


def source_fingerprint(document, run, revision):
    return digest_json(
        {
            "document": document.id,
            "project": document.project_id,
            "source": document.content_sha256,
            "upload": document.upload_sha256,
            "run": run.id,
            "run_source": run.document_content_sha256,
            "extractor": [run.extractor_name, run.extractor_version, run.chunker_version],
            "embedding": [
                run.embedding_provider,
                run.embedding_model,
                run.embedding_model_revision,
                run.embedding_dimensions,
                run.embedding_formatting_version,
            ],
            "summary_revision": revision,
            "contract": "submission-v1",
        }
    )


def response_for(record: SummaryApiRequest) -> ExternalSubmissionResponse:
    return ExternalSubmissionResponse(
        request_id=record.id,
        job_id=record.external_job_id,
        document_id=record.document_id,
        submission_state=record.state,
        status="UNAVAILABLE" if record.state in {"REJECTED", "SUBMISSION_UNKNOWN"} else "QUEUED",
        provider_status=record.acknowledgement.get("status"),
    )


async def create_submission(
    db,
    context: TenantContext,
    document_id: UUID,
    workflow_id: UUID | None,
    key: str | None,
    settings: Settings,
):
    try:
        config = submission_configuration(settings)
    except SubmissionFailure:
        raise HTTPException(503, detail="External summary submission is not configured.") from None
    if key is not None and (
        not 1 <= len(key) <= 128 or not key.isascii() or any(ord(c) < 33 for c in key)
    ):
        raise HTTPException(422, detail="Invalid summary idempotency key.")
    document, workflow, run, user, revision, fingerprint = await authorized_inputs(
        db,
        context.tenant.id,
        context.user.id,
        document_id,
        workflow_id,
    )
    key_digest = digest_json(key if key is not None else ["document-run", document_id, run.id])
    key_record = await db.get(SummarySubmissionKey, (context.tenant.id, user.id, key_digest))
    previous = (
        (
            await db.scalar(
                select(SummaryApiRequest).where(
                    SummaryApiRequest.id == key_record.request_id,
                    SummaryApiRequest.tenant_id == context.tenant.id,
                )
            )
        )
        if key_record
        else None
    )
    if previous and (
        previous.document_id != document_id
        or previous.input_digest != fingerprint
        or previous.config_digest != config.fingerprint
    ):
        raise HTTPException(409, detail="Summary idempotency key has different inputs.")
    if previous is None:
        previous = await db.scalar(
            select(SummaryApiRequest).where(
                SummaryApiRequest.tenant_id == context.tenant.id,
                SummaryApiRequest.document_id == document_id,
                SummaryApiRequest.processing_run_id == run.id,
            )
        )
        if previous and (
            previous.input_digest != fingerprint or previous.config_digest != config.fingerprint
        ):
            raise HTTPException(409, detail="An incompatible summary submission already exists.")
    if previous is None:
        previous = SummaryApiRequest(
            tenant_id=context.tenant.id,
            project_id=document.project_id,
            document_id=document_id,
            workflow_id=workflow.id,
            processing_run_id=run.id,
            created_by=user.id,
            auth_version=user.auth_version,
            expected_summary_revision=revision,
            key_digest=key_digest,
            input_digest=fingerprint,
            config_digest=config.fingerprint,
            available_at=await database_now(db),
        )
        db.add(previous)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                409, detail="Concurrent summary submission; retry safely."
            ) from None
    if key_record is None:
        db.add(
            SummarySubmissionKey(
                tenant_id=context.tenant.id,
                user_id=user.id,
                key_digest=key_digest,
                request_id=previous.id,
            )
        )
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, detail="Concurrent summary key; retry safely.") from None
    from app.services.external_summary_tracking import attach_request

    await attach_request(db, previous, workflow)
    result = response_for(previous)
    await db.commit()
    return result


async def publish_submission(
    tenant_id: UUID, request_id: UUID, background_tasks: BackgroundTasks, settings: Settings
):
    if settings.tasks_eager:
        background_tasks.add_task(process_submission, tenant_id, request_id)
        return
    from app.services.dispatcher import dispatch_app

    try:
        await asyncio.to_thread(
            dispatch_app.send_task, TASK, args=[str(tenant_id), str(request_id)], serializer="json"
        )
    except Exception:
        # Committed intent remains available for reconciliation. No raw broker error.
        logger.warning("External summary delivery deferred")


async def process_submission(
    tenant_id: UUID,
    request_id: UUID,
    *,
    session_factory=SessionLocal,
    settings: Settings | None = None,
    submit=submit_document,
):
    policy = settings or get_settings()
    if not policy.external_summary_enabled:
        return
    async with session_factory() as db:
        await ensure_tenant_transaction(db, tenant_id)
        record = await db.scalar(
            select(SummaryApiRequest).where(
                SummaryApiRequest.id == request_id,
                SummaryApiRequest.tenant_id == tenant_id,
            )
        )
        if record is None:
            return
        # Writers serialize on the document first, then the intent.
        try:
            inputs = await authorized_inputs(
                db, tenant_id, record.created_by, record.document_id, record.workflow_id
            )
            await db.refresh(record, with_for_update=True)
            now = await database_now(db)
            if record.state != "SUBMIT_PENDING" or utc(record.available_at) > now:
                return
            config = submission_configuration(policy)
            if (
                inputs[2].id != record.processing_run_id
                or inputs[5] != record.input_digest
                or inputs[3].auth_version != record.auth_version
                or record.config_digest != config.fingerprint
                or record.contract_version != "submission-v1"
            ):
                raise SubmissionFailure("EXTERNAL_SUMMARY_STALE_INPUT", ambiguous=False)
        except (HTTPException, SubmissionFailure):
            # Never overwrite a terminal/owned attempt on a late duplicate delivery.
            await db.refresh(record, with_for_update=True)
            if record.state == "SUBMIT_PENDING":
                record.state, record.error_code = "REJECTED", "EXTERNAL_SUMMARY_ADMISSION"
                await db.commit()
            return
        if record.attempt_count >= 5:
            record.state, record.error_code = "REJECTED", "EXTERNAL_SUMMARY_ATTEMPTS"
            await db.commit()
            return
        token, document_id = uuid4(), record.document_id
        record.state, record.owner_token = "SUBMITTING", token
        record.attempt_count += 1
        record.lease_expires_at = now + timedelta(seconds=config.total_timeout + 30)
        await db.commit()
    try:
        ack = await submit(document_id, config)
        if ack.document_id != document_id:
            raise SubmissionFailure("EXTERNAL_SUMMARY_INVALID_ACK")
        state, error = "ACKNOWLEDGED", None
    except asyncio.CancelledError:
        # Committed SUBMITTING intent expires to UNKNOWN, never automatically replayed.
        raise
    except SubmissionFailure as exc:
        state = "SUBMISSION_UNKNOWN" if exc.ambiguous else "SUBMIT_PENDING"
        error, ack = exc.code, None
    except Exception:
        state, error, ack = "SUBMISSION_UNKNOWN", "EXTERNAL_SUMMARY_SUBMISSION_UNKNOWN", None
    async with session_factory() as db:
        await ensure_tenant_transaction(db, tenant_id)
        record = await db.scalar(
            select(SummaryApiRequest)
            .where(
                SummaryApiRequest.id == request_id,
                SummaryApiRequest.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        now = await database_now(db)
        if (
            record is None
            or record.state != "SUBMITTING"
            or record.owner_token != token
            or utc(record.lease_expires_at) <= now
        ):
            return
        record.state, record.error_code = state, error
        record.owner_token = record.lease_expires_at = None
        record.available_at = now + timedelta(seconds=30)
        if ack is not None:
            record.external_job_id = ack.job_id
            record.acknowledgement = ack.model_dump(mode="json")
        await db.commit()


async def reconcile_submissions(*, session_factory=SessionLocal, settings: Settings | None = None):
    policy = settings or get_settings()
    if not policy.external_summary_enabled:
        return
    # Tenant identities are global authorization records, not protected document data.
    async with session_factory() as db:
        tenants = list(
            await db.scalars(
                select(Tenant.id).where(Tenant.is_active.is_(True)).order_by(Tenant.id).limit(1001)
            )
        )
    if len(tenants) > 1000:
        logger.warning("External summary tenant scan limit requires operator partitioning")
        return
    for tenant_id in tenants:
        async with session_factory() as db:
            await ensure_tenant_transaction(db, tenant_id)
            now = await database_now(db)
            records = list(
                await db.scalars(
                    select(SummaryApiRequest)
                    .where(
                        SummaryApiRequest.tenant_id == tenant_id,
                        SummaryApiRequest.state.in_(["SUBMIT_PENDING", "SUBMITTING"]),
                        SummaryApiRequest.available_at <= now,
                    )
                    .order_by(SummaryApiRequest.available_at, SummaryApiRequest.id)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            pending = []
            for record in records:
                if record.state == "SUBMITTING":
                    if utc(record.lease_expires_at) <= now:
                        record.state = "SUBMISSION_UNKNOWN"
                        record.owner_token = record.lease_expires_at = None
                        record.error_code = "EXTERNAL_SUMMARY_WORKER_LOST"
                else:
                    pending.append(record.id)
            await db.commit()
        # Publish only; this task never waits for child work on a single-slot worker.
        from app.services.dispatcher import dispatch_app

        for request_id in pending:
            try:
                await asyncio.to_thread(
                    dispatch_app.send_task,
                    TASK,
                    args=[str(tenant_id), str(request_id)],
                    serializer="json",
                )
            except Exception:
                logger.warning("External summary reconciliation delivery deferred")
