"""External summary submission intents only; no job tracking or result storage.

Revision ID: d82f6a913b70
Revises: c92e6b4a710d
"""

import sqlalchemy as sa
from alembic import op

revision = "d82f6a913b70"
down_revision = "c92e6b4a710d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "summary_api_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.UniqueConstraint("id", "tenant_id", name="uq_summary_submission_tenant"),
        *[
            sa.Column(name, sa.Uuid(), nullable=False)
            for name in (
                "tenant_id",
                "project_id",
                "document_id",
                "processing_run_id",
                "workflow_id",
                "created_by",
            )
        ],
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("expected_summary_revision", sa.Integer(), nullable=True),
        *[
            sa.Column(name, sa.String(64), nullable=False)
            for name in ("key_digest", "input_digest", "config_digest")
        ],
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("owner_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("external_job_id", sa.Uuid(), nullable=True),
        sa.Column("acknowledgement", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            for name in ("created_at", "updated_at")
        ],
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_summary_request_document",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_summary_request_run",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_summary_request_workflow",
        ),
        sa.UniqueConstraint(
            "tenant_id", "document_id", "processing_run_id", name="uq_summary_submission_run"
        ),
        sa.UniqueConstraint(
            "tenant_id", "created_by", "key_digest", name="uq_summary_submission_key"
        ),
        sa.CheckConstraint(
            "state IN ('SUBMIT_PENDING','SUBMITTING','ACKNOWLEDGED',"
            "'SUBMISSION_UNKNOWN','REJECTED')",
            name="ck_summary_submission_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 5", name="ck_summary_submission_attempts"
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64 AND length(config_digest) = 64 AND length(key_digest) = 64",
            name="ck_summary_submission_hashes",
        ),
        sa.CheckConstraint(
            "(state = 'SUBMITTING' AND owner_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state != 'SUBMITTING' AND owner_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_summary_submission_lease",
        ),
        sa.CheckConstraint(
            "(state = 'ACKNOWLEDGED' AND external_job_id IS NOT NULL) OR "
            "(state != 'ACKNOWLEDGED' AND external_job_id IS NULL)",
            name="ck_summary_submission_ack",
        ),
    )
    op.create_index(
        "ix_summary_submission_delivery",
        "summary_api_requests",
        ["tenant_id", "state", "available_at"],
    )
    op.create_table(
        "summary_submission_keys",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("key_digest", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            for name in ("created_at", "updated_at")
        ],
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["summary_api_requests.id", "summary_api_requests.tenant_id"],
            name="fk_summary_key_request",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        role = op.get_context().config.attributes.get("runtime_database_role")
        if not role:
            raise RuntimeError("Separate runtime role required for summary submission grants")
        flags = (
            op.get_bind()
            .execute(
                sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                {"role": str(role)},
            )
            .first()
        )
        current_role = op.get_bind().scalar(sa.text("SELECT current_user"))
        if flags is None or flags[0] or flags[1] or str(role) == current_role:
            raise RuntimeError("Summary runtime role must be separate and restricted")
        quoted = op.get_bind().dialect.identifier_preparer.quote(str(role))
        expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        for table in ("summary_api_requests", "summary_submission_keys"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING ({expression}) WITH CHECK ({expression})"
            )
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {quoted}")


def downgrade():
    op.drop_table("summary_submission_keys")
    op.drop_table("summary_api_requests")
