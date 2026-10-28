"""Step 5 production API tests with isolated synthetic SQLite fixtures."""

import copy
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document_workflows import DocumentWorkflow
from app.models.domain import Document, DocumentSummary, Job, TenantMembership
from app.services import external_summary_import as importer
from tests.test_document_deduplication_api import get_state
from tests.test_document_deduplication_api import workspace as workspace
from tests.test_external_summary_import import complete as complete
from tests.test_external_summary_import import read_import
from tests.test_external_summary_submission import fake_broker as fake_broker
from tests.test_external_summary_submission import prepared as prepared
from tests.test_external_summary_tracking import acknowledged as acknowledged


@pytest.fixture
async def draft(workspace, complete):
    created, request_id, job_id, raw = complete
    summary_id = await importer.process_import(UUID(workspace), request_id)
    base = f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary"
    return created, request_id, job_id, raw, summary_id, base


def patch(content="Edited caf\u00e9 text. [1]", revision=1, **changes):
    return {
        "format": "external_summary_v1",
        "expected_revision": revision,
        "sections": [{"id": "sec_1", "key": "project_overview", "content": content}],
        **changes,
    }


def approval(revision):
    return {"format": "external_summary_v1", "expected_revision": revision}


async def test_partial_edit_noop_approval_replay_and_scope(client, workspace, draft):
    created, request_id, job_id, raw, summary_id, base = draft
    initial = client.get(base).json()
    response = client.patch(base, json=patch())
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 2 and not saved["is_approved"]
    assert saved["structured_summary"]["generated_result"] == raw
    assert saved["structured_summary"]["current_sections"] == patch()["sections"]
    assert saved["structured_summary"]["content_state"] == "edited_review_required"
    assert saved["requirements"] == saved["key_points"] == []
    assert "Edited caf\u00e9 text." in saved["summary_text"]
    assert saved["provenance"] == initial["provenance"]
    assert saved["capabilities"] == {
        "structured_review_available": True,
        "can_generate_wbs": False,
        "reason": "REQUIREMENTS_CONTRACT_UNAVAILABLE",
    }
    state = get_state(client, workspace, created["workflow_id"])
    assert state["resume_screen"] == "doc_summary" and state["summary_revision"] == 2
    assert "start_generation" not in state["allowed_actions"]
    before = state["checkpoint_revision"]
    approved = client.post(base + "/approve", json=approval(2))
    assert approved.status_code == 200, approved.text
    approved = approved.json()
    assert approved["is_approved"] and approved["revision"] == 2
    assert (
        client.post(base + "/approve", json=approval(2)).json()["approved_at"]
        == approved["approved_at"]
    )
    assert get_state(client, workspace, created["workflow_id"])["checkpoint_revision"] == before + 1
    noop = client.patch(base, json=patch(revision=2)).json()
    assert noop["revision"] == 2 and noop["approved_at"] == approved["approved_at"]
    assert client.patch(base, json=patch(revision=1)).status_code == 409
    assert client.post(base + "/approve", json=approval(1)).status_code == 409
    second = client.patch(base, json=patch("New local text [99]", 2)).json()
    assert second["revision"] == 3 and second["is_approved"] is False
    assert second["approved_at"] is None
    assert await importer.process_import(UUID(workspace), request_id) == summary_id
    assert client.get(base).json()["structured_summary"] == second["structured_summary"]
    assert (await read_import(workspace, request_id)).imported_revision == 1
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.result_payload == raw and job.status == "COMPLETED"
    foreign = base.replace(workspace, str(get_settings().dev_tenant_id))
    assert client.get(foreign).status_code == 404
    assert client.patch(foreign, json=patch()).status_code == 404
    assert client.post(foreign + "/approve", json=approval(3)).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "key",
        "unknown",
        "limit",
        "extra",
        "citation",
        "raise_limit",
        "bool_revision",
        "null",
        "wrong_format",
        "nul",
        "surrogate",
    ],
)
async def test_reject_forged_and_bounded_edits_without_echo(client, draft, change):
    *_, base = draft
    body = patch()
    if change == "duplicate":
        body["sections"] *= 2
    elif change == "key":
        body["sections"][0]["key"] = "project_scope"
    elif change == "unknown":
        body["sections"][0]["id"] = "foreign"
    elif change == "limit":
        body["sections"][0]["content"] = "x" * 2001
    elif change == "extra":
        body["provenance"] = "synthetic-private-must-not-echo"
    elif change == "citation":
        body["sections"][0]["evidence_citations"] = ["synthetic-private-must-not-echo"]
    elif change == "raise_limit":
        body["sections"][0]["max_length"] = 3000
    elif change == "bool_revision":
        body["expected_revision"] = True
    elif change == "null":
        body["sections"][0]["content"] = None
    elif change == "wrong_format":
        body["format"] = "other"
    if change == "nul":
        body["sections"][0]["content"] = "bad\x00text"
    if change == "surrogate":
        body["sections"][0]["content"] = "bad\ud800text"
    result = client.patch(
        base,
        content=json.dumps(body, ensure_ascii=True),
        headers={"Content-Type": "application/json"},
    )
    assert result.status_code == 422, result.text
    assert "synthetic-private" not in result.text
    assert client.get(base).json()["revision"] == 1


async def test_noop_empty_patch_and_restore_original_preserve_generated(client, draft):
    _, _, _, raw, _, base = draft
    assert client.patch(base, json=patch(sections=[])).json()["revision"] == 1
    assert (
        client.patch(base, json=patch(raw["data"]["summary_sections"][0]["content"])).json()[
            "revision"
        ]
        == 1
    )
    client.patch(base, json=patch("Edited"))
    restored = client.patch(
        base, json=patch(raw["data"]["summary_sections"][0]["content"], 2)
    ).json()
    assert restored["revision"] == 3
    assert restored["structured_summary"]["current_sections"] == []
    assert restored["structured_summary"]["content_state"] == "generated_unreviewed"


