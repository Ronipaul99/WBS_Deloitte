"""ORM guards supplement PostgreSQL constraints; neither implements a workflow."""

import re

from sqlalchemy import String, event, inspect, select

from app.models.agent_workflows import (
    AgentCheckpoint,
    AgentStepRun,
    AgentWorkflowRun,
    SummaryApprovalEvent,
    SummaryEvidence,
    SummaryRevision,
    WorkflowDispatchOutbox,
)
from app.models.domain import DocumentChunk
from app.models.llm import (
    LlmConnection,
    LlmCredentialVersion,
    LlmModelProfile,
    LlmModelProfileVersion,
)
from app.services.agents.contracts import EvidenceReference, TenderSummary, WorkflowInput
from app.services.agents.persistence_types import (
    EndpointPolicyRecord,
    RunBudget,
    StoredArtifact,
    safe_json,
)
from app.services.llm.contracts import ModelProfileSnapshot, Usage

NEW_MODELS = (
    LlmConnection,
    LlmCredentialVersion,
    LlmModelProfile,
    LlmModelProfileVersion,
    AgentWorkflowRun,
    AgentStepRun,
    AgentCheckpoint,
    WorkflowDispatchOutbox,
    SummaryRevision,
    SummaryEvidence,
    SummaryApprovalEvent,
)
IMMUTABLE_MODELS = (
    LlmModelProfileVersion,
    AgentCheckpoint,
    SummaryRevision,
    SummaryEvidence,
    SummaryApprovalEvent,
)


