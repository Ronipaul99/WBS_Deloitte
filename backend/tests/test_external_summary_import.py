"""Synthetic Step 4; isolated --noconftest plugin only. No live DB or HTTP."""

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select

from app.core.config import get_settings
from app.db.session import SessionLocal, engine, ensure_tenant_transaction
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Document, DocumentChunk, DocumentSummary, Job, TenantMembership
from app.models.external_summary import SummaryApiRequest, SummaryResultImport
from app.schemas.external_summary_result import KEYS, ExternalSummaryResult
from app.services import external_summary_import as service
from tests.test_document_deduplication_api import get_state
from tests.test_document_deduplication_api import workspace as workspace  # noqa: F401
from tests.test_external_summary_submission import fake_broker as fake_broker  # noqa: F401
from tests.test_external_summary_submission import prepared as prepared  # noqa: F401
from tests.test_external_summary_tracking import acknowledged as acknowledged  # noqa: F401
from tests.test_external_summary_tracking import external_job, status

TEXT = "Synthetic café capacity is 12 MW.\nDelivery is conditional on approval."


def result_payload(created, run_id, chunk_id):
    sections = []
    for index, key in enumerate(KEYS, 1):
        answered = index != 4
        sections.append(
            dict(
                id=f"sec_{index}",
                order=index,
                key=key,
                title=key.replace("_", " "),
                badge="AI Draft",
                subtitle="Editable AI-generated summary",
                content="Capacity is 12 MW. [1]" if answered else "Evidence unavailable.",
                max_length=2000,
                source_references={
                    "label": "Canonical chunk pages",
                    "pages": [1] if answered else [],
                },
                question_id=f"Q{index:03}",
                answer_status="answered" if answered else "insufficient_evidence",
                evidence_context_truncated=index == 1,
                evidence_citations=[
                    {
                        "chunk_id": str(chunk_id),
                        "quote": "café capacity is 12 MW.\nDelivery",
                        "citation_number": 1,
                        "pages": [1],
                    }
                ]
                if answered
                else [],
            )
        )
    return {
        "status": "success",
        "message": "Project summary retrieved successfully",
        "data": {
            "project_id": created["project_id"],
            "document_id": created["document_id"],
            "processing_run_id": str(run_id),
            "document_information": {
                "filename": "synthetic.pdf",
                "file_size": "1 KB",
                "file_type": "PDF",
                "extraction_confidence": None,
                "confidence_status": "Not recorded; draft requires review.",
            },
            "summary_sections": sections,
            "question_set_id": "SYNTHETIC_V1",
            "llm_model": "synthetic-model",
        },
    }


@pytest.fixture
async def complete(client, workspace, acknowledged):
    created, request_id, job_id = acknowledged
    async with SessionLocal() as db:
        request = await db.get(SummaryApiRequest, request_id)
        chunk = await db.scalar(
            select(DocumentChunk).where(DocumentChunk.document_id == UUID(created["document_id"]))
        )
        chunk.content, chunk.content_sha256 = TEXT, hashlib.sha256(TEXT.encode()).hexdigest()
        chunk.page_number, chunk.source_metadata = 1, {"page_numbers": [1]}
        payload = result_payload(created, request.processing_run_id, chunk.id)
        await db.commit()
    await external_job(
        workspace, created, job_id, status="COMPLETED", progress=100, result_payload=payload
    )
    return created, request_id, job_id, payload


async def read_import(workspace, request_id):
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        return await db.get(SummaryResultImport, request_id)


async def alter_job(job_id, **values):
    async with SessionLocal() as db:
        row = await db.get(Job, job_id)
        for key, value in values.items():
            setattr(row, key, value)
        await db.commit()


