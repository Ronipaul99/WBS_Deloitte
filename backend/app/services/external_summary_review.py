"""Scoped structured review; original import and external execution remain immutable."""

import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import case, select

from app.api.routes.helpers import require_ready_active_run
from app.core.config import get_settings
from app.core.permissions import permissions_for_role
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import DocumentSummary, Tenant, TenantMembership, User
from app.models.external_summary import (
    SummaryApiRequest,
    SummaryResultImport,
    SummaryWorkflowBinding,
)
from app.schemas.domain import SummaryResponse
from app.schemas.external_summary_result import (
    StoredExternalSummary,
    StructuredSummaryResponse,
    SummaryImportProvenance,
)
from app.services.document_workflow_resume import scoped_document
from app.services.external_summary_import import byte_size
from app.services.external_summary_submission import source_fingerprint
from app.services.ingestion.release_identity import matches_release_identity


async def revalidate_review_authorization(db, context, permission):
    """Recheck after awaited locking, before accepting a structured mutation."""
    expected_version = context.user.auth_version
    user = await db.scalar(
        select(User).where(User.id == context.user.id).execution_options(populate_existing=True)
    )
    tenant = await db.scalar(
        select(Tenant)
        .where(Tenant.id == context.tenant.id)
        .execution_options(populate_existing=True)
    )
    role = await db.scalar(
        select(TenantMembership.role).where(
            TenantMembership.tenant_id == context.tenant.id,
            TenantMembership.user_id == context.user.id,
        )
    )
    if (
        user is None
        or not user.is_active
        or user.auth_version != expected_version
        or tenant is None
        or not tenant.is_active
        or permission not in permissions_for_role(role or "")
    ):
        raise HTTPException(403, detail="Summary review is no longer authorized.")


async def read_structured(db, tenant_id, document_id, summary):
    document = await scoped_document(db, tenant_id, document_id)
    maximum = get_settings().external_summary_max_result_bytes + 600_000
    stored = await db.scalar(
        select(
            case(
                (
                    byte_size(db, DocumentSummary.structured_summary) <= maximum,
                    DocumentSummary.structured_summary,
                ),
                else_=None,
            )
        ).where(
            DocumentSummary.id == summary.id,
            DocumentSummary.tenant_id == tenant_id,
            DocumentSummary.document_id == document_id,
        )
    )
    imported = await db.scalar(
        select(SummaryResultImport).where(
            SummaryResultImport.request_id == summary.source_request_id,
            SummaryResultImport.tenant_id == tenant_id,
            SummaryResultImport.project_id == document.project_id,
            SummaryResultImport.document_id == document_id,
            SummaryResultImport.summary_id == summary.id,
            SummaryResultImport.state == "IMPORTED",
        )
    )
    request = await db.scalar(
        select(SummaryApiRequest).where(
            SummaryApiRequest.id == summary.source_request_id,
            SummaryApiRequest.tenant_id == tenant_id,
            SummaryApiRequest.project_id == document.project_id,
            SummaryApiRequest.document_id == document_id,
        )
    )
    if (
        imported is None
        or request is None
        or stored is None
        or summary.revision < imported.imported_revision
    ):
        raise HTTPException(
            409, detail="Structured summary provenance or bounded content is unavailable."
        )
    run = await require_ready_active_run(db, tenant_id, document)
    if (
        run.id != request.processing_run_id
        or not matches_release_identity(document, run, get_settings())
        or source_fingerprint(document, run, request.expected_summary_revision)
        != request.input_digest
    ):
        raise HTTPException(
            409, detail="Structured summary source has changed; review is unavailable."
        )
    try:
        structured = StoredExternalSummary.model_validate(stored)
        data = structured.generated_result.data
        if (data.project_id, data.document_id, data.processing_run_id) != (
            request.project_id,
            request.document_id,
            request.processing_run_id,
        ):
            raise ValueError("Stored scope mismatch")
        return StructuredSummaryResponse(
            **SummaryResponse.model_validate(summary).model_dump(),
            revision=summary.revision,
            structured_summary=structured,
            provenance=SummaryImportProvenance(
                request_id=request.id,
                job_id=request.external_job_id,
                processing_run_id=request.processing_run_id,
                result_digest=imported.result_digest,
                imported_revision=imported.imported_revision,
            ),
        )
    except (ValidationError, ValueError):
        raise HTTPException(409, detail="Structured summary contract is unavailable.") from None


