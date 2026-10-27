"""Persistence-only types and constraints. No sessions or application settings."""

from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class WorkflowState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    PARTIAL = "partial"
    QUALITY_BLOCKED = "quality_blocked"
    STALE = "stale"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Completion of generation is not approval. No APPROVED workflow/job state exists.
WORKFLOW_JOB_STATUS = MappingProxyType(
    {
        WorkflowState.QUEUED: "QUEUED",
        WorkflowState.RUNNING: "IN_PROGRESS",
        WorkflowState.REVIEW_REQUIRED: "COMPLETED",
        WorkflowState.PARTIAL: "FAILED",
        WorkflowState.QUALITY_BLOCKED: "FAILED",
        WorkflowState.STALE: "FAILED",
        WorkflowState.FAILED: "FAILED",
        WorkflowState.CANCELLED: "CANCELLED",
    }
)


def workflow_job_status(state: WorkflowState | str) -> str:
    return WORKFLOW_JOB_STATUS[WorkflowState(state)]


class TenantRecord:
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)


class WorkflowChild(TenantRecord):
    workflow_run_id: Mapped[UUID] = mapped_column(nullable=False)


def scoped_run_fk(name: str):
    return ForeignKeyConstraint(
        ["workflow_run_id", "tenant_id"],
        ["agent_workflow_runs.id", "agent_workflow_runs.tenant_id"],
        name=name,
    )


def enum_check(column: str, values, name: str):
    return CheckConstraint(f"{column} IN ({', '.join(repr(str(v)) for v in values)})", name=name)


def bounded_json(column: str, name: str, maximum: int = 1_048_576):
    # Portable byte/shape/secret checks are supplemented by PostgreSQL constraints
    # in the migration and by validated repository writes on both dialects.
    return CheckConstraint(f"length(CAST({column} AS TEXT)) <= {maximum}", name=name)


def json_column():
    return mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