async def test_valid_import_is_atomic_lossless_unapproved_and_readable(client, workspace, complete):
    created, request_id, job_id, payload = complete
    summary_id = await service.process_import(UUID(workspace), request_id)
    assert summary_id
    imported = await read_import(workspace, request_id)
    assert imported.state == "IMPORTED" and imported.imported_revision == 1
    response = client.get(f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["structured_summary"]["generated_result"] == payload
    assert body["revision"] == 1 and body["is_approved"] is False and body["approved_at"] is None
    assert body["key_points"] == body["requirements"] == []
    assert body["capabilities"]["can_generate_wbs"] is False
    tracked = status(client, workspace, created, request_id).json()
    assert tracked["result_state"] == "IMPORTED" and tracked["summary_id"] == str(summary_id)
    resumed = get_state(client, workspace, created["workflow_id"])
    assert resumed["resume_screen"] == "doc_summary" and resumed["summary_id"] == str(summary_id)
    assert resumed["external_summary"]["result_state"] == "IMPORTED"
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.result_payload == payload and job.status == "COMPLETED" and job.progress == 100
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        assert workflow.summary_id == summary_id and workflow.summary_revision == 1
    base = f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary"
    assert client.patch(base, json={"summary_text": "legacy overwrite"}).status_code == 409
    assert client.post(base + "/approve").status_code == 409
    assert (
        client.post(
            f"/api/v1/tenants/{workspace}/projects/{created['project_id']}/generations",
            json={"document_id": created["document_id"], "summary_id": str(summary_id)},
        ).status_code
        == 409
    )


async def test_duplicate_import_preserves_later_edits_and_approval(client, workspace, complete):
    created, request_id, _, _ = complete
    summary_id = await service.process_import(UUID(workspace), request_id)
    async with SessionLocal() as db:
        summary = await db.get(DocumentSummary, summary_id)
        summary.summary_text, summary.revision, summary.is_approved = "Later human edit", 2, True
        await db.commit()
    assert await service.process_import(UUID(workspace), request_id) == summary_id
    async with SessionLocal() as db:
        summary = await db.get(DocumentSummary, summary_id)
        assert (summary.summary_text, summary.revision, summary.is_approved) == (
            "Later human edit",
            2,
            True,
        )
    assert (await read_import(workspace, request_id)).imported_revision == 1


@pytest.mark.parametrize(
    "change",
    [
        "failure",
        "missing",
        "extra",
        "duplicate_id",
        "duplicate_order",
        "missing_citation",
        "quote",
        "pages",
        "foreign_chunk",
        "foreign_document",
        "confidence",
        "overflow",
    ],
)
async def test_invalid_result_fails_closed(client, workspace, complete, change):
    created, request_id, job_id, payload = complete
    data = payload["data"]
    first = data["summary_sections"][0]
    if change == "failure":
        payload["status"] = "failure"
    elif change == "missing":
        data["summary_sections"].pop()
    elif change == "extra":
        first["unexpected"] = "not allowed"
    elif change == "duplicate_id":
        data["summary_sections"][1]["id"] = first["id"]
    elif change == "duplicate_order":
        data["summary_sections"][1]["order"] = first["order"]
    elif change == "missing_citation":
        first["content"] = "No matching number [2]"
    elif change == "quote":
        first["evidence_citations"][0]["quote"] = "Invented quote"
    elif change == "pages":
        first["source_references"]["pages"] = first["evidence_citations"][0]["pages"] = [99]
    elif change == "foreign_chunk":
        first["evidence_citations"][0]["chunk_id"] = str(uuid4())
    elif change == "foreign_document":
        data["document_id"] = str(uuid4())
    elif change == "confidence":
        data["document_information"]["extraction_confidence"] = True
    elif change == "overflow":
        first["max_length"] = 1
    await alter_job(job_id, result_payload=payload)
    assert await service.process_import(UUID(workspace), request_id) is None
    row = await read_import(workspace, request_id)
    assert row.state in {"INVALID", "STALE"}
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(DocumentSummary.id).where(
                    DocumentSummary.document_id == UUID(created["document_id"])
                )
            )
            is None
        )
    assert status(client, workspace, created, request_id).json()["result_state"] in {
        "INVALID",
        "STALE",
    }


