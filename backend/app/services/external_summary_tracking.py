"""Exact shared-job metadata and guarded workflow binding; no HTTP or result reads."""

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import JSON, cast, func, select

from app.core.config import get_settings
from app.core.permissions import Permission
from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.domain import DocumentSummary, Job, Tenant
from app.models.external_summary import (
    SummaryApiRequest,
    SummaryResultImport,
    SummaryWorkflowBinding,
)
from app.schemas.external_summary_tracking import ExternalSummaryStatus
from app.services.document_content import database_now, utc
from app.services.external_summary_submission import authorized_inputs
from app.services.external_summary_transport import SubmissionFailure, submission_configuration

EXTERNAL_TYPE = "DOCUMENT_SUMMERIZATION"
READ_PERMISSIONS = frozenset({Permission.SUMMARY_READ, Permission.JOB_READ})


def job_scope(db, record):
    object_type = (
        func.json_typeof(cast(Job.request_payload, JSON))
        if db.get_bind().dialect.name == "postgresql"
        else func.json_type(Job.request_payload)
    )
    return (
        Job.id == record.external_job_id,
        Job.job_type == EXTERNAL_TYPE,
        Job.tenant_id == record.tenant_id,
        Job.project_id == record.project_id,
        object_type == "object",
        Job.request_payload["document_id"].as_string() == str(record.document_id),
    )


# Explicit integration policy, not a claim of live provider qualification. RUNNING is
# sampled; completed/COMPLETED is user-described. Other lifecycle values are defensive.
STATUS_MAP = {
    "RUNNING": "IN_PROGRESS",
    "QUEUED": "QUEUED",
    "COMPLETED": "COMPLETED",
    "completed": "COMPLETED",
    "FAILED": "FAILED",
    "CANCELLED": "CANCELLED",
}


class JobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    status: str = Field(max_length=24)
    progress: int = Field(strict=True, ge=0, le=100)
    current_step: str | None = Field(max_length=120)
    attempt_count: int = Field(strict=True, ge=0, le=1000)


async def attach_request(db, record, workflow):
    """Called within the document-locked submission transaction, never on a GET."""
    if (workflow.tenant_id, workflow.project_id, workflow.document_id) != (
        record.tenant_id,
        record.project_id,
        record.document_id,
    ):
        raise HTTPException(409, detail="Summary workflow scope mismatch.")
    binding = await db.get(SummaryWorkflowBinding, (workflow.id, workflow.tenant_id))
    if binding:
        if binding.request_id != record.id:
            raise HTTPException(409, detail="Another summary request is attached to this workflow.")
        return
    if workflow.generation_job_id:
        raise HTTPException(409, detail="Historical generated work cannot attach another summary.")
    db.add(
        SummaryWorkflowBinding(
            tenant_id=record.tenant_id,
            workflow_id=workflow.id,
            project_id=record.project_id,
            document_id=record.document_id,
            request_id=record.id,
            expected_checkpoint=workflow.checkpoint_revision,
            previous_job_id=workflow.summary_job_id,
        )
    )
    await db.flush()


def failure(view, code, *, stale=False):
    return view.model_copy(
        update={
            "binding_state": "STALE" if stale else "UNAVAILABLE",
            "status": "UNAVAILABLE",
            "result_state": "STALE" if stale else "INVALID",
            "error_code": code,
            "error_message": "Summary status is unavailable; check this document's saved workflow.",
            "current_step": None,
        }
    )


