"""Step 2 synthetic metadata tests; --noconftest -p tests.upload_transaction_support."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db.session import SessionLocal, engine, ensure_tenant_transaction
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Document, DocumentSummary, Job, TenantMembership
from app.models.external_summary import SummaryApiRequest
from app.services import external_summary_tracking as tracking
from tests.test_document_deduplication_api import get_state
from tests.test_document_deduplication_api import workspace as workspace  # noqa: F401
from tests.test_external_summary_submission import acknowledgement, submit_route  # noqa: F401
from tests.test_external_summary_submission import prepared as prepared

PRIVATE = "synthetic-private-error-must-not-escape"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from app.services.dispatcher import dispatch_app

    monkeypatch.setattr(dispatch_app, "send_task", lambda *a, **kw: None)


@pytest.fixture
async def acknowledged(client, workspace, prepared):
    created, _ = prepared
    response = submit_route(client, workspace, created)
    assert response.status_code == 202, response.text
    request_id = UUID(response.json()["request_id"])
    job_id = uuid4()
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        request = await db.get(SummaryApiRequest, request_id)
        request.state = "ACKNOWLEDGED"
        request.external_job_id = job_id
        request.acknowledgement = acknowledgement(
            request.document_id,
            job_id=str(job_id),
            result_url=f"/api/v2.1/project-summary/jobs/{job_id}/result",
        )
        await db.commit()
    return created, request_id, job_id


async def external_job(workspace, created, job_id, **changes):
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        values = dict(
            id=job_id,
            tenant_id=UUID(workspace),
            project_id=UUID(created["project_id"]),
            created_by=get_settings().dev_user_id,
            job_type="DOCUMENT_SUMMERIZATION",
            status="RUNNING",
            progress=31,
            current_step="SUMMARY:READING",
            request_payload={"document_id": created["document_id"]},
            result_payload={"private": PRIVATE},
            error_message=PRIVATE,
        )
        values.update(changes)
        db.add(Job(**values))
        await db.commit()


def status(client, workspace, created, request_id, **params):
    return client.get(
        f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary/requests/{request_id}",
        params=params,
    )


async def test_exact_row_metadata_binding_and_no_execution_mutation(
    client, workspace, acknowledged
):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, workflow_id=UUID(created["workflow_id"]))
    await external_job(workspace, created, uuid4(), progress=99, current_step="wrong newer job")
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = status(client, workspace, created, request_id)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == str(job_id) and body["request_id"] == str(request_id)
    assert body["provider_status"] == "RUNNING" and body["status"] == "IN_PROGRESS"
    assert body["progress"] == 31 and body["current_step"] == "SUMMARY:READING"
    assert body["binding_state"] == "VERIFIED" and not body["can_retry"] and not body["can_cancel"]
    assert PRIVATE not in response.text and "result_payload" not in response.text
    assert not any("result_payload" in sql for sql in statements)
    assert not any("update jobs" in sql for sql in statements)
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        assert workflow.summary_job_id == job_id
        revision = workflow.checkpoint_revision
        job = await db.get(Job, job_id)
        assert job.status == "RUNNING" and job.result_payload == {"private": PRIVATE}
        assert job.workflow_id == workflow.id
    assert status(client, workspace, created, request_id).status_code == 200
    async with SessionLocal() as db:
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        assert workflow.checkpoint_revision == revision


@pytest.mark.parametrize(
    ("wire", "progress", "normalized", "result"),
    [
        ("QUEUED", 0, "QUEUED", "NOT_READY"),
        ("RUNNING", 100, "IN_PROGRESS", "NOT_READY"),
        ("COMPLETED", 100, "COMPLETED", "IMPORT_PENDING"),
        ("completed", 100, "COMPLETED", "IMPORT_PENDING"),
        ("COMPLETED", 80, "IN_PROGRESS", "NOT_READY"),
        ("FAILED", 100, "FAILED", "NOT_READY"),
        ("CANCELLED", 100, "CANCELLED", "NOT_READY"),
    ],
)
async def test_explicit_status_policy(
    client, workspace, acknowledged, wire, progress, normalized, result
):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, status=wire, progress=progress)
    response = status(client, workspace, created, request_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == normalized
    assert response.json()["provider_status"] == wire
    assert response.json()["result_state"] == result
    assert response.json()["summary_id"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"job_type": "DOCUMENT_SUMMARY"},
        {"project_id": None},
        {"request_payload": {"document_id": str(uuid4())}},
        {"request_payload": []},
        {"request_payload": "not-an-object"},
        {"request_payload": {"document_id": 123}},
    ],
)
async def test_wrong_contract_never_replaced_by_latest(client, workspace, acknowledged, changes):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, **changes)
    await external_job(workspace, created, uuid4())
    response = status(client, workspace, created, request_id)
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["error_code"] == "SUMMARY_JOB_SCOPE_OR_TYPE_INVALID"
    async with SessionLocal() as db:
        assert (await db.get(DocumentWorkflow, UUID(created["workflow_id"]))).summary_job_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "running"},
        {"status": "SUCCESS"},
        {"current_step": "x" * 121},
        {"current_step": "unsafe\r\nstep"},
        {"attempt_count": 1001},
    ],
)
async def test_unsupported_metadata_fails_closed(client, workspace, acknowledged, changes):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, **changes)
    response = status(client, workspace, created, request_id)
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["binding_state"] == "UNAVAILABLE"


async def test_missing_visibility_grace_then_exact_recovery(client, workspace, acknowledged):
    created, request_id, job_id = acknowledged
    assert (
        status(client, workspace, created, request_id).json()["binding_state"] == "WAITING_FOR_JOB"
    )
    async with SessionLocal() as db:
        request = await db.get(SummaryApiRequest, request_id)
        request.updated_at = datetime.now(UTC) - timedelta(seconds=601)
        await db.commit()
    assert (
        status(client, workspace, created, request_id).json()["error_code"]
        == "SUMMARY_JOB_VISIBILITY_EXPIRED"
    )
    await external_job(workspace, created, job_id)
    assert status(client, workspace, created, request_id).json()["binding_state"] == "VERIFIED"


async def test_inconsistent_completion_deadline_cannot_be_extended_by_heartbeat(
    client, workspace, acknowledged
):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, status="COMPLETED", progress=80)
    async with SessionLocal() as db:
        request = await db.get(SummaryApiRequest, request_id)
        request.updated_at = datetime.now(UTC) - timedelta(seconds=601)
        await db.commit()
    response = status(client, workspace, created, request_id)
    assert response.json()["error_code"] == "SUMMARY_COMPLETION_INCONSISTENT"


async def test_recovery_pending_and_completed_never_reopens_old_draft(client, workspace, prepared):
    created, _ = prepared
    async with SessionLocal() as db:
        db.add(
            DocumentSummary(
                tenant_id=UUID(workspace),
                document_id=UUID(created["document_id"]),
                summary_text="Old draft",
                is_approved=True,
            )
        )
        await db.commit()
    submission = submit_route(client, workspace, created)
    assert submission.status_code == 202, submission.text
    request_id = UUID(submission.json()["request_id"])
    pending = get_state(client, workspace, created["workflow_id"])
    assert pending["stage"] == "SUMMARIZING" and pending["summary_id"] is None
    assert "start_summary" not in pending["allowed_actions"]
    async with SessionLocal() as db:
        request = await db.get(SummaryApiRequest, request_id)
        request.state, request.external_job_id = "ACKNOWLEDGED", uuid4()
        job_id = request.external_job_id
        await db.commit()
    await external_job(workspace, created, job_id, status="COMPLETED", progress=100)
    complete = get_state(client, workspace, created["workflow_id"])
    assert complete["stage"] == "SUMMARIZING" and complete["resume_screen"] == "checkpoint"
    assert complete["external_summary"]["result_state"] == "IMPORT_PENDING"
    assert complete["summary_id"] is None and "start_generation" not in complete["allowed_actions"]


async def test_stale_checkpoint_and_source_reject_binding(client, workspace, acknowledged):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id)
    async with SessionLocal() as db:
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        workflow.checkpoint_revision += 1
        await db.commit()
    assert (
        status(client, workspace, created, request_id).json()["error_code"]
        == "SUMMARY_CHECKPOINT_CHANGED"
    )
    async with SessionLocal() as db:
        document = await db.get(Document, UUID(created["document_id"]))
        document.current_processing_run_id = None
        await db.commit()
    assert status(client, workspace, created, request_id).json()["binding_state"] == "STALE"


async def test_cross_scope_permissions_and_revocation(client, workspace, acknowledged):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id)
    assert (
        status(client, workspace, dict(created, document_id=str(uuid4())), request_id).status_code
        == 404
    )
    assert status(client, str(uuid4()), created, request_id).status_code in {403, 404}
    assert status(client, workspace, created, uuid4()).status_code == 404
    assert (
        status(client, workspace, created, request_id, workflow_id=str(uuid4())).json()["status"]
        == "UNAVAILABLE"
    )
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        with pytest.raises(Exception) as caught:
            await tracking.read_status(
                db, UUID(workspace), UUID(created["document_id"]), request_id, []
            )
        assert caught.value.status_code == 403
        member = await db.get(TenantMembership, (UUID(workspace), get_settings().dev_user_id))
        member.role = "VIEWER"
        await db.commit()
    # Viewer can read metadata, but revoked submission authority prevents new binding.
    assert status(client, workspace, created, request_id).json()["binding_state"] == "STALE"


async def test_generic_job_boundaries_never_load_payload_or_mutate(client, workspace, acknowledged):
    created, _, job_id = acknowledged
    await external_job(workspace, created, job_id)
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        base = f"/api/v1/tenants/{workspace}/jobs/{job_id}"
        for method, suffix in [
            ("GET", ""),
            ("GET", "/events"),
            ("POST", "/cancel"),
            ("POST", "/retry"),
        ]:
            response = client.request(method, base + suffix)
            assert response.status_code == 409, response.text
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert not any("result_payload" in sql or "update jobs" in sql for sql in statements)


async def test_database_failure_is_sanitized(client, workspace, acknowledged, monkeypatch):
    created, request_id, _ = acknowledged

    async def offline(*a, **kw):
        raise OperationalError("private-sql", {}, Exception(PRIVATE))

    monkeypatch.setattr(tracking, "read_status", offline)
    response = status(client, workspace, created, request_id)
    assert response.status_code == 503 and PRIVATE not in response.text


async def test_worker_tracking_and_fork_do_not_steal_job_workflow(client, workspace, acknowledged):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id, workflow_id=UUID(created["workflow_id"]))
    async with SessionLocal() as db:
        original = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        fork = DocumentWorkflow(
            tenant_id=original.tenant_id,
            project_id=original.project_id,
            document_id=original.document_id,
            is_base=False,
        )
        db.add(fork)
        await db.commit()
        fork_id = fork.id
    fork_data = dict(created, workflow_id=str(fork_id))
    response = submit_route(client, workspace, fork_data, "fork-key")
    assert response.status_code == 202, response.text
    assert response.json()["request_id"] == str(request_id)
    await tracking.reconcile_tracking()
    async with SessionLocal() as db:
        for workflow_id in [UUID(created["workflow_id"]), fork_id]:
            assert (await db.get(DocumentWorkflow, workflow_id)).summary_job_id == job_id
        assert (await db.get(Job, job_id)).workflow_id == UUID(created["workflow_id"])
        assert (await db.get(SummaryApiRequest, request_id)).database_verified_at


@pytest.mark.parametrize("progress", [True, -1, 101, "50"])
def test_metadata_progress_is_strict(progress):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        tracking.JobMetadata(
            status="RUNNING", progress=progress, current_step=None, attempt_count=0
        )


async def test_actual_foreign_tenant_row_cannot_bind(client, workspace, acknowledged):
    from app.models.domain import Tenant

    created, request_id, job_id = acknowledged
    async with SessionLocal() as db:
        tenant = Tenant(name="Foreign synthetic", slug=f"foreign-{uuid4()}")
        db.add(tenant)
        await db.flush()
        foreign_id = tenant.id
        await db.commit()
    await external_job(workspace, created, job_id, tenant_id=foreign_id, project_id=None)
    response = status(client, workspace, created, request_id)
    assert response.json()["binding_state"] == "WAITING_FOR_JOB"
    async with SessionLocal() as db:
        assert (await db.get(DocumentWorkflow, UUID(created["workflow_id"]))).summary_job_id is None


async def test_original_association_gap_is_not_silently_backfilled(client, workspace, acknowledged):
    from sqlalchemy import delete

    from app.models.external_summary import SummaryWorkflowBinding

    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id)
    async with SessionLocal() as db:
        await db.execute(
            delete(SummaryWorkflowBinding).where(SummaryWorkflowBinding.request_id == request_id)
        )
        await db.commit()
    response = status(client, workspace, created, request_id)
    assert response.json()["error_code"] == "SUMMARY_ASSOCIATION_MISSING"
    assert submit_route(client, workspace, created).status_code == 202
    assert status(client, workspace, created, request_id).json()["binding_state"] == "VERIFIED"


async def test_committed_scope_and_read_queries_survive_fresh_sessions(workspace, acknowledged):
    created, request_id, job_id = acknowledged
    await external_job(workspace, created, job_id)
    for finish in ("commit", "rollback"):
        async with SessionLocal() as db:
            await db.begin()
            await getattr(db, finish)()
            result = await tracking.read_status(
                db,
                UUID(workspace),
                UUID(created["document_id"]),
                request_id,
                tracking.READ_PERMISSIONS,
            )
            assert result.status == "IN_PROGRESS"
            assert db.in_transaction()


async def test_association_fk_rejects_cross_document_workflow(client, workspace, acknowledged):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.models.external_summary import SummaryWorkflowBinding
    from tests.test_document_deduplication_api import upload

    created, request_id, _ = acknowledged
    other = upload(
        client, workspace, created["project_id"], content=b"Task,Description\n1,Other scope\n"
    ).json()["workflow"]
    async with SessionLocal() as db:
        await db.execute(text("PRAGMA foreign_keys=ON"))
        assert await db.scalar(text("PRAGMA foreign_keys")) == 1
        await ensure_tenant_transaction(db, UUID(workspace))
        db.add(
            SummaryWorkflowBinding(
                workflow_id=UUID(other["workflow_id"]),
                tenant_id=UUID(workspace),
                project_id=UUID(created["project_id"]),
                document_id=UUID(created["document_id"]),
                request_id=request_id,
                expected_checkpoint=1,
            )
        )
        try:
            with pytest.raises(IntegrityError):
                await db.flush()
        finally:
            await db.rollback()
            await db.execute(text("PRAGMA foreign_keys=OFF"))


async def test_pending_request_checkpoint_change_is_stale(client, workspace, prepared):
    created, _ = prepared
    response = submit_route(client, workspace, created)
    async with SessionLocal() as db:
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        workflow.checkpoint_revision += 1
        await db.commit()
    assert (
        status(client, workspace, created, response.json()["request_id"]).json()["binding_state"]
        == "STALE"
    )


def test_step2_migration_upgrade_recovery_preserves_existing_data():
    import importlib.util
    from pathlib import Path

    from alembic.config import Config
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from app.models.external_summary import SummarySubmissionKey, SummaryWorkflowBinding
    from tests.external_summary_schema_support import pre_import_metadata

    assert ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == ["f05c8e31b742"]

    def load(name):
        path = next(Path("migrations/versions").glob(name + "*.py"))
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    first, second = load("d82f6a913b70"), load("e94b7d20a631")
    exclude = {"summary_api_requests", "summary_submission_keys", "summary_workflow_bindings"}
    metadata = pre_import_metadata(exclude)
    workflow_table = metadata.tables["document_workflows"]
    workflow_table.constraints.remove(
        next(
            constraint
            for constraint in workflow_table.constraints
            if constraint.name == "uq_workflow_document_binding"
        )
    )
    isolated = create_engine("sqlite:///:memory:")
    with isolated.begin() as conn:
        metadata.create_all(conn)
        conn.exec_driver_sql(
            "INSERT INTO tenants (id,name,slug,is_active) VALUES "
            "('00000000000000000000000000000001','preserve','preserve',1)"
        )
        with Operations.context(MigrationContext.configure(conn)):
            first.upgrade()
            for _ in range(2):
                second.upgrade()
                for model in (SummaryApiRequest, SummarySubmissionKey, SummaryWorkflowBinding):
                    assert {
                        column["name"] for column in inspect(conn).get_columns(model.__tablename__)
                    } == set(model.__table__.columns.keys())
                assert any(
                    constraint["name"] == "fk_summary_binding_workflow"
                    for constraint in inspect(conn).get_foreign_keys("summary_workflow_bindings")
                )
                second.downgrade()
            assert conn.exec_driver_sql("SELECT count(*) FROM tenants").scalar() == 1
    isolated.dispose()


@pytest.mark.skip(reason="No verified disposable PostgreSQL target and separate roles provisioned")
def test_postgresql_json_rls_pooling_and_concurrent_binding_pending():
    """SQLite metadata/FK tests do not establish these PostgreSQL properties."""