@pytest.mark.parametrize(
    ("wire", "progress"), [("RUNNING", 100), ("COMPLETED", 80), ("FAILED", 100), ("CANCELLED", 100)]
)
async def test_non_completion_never_reads_result(client, workspace, complete, wire, progress):
    _, request_id, job_id, _ = complete
    await alter_job(job_id, status=wire, progress=progress)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await service.process_import(UUID(workspace), request_id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not any("jobs.result_payload" in query.lower() for query in statements)


async def test_missing_result_waits_then_expires_without_resubmission(client, workspace, complete):
    _, request_id, job_id, _ = complete
    await alter_job(job_id, result_payload={})
    await service.process_import(UUID(workspace), request_id)
    assert (await read_import(workspace, request_id)).state == "WAITING"
    async with SessionLocal() as db:
        row = await db.get(SummaryResultImport, request_id)
        row.available_at = row.first_completed_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()
    await service.process_import(UUID(workspace), request_id)
    assert (await read_import(workspace, request_id)).state == "INVALID"


@pytest.mark.parametrize("boundary", ["summary", "workflow", "marker"])
async def test_fault_rolls_back_all_writes_and_recovery_reuses_lease(
    client, workspace, complete, boundary
):
    created, request_id, _, _ = complete

    async def fail(stage, db):
        if stage == boundary:
            raise RuntimeError("synthetic interruption")

    with pytest.raises(RuntimeError):
        await service.process_import(UUID(workspace), request_id, fault=fail)
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(DocumentSummary.id).where(
                    DocumentSummary.document_id == UUID(created["document_id"])
                )
            )
            is None
        )
        row = await db.get(SummaryResultImport, request_id)
        assert row.state == "VALIDATING"
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert await service.process_import(UUID(workspace), request_id)
    assert (await read_import(workspace, request_id)).attempt_count == 2


@pytest.mark.parametrize(
    "change",
    [
        "payload",
        "canonical",
        "source",
        "authorization",
        "fence",
        "revision",
        "approval",
        "checkpoint",
    ],
)
async def test_change_between_validation_and_acceptance_cannot_publish(
    client, workspace, complete, change
):
    created, request_id, job_id, payload = complete

    async def mutate():
        async with SessionLocal() as db:
            if change == "payload":
                job = await db.get(Job, job_id)
                changed = copy.deepcopy(payload)
                changed["message"] = "changed"
                job.result_payload = changed
            elif change == "canonical":
                chunk = await db.scalar(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == UUID(created["document_id"])
                    )
                )
                chunk.content = "Changed canonical text"
            elif change == "source":
                document = await db.get(Document, UUID(created["document_id"]))
                document.current_processing_run_id = None
            elif change == "authorization":
                member = await db.scalar(
                    select(TenantMembership).where(TenantMembership.tenant_id == UUID(workspace))
                )
                member.role = "VIEWER"
            elif change == "fence":
                row = await db.get(SummaryResultImport, request_id)
                row.owner_token = uuid4()
            elif change == "checkpoint":
                workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
                workflow.checkpoint_revision += 1
            else:
                db.add(
                    DocumentSummary(
                        tenant_id=UUID(workspace),
                        document_id=UUID(created["document_id"]),
                        revision=2,
                        is_approved=change == "approval",
                        summary_text="Keep human work",
                    )
                )
            await db.commit()

    assert await service.process_import(UUID(workspace), request_id, before_accept=mutate) is None
    row = await read_import(workspace, request_id)
    assert row.state in {"STALE", "INVALID", "VALIDATING"}
    async with SessionLocal() as db:
        summary = await db.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == UUID(created["document_id"])
            )
        )
        assert summary is None or summary.summary_text == "Keep human work"


async def test_worker_reconciliation_imports_without_browser(
    client, workspace, complete, monkeypatch
):
    _, request_id, _, _ = complete

    async def forbidden(*args, **kwargs):
        raise AssertionError("No HTTP or submission allowed")

    from app.services import external_summary_submission

    monkeypatch.setattr(external_summary_submission, "submit_document", forbidden)
    await service.reconcile_imports()
    assert (await read_import(workspace, request_id)).state == "IMPORTED"


def test_contract_preserves_unicode_null_and_local_numbers():
    payload = result_payload(
        {"project_id": str(uuid4()), "document_id": str(uuid4())}, uuid4(), uuid4()
    )
    assert ExternalSummaryResult.model_validate(payload).model_dump(mode="json") == payload
    payload["data"]["summary_sections"][0]["order"] = True
    with pytest.raises(ValidationError):
        ExternalSummaryResult.model_validate(payload)