async def read_status(
    db,
    tenant_id: UUID,
    document_id: UUID,
    request_id: UUID,
    permissions,
    *,
    workflow_id: UUID | None = None,
    bind=False,
):
    if not READ_PERMISSIONS.issubset(permissions):
        raise HTTPException(403, detail="Summary and job read permissions are required.")
    await ensure_tenant_transaction(db, tenant_id)
    record = await db.scalar(
        select(SummaryApiRequest).where(
            SummaryApiRequest.id == request_id,
            SummaryApiRequest.tenant_id == tenant_id,
            SummaryApiRequest.document_id == document_id,
        )
    )
    if record is None:
        raise HTTPException(404, detail="Summary request not found.")
    target_workflow = workflow_id or record.workflow_id
    view = ExternalSummaryStatus(
        request_id=record.id,
        document_id=document_id,
        workflow_id=target_workflow,
        job_id=record.external_job_id,
        submission_state=record.state,
        binding_state="PENDING",
        status="QUEUED",
        updated_at=record.updated_at,
    )
    binding = await db.scalar(
        select(SummaryWorkflowBinding).where(
            SummaryWorkflowBinding.request_id == record.id,
            SummaryWorkflowBinding.workflow_id == target_workflow,
            SummaryWorkflowBinding.tenant_id == tenant_id,
            SummaryWorkflowBinding.project_id == record.project_id,
            SummaryWorkflowBinding.document_id == document_id,
        )
    )
    if binding is None:
        return failure(view, "SUMMARY_ASSOCIATION_MISSING")
    imported = await db.scalar(
        select(SummaryResultImport).where(
            SummaryResultImport.request_id == request_id,
            SummaryResultImport.tenant_id == tenant_id,
            SummaryResultImport.project_id == record.project_id,
            SummaryResultImport.document_id == document_id,
        )
    )
    imported_summary = None
    kwargs = {}
    if imported is not None and imported.state == "IMPORTED":
        imported_summary = (
            await db.execute(
                select(
                    DocumentSummary.id, DocumentSummary.revision, DocumentSummary.source_request_id
                ).where(
                    DocumentSummary.id == imported.summary_id,
                    DocumentSummary.tenant_id == tenant_id,
                    DocumentSummary.document_id == document_id,
                    DocumentSummary.source_request_id == request_id,
                )
            )
        ).first()
        if imported_summary is None:
            return failure(view, "SUMMARY_IMPORT_SUPERSEDED", stale=True)
        kwargs["fingerprint_revision"] = record.expected_summary_revision
    try:
        document, workflow, run, user, _, fingerprint = await authorized_inputs(
            db,
            tenant_id,
            record.created_by,
            document_id,
            target_workflow,
            **kwargs,
        )
    except HTTPException:
        return failure(view, "SUMMARY_SOURCE_OR_AUTHORIZATION_CHANGED", stale=True)
    if (
        record.contract_version != "submission-v1"
        or run.id != record.processing_run_id
        or fingerprint != record.input_digest
        or user.auth_version != record.auth_version
    ):
        return failure(view, "SUMMARY_INPUTS_CHANGED", stale=True)
    # Reading history does not require a key, but changed configured policy cannot
    # silently bless a different endpoint. Missing configuration is truthful unavailable.
    try:
        if submission_configuration(get_settings()).fingerprint != record.config_digest:
            return failure(view, "SUMMARY_CONFIGURATION_CHANGED", stale=True)
    except SubmissionFailure:
        return failure(view, "SUMMARY_CONFIGURATION_UNAVAILABLE")
    if (
        binding.verified_at is None
        and (
            workflow.checkpoint_revision != binding.expected_checkpoint
            or workflow.summary_job_id != binding.previous_job_id
        )
    ) or (binding.verified_at is not None and workflow.summary_job_id != record.external_job_id):
        return failure(view, "SUMMARY_CHECKPOINT_CHANGED", stale=True)

    if record.state in {"SUBMISSION_UNKNOWN", "REJECTED"}:
        return failure(view, "SUMMARY_SUBMISSION_UNAVAILABLE")
    if record.state != "ACKNOWLEDGED":
        return view
    if record.external_job_id is None:
        return failure(view, "SUMMARY_ACKNOWLEDGEMENT_INVALID")

    # Explicit columns: neither result_payload, full request_payload nor raw errors are loaded.
    row = (
        await db.execute(
            select(
                Job.id,
                Job.status,
                Job.progress,
                Job.current_step,
                Job.attempt_count,
                Job.created_at,
                Job.updated_at,
            ).where(
                *job_scope(db, record),
            )
        )
    ).first()
    now = await database_now(db)
    grace = timedelta(seconds=get_settings().external_summary_job_visibility_grace_seconds)
    if row is None:
        # Same-tenant existence can distinguish a wrong contract without exposing
        # foreign-tenant existence. RLS-hidden rows are indistinguishable from missing.
        exists = await db.scalar(
            select(Job.id).where(
                Job.id == record.external_job_id,
                Job.tenant_id == tenant_id,
            )
        )
        if exists:
            return failure(view, "SUMMARY_JOB_SCOPE_OR_TYPE_INVALID")
        if record.database_verified_at is not None:
            return failure(view, "SUMMARY_VERIFIED_JOB_MISSING")
        if now <= utc(record.updated_at) + grace:
            return view.model_copy(update={"binding_state": "WAITING_FOR_JOB"})
        return failure(view, "SUMMARY_JOB_VISIBILITY_EXPIRED")
    try:
        metadata = JobMetadata.model_validate(
            {
                name: getattr(row, name)
                for name in (
                    "status",
                    "progress",
                    "current_step",
                    "attempt_count",
                )
            }
        )
    except ValidationError:
        return failure(view, "SUMMARY_JOB_METADATA_INVALID")
    secret = get_settings().external_summary_api_key
    step = metadata.current_step or ""
    if any(ord(c) < 32 for c in step) or (secret and secret.get_secret_value() in step):
        return failure(view, "SUMMARY_JOB_METADATA_INVALID")
    normalized = STATUS_MAP.get(metadata.status)
    if normalized is None or utc(row.updated_at) < utc(row.created_at):
        return failure(view, "SUMMARY_JOB_STATUS_UNSUPPORTED")
    view = view.model_copy(
        update={
            "provider_status": metadata.status,
            "status": normalized,
            "progress": metadata.progress,
            "current_step": metadata.current_step,
            "attempt_count": metadata.attempt_count,
            "updated_at": row.updated_at,
            "binding_state": "VERIFIED",
        }
    )
    if normalized == "COMPLETED":
        if metadata.progress != 100:
            view = view.model_copy(update={"status": "IN_PROGRESS"})
            # The application's first-verification/ack clock bounds inconsistency;
            # remote heartbeat updates must not extend this wait indefinitely.
            if now > utc(record.database_verified_at or record.updated_at) + grace:
                return failure(view, "SUMMARY_COMPLETION_INCONSISTENT")
        else:
            view = view.model_copy(update={"result_state": "IMPORT_PENDING"})
    elif normalized in {"FAILED", "CANCELLED"}:
        view = view.model_copy(
            update={
                "error_code": "SUMMARY_EXECUTION_STOPPED",
                "error_message": "Summary execution stopped at the service.",
            }
        )
    if bind:
        # Guarded by the document lock from authorized_inputs, plus both expected values.
        await db.refresh(workflow, with_for_update=True)
        await db.refresh(binding, with_for_update=True)
        if binding.verified_at is None:
            if (
                workflow.checkpoint_revision != binding.expected_checkpoint
                or workflow.summary_job_id != binding.previous_job_id
            ):
                return failure(view, "SUMMARY_CHECKPOINT_CHANGED", stale=True)
            workflow.summary_job_id = record.external_job_id
            workflow.checkpoint_revision += 1
            binding.verified_at = now
        if record.database_verified_at is None:
            record.database_verified_at = now
        await db.flush()
    if imported is not None and imported.state in {"INVALID", "STALE"}:
        return failure(
            view, imported.error_code or "SUMMARY_IMPORT_INVALID", stale=imported.state == "STALE"
        )
    if imported_summary is not None:
        if view.result_state != "IMPORT_PENDING":
            return failure(view, "SUMMARY_IMPORTED_JOB_CHANGED", stale=True)
        return view.model_copy(
            update={
                "result_state": "IMPORTED",
                "summary_id": imported_summary.id,
                "summary_revision": imported_summary.revision,
            }
        )
    return view


