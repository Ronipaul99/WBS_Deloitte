"""Add tenant content claims and durable document workflow provenance.

Revision ID: f31a0d8c72e9
Revises: e71c4a9b203d
"""

import sqlalchemy as sa
from alembic import op

revision = "f31a0d8c72e9"
down_revision = "e71c4a9b203d"
branch_labels = None
depends_on = None

SCOPES = (
    ("document_summaries", "uq_summary_document_scope", ["id", "tenant_id", "document_id"]),
    ("wbs_templates", "uq_template_tenant_scope", ["id", "tenant_id"]),
    ("wbs_versions", "uq_wbs_project_scope", ["id", "tenant_id", "project_id"]),
    ("validation_runs", "uq_validation_wbs_scope", ["id", "tenant_id", "wbs_version_id"]),
)
NEW_TABLES = (
    "document_content_claims",
    "document_upload_attempts",
    "document_workflows",
    "workflow_request_keys",
    "document_workflow_dispatches",
    "document_content_rejections",
)


def upgrade():
    op.add_column("documents", sa.Column("upload_sha256", sa.String(64), nullable=True))
    op.create_index(
        "ix_documents_upload_fingerprint", "documents", ["tenant_id", "upload_sha256", "size_bytes"]
    )
    op.add_column(
        "document_summaries",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "wbs_versions", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("validation_runs", sa.Column("wbs_revision", sa.Integer(), nullable=True))
    op.add_column("validation_runs", sa.Column("wbs_snapshot", sa.JSON(), nullable=True))
    for table in ("jobs", "wbs_versions"):
        op.add_column(table, sa.Column("workflow_id", sa.Uuid(), nullable=True))
        op.create_index("ix_" + table + "_workflow_id", table, ["workflow_id"])
    for table, name, columns in SCOPES:
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(name, columns)

    op.create_table(
        "document_content_claims",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("owner_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_storage_key", sa.String(length=600), nullable=True),
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
            "(state = 'RESERVED' AND owner_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state IN ('READY', 'DELETING') AND document_id IS NOT NULL AND project_id IS NOT NULL)",
            name="ck_claim_state",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="ck_claim_hash_length"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_claim_size"),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_claim_document_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "sha256"),
    )

    op.create_table(
        "document_upload_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("storage_key", sa.String(length=600), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
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
        sa.CheckConstraint("length(sha256) = 64", name="ck_attempt_hash_length"),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_attempt_document_scope",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_upload_attempt_tenant"),
        sa.UniqueConstraint("storage_key"),
    )

    op.create_table(
        "document_workflows",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("is_base", sa.Boolean(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=True),
        sa.Column("summary_id", sa.Uuid(), nullable=True),
        sa.Column("summary_job_id", sa.Uuid(), nullable=True),
        sa.Column("summary_revision", sa.Integer(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("template_identity", sa.JSON(), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=True),
        sa.Column("wbs_version_id", sa.Uuid(), nullable=True),
        sa.Column("validation_id", sa.Uuid(), nullable=True),
        sa.Column("generation_input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_revision", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_workflow_document_scope",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_generation_scope",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_workflow_run_scope",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_workflow_summary_scope",
        ),
        sa.ForeignKeyConstraint(
            ["summary_job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_summary_job_scope",
        ),
        sa.ForeignKeyConstraint(
            ["template_id", "tenant_id"],
            ["wbs_templates.id", "wbs_templates.tenant_id"],
            name="fk_workflow_template_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["validation_id", "tenant_id", "wbs_version_id"],
            ["validation_runs.id", "validation_runs.tenant_id", "validation_runs.wbs_version_id"],
            name="fk_workflow_validation_scope",
        ),
        sa.ForeignKeyConstraint(
            ["wbs_version_id", "tenant_id", "project_id"],
            ["wbs_versions.id", "wbs_versions.tenant_id", "wbs_versions.project_id"],
            name="fk_workflow_wbs_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", "project_id", name="uq_workflow_project_scope"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_workflow_tenant_scope"),
    )

    op.create_table(
        "workflow_request_keys",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("result_workflow_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["document_upload_attempts.id", "document_upload_attempts.tenant_id"],
            name="fk_request_upload_scope",
        ),
        sa.ForeignKeyConstraint(
            ["result_workflow_id", "tenant_id"],
            ["document_workflows.id", "document_workflows.tenant_id"],
            name="fk_request_workflow_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", "key_digest"),
    )

    op.create_table(
        "document_workflow_dispatches",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("validation_id", sa.Uuid(), nullable=True),
        sa.Column("wbs_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "(kind IN ('summary', 'generation') AND job_id IS NOT NULL AND validation_id IS NULL) OR (kind = 'validation' AND validation_id IS NOT NULL AND wbs_version_id IS NOT NULL AND job_id IS NULL)",
            name="ck_workflow_dispatch_target",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_workflow_dispatch_job",
        ),
        sa.ForeignKeyConstraint(
            ["validation_id", "tenant_id", "wbs_version_id"],
            ["validation_runs.id", "validation_runs.tenant_id", "validation_runs.wbs_version_id"],
            name="fk_workflow_dispatch_validation",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id", "tenant_id", "project_id"],
            [
                "document_workflows.id",
                "document_workflows.tenant_id",
                "document_workflows.project_id",
            ],
            name="fk_workflow_dispatch_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_workflow_dispatch_job"),
        sa.UniqueConstraint("validation_id", name="uq_workflow_dispatch_validation"),
    )

    op.create_table(
        "document_content_rejections",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
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
        sa.CheckConstraint("length(sha256) = 64", name="ck_rejection_hash_length"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "sha256"),
    )

    op.create_index(
        "ix_workflow_dispatch_pending",
        "document_workflow_dispatches",
        ["tenant_id", "status", "lease_expires_at"],
    )
    op.create_index(
        "ix_upload_attempt_cleanup", "document_upload_attempts", ["state", "updated_at"]
    )
    op.create_index(
        "ix_workflow_document", "document_workflows", ["tenant_id", "document_id", "created_at"]
    )
    op.create_index(
        "uq_workflow_base_document",
        "document_workflows",
        ["tenant_id", "document_id"],
        unique=True,
        postgresql_where=sa.text("is_base"),
        sqlite_where=sa.text("is_base = 1"),
    )
    for table, name in (
        ("jobs", "fk_job_workflow_scope"),
        ("wbs_versions", "fk_wbs_workflow_scope"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                name,
                "document_workflows",
                ["workflow_id", "tenant_id", "project_id"],
                ["id", "tenant_id", "project_id"],
            )
    if op.get_bind().dialect.name == "postgresql":
        role = op.get_context().config.attributes.get("runtime_database_role")
        if not role:
            raise RuntimeError("Runtime role required for document workflow grants")
        quoted = op.get_bind().dialect.identifier_preparer.quote(str(role))
        for table in NEW_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} USING ({expression}) WITH CHECK ({expression})"
            )
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {quoted}")


def downgrade():
    for table, name in (
        ("jobs", "fk_job_workflow_scope"),
        ("wbs_versions", "fk_wbs_workflow_scope"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    for table, name, _ in reversed(SCOPES):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="unique")
    for table in ("jobs", "wbs_versions"):
        op.drop_index("ix_" + table + "_workflow_id", table_name=table)
        op.drop_column(table, "workflow_id")
    op.drop_column("validation_runs", "wbs_snapshot")
    op.drop_column("validation_runs", "wbs_revision")
    op.drop_column("wbs_versions", "revision")
    op.drop_column("document_summaries", "revision")
    op.drop_index("ix_documents_upload_fingerprint", table_name="documents")
    op.drop_column("documents", "upload_sha256")
