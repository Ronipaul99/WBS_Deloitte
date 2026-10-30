"""Local result import only. No upstream HTTP, result URL, broker, or generation calls."""

import hashlib
import json
import logging
import re
from datetime import timedelta
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import LargeBinary, Text, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentSummary,
    Job,
    Tenant,
)
from app.models.external_summary import (
    SummaryApiRequest,
    SummaryResultImport,
    SummaryWorkflowBinding,
)
from app.schemas.external_summary_result import ExternalSummaryResult, StoredExternalSummary
from app.services.document_content import database_now, utc
from app.services.external_summary_tracking import READ_PERMISSIONS, job_scope, read_status
from app.services.ingestion.chunking import canonical_chunk_sha256
from app.services.ingestion.types import confirmed_format_from_suffix

logger = logging.getLogger(__name__)


class ImportFailure(Exception):
    def __init__(self, code, *, stale=False, pending=False):
        super().__init__(code)
        self.code, self.stale, self.pending = code, stale, pending


def encoded(value):
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ImportFailure("SUMMARY_RESULT_ENCODING_INVALID") from None


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def byte_size(db, column):
    return (
        func.octet_length(cast(column, Text))
        if db.get_bind().dialect.name == "postgresql"
        else func.length(cast(column, LargeBinary))
    )


async def bounded_result(db, record, *, lock=False):
    maximum = get_settings().external_summary_max_result_bytes
    size = byte_size(db, Job.result_payload)
    query = select(
        Job.id,
        size.label("size"),
        case((size <= maximum, Job.result_payload), else_=None).label("payload"),
    ).where(*job_scope(db, record), Job.status.in_(["COMPLETED", "completed"]), Job.progress == 100)
    if lock:
        query = query.with_for_update(read=True)
    row = (await db.execute(query)).first()
    if row is None:
        raise ImportFailure("SUMMARY_IMPORT_JOB_CHANGED", stale=True)
    if row.size is not None and row.size > maximum:
        raise ImportFailure("SUMMARY_RESULT_TOO_LARGE")
    if row.payload is None or row.payload == {}:
        raise ImportFailure("SUMMARY_RESULT_NOT_VISIBLE", pending=True)
    if len(encoded(row.payload)) > maximum:
        raise ImportFailure("SUMMARY_RESULT_TOO_LARGE")
    return row.payload


def validate_result(payload, record):
    secret = get_settings().external_summary_api_key
    if secret and secret.get_secret_value().encode() in encoded(payload):
        raise ImportFailure("SUMMARY_RESULT_SECRET_REJECTED")
    try:
        result = ExternalSummaryResult.model_validate(payload)
    except (ValidationError, ValueError, RecursionError):
        raise ImportFailure("SUMMARY_RESULT_CONTRACT_INVALID") from None
    data = result.data
    if (data.project_id, data.document_id, data.processing_run_id) != (
        record.project_id,
        record.document_id,
        record.processing_run_id,
    ):
        raise ImportFailure("SUMMARY_RESULT_SOURCE_MISMATCH", stale=True)
    projection = "\n\n".join(
        f"{s.title}\n{s.content}" for s in sorted(data.summary_sections, key=lambda s: s.order)
    )
    if len(projection) > 50_000:
        raise ImportFailure("SUMMARY_LEGACY_PROJECTION_TOO_LARGE")
    return result, projection


def canonical_quote(content, quote):
    """Resolve line-wrap/spacing differences to an exact, unambiguous source quote."""
    if quote in content:
        return quote
    words = quote.split()
    if words:
        matches = re.finditer(r"\s+".join(re.escape(word) for word in words), content)
        match = next(matches, None)
        if match is not None and next(matches, None) is None and len(match.group()) <= 20_000:
            return match.group()
    raise ImportFailure("SUMMARY_CITATION_QUOTE_INVALID")