async def reject_generic_external_access(db, tenant_id, job_id):
    await ensure_tenant_transaction(db, tenant_id)
    kind = await db.scalar(select(Job.job_type).where(Job.id == job_id, Job.tenant_id == tenant_id))
    associated = False
    if kind != EXTERNAL_TYPE and get_settings().external_summary_enabled:
        associated = bool(
            await db.scalar(
                select(SummaryApiRequest.id)
                .where(
                    SummaryApiRequest.tenant_id == tenant_id,
                    SummaryApiRequest.external_job_id == job_id,
                )
                .limit(1)
            )
        )
    if kind == EXTERNAL_TYPE or associated:
        raise HTTPException(
            409,
            detail="Use the scoped summary request status; external job controls are unavailable.",
        )


async def reconcile_tracking(*, session_factory=SessionLocal):
    """Existing-worker DB-only binding. No HTTP, submission, or result import."""
    if not get_settings().external_summary_enabled:
        return
    async with session_factory() as db:
        tenants = list(
            await db.scalars(
                select(Tenant.id).where(Tenant.is_active.is_(True)).order_by(Tenant.id).limit(1001)
            )
        )
    if len(tenants) > 1000:
        return
    for tenant_id in tenants:
        async with session_factory() as db:
            await ensure_tenant_transaction(db, tenant_id)
            candidates = list(
                (
                    await db.execute(
                        select(
                            SummaryWorkflowBinding.request_id,
                            SummaryWorkflowBinding.workflow_id,
                            SummaryWorkflowBinding.document_id,
                        )
                        .join(
                            SummaryApiRequest,
                            (SummaryApiRequest.id == SummaryWorkflowBinding.request_id)
                            & (SummaryApiRequest.tenant_id == SummaryWorkflowBinding.tenant_id),
                        )
                        .where(
                            SummaryWorkflowBinding.tenant_id == tenant_id,
                            SummaryWorkflowBinding.verified_at.is_(None),
                            SummaryApiRequest.state == "ACKNOWLEDGED",
                        )
                        .order_by(SummaryWorkflowBinding.updated_at)
                        .limit(100)
                    )
                ).all()
            )
        for candidate in candidates:
            async with session_factory() as db:
                await read_status(
                    db,
                    tenant_id,
                    candidate.document_id,
                    candidate.request_id,
                    READ_PERMISSIONS,
                    workflow_id=candidate.workflow_id,
                    bind=True,
                )
                await db.commit()
