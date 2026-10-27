"""Bounded continuation/checkpoint contracts. No framework serializer or transcripts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.services.agents.analyst_types import AnalystArtifact
from app.services.agents.evidence_types import EvidenceArtifact, ToolUsage
from app.services.agents.persistence_types import EndpointPolicyRecord, StoredArtifact
from app.services.agents.writer_types import WriterArtifact
from app.services.llm.adapter_types import AttemptRecord
from app.services.llm.contracts import Contract, Count, Identity, Sha256, Usage


class Node(StrEnum):
    PIN = "validate_pin"
    INVENTORY = "inventory"
    ANALYZE = "analyze"
    CONSOLIDATE = "consolidate"
    WRITE = "write"
    VERIFY = "verify"
    REPAIR = "repair"
    PUBLISH = "publish_draft"
    DONE = "done"
    BLOCKED = "quality_blocked"


class Cursor(Contract):
    version: Literal["agent_graph.v1"] = "agent_graph.v1"
    node: Node = Node.PIN
    sequence: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0
    batch: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0
    graph_repairs: Annotated[int, Field(strict=True, ge=0, le=1)] = 0


class NodeResult(Contract):
    next_node: Node
    artifact: StoredArtifact | EvidenceArtifact | AnalystArtifact | WriterArtifact | None = None
    usage: Usage = Field(default_factory=Usage)


class CompletedNode(Contract):
    version: Literal["node_completion.v1"] = "node_completion.v1"
    workflow_run_id: Identity
    input_sha256: Sha256
    before: Cursor
    after: Cursor
    result: NodeResult

    @model_validator(mode="after")
    def transition(self):
        expected = advance(self.before, self.result)
        if expected != self.after:
            raise ValueError("checkpoint transition mismatch")
        artifact = self.result.artifact
        if isinstance(artifact, AnalystArtifact):
            if artifact.kind == "analyst_batch.v1":
                if (
                    self.before.node != Node.ANALYZE
                    or artifact.payload.batch.index != self.before.batch
                ):
                    raise ValueError("analyst batch checkpoint mismatch")
            elif self.before.node != Node.CONSOLIDATE or self.after.node != (
                Node.WRITE if artifact.kind == "fact_register.v1" else Node.CONSOLIDATE
            ):
                raise ValueError("analyst consolidation checkpoint mismatch")
        if isinstance(artifact, WriterArtifact):
            if self.before.node != Node.WRITE or self.after.node != (
                Node.VERIFY if artifact.kind == "writer_draft.v1" else Node.WRITE
            ):
                raise ValueError("writer checkpoint transition mismatch")
        return self


class OrchestrationArtifact(Contract):
    kind: Literal["orchestration.v1"] = "orchestration.v1"
    payload: CompletedNode


def advance(cursor: Cursor, result: NodeResult) -> Cursor:
    edges = {
        Node.PIN: {Node.INVENTORY},
        Node.INVENTORY: {Node.ANALYZE},
        Node.ANALYZE: {Node.ANALYZE, Node.CONSOLIDATE},
        Node.CONSOLIDATE: {Node.CONSOLIDATE, Node.WRITE},
        Node.WRITE: {Node.WRITE, Node.VERIFY},
        Node.VERIFY: {Node.REPAIR, Node.PUBLISH, Node.BLOCKED},
        Node.REPAIR: {Node.VERIFY},
        Node.PUBLISH: {Node.DONE},
    }
    if result.next_node not in edges.get(cursor.node, set()):
        raise ValueError("illegal graph transition")
    repairs = cursor.graph_repairs
    if result.next_node == Node.REPAIR:
        if repairs:
            raise ValueError("graph repair already consumed")
        repairs += 1
    return Cursor(
        node=result.next_node,
        sequence=cursor.sequence + 1,
        batch=cursor.batch + int(cursor.node == Node.ANALYZE),
        graph_repairs=repairs,
    )


class ExecutionLedger(Contract):
    version: Literal["execution_ledger.v1"] = "execution_ledger.v1"
    deadline: datetime
    endpoint: EndpointPolicyRecord
    cursor: Cursor = Field(default_factory=Cursor)
    binding: Sha256 | None = None
    calls: Annotated[int, Field(strict=True, ge=0, le=120)] = 0
    node_start_calls: Annotated[int, Field(strict=True, ge=0, le=120)] = 0
    reserved_tokens: Annotated[int, Field(strict=True, ge=0, le=20000000)] = 0
    format_repairs: Annotated[int, Field(strict=True, ge=0, le=1)] = 0
    violated: bool = False
    resumes: Annotated[int, Field(strict=True, ge=0, le=3)] = 0
    evidence_tools: ToolUsage | None = None
    # Unfinished reservations remain charged and ambiguous across process death.
    records: Annotated[tuple[AttemptRecord, ...], Field(max_length=120)] = ()

    @model_validator(mode="after")
    def coherent(self):
        if self.deadline.utcoffset() is None:
            raise ValueError("deadline must be timezone aware")
        if self.node_start_calls > self.calls:
            raise ValueError("node admission baseline exceeds calls")
        sequences = [record.sequence for record in self.records]
        if len(set(sequences)) != len(sequences) or any(i > self.calls for i in sequences):
            raise ValueError("invalid attempt accounting")
        return self


class Progress(Contract):
    workflow_run_id: Identity
    state: Literal[
        "queued",
        "running",
        "review_required",
        "partial",
        "quality_blocked",
        "stale",
        "failed",
        "cancelled",
    ]
    node: Node
    completed_nodes: Count
    calls_reserved: Count
    tokens_reserved: Count
    usage_unknown: bool


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def node_input_hash(workflow, cursor: Cursor):
    return digest({"workflow": workflow, "cursor": cursor.model_dump(mode="json")})
