"""Guarded external summary job/workflow associations; metadata only.

Revision ID: e94b7d20a631
Revises: d82f6a913b70
"""

import sqlalchemy as sa
from alembic import op

revision = "e94b7d20a631"
down_revision = "d82f6a913b70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("summary_api_requests") as batch:
        batch.add_column(
            sa.Column("database_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_unique_constraint(
            "uq_summary_request_binding_scope", ["id", "tenant_id", "project_id", "document_id"]
        )
    with op.batch_alter_table("document_workflows") as batch:
        batch.create_unique_constraint(
            "uq_workflow_document_binding", ["id", "tenant_id", "project_id", "document_id"]
        )
    op.create_table(
        "summary_workflow_bindings",
        sa.Column("workflow_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("expected_checkpoint", sa.Integer(), nullable=False),
        sa.Column("previous_job_id", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
            for name in ("created_at", "updated_at")
        ],
        sa.ForeignKeyConstraint(
            ["request_id", "tenant_id", "project_id", "document_id"],
            [
                "summary_api_requests.id",
                "summary_api_requests.tenant_id",
                "summary_api_requests.project_id",
                "summary_api_requests.document_id",
            ],
            name="fk_summary_binding_request",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id", "document_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
                "document_workflows.document_id",
            ],
            name="fk_summary_binding_workflow",
        ),
        sa.CheckConstraint("expected_checkpoint >= 1", name="ck_summary_binding_checkpoint"),
    )
    if op.get_bind().dialect.name == "postgresql":
        role = op.get_context().config.attributes.get("runtime_database_role")
        flags = (
            op.get_bind()
            .execute(
                sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                {"role": str(role)},
            )
            .first()
        )
        current = op.get_bind().scalar(sa.text("SELECT current_user"))
        if not role or flags is None or flags[0] or flags[1] or str(role) == current:
            raise RuntimeError("Summary binding runtime role must be separate and restricted")
        quoted = op.get_bind().dialect.identifier_preparer.quote(str(role))
        op.execute("ALTER TABLE summary_workflow_bindings ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE summary_workflow_bindings FORCE ROW LEVEL SECURITY")
        expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON summary_workflow_bindings "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON summary_workflow_bindings TO {quoted}")


def downgrade():
    op.drop_table("summary_workflow_bindings")
    with op.batch_alter_table("document_workflows") as batch:
        batch.drop_constraint("uq_workflow_document_binding", type_="unique")
    with op.batch_alter_table("summary_api_requests") as batch:
        batch.drop_constraint("uq_summary_request_binding_scope", type_="unique")
        batch.drop_column("database_verified_at")
