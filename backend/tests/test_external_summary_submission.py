"""Synthetic Step 1 checks. Run --noconftest -p tests.upload_transaction_support."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal, ensure_tenant_transaction
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Document, Job, TenantMembership
from app.models.external_summary import SummaryApiRequest
from app.schemas.external_summary import SubmissionAcknowledgement
from app.services import external_summary_submission as service
from app.services.external_summary_transport import (
    ORIGIN,
    PATH,
    SubmissionFailure,
    submission_configuration,
    submit_document,
)
from tests.test_document_deduplication_api import project, ready_ingestion, upload
from tests.test_document_deduplication_api import workspace as workspace  # noqa: F401

SYNTHETIC_KEY = "synthetic-summary-test-key-123456789"


@pytest.fixture(autouse=True)
def fake_broker(monkeypatch):
    from app.services.dispatcher import dispatch_app

    monkeypatch.setattr(dispatch_app, "send_task", lambda *args, **kwargs: None)


def acknowledgement(document_identity, **changes):
    job_id = str(uuid4())
    return {
        "job_id": job_id,
        "document_id": str(document_identity),
        "job_type": "DOCUMENT_SUMMERIZATION",
        "status": "RUNNING",
        "progress": 0,
        "current_step": "SUMMARY:QUEUED",
        "attempt_count": 0,
        "error_code": None,
        "error_message": None,
        "created_at": "2026-10-28T10:00:00Z",
        "updated_at": "2026-10-28T10:00:00Z",
        "result_url": f"/api/v2.1/project-summary/jobs/{job_id}/result",
        **changes,
    }


def policy():
    return Settings(
        _env_file=None,
        external_summary_enabled=True,
        external_summary_base_url=ORIGIN,
        external_summary_api_key=SecretStr(SYNTHETIC_KEY),
    )


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        yield self.data


async def transport_ack(document_id, payload=None, *, status=202, headers=None):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            status,
            headers=headers or {"content-type": "application/json"},
            stream=BytesStream(json.dumps(payload or acknowledgement(document_id)).encode()),
        )

    result = await submit_document(
        document_id, submission_configuration(policy()), transport=httpx.MockTransport(handler)
    )
    return result, captured


async def test_fixed_transport_and_acknowledgement():
    document = uuid4()
    ack, requests = await transport_ack(document)
    assert ack.document_id == document
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == ORIGIN + PATH
    assert request.method == "POST"
    assert json.loads(request.content) == {"document_id": str(document)}
    assert request.headers["x-api-key"] == SYNTHETIC_KEY
    assert request.headers["ngrok-skip-browser-warning"] == "true"
    assert request.headers["accept-encoding"] == "identity"
    assert SYNTHETIC_KEY not in repr(submission_configuration(policy()))
    assert "external_summary_api_key" not in policy().model_dump()


@pytest.mark.parametrize(
    "changes",
    [
        {"document_id": str(uuid4())},
        {"job_id": "bad"},
        {"job_type": "DOCUMENT_SUMMARY"},
        {"status": "COMPLETED"},
        {"progress": 101},
        {"progress": True},
        {"attempt_count": -1},
        {"current_step": "x" * 121},
        {"result_url": "https://attacker.example/result"},
        {"created_at": "2026-10-29T10:00:00Z"},
        {"error_message": SYNTHETIC_KEY},
    ],
)
async def test_invalid_acknowledgement_is_unknown_and_sanitized(changes):
    document = uuid4()
    with pytest.raises(SubmissionFailure) as caught:
        await transport_ack(document, acknowledgement(document, **changes))
    assert caught.value.ambiguous
    assert SYNTHETIC_KEY not in str(caught.value)


@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500, 503])
async def test_http_failure_is_conservatively_ambiguous(status):
    with pytest.raises(SubmissionFailure) as caught:
        await transport_ack(uuid4(), status=status)
    assert caught.value.ambiguous


async def test_bounded_protocol_and_transport_errors():
    document = uuid4()
    for data, headers in [
        (b"x" * 17000, {"content-type": "application/json"}),
        (b"{}", {"content-type": "text/html"}),
        (b"{}", {"content-type": "application/json", "content-encoding": "gzip"}),
        (b"malformed", {"content-type": "application/json"}),
    ]:
        with pytest.raises(SubmissionFailure):
            await submit_document(
                document,
                submission_configuration(policy()),
                transport=httpx.MockTransport(
                    lambda _, headers=headers, data=data: httpx.Response(
                        202, headers=headers, stream=BytesStream(data)
                    )
                ),
            )
    for exception, ambiguous in [
        (httpx.ConnectError("private"), False),
        (httpx.ReadTimeout("private"), True),
    ]:

        def fail(_, exception=exception):
            raise exception

        with pytest.raises(SubmissionFailure) as caught:
            await submit_document(
                document, submission_configuration(policy()), transport=httpx.MockTransport(fail)
            )
        assert caught.value.ambiguous is ambiguous
        assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost",
        ORIGIN + "/",
        ORIGIN + "@evil.test",
        ORIGIN + "/other",
        "https://127.0.0.1",
    ],
)
def test_operator_origin_is_exact(origin):
    settings = policy()
    settings.external_summary_base_url = origin
    with pytest.raises(SubmissionFailure):
        submission_configuration(settings)


def test_disabled_configuration_and_secret_errors():
    settings = Settings(
        _env_file=None, external_summary_enabled=False, external_summary_base_url="not configured"
    )
    assert not settings.external_summary_enabled
    for key in [None, SecretStr("short"), SecretStr("a" * 20 + "\r\nInjected")]:
        settings.external_summary_enabled = True
        settings.external_summary_base_url = ORIGIN
        settings.external_summary_api_key = key
        with pytest.raises(SubmissionFailure):
            submission_configuration(settings)


@pytest.fixture
async def prepared(client, workspace, monkeypatch):
    from app.api.routes import summaries

    created = upload(client, workspace, project(client, workspace)).json()["workflow"]
    await ready_ingestion(created["document_id"])
    settings = get_settings()
    monkeypatch.setattr(settings, "external_summary_enabled", True)
    monkeypatch.setattr(settings, "external_summary_base_url", ORIGIN)
    monkeypatch.setattr(settings, "external_summary_api_key", SecretStr(SYNTHETIC_KEY))
    publisher = AsyncMock()
    monkeypatch.setattr(summaries, "publish_submission", publisher)
    return created, publisher


def submit_route(client, workspace, created, key="synthetic-submit"):
    return client.post(
        f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary",
        params={"workflow_id": created["workflow_id"]},
        headers={"Idempotency-Key": key},
    )


async def read_request(workspace, request_id):
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        return await db.scalar(
            select(SummaryApiRequest).where(
                SummaryApiRequest.id == UUID(str(request_id)),
                SummaryApiRequest.tenant_id == UUID(workspace),
            )
        )


async def test_route_reuses_intent_without_job_or_workflow_binding(client, workspace, prepared):
    created, publisher = prepared
    first = submit_route(client, workspace, created)
    second = submit_route(client, workspace, created, "another-key")
    assert first.status_code == second.status_code == 202, first.text
    assert first.json()["request_id"] == second.json()["request_id"]
    assert first.json()["job_id"] is None
    record = await read_request(workspace, first.json()["request_id"])
    assert record.state == "SUBMIT_PENDING" and record.external_job_id is None
    assert SYNTHETIC_KEY not in first.text + repr(record.acknowledgement)
    assert publisher.await_count == 2
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.tenant_id == UUID(workspace), Job.job_type == "DOCUMENT_SUMMARY")
            )
            == 0
        )
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        assert workflow.summary_job_id is None


async def test_worker_acknowledges_once_outside_transaction(client, workspace, prepared):
    created, _ = prepared
    result = submit_route(client, workspace, created).json()
    calls = []

    async def fake(document_id, config):
        # A separate session can observe committed ownership before any HTTP work.
        row = await read_request(workspace, result["request_id"])
        assert row.state == "SUBMITTING" and row.owner_token
        calls.append(document_id)
        return SubmissionAcknowledgement.model_validate(acknowledgement(document_id))

    for _ in range(2):
        await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=fake)
    row = await read_request(workspace, result["request_id"])
    assert row.state == "ACKNOWLEDGED" and row.external_job_id
    assert len(calls) == 1 and row.owner_token is None


@pytest.mark.parametrize("ambiguous", [True, False])
async def test_worker_preserves_failure_classification(client, workspace, prepared, ambiguous):
    created, _ = prepared
    result = submit_route(client, workspace, created).json()

    async def fail(*_):
        raise SubmissionFailure("EXTERNAL_SUMMARY_CONNECT", ambiguous=ambiguous)

    await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=fail)
    row = await read_request(workspace, result["request_id"])
    assert row.state == ("SUBMISSION_UNKNOWN" if ambiguous else "SUBMIT_PENDING")
    assert row.external_job_id is None
    forbidden = AsyncMock(side_effect=AssertionError("must not send"))
    await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=forbidden)
    forbidden.assert_not_awaited()


async def test_expired_or_superseded_worker_cannot_ack(client, workspace, prepared):
    created, _ = prepared
    result = submit_route(client, workspace, created).json()

    async def expire(document_id, config):
        async with SessionLocal() as db:
            await ensure_tenant_transaction(db, UUID(workspace))
            row = await db.get(SummaryApiRequest, UUID(result["request_id"]))
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
            await db.commit()
        return SubmissionAcknowledgement.model_validate(acknowledgement(document_id))

    await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=expire)
    await service.reconcile_submissions()
    row = await read_request(workspace, result["request_id"])
    assert row.state == "SUBMISSION_UNKNOWN" and row.external_job_id is None


@pytest.mark.parametrize("change", ["revoked", "source", "archived", "unknown-role"])
async def test_worker_revalidates_before_send(client, workspace, prepared, change):
    from app.models.domain import Project

    created, _ = prepared
    result = submit_route(client, workspace, created).json()
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        if change in {"revoked", "unknown-role"}:
            member = await db.get(TenantMembership, (UUID(workspace), get_settings().dev_user_id))
            member.role = "VIEWER" if change == "revoked" else "UNKNOWN"
        elif change == "source":
            document = await db.get(Document, UUID(created["document_id"]))
            document.current_processing_run_id = None
        else:
            project_row = await db.get(Project, UUID(created["project_id"]))
            project_row.status = "ARCHIVED"
        await db.commit()
    fake = AsyncMock()
    await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=fake)
    fake.assert_not_awaited()
    assert (await read_request(workspace, result["request_id"])).state == "REJECTED"


async def test_cross_scope_and_configuration_errors(client, workspace, prepared, monkeypatch):
    created, publisher = prepared
    bad = dict(created, workflow_id=str(uuid4()))
    assert submit_route(client, workspace, bad).status_code == 404
    assert client.post(
        f"/api/v1/tenants/{uuid4()}/documents/{created['document_id']}/summary"
    ).status_code in {403, 404}
    monkeypatch.setattr(get_settings(), "external_summary_api_key", None)
    response = submit_route(client, workspace, created)
    assert response.status_code == 503
    publisher.assert_not_awaited()


async def test_id_only_publication_and_broker_failure_is_recoverable(prepared, monkeypatch):
    from fastapi import BackgroundTasks

    from app.services.dispatcher import dispatch_app

    # send_task is synchronous; inspect its arguments without touching a broker.
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("private broker details")

    monkeypatch.setattr(dispatch_app, "send_task", capture)
    settings = policy()
    settings.tasks_eager = False
    tenant_id, request_id = uuid4(), uuid4()
    await service.publish_submission(tenant_id, request_id, BackgroundTasks(), settings)
    assert calls == [
        ((service.TASK,), {"args": [str(tenant_id), str(request_id)], "serializer": "json"})
    ]


async def test_reused_key_alias_cannot_name_other_content(client, workspace, prepared):
    created, _ = prepared
    first = submit_route(client, workspace, created).json()
    assert (
        submit_route(client, workspace, created, "alias").json()["request_id"]
        == first["request_id"]
    )
    other = upload(
        client,
        workspace,
        project(client, workspace),
        content=b"Task,Description\n1,Another synthetic source\n",
    ).json()["workflow"]
    await ready_ingestion(other["document_id"])
    assert submit_route(client, workspace, other, "alias").status_code == 409


@pytest.mark.parametrize("change", ["viewer", "unknown", "incomplete", "deleting"])
async def test_route_denies_ineligible_submission(client, workspace, prepared, change):
    created, publisher = prepared
    async with SessionLocal() as db:
        await ensure_tenant_transaction(db, UUID(workspace))
        if change in {"viewer", "unknown"}:
            member = await db.get(TenantMembership, (UUID(workspace), get_settings().dev_user_id))
            member.role = "VIEWER" if change == "viewer" else "UNKNOWN"
        else:
            document = await db.get(Document, UUID(created["document_id"]))
            if change == "incomplete":
                document.current_processing_run_id = None
            else:
                document.lifecycle_status = "DELETING"
                document.deletion_requested_at = document.vectors_hidden_at = datetime.now(UTC)
        await db.commit()
    assert submit_route(client, workspace, created).status_code in {403, 409, 410}
    publisher.assert_not_awaited()


async def test_cancelled_worker_expires_unknown(client, workspace, prepared):
    import asyncio

    created, _ = prepared
    result = submit_route(client, workspace, created).json()

    async def cancel(*_):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=cancel)
    row = await read_request(workspace, result["request_id"])
    assert row.state == "SUBMITTING" and row.external_job_id is None


async def test_replaced_fence_rejects_late_ack(client, workspace, prepared):
    created, _ = prepared
    result = submit_route(client, workspace, created).json()

    async def replace(document_id, config):
        async with SessionLocal() as db:
            await ensure_tenant_transaction(db, UUID(workspace))
            row = await db.get(SummaryApiRequest, UUID(result["request_id"]))
            row.owner_token = uuid4()
            await db.commit()
        return SubmissionAcknowledgement.model_validate(acknowledgement(document_id))

    await service.process_submission(UUID(workspace), UUID(result["request_id"]), submit=replace)
    row = await read_request(workspace, result["request_id"])
    assert row.state == "SUBMITTING" and row.external_job_id is None


async def test_http_policy_does_not_use_redirects_proxies_or_disable_tls(monkeypatch):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    await transport_ack(uuid4())
    assert options[0]["verify"] is True
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False


def test_submission_migration_upgrade_downgrade_isolated():
    import importlib.util
    from pathlib import Path

    from alembic.config import Config
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    from app.models.external_summary import SummarySubmissionKey
    from tests.external_summary_schema_support import pre_import_metadata

    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["f05c8e31b742"]
    assert scripts.get_revision("d82f6a913b70").down_revision == "c92e6b4a710d"
    path = Path("migrations/versions/d82f6a913b70_external_summary_submission_intents.py")
    spec = importlib.util.spec_from_file_location("isolated_summary_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    new_tables = {"summary_api_requests", "summary_submission_keys", "summary_workflow_bindings"}
    with engine.begin() as connection:
        pre_import_metadata(new_tables).create_all(connection)
        connection.exec_driver_sql(
            "INSERT INTO tenants (id,name,slug,is_active) VALUES "
            "('00000000000000000000000000000001','preserve','preserve',1)"
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for _ in range(2):
                migration.upgrade()
                for model in [SummaryApiRequest, SummarySubmissionKey]:
                    assert {
                        column["name"]
                        for column in inspect(connection).get_columns(model.__tablename__)
                    } == set(model.__table__.columns.keys()) - {"database_verified_at"}
                migration.downgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM tenants").scalar() == 1
    engine.dispose()


async def test_disabled_external_branch_keeps_legacy_submission(
    client, workspace, prepared, monkeypatch
):
    from unittest.mock import Mock

    from app.api.routes import summaries

    created, publisher = prepared
    monkeypatch.setattr(get_settings(), "external_summary_enabled", False)
    monkeypatch.setattr(get_settings(), "document_workflow_resume_enabled", False)
    legacy_dispatch = Mock()
    monkeypatch.setattr(summaries, "dispatch_summary", legacy_dispatch)
    result = submit_route(client, workspace, created)
    assert result.status_code == 202, result.text
    assert result.json()["job_type"] == "DOCUMENT_SUMMARY"
    assert "request_id" not in result.json()
    legacy_dispatch.assert_called_once()
    publisher.assert_not_awaited()


@pytest.mark.skip(reason="No verified disposable PostgreSQL/migration/runtime roles provisioned")
def test_postgresql_rls_and_competing_claims_pending():
    """SQLite tests above must never be reported as PostgreSQL verification."""
