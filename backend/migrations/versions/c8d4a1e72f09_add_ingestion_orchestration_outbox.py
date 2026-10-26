"""add ingestion orchestration and transactional outbox

Revision ID: c8d4a1e72f09
Revises: b6e2f719c4d8
Create Date: 2026-10-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8d4a1e72f09"
down_revision: str | None = "b6e2f719c4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY_EXPRESSION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
RUN_STAGES = (
    "'QUEUED', 'SCANNING', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', "
    "'PERSISTING', 'ACTIVATING', 'RETRY_WAIT', 'COMPLETED', 'FAILED'"
)
IDENTITY_STATE = (
    "((document_content_sha256 IS NULL AND extractor_name IS NULL "
    "AND extractor_version IS NULL AND chunker_version IS NULL "
    "AND embedding_provider IS NULL AND embedding_model IS NULL "
    "AND embedding_model_revision IS NULL AND embedding_dimensions IS NULL "
    "AND embedding_formatting_version IS NULL) OR "
    "(document_content_sha256 IS NOT NULL AND extractor_name IS NOT NULL "
    "AND extractor_version IS NOT NULL AND chunker_version IS NOT NULL "
    "AND embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
    "AND embedding_model_revision IS NOT NULL AND embedding_dimensions IS NOT NULL "
    "AND embedding_formatting_version IS NOT NULL) OR "
    "(status = 'COMPLETED' AND document_content_sha256 IS NOT NULL "
    "AND extractor_name IS NOT NULL AND extractor_version IS NOT NULL "
    "AND embedding_provider IS NOT NULL AND embedding_model IS NOT NULL "
    "AND embedding_dimensions IS NOT NULL AND chunker_version IS NULL "
    "AND embedding_model_revision IS NULL AND embedding_formatting_version IS NULL))"
)


def _runtime_role() -> str | None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    role = op.get_context().config.attributes.get("runtime_database_role")
    if not role:
        raise RuntimeError("Runtime database role is required for the ingestion outbox migration")
    return str(role)


def _protect_outbox(runtime_role: str | None) -> None:
    if runtime_role is None:
        return
    bind = op.get_bind()
    quoted_role = bind.dialect.identifier_preparer.quote(runtime_role)
    op.execute("REVOKE ALL ON TABLE job_dispatch_outbox FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE job_dispatch_outbox TO {quoted_role}"
    )
    op.execute("ALTER TABLE job_dispatch_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_dispatch_outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY job_dispatch_outbox_tenant_isolation "
        f"ON job_dispatch_outbox FOR ALL TO {quoted_role} "
        f"USING ({TENANT_POLICY_EXPRESSION}) WITH CHECK ({TENANT_POLICY_EXPRESSION})"
    )


def upgrade() -> None:
    runtime_role = _runtime_role()
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("error_code", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_jobs_progress_range", "progress >= 0 AND progress <= 100"
        )
        batch_op.create_check_constraint("ck_jobs_attempt_count_nonnegative", "attempt_count >= 0")

    with op.batch_alter_table("document_processing_runs") as batch_op:
        for column_name, column_type in (
            ("document_content_sha256", sa.String(length=64)),
            ("extractor_name", sa.String(length=80)),
            ("extractor_version", sa.String(length=40)),
            ("embedding_provider", sa.String(length=40)),
            ("embedding_model", sa.String(length=160)),
            ("embedding_dimensions", sa.Integer()),
        ):
            batch_op.alter_column(column_name, existing_type=column_type, nullable=True)
        batch_op.add_column(sa.Column("current_stage", sa.String(length=24), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "last_heartbeat_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "warning_codes",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint("ck_runs_identity_state", IDENTITY_STATE)
        batch_op.create_check_constraint(
            "ck_runs_completed_identity",
            "status <> 'COMPLETED' OR document_content_sha256 IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "ck_runs_current_stage", f"current_stage IS NULL OR current_stage IN ({RUN_STAGES})"
        )
        batch_op.create_check_constraint("ck_runs_attempt_count_nonnegative", "attempt_count >= 0")

    op.create_table(
        "job_dispatch_outbox",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'DEAD')",
            name="ck_dispatch_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_dispatch_outbox_attempt_count_nonnegative"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_dispatch_outbox_job_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_dispatch_outbox_run_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "processing_run_id", "task_name", name="uq_dispatch_outbox_delivery"
        ),
    )
    op.create_index(
        "ix_dispatch_outbox_pending",
        "job_dispatch_outbox",
        ["tenant_id", "status", "available_at", "created_at"],
        unique=False,
    )
    _protect_outbox(runtime_role)


def _assert_safe_downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM job_dispatch_outbox)")):
        raise RuntimeError(
            "Ingestion dispatch records exist; use a reviewed forward fix instead of downgrade"
        )
    incomplete_identity = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_processing_runs "
            "WHERE document_content_sha256 IS NULL OR extractor_name IS NULL "
            "OR extractor_version IS NULL OR embedding_provider IS NULL "
            "OR embedding_model IS NULL OR embedding_dimensions IS NULL)"
        )
    )
    orchestration_state = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_processing_runs "
            "WHERE current_stage IS NOT NULL OR attempt_count <> 0 "
            "OR warning_codes <> '[]')"
        )
    )
    job_state = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM jobs WHERE error_code IS NOT NULL OR attempt_count <> 0)"
        )
    )
    if incomplete_identity or orchestration_state or job_state:
        raise RuntimeError(
            "Ingestion orchestration state exists; use a reviewed forward fix instead of downgrade"
        )


def downgrade() -> None:
    _assert_safe_downgrade()
    op.drop_index("ix_dispatch_outbox_pending", table_name="job_dispatch_outbox")
    op.drop_table("job_dispatch_outbox")

    with op.batch_alter_table("document_processing_runs") as batch_op:
        batch_op.drop_constraint("ck_runs_attempt_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_runs_current_stage", type_="check")
        batch_op.drop_constraint("ck_runs_completed_identity", type_="check")
        batch_op.drop_constraint("ck_runs_identity_state", type_="check")
        batch_op.drop_column("warning_codes")
        batch_op.drop_column("last_heartbeat_at")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("current_stage")
        for column_name, column_type in (
            ("embedding_dimensions", sa.Integer()),
            ("embedding_model", sa.String(length=160)),
            ("embedding_provider", sa.String(length=40)),
            ("extractor_version", sa.String(length=40)),
            ("extractor_name", sa.String(length=80)),
            ("document_content_sha256", sa.String(length=64)),
        ):
            batch_op.alter_column(column_name, existing_type=column_type, nullable=False)

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_attempt_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_jobs_progress_range", type_="check")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("error_code")