def _validate(mapper, connection, row):
    for column in mapper.columns:
        value = getattr(row, column.key)
        if value is not None and isinstance(column.type, String):
            if (
                not isinstance(value, str)
                or not value.strip()
                or (column.type.length is not None and len(value) > column.type.length)
            ):
                raise ValueError("storage label exceeds its string bounds")
            if column.key.endswith("sha256") and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("storage hash must be a canonical SHA-256")
        if isinstance(value, dict):
            limit = {
                "content": 8_388_608,
                "input_snapshot": 32768,
                "snapshot": 16384,
                "endpoint_policy": 8192,
                "budget": 4096,
                "usage": 2048,
                "execution": 131072,
                "locator": 65536,
            }.get(column.key, 1_048_576)
            safe_json(value, limit)
    if isinstance(row, LlmConnection):
        row.endpoint_policy = EndpointPolicyRecord.model_validate(row.endpoint_policy).model_dump(
            mode="json"
        )
    elif isinstance(row, LlmCredentialVersion):
        if not isinstance(row.ciphertext, bytes) or not 16 <= len(row.ciphertext) <= 16384:
            raise ValueError("credential version requires bounded encrypted bytes")
        if not isinstance(row.nonce, bytes) or not 12 <= len(row.nonce) <= 32:
            raise ValueError("credential version requires a bounded nonce")
    elif isinstance(row, LlmModelProfileVersion):
        snapshot = ModelProfileSnapshot.model_validate(row.snapshot)
        protocol = connection.execute(
            select(LlmConnection.provider, LlmConnection.protocol).where(
                LlmConnection.id == row.connection_id, LlmConnection.tenant_id == row.tenant_id
            )
        ).first()
        if protocol is None or tuple(protocol) != (snapshot.provider, snapshot.protocol):
            raise ValueError("profile protocol differs from its connection")
        if (
            snapshot.tenant_id,
            snapshot.connection_id,
            snapshot.profile_id,
            snapshot.profile_version,
        ) != (row.tenant_id, row.connection_id, row.profile_id, row.version):
            raise ValueError("profile snapshot identity mismatch")
        row.snapshot = snapshot.model_dump(mode="json")
    elif isinstance(row, LlmModelProfile) and row.enabled:
        snapshot = connection.scalar(
            select(LlmModelProfileVersion.snapshot).where(
                LlmModelProfileVersion.id == row.active_version_id,
                LlmModelProfileVersion.tenant_id == row.tenant_id,
                LlmModelProfileVersion.profile_id == row.id,
                LlmModelProfileVersion.connection_id == row.connection_id,
            )
        )
        if snapshot is None:
            raise ValueError("enabled profile requires an active version")
        data = ModelProfileSnapshot.model_validate(snapshot)
        if (
            data.capabilities.qualification != "live_worker"
            or data.capabilities.context_tokens is None
            or data.capabilities.output_tokens is None
        ):
            raise ValueError("enabled profile requires live qualification")
    elif isinstance(row, AgentWorkflowRun):
        data = WorkflowInput.model_validate(row.input_snapshot)
        budget = RunBudget.model_validate(row.budget)
        if (
            budget.max_calls > data.profile.max_calls
            or budget.max_total_tokens > data.profile.max_total_tokens
            or budget.timeout_seconds > data.profile.timeout_seconds
        ):
            raise ValueError("run budget exceeds pinned profile")
        if (
            data.workflow_run_id,
            data.scope.tenant_id,
            data.scope.project_id,
            data.scope.document_id,
            data.scope.processing_run_id,
            data.scope.source_sha256,
            data.requested_by,
            data.profile.profile_id,
            data.profile.connection_id,
        ) != (
            row.id,
            row.tenant_id,
            row.project_id,
            row.document_id,
            row.processing_run_id,
            row.source_sha256,
            row.requested_by,
            row.profile_id,
            row.connection_id,
        ):
            raise ValueError("workflow snapshot identity mismatch")
        snapshot = connection.scalar(
            select(LlmModelProfileVersion.snapshot).where(
                LlmModelProfileVersion.id == row.profile_version_id,
                LlmModelProfileVersion.tenant_id == row.tenant_id,
                LlmModelProfileVersion.profile_id == row.profile_id,
                LlmModelProfileVersion.connection_id == row.connection_id,
            )
        )
        if snapshot is None or ModelProfileSnapshot.model_validate(snapshot) != data.profile:
            raise ValueError("workflow profile snapshot mismatch")
        row.input_snapshot = data.model_dump(mode="json")
        row.budget = budget.model_dump(mode="json")
        if row.execution:
            from app.services.agents.state import ExecutionLedger

            row.execution = ExecutionLedger.model_validate(row.execution).model_dump(mode="json")
    elif isinstance(row, AgentStepRun | AgentCheckpoint):
        if isinstance(row, AgentStepRun) and row.artifact.get("kind") in {
            "inventory_manifest.v1",
            "inventory_page.v1",
            "reading_batch.v1",
            "coverage_page.v1",
        }:
            from app.services.agents.evidence_types import EvidenceArtifact

            item = EvidenceArtifact.model_validate(row.artifact)
            if row.node != "evidence:" + item.kind or row.state != "completed":
                raise ValueError("evidence artifact identity mismatch")
            row.artifact = item.model_dump(mode="json")
        elif row.artifact.get("kind") == "orchestration.v1":
            from app.services.agents.state import OrchestrationArtifact

            artifact = OrchestrationArtifact.model_validate(row.artifact)
            if artifact.payload.workflow_run_id != row.workflow_run_id:
                raise ValueError("checkpoint run mismatch")
            row.artifact = artifact.model_dump(mode="json")
        else:
            row.artifact = StoredArtifact.model_validate(row.artifact).model_dump(mode="json")
        if isinstance(row, AgentStepRun):
            row.usage = Usage.model_validate(row.usage).model_dump(mode="json")
            if (row.state == "completed") != (row.completed_at is not None):
                raise ValueError("step completion timestamp mismatch")
    elif isinstance(row, SummaryRevision):
        data = TenderSummary.model_validate(row.content)
        if (
            data.revision_id,
            data.workflow.workflow_run_id,
            data.workflow.scope.tenant_id,
            data.workflow.scope.project_id,
            data.workflow.scope.document_id,
            data.workflow.scope.processing_run_id,
        ) != (
            row.id,
            row.workflow_run_id,
            row.tenant_id,
            row.project_id,
            row.document_id,
            row.processing_run_id,
        ):
            raise ValueError("revision content identity mismatch")
        pinned = connection.scalar(
            select(AgentWorkflowRun.input_snapshot).where(
                AgentWorkflowRun.id == row.workflow_run_id,
                AgentWorkflowRun.tenant_id == row.tenant_id,
            )
        )
        if pinned is None or WorkflowInput.model_validate(pinned) != data.workflow:
            raise ValueError("revision workflow provenance mismatch")
        expected = (
            "partial"
            if not data.coverage.complete
            else "quality_blocked"
            if data.verification is None or data.verification.verdict == "quality_blocked"
            else "review_required"
        )
        if row.quality != "stale" and row.quality != expected:
            raise ValueError("revision quality must match its validated report")
        row.content = data.model_dump(mode="json")
    elif isinstance(row, SummaryEvidence):
        data = EvidenceReference.model_validate(row.locator)
        if (
            data.evidence_id,
            data.chunk_id,
            data.chunk_sha256,
            data.scope.tenant_id,
            data.scope.project_id,
            data.scope.document_id,
            data.scope.processing_run_id,
        ) != (
            row.evidence_id,
            row.chunk_id,
            row.chunk_sha256,
            row.tenant_id,
            row.project_id,
            row.document_id,
            row.processing_run_id,
        ):
            raise ValueError("evidence locator identity mismatch")
        canonical = connection.execute(
            select(DocumentChunk.content, DocumentChunk.content_sha256).where(
                DocumentChunk.id == row.chunk_id,
                DocumentChunk.tenant_id == row.tenant_id,
                DocumentChunk.project_id == row.project_id,
                DocumentChunk.document_id == row.document_id,
                DocumentChunk.processing_run_id == row.processing_run_id,
            )
        ).first()
        if (
            canonical is None
            or canonical.content_sha256 != row.chunk_sha256
            or canonical.content[data.char_start : data.char_end] != data.exact_quote
        ):
            raise ValueError("evidence does not match canonical chunk")
        content = connection.scalar(
            select(SummaryRevision.content).where(
                SummaryRevision.id == row.revision_id,
                SummaryRevision.tenant_id == row.tenant_id,
                SummaryRevision.workflow_run_id == row.workflow_run_id,
            )
        )
        if content is None:
            raise ValueError("evidence revision unavailable")
        revision = TenderSummary.model_validate(content)
        claims = (*revision.facts, *revision.requirements)
        if not any(
            getattr(claim, "fact_id", getattr(claim, "requirement_id", None)) == row.claim_id
            and row.evidence_id in claim.evidence_ids
            for claim in claims
        ):
            raise ValueError("evidence does not belong to revision claim")
        if data not in revision.evidence:
            raise ValueError("evidence is outside immutable revision")
        row.locator = data.model_dump(mode="json")