async def test_payload_size_and_secret_fail_without_exposing_content(
    client, workspace, complete, monkeypatch
):
    created, request_id, job_id, payload = complete
    monkeypatch.setattr(get_settings(), "external_summary_max_result_bytes", 1024)
    await service.process_import(UUID(workspace), request_id)
    row = await read_import(workspace, request_id)
    assert row.error_code == "SUMMARY_RESULT_TOO_LARGE"
    response = status(client, workspace, created, request_id)
    assert "café" not in response.text and "synthetic-model" not in response.text


async def test_credential_echo_is_not_imported(client, workspace, complete):
    _, request_id, job_id, payload = complete
    secret = get_settings().external_summary_api_key.get_secret_value()
    payload["message"] = secret
    await alter_job(job_id, result_payload=payload)
    await service.process_import(UUID(workspace), request_id)
    assert (await read_import(workspace, request_id)).error_code == "SUMMARY_RESULT_SECRET_REJECTED"


async def test_disabled_gate_and_foreign_request_cannot_import(
    client, workspace, complete, monkeypatch
):
    _, request_id, _, _ = complete
    assert await service.process_import(uuid4(), request_id) is None
    monkeypatch.setattr(get_settings(), "external_summary_enabled", False)
    assert await service.process_import(UUID(workspace), request_id) is None
    assert await read_import(workspace, request_id) is None


async def test_active_lease_blocks_competitor_and_expired_fence_cannot_accept(
    client, workspace, complete
):
    _, request_id, _, payload = complete
    claim = await service.claim_import(UUID(workspace), request_id, SessionLocal)
    assert claim[0] == "CLAIMED"
    assert await service.claim_import(UUID(workspace), request_id, SessionLocal) is None
    async with SessionLocal() as db:
        row = await db.get(SummaryResultImport, request_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    assert (
        await service.accept_result(
            UUID(workspace), request_id, claim[1], payload, "unused", SessionLocal
        )
        is None
    )
    assert await service.process_import(UUID(workspace), request_id)


async def test_result_mutation_after_import_cannot_create_revision(client, workspace, complete):
    _, request_id, job_id, payload = complete
    summary_id = await service.process_import(UUID(workspace), request_id)
    payload["message"] = "Mutated after accepted import"
    await alter_job(job_id, result_payload=payload)
    assert await service.process_import(UUID(workspace), request_id) == summary_id
    row = await read_import(workspace, request_id)
    assert row.result_digest != service.digest(payload) and row.imported_revision == 1


@pytest.mark.parametrize("kind", ["hash", "pages_unknown", "multipage_subset", "deleting"])
async def test_canonical_and_lifecycle_guards(client, workspace, complete, kind):
    created, request_id, _, _ = complete

    async def mutate():
        async with SessionLocal() as db:
            chunk = await db.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == UUID(created["document_id"])
                )
            )
            if kind == "hash":
                chunk.content_sha256 = "f" * 64
            elif kind == "pages_unknown":
                chunk.page_number, chunk.source_metadata = None, {}
            elif kind == "multipage_subset":
                chunk.page_number, chunk.source_metadata = None, {"page_numbers": [1, 2]}
            else:
                document = await db.get(Document, UUID(created["document_id"]))
                document.lifecycle_status = "DELETING"
                document.deletion_requested_at = document.vectors_hidden_at = datetime.now(UTC)
            await db.commit()

    await service.process_import(UUID(workspace), request_id, before_accept=mutate)
    assert (await read_import(workspace, request_id)).state in {"INVALID", "STALE"}