async def lock_review(db, tenant_id, document_id):
    # All writers first take the document guard, including import and deletion.
    await scoped_document(db, tenant_id, document_id, lock=True)
    workflows = list(
        await db.scalars(
            select(DocumentWorkflow)
            .where(
                DocumentWorkflow.tenant_id == tenant_id, DocumentWorkflow.document_id == document_id
            )
            .order_by(DocumentWorkflow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    summary = await db.scalar(
        select(DocumentSummary)
        .where(DocumentSummary.tenant_id == tenant_id, DocumentSummary.document_id == document_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if summary is None:
        raise HTTPException(404, detail="Document summary not found.")
    if summary.source_request_id is not None:
        verified = set(
            await db.scalars(
                select(SummaryWorkflowBinding.workflow_id).where(
                    SummaryWorkflowBinding.tenant_id == tenant_id,
                    SummaryWorkflowBinding.document_id == document_id,
                    SummaryWorkflowBinding.request_id == summary.source_request_id,
                    SummaryWorkflowBinding.verified_at.is_not(None),
                )
            )
        )
        workflows = [workflow for workflow in workflows if workflow.id in verified]
    return summary, workflows


def advance_workflows(workflows, response, *, expected_revision=None):
    for workflow in workflows:
        if (
            workflow.summary_revision
            == (response.revision if expected_revision is None else expected_revision)
            and workflow.summary_id == response.id
            and workflow.summary_job_id == response.provenance.job_id
            and workflow.processing_run_id == response.provenance.processing_run_id
            and workflow.generation_job_id is None
        ):
            workflow.summary_revision = response.revision
            workflow.checkpoint_revision += 1


def check_revision(summary, expected):
    if summary.revision != expected:
        raise HTTPException(
            409,
            detail={
                "code": "SUMMARY_REVISION_CONFLICT",
                "message": (
                    "The saved summary changed. Your local edits are retained; "
                    "refresh and review before saving."
                ),
            },
        )


async def patch_structured(db, tenant_id, document_id, summary, workflows, payload):
    check_revision(summary, payload.expected_revision)
    response = await read_structured(db, tenant_id, document_id, summary)
    stored = response.structured_summary
    originals = {s.id: s for s in stored.generated_result.data.summary_sections}
    edits = {e.id: e for e in stored.current_sections}
    changed = False
    for edit in payload.sections:
        section = originals.get(edit.id)
        if section is None or section.key != edit.key or len(edit.content) > section.max_length:
            raise HTTPException(422, detail="Invalid section identity or persisted edit limit.")
        changed |= edit.content != stored.current_content(section)
        edits[edit.id] = edit
    if not changed:
        return response
    current = [
        edits[s.id]
        for s in sorted(originals.values(), key=lambda s: s.order)
        if s.id in edits and edits[s.id].content != s.content
    ]
    candidate = StoredExternalSummary.model_validate(
        {
            **stored.model_dump(),
            "current_sections": [e.model_dump() for e in current],
            "content_state": "edited_review_required" if current else "generated_unreviewed",
        }
    )
    projection = "\n\n".join(
        f"{s.title}\n{candidate.current_content(s)}"
        for s in sorted(originals.values(), key=lambda s: s.order)
    )
    if len(projection) > 50_000:
        raise HTTPException(422, detail="Summary exceeds the supported legacy projection bound.")
    persisted = candidate.model_dump(mode="json")
    # Conservative serialized bound also covers escaped Unicode in JSON storage.
    if len(json.dumps(persisted, ensure_ascii=True, allow_nan=False).encode("utf-8")) > (
        get_settings().external_summary_max_result_bytes + 600_000
    ):
        raise HTTPException(422, detail="Summary exceeds the supported structured storage bound.")
    summary.structured_summary = persisted
    summary.summary_text, summary.key_points, summary.requirements = projection, [], []
    summary.revision += 1
    summary.is_approved, summary.approved_at = False, None
    previous_revision = response.revision
    response.revision = summary.revision
    advance_workflows(workflows, response, expected_revision=previous_revision)
    await db.flush()
    await db.refresh(summary)
    return await read_structured(db, tenant_id, document_id, summary)