async def canonical_digest(db, record, result):
    citations = [c for section in result.data.summary_sections for c in section.evidence_citations]
    ids = {c.chunk_id for c in citations}
    if len(ids) > 64:
        raise ImportFailure("SUMMARY_CANONICAL_CONTEXT_TOO_LARGE")
    identity = (
        await db.execute(
            select(
                Document.storage_key,
                DocumentProcessingRun.chunker_version,
                DocumentProcessingRun.embedding_model,
                DocumentProcessingRun.embedding_model_revision,
                DocumentProcessingRun.document_content_sha256,
            )
            .join(DocumentProcessingRun, DocumentProcessingRun.document_id == Document.id)
            .where(
                Document.id == record.document_id,
                Document.tenant_id == record.tenant_id,
                Document.project_id == record.project_id,
                DocumentProcessingRun.id == record.processing_run_id,
                DocumentProcessingRun.tenant_id == record.tenant_id,
                DocumentProcessingRun.project_id == record.project_id,
            )
        )
    ).first()
    if identity is None:
        raise ImportFailure("SUMMARY_CANONICAL_METADATA_UNAVAILABLE")
    try:
        confirmed_format = confirmed_format_from_suffix(
            PurePosixPath(identity.storage_key).suffix.casefold()
        ).value
    except ValueError:
        raise ImportFailure("SUMMARY_CANONICAL_METADATA_UNAVAILABLE") from None
    size = byte_size(db, DocumentChunk.content)
    metadata_size = byte_size(db, DocumentChunk.source_metadata)
    rows = list(
        (
            await db.execute(
                select(
                    DocumentChunk.id,
                    case((size <= 100_000, DocumentChunk.content), else_=None).label("content"),
                    DocumentChunk.content_sha256,
                    DocumentChunk.block_type,
                    case(
                        (
                            byte_size(db, DocumentChunk.heading_path) <= 65_536,
                            DocumentChunk.heading_path,
                        ),
                        else_=None,
                    ).label("headings"),
                    DocumentChunk.page_number,
                    case(
                        (metadata_size <= 65_536, DocumentChunk.source_metadata), else_=None
                    ).label("metadata"),
                ).where(
                    DocumentChunk.id.in_(ids),
                    DocumentChunk.tenant_id == record.tenant_id,
                    DocumentChunk.project_id == record.project_id,
                    DocumentChunk.document_id == record.document_id,
                    DocumentChunk.processing_run_id == record.processing_run_id,
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    if set(by_id) != ids:
        raise ImportFailure("SUMMARY_CITATION_SCOPE_INVALID")
    snapshots = []
    for row in rows:
        if row.content is None or row.metadata is None or not isinstance(row.metadata, dict):
            raise ImportFailure("SUMMARY_CANONICAL_METADATA_UNAVAILABLE")
        references = row.metadata.get("source_references")
        if (
            row.block_type != "canonical_chunk"
            or row.metadata.get("schema_version") != 1
            or not isinstance(row.headings, list)
            or not isinstance(references, list)
            or not references
        ):
            raise ImportFailure("SUMMARY_CANONICAL_METADATA_UNAVAILABLE")
        expected_hash = canonical_chunk_sha256(
            content=row.content,
            heading_path=row.headings,
            source_references=references,
            chunker_version=identity.chunker_version,
            tokenizer_name=identity.embedding_model,
            tokenizer_revision=identity.embedding_model_revision,
            source_content_sha256=identity.document_content_sha256,
            confirmed_format=confirmed_format,
        )
        if expected_hash != row.content_sha256:
            raise ImportFailure("SUMMARY_CANONICAL_HASH_INVALID")
        snapshots.append([str(row.id), row.content_sha256, row.page_number, row.metadata])
    for citation in citations:
        row = by_id[citation.chunk_id]
        pages = row.metadata.get("page_numbers")
        if pages is None and row.page_number is not None:
            pages = [row.page_number]
        if (
            not isinstance(pages, list)
            or not pages
            or any(type(p) is not int or p < 1 for p in pages)
        ):
            raise ImportFailure("SUMMARY_CITATION_PAGES_UNAVAILABLE")
        # Ingestion has chunk-level page sets, not quote offsets per physical page.
        # Require the entire chunk page set; subsets would assert unavailable precision.
        if set(citation.pages) != set(pages):
            raise ImportFailure("SUMMARY_CITATION_PAGES_UNSUPPORTED")
        # Save exact canonical text in the review representation. The provider's
        # raw job payload and its result digest remain untouched for provenance.
        citation.quote = canonical_quote(row.content, citation.quote)
    return digest(sorted(snapshots, key=lambda row: row[0]))


async def request_record(db, tenant_id, request_id):
    return await db.scalar(
        select(SummaryApiRequest).where(
            SummaryApiRequest.id == request_id, SummaryApiRequest.tenant_id == tenant_id
        )
    )


async def import_record(db, record, *, lock=False):
    query = (
        select(SummaryResultImport)
        .where(
            SummaryResultImport.request_id == record.id,
            SummaryResultImport.tenant_id == record.tenant_id,
            SummaryResultImport.project_id == record.project_id,
            SummaryResultImport.document_id == record.document_id,
        )
        .execution_options(populate_existing=True)
    )
    return await db.scalar(query.with_for_update() if lock else query)


async def claim_import(tenant_id, request_id, session_factory):
    async with session_factory() as db:
        await ensure_tenant_transaction(db, tenant_id)
        record = await request_record(db, tenant_id, request_id)
        if record is None:
            return None
        view = await read_status(
            db, tenant_id, record.document_id, request_id, READ_PERMISSIONS, bind=True
        )
        await db.refresh(record, with_for_update=True)
        if view.result_state == "IMPORTED":
            return ("IMPORTED", view.summary_id)
        if view.result_state not in {"IMPORT_PENDING", "INVALID", "STALE"}:
            return None
        row = await import_record(db, record, lock=True)
        now = await database_now(db)
        if row is not None and (
            row.state in {"IMPORTED", "INVALID", "STALE"}
            or utc(row.available_at) > now
            or (row.state == "VALIDATING" and utc(row.lease_expires_at) > now)
        ):
            return None
        if row is None:
            row = SummaryResultImport(
                request_id=request_id,
                tenant_id=tenant_id,
                project_id=record.project_id,
                document_id=record.document_id,
                first_completed_at=now,
                available_at=now,
                attempt_count=0,
            )
            db.add(row)
        if view.result_state in {"INVALID", "STALE"}:
            row.state = "STALE" if view.result_state == "STALE" else "INVALID"
            row.error_code = "SUMMARY_IMPORT_ADMISSION_REJECTED"
            row.owner_token = row.lease_expires_at = None
            await db.commit()
            return None
        if row.attempt_count >= 5:
            row.state, row.error_code = "INVALID", "SUMMARY_IMPORT_ATTEMPTS_EXHAUSTED"
            row.owner_token = row.lease_expires_at = None
            await db.commit()
            return None
        row.state, row.owner_token = "VALIDATING", uuid4()
        row.lease_expires_at = now + timedelta(seconds=120)
        row.attempt_count += 1
        row.error_code = None
        await db.commit()
        return ("CLAIMED", row.owner_token)


async def finish_failure(tenant_id, request_id, owner, failure, session_factory):
    async with session_factory() as db:
        await ensure_tenant_transaction(db, tenant_id)
        record = await request_record(db, tenant_id, request_id)
        if record is None:
            return
        row = await import_record(db, record, lock=True)
        now = await database_now(db)
        if (
            row is None
            or row.state != "VALIDATING"
            or row.owner_token != owner
            or utc(row.lease_expires_at) <= now
        ):
            return
        state = "STALE" if failure.stale else "INVALID"
        if failure.pending and now <= utc(row.first_completed_at) + timedelta(
            seconds=get_settings().external_summary_import_grace_seconds
        ):
            state = "WAITING"
            row.attempt_count -= 1  # Visibility waiting is bounded by its clock, not crash retries.
        elif failure.pending:
            failure = ImportFailure("SUMMARY_RESULT_VISIBILITY_EXPIRED")
        row.state, row.error_code = state, failure.code
        row.owner_token = row.lease_expires_at = None
        row.available_at = now + timedelta(seconds=15)
        await db.commit()


async def accept_result(
    tenant_id, request_id, owner, payload, canonical, session_factory, *, fault=None
):
    async with session_factory() as db:
        await ensure_tenant_transaction(db, tenant_id)
        record = await request_record(db, tenant_id, request_id)
        if record is None:
            return None
        view = await read_status(db, tenant_id, record.document_id, request_id, READ_PERMISSIONS)
        await db.refresh(record, with_for_update=True)
        view = await read_status(db, tenant_id, record.document_id, request_id, READ_PERMISSIONS)
        row = await import_record(db, record, lock=True)
        now = await database_now(db)
        if (
            row is None
            or row.state != "VALIDATING"
            or row.owner_token != owner
            or utc(row.lease_expires_at) <= now
        ):
            return None
        if view.result_state != "IMPORT_PENDING":
            raise ImportFailure("SUMMARY_IMPORT_SOURCE_CHANGED", stale=True)
        current = await bounded_result(db, record, lock=True)
        if digest(current) != digest(payload):
            raise ImportFailure("SUMMARY_RESULT_CHANGED", stale=True)
        result, projection = validate_result(payload, record)
        if await canonical_digest(db, record, result) != canonical:
            raise ImportFailure("SUMMARY_CANONICAL_CHANGED", stale=True)
        summary = await db.scalar(
            select(DocumentSummary)
            .where(
                DocumentSummary.tenant_id == tenant_id,
                DocumentSummary.document_id == record.document_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (summary.revision if summary else None) != record.expected_summary_revision or (
            summary and (summary.is_approved or summary.requirements)
        ):
            raise ImportFailure("SUMMARY_IMPORT_REVISION_CONFLICT", stale=True)
        bindings = list(
            await db.scalars(
                select(SummaryWorkflowBinding)
                .where(
                    SummaryWorkflowBinding.request_id == request_id,
                    SummaryWorkflowBinding.tenant_id == tenant_id,
                    SummaryWorkflowBinding.project_id == record.project_id,
                    SummaryWorkflowBinding.document_id == record.document_id,
                )
                .order_by(SummaryWorkflowBinding.workflow_id)
                .with_for_update()
            )
        )
        workflows = []
        for binding in bindings:
            workflow = await db.scalar(
                select(DocumentWorkflow)
                .where(
                    DocumentWorkflow.id == binding.workflow_id,
                    DocumentWorkflow.tenant_id == tenant_id,
                    DocumentWorkflow.project_id == record.project_id,
                    DocumentWorkflow.document_id == record.document_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            compatible = (
                workflow
                and binding.verified_at
                and workflow.summary_job_id == record.external_job_id
                and workflow.checkpoint_revision == binding.expected_checkpoint + 1
                and workflow.generation_job_id is None
            )
            if workflow and workflow.id == record.workflow_id and not compatible:
                raise ImportFailure("SUMMARY_IMPORT_WORKFLOW_CHANGED", stale=True)
            if compatible:
                workflows.append(workflow)
        if not any(w.id == record.workflow_id for w in workflows):
            raise ImportFailure("SUMMARY_IMPORT_ASSOCIATION_CHANGED", stale=True)
        if summary is None:
            summary = DocumentSummary(
                tenant_id=tenant_id, document_id=record.document_id, revision=1
            )
            db.add(summary)
        else:
            summary.revision += 1
        summary.source_request_id = request_id
        summary.structured_summary = StoredExternalSummary(generated_result=result).model_dump(
            mode="json"
        )
        if (
            len(encoded(summary.structured_summary))
            > get_settings().external_summary_max_result_bytes + 600_000
        ):
            raise ImportFailure("SUMMARY_RESULT_TOO_LARGE")
        summary.summary_text, summary.key_points, summary.requirements = projection, [], []
        summary.is_approved, summary.approved_at = False, None
        await db.flush()
        if fault:
            await fault("summary", db)
        for workflow in workflows:
            workflow.summary_id, workflow.summary_revision = summary.id, summary.revision
            workflow.processing_run_id = record.processing_run_id
            workflow.checkpoint_revision += 1
        await db.flush()
        if fault:
            await fault("workflow", db)
        row.state, row.summary_id, row.imported_revision = "IMPORTED", summary.id, summary.revision
        row.result_digest, row.imported_at = digest(payload), now
        row.owner_token = row.lease_expires_at = None
        await db.flush()
        if fault:
            await fault("marker", db)
        await db.commit()
        if fault:
            await fault("committed", db)
        return summary.id


async def process_import(
    tenant_id, request_id, *, session_factory=SessionLocal, before_accept=None, fault=None
):
    if not get_settings().external_summary_enabled:
        return None
    claim = await claim_import(tenant_id, request_id, session_factory)
    if claim is None:
        return None
    if claim[0] == "IMPORTED":
        return claim[1]
    owner = claim[1]
    try:
        async with session_factory() as db:
            await ensure_tenant_transaction(db, tenant_id)
            record = await request_record(db, tenant_id, request_id)
            view = await read_status(
                db, tenant_id, record.document_id, request_id, READ_PERMISSIONS
            )
            if view.result_state != "IMPORT_PENDING":
                raise ImportFailure("SUMMARY_IMPORT_SOURCE_CHANGED", stale=True)
            payload = await bounded_result(db, record)
            result, _ = validate_result(payload, record)
            canonical = await canonical_digest(db, record, result)
            await db.commit()
        if before_accept:
            await before_accept()
        return await accept_result(
            tenant_id, request_id, owner, payload, canonical, session_factory, fault=fault
        )
    except ImportFailure as error:
        await finish_failure(tenant_id, request_id, owner, error, session_factory)
    except HTTPException:
        await finish_failure(
            tenant_id,
            request_id,
            owner,
            ImportFailure("SUMMARY_IMPORT_AUTHORIZATION_CHANGED", stale=True),
            session_factory,
        )
    except SQLAlchemyError:
        # Leave the durable fenced lease for bounded crash recovery; never log SQL/payload.
        logger.warning("summary_import_database_unavailable")
    return None


async def reconcile_imports(*, session_factory=SessionLocal):
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
    for tenant in tenants:
        async with session_factory() as db:
            await ensure_tenant_transaction(db, tenant)
            now = await database_now(db)
            # Keyset-free fixed prefix is safe only with terminal requests excluded.
            candidates = list(
                await db.scalars(
                    select(SummaryApiRequest.id)
                    .join(
                        Job,
                        (Job.id == SummaryApiRequest.external_job_id)
                        & (Job.tenant_id == SummaryApiRequest.tenant_id)
                        & (Job.project_id == SummaryApiRequest.project_id),
                    )
                    .outerjoin(
                        SummaryResultImport,
                        (SummaryResultImport.request_id == SummaryApiRequest.id)
                        & (SummaryResultImport.tenant_id == tenant),
                    )
                    .where(
                        SummaryApiRequest.tenant_id == tenant,
                        SummaryApiRequest.state == "ACKNOWLEDGED",
                        Job.job_type == "DOCUMENT_SUMMERIZATION",
                        Job.status.in_(["COMPLETED", "completed"]),
                        Job.progress == 100,
                        (SummaryResultImport.state.is_(None))
                        | (
                            SummaryResultImport.state.in_(["WAITING", "VALIDATING"])
                            & (SummaryResultImport.available_at <= now)
                            & (
                                (SummaryResultImport.lease_expires_at.is_(None))
                                | (SummaryResultImport.lease_expires_at <= now)
                            )
                        ),
                    )
                    .order_by(SummaryApiRequest.created_at, SummaryApiRequest.id)
                    .limit(100)
                )
            )
        for request in candidates:
            try:
                await process_import(tenant, request, session_factory=session_factory)
            except (SQLAlchemyError, HTTPException):
                logger.warning("summary_import_reconciliation_unavailable")
