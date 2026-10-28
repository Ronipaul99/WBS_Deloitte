"""Step 6 fault/security regressions; isolated --noconftest plugin only."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import BackgroundTasks
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.domain import DocumentSummary, Tenant, TenantMembership, User
from app.models.external_summary import SummaryApiRequest
from app.schemas.external_summary import SubmissionAcknowledgement
from app.services import external_summary_submission as service
from app.services.external_summary_transport import SubmissionFailure
from tests.test_document_deduplication_api import workspace as workspace  # noqa: F401
from tests.test_external_summary_import import complete as complete  # noqa: F401
from tests.test_external_summary_review import approval, patch
from tests.test_external_summary_review import draft as draft  # noqa: F401
from tests.test_external_summary_submission import acknowledgement, read_request, submit_route
from tests.test_external_summary_submission import fake_broker as fake_broker
from tests.test_external_summary_submission import prepared as prepared  # noqa: F401
from tests.test_external_summary_tracking import acknowledged as acknowledged  # noqa: F401


@pytest.fixture(autouse=True)
async def restore_synthetic_user(client):
    # The isolated plugin shares its synthetic bootstrap user across test cases.
    async with SessionLocal() as db:
        user = await db.get(User, get_settings().dev_user_id)
        original = (user.is_active, user.auth_version)
    try:
        yield
    finally:
        async with SessionLocal() as db:
            user = await db.get(User, get_settings().dev_user_id)
            user.is_active, user.auth_version = original
            await db.commit()


@pytest.mark.parametrize("operation", ["save", "approve"])
@pytest.mark.parametrize("change", ["role", "user", "tenant", "auth_version"])
async def test_revocation_after_route_admission_prevents_review_write(
    client, workspace, draft, monkeypatch, operation, change
):
    from app.api.routes import summaries

    _, _, _, _, _, base = draft
    original = summaries.lock_review

    async def after_admission(db, tenant_id, document_id):
        async with SessionLocal() as revoked:
            member = await revoked.scalar(
                select(TenantMembership).where(TenantMembership.tenant_id == UUID(workspace))
            )
            if change == "role":
                member.role = "VIEWER"
            elif change == "tenant":
                (await revoked.get(Tenant, UUID(workspace))).is_active = False
            else:
                user = await revoked.get(User, get_settings().dev_user_id)
                if change == "user":
                    user.is_active = False
                else:
                    user.auth_version += 1
            await revoked.commit()
        return await original(db, tenant_id, document_id)

    monkeypatch.setattr(summaries, "lock_review", after_admission)
    response = (
        client.patch(base, json=patch())
        if operation == "save"
        else client.post(base + "/approve", json=approval(1))
    )
    assert response.status_code == 403
    async with SessionLocal() as db:
        current = await db.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == UUID(draft[0]["document_id"])
            )
        )
        assert current.revision == 1 and not current.is_approved


@pytest.mark.parametrize("role", ["ADMIN", "EDITOR"])
async def test_existing_authorized_roles_can_read_edit_and_approve(client, workspace, draft, role):
    _, request_id, _, _, _, base = draft
    async with SessionLocal() as db:
        member = await db.scalar(
            select(TenantMembership).where(TenantMembership.tenant_id == UUID(workspace))
        )
        member.role = role
        await db.commit()
    assert client.get(base).status_code == 200
    assert client.get(base + f"/requests/{request_id}").status_code == 200
    saved = client.patch(base, json=patch())
    assert saved.status_code == 200
    assert (
        client.post(base + "/approve", json=approval(saved.json()["revision"])).status_code == 200
    )


async def test_intent_commit_failure_leaves_no_delivery_or_partial_request(
    client, workspace, prepared, monkeypatch
):
    created, publisher = prepared
    commit = AsyncSession.commit

    async def fail_intent_commit(db):
        if any(
            isinstance(row, SummaryApiRequest) and row.state == "SUBMIT_PENDING"
            for row in db.identity_map.values()
        ):
            raise RuntimeError("synthetic-intent-commit-failure")
        await commit(db)

    with monkeypatch.context() as fault:
        fault.setattr(AsyncSession, "commit", fail_intent_commit)
        with pytest.raises(RuntimeError, match="synthetic-intent-commit-failure"):
            submit_route(client, workspace, created)
    publisher.assert_not_awaited()
    async with SessionLocal() as db:
        assert (
            await db.scalar(
                select(SummaryApiRequest.id).where(
                    SummaryApiRequest.document_id == UUID(created["document_id"])
                )
            )
            is None
        )
    assert submit_route(client, workspace, created).status_code == 202


async def test_safe_retry_resolves_rotated_secret_and_keeps_attempt_count(
    client, workspace, prepared
):
    created, _ = prepared
    request_id = UUID(submit_route(client, workspace, created).json()["request_id"])
    seen = []

    async def safe_failure(document_id, config):
        seen.append(config.key)
        raise SubmissionFailure("EXTERNAL_SUMMARY_CONNECT", ambiguous=False)

    await service.process_submission(UUID(workspace), request_id, submit=safe_failure)
    async with SessionLocal() as db:
        row = await db.get(SummaryApiRequest, request_id)
        assert row.state == "SUBMIT_PENDING" and row.attempt_count == 1
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    get_settings().external_summary_api_key = SecretStr("synthetic-rotated-summary-key-123456789")

    async def success(document_id, config):
        seen.append(config.key)
        return SubmissionAcknowledgement.model_validate(acknowledgement(document_id))

    await service.process_submission(UUID(workspace), request_id, submit=success)
    row = await read_request(workspace, request_id)
    assert row.state == "ACKNOWLEDGED" and row.attempt_count == 2
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(secret not in repr(row.acknowledgement) for secret in seen)


async def test_publish_then_raise_and_duplicate_delivery_use_one_submission(
    client, workspace, prepared, monkeypatch, caplog
):
    from app.services.dispatcher import dispatch_app

    created, _ = prepared
    request_id = UUID(submit_route(client, workspace, created).json()["request_id"])
    messages = []

    def lost_broker_ack(name, **kwargs):
        messages.append((name, kwargs["args"]))
        raise RuntimeError("synthetic-private-broker-detail")

    monkeypatch.setattr(dispatch_app, "send_task", lost_broker_ack)
    settings = get_settings().model_copy(update={"tasks_eager": False})
    await service.publish_submission(UUID(workspace), request_id, BackgroundTasks(), settings)
    assert messages == [(service.TASK, [workspace, str(request_id)])]
    calls = []

    async def submit(identity, config):
        calls.append(identity)
        return SubmissionAcknowledgement.model_validate(acknowledgement(identity))

    await service.process_submission(UUID(workspace), request_id, submit=submit)
    await service.process_submission(UUID(workspace), request_id, submit=submit)
    assert len(calls) == 1
    assert "synthetic-private-broker-detail" not in caplog.text


async def test_lost_database_ack_expires_unknown_without_remote_replay(
    client, workspace, prepared, monkeypatch
):
    created, _ = prepared
    request_id = UUID(submit_route(client, workspace, created).json()["request_id"])
    commit = AsyncSession.commit
    calls = []

    async def fail_ack_commit(db):
        if any(
            isinstance(row, SummaryApiRequest) and row.state == "ACKNOWLEDGED" for row in db.dirty
        ):
            raise RuntimeError("synthetic-ack-persistence-failure")
        await commit(db)

    async def submit(identity, config):
        calls.append(identity)
        return SubmissionAcknowledgement.model_validate(acknowledgement(identity))

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", fail_ack_commit)
        with pytest.raises(RuntimeError, match="synthetic-ack-persistence-failure"):
            await service.process_submission(UUID(workspace), request_id, submit=submit)
    async with SessionLocal() as db:
        row = await db.get(SummaryApiRequest, request_id)
        assert row.state == "SUBMITTING"
        row.lease_expires_at = row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    await service.reconcile_submissions()
    assert (await read_request(workspace, request_id)).state == "SUBMISSION_UNKNOWN"
    await service.process_submission(UUID(workspace), request_id, submit=submit)
    assert len(calls) == 1


def test_hostile_nested_payload_is_bounded_and_sanitized():
    from app.services.external_summary_import import ImportFailure, validate_result

    value = {"private": "synthetic-private-body"}
    for _ in range(2000):
        value = [value]
    with pytest.raises(ImportFailure) as caught:
        validate_result(value, None)
    assert str(caught.value) in {
        "SUMMARY_RESULT_ENCODING_INVALID",
        "SUMMARY_RESULT_CONTRACT_INVALID",
    }


@pytest.mark.skip(reason="No verified disposable PostgreSQL or restricted runtime roles supplied")
def test_postgresql_concurrent_recovery_and_permission_fencing_pending():
    pass
