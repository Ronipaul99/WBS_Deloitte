"""add durable document deletion lifecycle

Revision ID: d4e7b2c91a63
Revises: c8d4a1e72f09
Create Date: 2026-10-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e7b2c91a63"
down_revision: str | None = "c8d4a1e72f09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_POLICY_EXPRESSION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _runtime_role() -> str | None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    role = op.get_context().config.attributes.get("runtime_database_role")
    if not role:
        raise RuntimeError("Runtime database role is required for the deletion outbox migration")
    return str(role)


def _protect_outbox(runtime_role: str | None) -> None:
    if runtime_role is None:
        return
    bind = op.get_bind()
    quoted_role = bind.dialect.identifier_preparer.quote(runtime_role)
    op.execute("REVOKE ALL ON TABLE document_deletion_outbox FROM PUBLIC")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE document_deletion_outbox TO {quoted_role}"
    )
    op.execute("ALTER TABLE document_deletion_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_deletion_outbox FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY document_deletion_outbox_tenant_isolation "
        f"ON document_deletion_outbox FOR ALL TO {quoted_role} "
        f"USING ({TENANT_POLICY_EXPRESSION}) WITH CHECK ({TENANT_POLICY_EXPRESSION})"
    )


def upgrade() -> None:
    runtime_role = _runtime_role()
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                sa.String(length=20),
                server_default="ACTIVE",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("deletion_job_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("vectors_hidden_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("deletion_completed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("deletion_error_code", sa.String(length=80), nullable=True))
        batch_op.create_foreign_key(
            "fk_documents_deletion_job_scope",
            "jobs",
            ["deletion_job_id", "tenant_id", "project_id"],
            ["id", "tenant_id", "project_id"],
            deferrable=True,
            initially="DEFERRED",
        )
        batch_op.create_check_constraint(
            "ck_documents_lifecycle_status",
            "lifecycle_status IN ('ACTIVE', 'DELETING', 'DELETED')",
        )
        batch_op.create_check_constraint(
            "ck_documents_deletion_lifecycle",
            "(lifecycle_status = 'ACTIVE' AND deletion_requested_at IS NULL "
            "AND vectors_hidden_at IS NULL AND deletion_completed_at IS NULL) OR "
            "(lifecycle_status = 'DELETING' AND deletion_requested_at IS NOT NULL "
            "AND vectors_hidden_at IS NOT NULL AND deletion_completed_at IS NULL) OR "
            "(lifecycle_status = 'DELETED' AND deletion_requested_at IS NOT NULL "
            "AND vectors_hidden_at IS NOT NULL AND deletion_completed_at IS NOT NULL)",
        )

    op.create_table(
        "document_deletion_outbox",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
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
            name="ck_deletion_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_deletion_outbox_attempt_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_deletion_outbox_document_scope",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_deletion_outbox_job_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "task_name", name="uq_deletion_outbox_delivery"),
    )
    op.create_index(
        "ix_deletion_outbox_pending",
        "document_deletion_outbox",
        ["tenant_id", "status", "available_at", "created_at"],
        unique=False,
    )
    _protect_outbox(runtime_role)


def _assert_safe_downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM document_deletion_outbox)")):
        raise RuntimeError(
            "Document deletion dispatch records exist; use a reviewed forward fix instead"
        )
    if bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM documents "
            "WHERE lifecycle_status <> 'ACTIVE' OR deletion_job_id IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Document deletion lifecycle state exists; use a reviewed forward fix instead"
        )


def downgrade() -> None:
    _assert_safe_downgrade()
    op.drop_index("ix_deletion_outbox_pending", table_name="document_deletion_outbox")
    op.drop_table("document_deletion_outbox")
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("ck_documents_deletion_lifecycle", type_="check")
        batch_op.drop_constraint("ck_documents_lifecycle_status", type_="check")
        batch_op.drop_constraint("fk_documents_deletion_job_scope", type_="foreignkey")
        batch_op.drop_column("deletion_error_code")
        batch_op.drop_column("deletion_completed_at")
        batch_op.drop_column("vectors_hidden_at")
        batch_op.drop_column("deletion_requested_at")
        batch_op.drop_column("deletion_job_id")
        batch_op.drop_column("lifecycle_status")