def _update(mapper, connection, row):
    state = inspect(row)
    changed = {attr.key for attr in state.attrs if attr.history.has_changes()}
    if isinstance(row, IMMUTABLE_MODELS) and changed:
        raise ValueError("append-only record cannot be updated")
    identity_fields = {
        "id",
        "tenant_id",
        "connection_id",
        "profile_id",
        "workflow_run_id",
        "project_id",
        "document_id",
        "processing_run_id",
        "job_id",
    }
    if changed & identity_fields:
        raise ValueError("persisted scope is immutable")
    if isinstance(row, AgentWorkflowRun) and changed & {
        "input_snapshot",
        "source_sha256",
        "profile_version_id",
        "requested_by",
        "budget",
        "request_sequence",
    }:
        raise ValueError("pinned workflow input is immutable")
    if isinstance(row, AgentWorkflowRun) and "execution" in changed:
        history = state.attrs.execution.history
        if history.deleted and history.deleted[0]:
            previous, current = history.deleted[0], row.execution
            for key in (
                "calls",
                "reserved_tokens",
                "format_repairs",
                "node_start_calls",
                "resumes",
            ):
                if current.get(key, -1) < previous.get(key, 0):
                    raise ValueError("execution ledger cannot reset")
            for key in ("deadline", "endpoint"):
                if current.get(key) != previous.get(key):
                    raise ValueError("execution pin cannot change")
            if previous.get("binding") and current.get("binding") != previous["binding"]:
                raise ValueError("execution binding cannot change")
            if previous.get("violated") and not current.get("violated"):
                raise ValueError("execution violation cannot reset")
            for key in ("sequence", "graph_repairs"):
                if current.get("cursor", {}).get(key, -1) < previous.get("cursor", {}).get(key, 0):
                    raise ValueError("execution cursor cannot reset")
    if isinstance(row, AgentStepRun) and "completed" in state.attrs.state.history.deleted:
        raise ValueError("completed steps are immutable")
    if isinstance(row, AgentStepRun) and row.state == "completed" and "state" not in changed:
        raise ValueError("completed steps are immutable")
    if isinstance(row, LlmCredentialVersion) and changed - {"retired_at", "updated_at"}:
        raise ValueError("credential bytes and identity are immutable")
    if isinstance(row, LlmConnection) and changed & {"provider", "protocol"}:
        raise ValueError("connection protocol is immutable")
    _validate(mapper, connection, row)


for _model in NEW_MODELS:
    event.listen(_model, "before_insert", _validate)
    event.listen(_model, "before_update", _update)


def _delete(mapper, connection, row):
    raise ValueError("append-only record deletion requires an explicit privileged cleanup")


for _model in IMMUTABLE_MODELS:
    event.listen(_model, "before_delete", _delete)