@pytest.mark.parametrize("mode", ["deleting", "source", "run", "membership"])
async def test_lifecycle_and_authorization_revalidated(client, workspace, draft, mode):
    created, _, _, _, _, base = draft
    async with SessionLocal() as db:
        doc = await db.get(Document, UUID(created["document_id"]))
        if mode == "deleting":
            doc.lifecycle_status = "DELETING"
            doc.deletion_requested_at = doc.vectors_hidden_at = datetime.now(UTC)
        elif mode == "source":
            doc.content_sha256 = "f" * 64
        elif mode == "run":
            doc.current_processing_run_id = None
        else:
            member = await db.scalar(
                select(TenantMembership).where(TenantMembership.tenant_id == UUID(workspace))
            )
            member.role = "VIEWER"
        await db.commit()
    assert client.patch(base, json=patch()).status_code in {403, 409}
    assert client.post(base + "/approve", json=approval(1)).status_code in {403, 409}


async def test_reordered_storage_keeps_identity_and_citations(client, draft):
    _, _, _, _, summary_id, base = draft
    async with SessionLocal() as db:
        summary = await db.get(DocumentSummary, summary_id)
        await db.refresh(summary, ["structured_summary"])
        stored = copy.deepcopy(summary.structured_summary)
        stored["generated_result"]["data"]["summary_sections"].reverse()
        summary.structured_summary = stored
        await db.commit()
    result = client.patch(base, json=patch("Unicode \U0001f600\n<script>plain text</script> [99]"))
    assert result.status_code == 200, result.text
    saved = result.json()["structured_summary"]
    assert saved["current_sections"][0]["id"] == "sec_1"
    assert saved["generated_result"]["data"]["summary_sections"][0]["id"] == "sec_7"
    assert (
        saved["generated_result"]["data"]["summary_sections"][-1]["evidence_citations"][0][
            "citation_number"
        ]
        == 1
    )


async def test_atomic_rollback_when_workflow_update_fails(client, draft, monkeypatch):
    from app.services import external_summary_review

    created, _, _, _, _, base = draft

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic local fault")

    monkeypatch.setattr(external_summary_review, "advance_workflows", fail)
    with pytest.raises(RuntimeError, match="synthetic local fault"):
        client.patch(base, json=patch())
    assert client.get(base).json()["revision"] == 1
    async with SessionLocal() as db:
        workflow = await db.get(DocumentWorkflow, UUID(created["workflow_id"]))
        assert workflow.summary_revision == 1


async def test_projection_limit_rejects_without_partial_save(client, workspace, complete):
    from tests.test_external_summary_import import alter_job

    created, request_id, job_id, raw = complete
    for section in raw["data"]["summary_sections"]:
        section["max_length"] = 20000
    await alter_job(job_id, result_payload=raw)
    await importer.process_import(UUID(workspace), request_id)
    base = f"/api/v1/tenants/{workspace}/documents/{created['document_id']}/summary"
    edits = [
        {"id": s["id"], "key": s["key"], "content": "x" * 20000}
        for s in raw["data"]["summary_sections"][:3]
    ]
    result = client.patch(base, json=patch(sections=edits))
    assert result.status_code == 422
    assert client.get(base).json()["revision"] == 1


async def test_unicode_codepoint_limit_and_approval_save_order(client, draft):
    *_, base = draft
    assert client.patch(base, json=patch("\U0001f600" * 2000)).status_code == 200
    assert client.patch(base, json=patch("\U0001f600" * 2001, 2)).status_code == 422
    assert client.post(base + "/approve", json=approval(1)).status_code == 409
    assert client.post(base + "/approve", json=approval(2)).status_code == 200
    assert client.patch(base, json=patch("later", 2)).json()["revision"] == 3
    assert client.post(base + "/approve", json=approval(2)).status_code == 409
    assert not client.get(base).json()["is_approved"]


@pytest.mark.parametrize("role", ["VIEWER", "unknown-role"])
async def test_review_permission_denial(client, workspace, draft, role):
    *_, base = draft
    async with SessionLocal() as db:
        membership = await db.scalar(
            select(TenantMembership).where(TenantMembership.tenant_id == UUID(workspace))
        )
        membership.role = role
        await db.commit()
    assert client.patch(base, json=patch()).status_code == 403
    assert client.post(base + "/approve", json=approval(1)).status_code == 403
    assert client.get(base).status_code == (200 if role == "VIEWER" else 403)


async def test_unassociated_workflow_is_not_rewritten(client, workspace, draft):
    created, _, job_id, raw, summary_id, base = draft
    async with SessionLocal() as db:
        # A same-document row is not a verified association merely because its IDs match.
        unassociated = DocumentWorkflow(
            tenant_id=UUID(workspace),
            project_id=UUID(created["project_id"]),
            document_id=UUID(created["document_id"]),
            summary_id=summary_id,
            summary_revision=1,
            summary_job_id=job_id,
            processing_run_id=UUID(raw["data"]["processing_run_id"]),
        )
        db.add(unassociated)
        await db.flush()
        other_id, checkpoint = unassociated.id, unassociated.checkpoint_revision
        await db.commit()
    response = client.patch(base, json=patch())
    assert response.status_code == 200, response.text
    async with SessionLocal() as db:
        other = await db.get(DocumentWorkflow, other_id)
        assert other.summary_revision == 1 and other.checkpoint_revision == checkpoint


@pytest.mark.skip(
    reason="No verified disposable PostgreSQL target and restricted runtime roles available"
)
def test_postgresql_review_locking_rls_and_concurrent_save_approval():
    pass