def test_step4_migration_recovery_preserves_legacy_summary_and_vectors():
    import importlib.util
    from pathlib import Path

    from alembic.config import Config
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from tests.external_summary_schema_support import pre_import_metadata

    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == ["f05c8e31b742"]
    path = Path("migrations/versions/f05c8e31b742_external_summary_result_import.py")
    spec = importlib.util.spec_from_file_location("isolated_step4_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    prior = pre_import_metadata()
    isolated = create_engine("sqlite:///:memory:")
    tenant, user, project_id, document, run, job, chunk, summary = [uuid4() for _ in range(8)]
    with isolated.begin() as conn:
        prior.create_all(conn)
        conn.execute(
            prior.tables["tenants"].insert().values(id=tenant, name="Preserved", slug=str(tenant))
        )
        conn.execute(
            prior.tables["users"]
            .insert()
            .values(
                id=user,
                external_subject=str(user),
                email="synthetic@example.invalid",
                display_name="Synthetic",
            )
        )
        conn.execute(
            prior.tables["projects"]
            .insert()
            .values(id=project_id, tenant_id=tenant, created_by=user, name="Preserved")
        )
        conn.execute(
            prior.tables["documents"]
            .insert()
            .values(
                id=document,
                tenant_id=tenant,
                project_id=project_id,
                uploaded_by=user,
                file_name="synthetic.pdf",
                content_type="application/pdf",
                size_bytes=12,
                storage_key="synthetic-preserve",
            )
        )
        conn.execute(
            prior.tables["jobs"]
            .insert()
            .values(
                id=job,
                tenant_id=tenant,
                project_id=project_id,
                created_by=user,
                job_type="DOCUMENT_INGESTION",
            )
        )
        conn.execute(
            prior.tables["document_processing_runs"]
            .insert()
            .values(
                id=run,
                tenant_id=tenant,
                project_id=project_id,
                document_id=document,
                job_id=job,
                status="COMPLETED",
                document_content_sha256="a" * 64,
                extractor_name="test",
                extractor_version="1",
                chunker_version="1",
                embedding_provider="fastembed",
                embedding_model="synthetic",
                embedding_model_revision="a" * 40,
                embedding_dimensions=384,
                embedding_formatting_version="1",
            )
        )
        conn.execute(
            prior.tables["document_chunks"]
            .insert()
            .values(
                id=chunk,
                tenant_id=tenant,
                project_id=project_id,
                document_id=document,
                processing_run_id=run,
                ordinal=0,
                token_count=1,
                content="Preserved vector",
                content_sha256="b" * 64,
                block_type="paragraph",
                embedding=[0.1] * 384,
            )
        )
        conn.execute(
            prior.tables["document_summaries"]
            .insert()
            .values(
                id=summary,
                tenant_id=tenant,
                document_id=document,
                summary_text="Preserved approved legacy summary",
                is_approved=True,
                revision=3,
            )
        )
        with Operations.context(MigrationContext.configure(conn)):
            for _ in range(2):
                migration.upgrade()
                assert set(SummaryResultImport.__table__.columns.keys()) == {
                    c["name"] for c in inspect(conn).get_columns("summary_result_imports")
                }
                assert conn.exec_driver_sql(
                    "SELECT summary_text, revision, is_approved FROM document_summaries"
                ).first() == ("Preserved approved legacy summary", 3, 1)
                assert (
                    len(conn.execute(select(prior.tables["document_chunks"].c.embedding)).scalar())
                    == 384
                )
                migration.downgrade()
    isolated.dispose()


async def test_after_commit_failure_returns_existing_identity_on_recovery(
    client, workspace, complete
):
    _, request_id, _, _ = complete

    async def fail(stage, db):
        if stage == "committed":
            raise RuntimeError("Synthetic response loss")

    with pytest.raises(RuntimeError):
        await service.process_import(UUID(workspace), request_id, fault=fail)
    imported = await read_import(workspace, request_id)
    assert imported.state == "IMPORTED"
    assert await service.process_import(UUID(workspace), request_id) == imported.summary_id
    assert (await read_import(workspace, request_id)).imported_revision == 1


async def test_progress_reads_exclude_result_and_structured_payload(client, workspace, complete):
    created, request_id, _, _ = complete
    await service.process_import(UUID(workspace), request_id)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert status(client, workspace, created, request_id).status_code == 200
        assert (
            get_state(client, workspace, created["workflow_id"])["resume_screen"] == "doc_summary"
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not any(
        "jobs.result_payload" in query or "document_summaries.structured_summary" in query
        for query in statements
    )


async def test_legacy_worker_cannot_overwrite_imported_draft(client, workspace, complete):
    created, request_id, _, _ = complete
    summary_id = await service.process_import(UUID(workspace), request_id)
    job_id = uuid4()
    async with SessionLocal() as db:
        db.add(
            Job(
                id=job_id,
                tenant_id=UUID(workspace),
                project_id=UUID(created["project_id"]),
                created_by=get_settings().dev_user_id,
                job_type="DOCUMENT_SUMMARY",
                status="QUEUED",
            )
        )
        await db.commit()
    from app.services.workflows import process_document_summary

    with pytest.raises(RuntimeError, match="cannot replace"):
        await process_document_summary(job_id, UUID(created["document_id"]))
    async with SessionLocal() as db:
        summary = await db.get(DocumentSummary, summary_id)
        assert summary.source_request_id == request_id and summary.revision == 1


async def test_structured_read_is_scoped_and_corrupt_contract_is_sanitized(
    client, workspace, complete
):
    created, request_id, _, _ = complete
    summary_id = await service.process_import(UUID(workspace), request_id)
    default = get_settings().dev_tenant_id
    assert (
        client.get(
            f"/api/v1/tenants/{default}/documents/{created['document_id']}/summary"
        ).status_code
        == 404
    )
    async with SessionLocal() as db:
        summary = await db.get(DocumentSummary, summary_id)
        summary.structured_summary = {"private": "synthetic-corruption-must-not-echo"}
        await db.commit()
    response = client.get(f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary")
    assert response.status_code == 409 and "synthetic-corruption" not in response.text


async def test_compatible_fork_updates_but_historical_generation_lineage_is_preserved(
    client, workspace, complete
):
    created, request_id, _, _ = complete
    from app.models.external_summary import SummaryWorkflowBinding
    from app.services.external_summary_tracking import READ_PERMISSIONS, attach_request, read_status

    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        record = await db.get(SummaryApiRequest, request_id)
        fork = DocumentWorkflow(
            tenant_id=UUID(workspace), project_id=record.project_id, document_id=record.document_id
        )
        history = DocumentWorkflow(
            tenant_id=UUID(workspace), project_id=record.project_id, document_id=record.document_id
        )
        db.add_all([fork, history])
        await db.flush()
        await attach_request(db, record, fork)
        await attach_request(db, record, history)
        for workflow in [fork, history]:
            await read_status(
                db,
                UUID(workspace),
                record.document_id,
                request_id,
                READ_PERMISSIONS,
                workflow_id=workflow.id,
                bind=True,
            )
        historical_job = Job(
            tenant_id=UUID(workspace),
            project_id=record.project_id,
            created_by=get_settings().dev_user_id,
            job_type="WBS_GENERATION",
            status="COMPLETED",
        )
        db.add(historical_job)
        await db.flush()
        history.generation_job_id = historical_job.id
        fork_id, history_id = fork.id, history.id
        await db.commit()
    summary_id = await service.process_import(UUID(workspace), request_id)
    assert summary_id
    async with SessionLocal() as db:
        assert (await db.get(DocumentWorkflow, fork_id)).summary_id == summary_id
        historical = await db.get(DocumentWorkflow, history_id)
        assert historical.summary_id is None and historical.generation_job_id == historical_job.id
        assert (
            await db.scalar(
                select(SummaryWorkflowBinding.request_id).where(
                    SummaryWorkflowBinding.workflow_id == fork_id
                )
            )
            == request_id
        )


async def test_import_scope_foreign_key_rejects_another_project(client, workspace, complete):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    _, request_id, _, _ = complete
    async with SessionLocal() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        try:
            record = await db.get(SummaryApiRequest, request_id)
            now = datetime.now(UTC)
            db.add(
                SummaryResultImport(
                    request_id=request_id,
                    tenant_id=UUID(workspace),
                    project_id=uuid4(),
                    document_id=record.document_id,
                    state="WAITING",
                    first_completed_at=now,
                    available_at=now,
                    attempt_count=0,
                )
            )
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()
        finally:
            await db.execute(text("PRAGMA foreign_keys=OFF"))
            await db.commit()


@pytest.mark.skip(reason="No verified disposable PostgreSQL database and separate roles available")
def test_postgresql_rls_json_admission_competing_importers_and_recovery_pending():
    pass
