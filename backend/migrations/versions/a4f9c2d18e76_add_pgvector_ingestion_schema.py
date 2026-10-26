"""add pgvector ingestion schema

Revision ID: a4f9c2d18e76
Revises: f2a84d719c35
Create Date: 2026-10-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "a4f9c2d18e76"
down_revision: str | None = "f2a84d719c35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_RUN_PREDICATE = "status IN ('QUEUED', 'IN_PROGRESS')"
TENANT_POLICY_EXPRESSION = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
PROTECTED_TABLES = ("document_processing_runs", "document_chunks")


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _runtime_role() -> str:
    role = op.get_context().config.attributes.get("runtime_database_role")
    if not role:
        raise RuntimeError("Runtime database role is required for the ingestion schema migration")
    return str(role)


def _prepare_postgresql_security() -> str | None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    if op.get_context().as_sql:
        raise RuntimeError(
            "The ingestion schema migration requires an online PostgreSQL connection"
        )

    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except sa.exc.SQLAlchemyError:
        raise RuntimeError(
            "pgvector extension setup failed; verify migration-role extension privileges"
        ) from None

    runtime_role = _runtime_role()
    configured_migration_role = op.get_context().config.attributes.get("migration_database_role")
    role = (
        bind.execute(
            sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :runtime_role"),
            {"runtime_role": runtime_role},
        )
        .mappings()
        .one_or_none()
    )
    current_role = str(bind.scalar(sa.text("SELECT current_user")))
    if role is None:
        raise RuntimeError("Configured runtime database role does not exist")
    if (
        not configured_migration_role
        or configured_migration_role != current_role
        or runtime_role == current_role
        or runtime_role == configured_migration_role
        or role["rolsuper"]
        or role["rolbypassrls"]
    ):
        raise RuntimeError(
            "Database roles must be separate; runtime must be non-superuser without BYPASSRLS"
        )
    return runtime_role


def _apply_postgresql_security(runtime_role: str | None) -> None:
    if runtime_role is None:
        return
    bind = op.get_bind()
    quoted_role = bind.dialect.identifier_preparer.quote(runtime_role)
    for table in PROTECTED_TABLES:
        policy = f"{table}_tenant_isolation"
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {quoted_role}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {policy} ON {table} FOR ALL TO {quoted_role} "
            f"USING ({TENANT_POLICY_EXPRESSION}) "
            f"WITH CHECK ({TENANT_POLICY_EXPRESSION})"
        )


def upgrade() -> None:
    runtime_role = _prepare_postgresql_security()

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.create_unique_constraint("uq_jobs_scope", ["id", "tenant_id", "project_id"])

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("content_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("processing_status", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("processing_error_code", sa.String(length=80), nullable=True))
        batch_op.create_unique_constraint("uq_documents_scope", ["id", "tenant_id", "project_id"])
        batch_op.create_check_constraint(
            "ck_documents_processing_status",
            "processing_status IS NULL OR processing_status IN "
            "('QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED')",
        )
        batch_op.create_check_constraint(
            "ck_documents_content_sha256",
            "content_sha256 IS NULL OR length(content_sha256) = 64",
        )

    op.create_table(
        "document_processing_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("document_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("extractor_name", sa.String(length=80), nullable=False),
        sa.Column("extractor_version", sa.String(length=40), nullable=False),
        sa.Column("embedding_provider", sa.String(length=40), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("worksheet_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("block_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_runs_status",
        ),
        sa.CheckConstraint("embedding_dimensions = 384", name="ck_runs_embedding_dimensions"),
        sa.CheckConstraint(
            "length(document_content_sha256) = 64",
            name="ck_runs_document_content_sha256",
        ),
        sa.CheckConstraint(
            "page_count >= 0 AND worksheet_count >= 0 AND block_count >= 0 AND chunk_count >= 0",
            name="ck_runs_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_runs_document_scope",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_runs_job_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", "project_id", "document_id", name="uq_runs_scope"),
        sa.UniqueConstraint(
            "document_id",
            "document_content_sha256",
            "extractor_name",
            "extractor_version",
            "embedding_provider",
            "embedding_model",
            "embedding_dimensions",
            name="uq_runs_idempotency",
        ),
    )
    op.create_index(
        "ix_runs_scope_history",
        "document_processing_runs",
        ["tenant_id", "project_id", "document_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_runs_active_document",
        "document_processing_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_RUN_PREDICATE),
        sqlite_where=sa.text(ACTIVE_RUN_PREDICATE),
    )

    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "document_chunks",
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("block_type", sa.String(length=40), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("worksheet_name", sa.String(length=160), nullable=True),
        sa.Column("row_start", sa.Integer(), nullable=True),
        sa.Column("row_end", sa.Integer(), nullable=True),
        sa.Column("heading_path", json_type, nullable=False),
        sa.Column("source_metadata", json_type, nullable=False),
        sa.Column("embedding", Vector(384).with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        sa.CheckConstraint("token_count > 0", name="ck_chunks_token_count_positive"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_chunks_content_sha256"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_chunks_page_number_positive",
        ),
        sa.CheckConstraint(
            "(row_start IS NULL AND row_end IS NULL) OR (row_start > 0 AND row_end >= row_start)",
            name="ck_chunks_row_range",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_chunks_run_scope",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("processing_run_id", "ordinal", name="uq_chunks_run_ordinal"),
    )
    op.create_index(
        "ix_chunks_scope",
        "document_chunks",
        ["tenant_id", "project_id", "document_id", "processing_run_id"],
        unique=False,
    )

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("current_processing_run_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_documents_active_run_scope",
            "document_processing_runs",
            ["current_processing_run_id", "tenant_id", "project_id", "id"],
            ["id", "tenant_id", "project_id", "document_id"],
            deferrable=True,
            initially="DEFERRED",
        )

    _apply_postgresql_security(runtime_role)


def _assert_ingestion_tables_empty() -> None:
    bind = op.get_bind()
    has_data = bind.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_chunks) "
            "OR EXISTS (SELECT 1 FROM document_processing_runs)"
        )
    )
    if has_data:
        raise RuntimeError(
            "Ingestion schema contains data; use a reviewed forward fix instead of downgrade"
        )


def downgrade() -> None:
    _assert_ingestion_tables_empty()

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("fk_documents_active_run_scope", type_="foreignkey")
        batch_op.drop_column("current_processing_run_id")

    op.drop_index("ix_chunks_scope", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("uq_runs_active_document", table_name="document_processing_runs")
    op.drop_index("ix_runs_scope_history", table_name="document_processing_runs")
    op.drop_table("document_processing_runs")

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("ck_documents_content_sha256", type_="check")
        batch_op.drop_constraint("ck_documents_processing_status", type_="check")
        batch_op.drop_constraint("uq_documents_scope", type_="unique")
        batch_op.drop_column("processing_error_code")
        batch_op.drop_column("processed_at")
        batch_op.drop_column("processing_status")
        batch_op.drop_column("content_sha256")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("uq_jobs_scope", type_="unique")

    # The vector extension may be shared by other applications or schemas.
    # Downgrade intentionally never drops it.
