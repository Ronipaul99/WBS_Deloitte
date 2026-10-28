"""Scoped structured drafts and fenced local result import.

Revision ID: f05c8e31b742
Revises: e94b7d20a631
"""

import sqlalchemy as sa
from alembic import op

revision = "f05c8e31b742"
down_revision = "e94b7d20a631"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("summary_api_requests") as batch:
        batch.create_unique_constraint(
            "uq_summary_request_document", ["id", "tenant_id", "document_id"]
        )
    with op.batch_alter_table("document_summaries") as batch:
        batch.add_column(sa.Column("source_request_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("structured_summary", sa.JSON(none_as_null=True), nullable=True))
        batch.create_foreign_key(
            "fk_summary_external_source",
            "summary_api_requests",
            ["source_request_id", "tenant_id", "document_id"],
            ["id", "tenant_id", "document_id"],
        )
    op.create_table(
        "summary_result_imports",
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        *[
            sa.Column(name, sa.Uuid(), nullable=False)
            for name in ("tenant_id", "project_id", "document_id")
        ],
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("first_completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("summary_id", sa.Uuid(), nullable=True),
        sa.Column("imported_revision", sa.Integer(), nullable=True),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_summary_import_request",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_summary_import_summary",
        ),
        sa.CheckConstraint(
            "state IN ('WAITING','VALIDATING','IMPORTED','INVALID','STALE')",
            name="ck_summary_import_state",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_summary_import_attempts"),
        sa.CheckConstraint(
            "(state = 'VALIDATING' AND owner_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (state != 'VALIDATING' "
            "AND owner_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_summary_import_lease",
        ),
        sa.CheckConstraint(
            "(state = 'IMPORTED' AND summary_id IS NOT NULL "
            "AND imported_revision IS NOT NULL AND imported_revision > 0 "
            "AND result_digest IS NOT NULL AND length(result_digest) = 64 "
            "AND imported_at IS NOT NULL) OR (state != 'IMPORTED' "
            "AND summary_id IS NULL AND imported_revision IS NULL "
            "AND result_digest IS NULL AND imported_at IS NULL)",
            name="ck_summary_import_identity",
        ),
    )
    op.create_index(
        "ix_summary_import_due", "summary_result_imports", ["tenant_id", "state", "available_at"]
    )
    if op.get_bind().dialect.name == "postgresql":
        role = op.get_context().config.attributes.get("runtime_database_role")
        flags = (
            op.get_bind()
            .execute(
                sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"),
                {"role": role},
            )
            .first()
        )
        if not role or flags is None or any(flags):
            raise RuntimeError("A separate restricted runtime role is required")
        current = op.get_bind().execute(sa.text("SELECT current_user")).scalar()
        if current == role:
            raise RuntimeError("Migration and runtime roles must be separate")
        quoted = op.get_bind().dialect.identifier_preparer.quote(role)
        op.execute("ALTER TABLE summary_result_imports ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE summary_result_imports FORCE ROW LEVEL SECURITY")
        expression = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            "CREATE POLICY tenant_isolation ON summary_result_imports "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON summary_result_imports TO {quoted}")
        op.execute("""CREATE FUNCTION protect_summary_import_identity()
          RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF OLD.state = 'IMPORTED' AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'Imported summary identity is immutable';
          END IF; RETURN NEW; END $$""")
        op.execute(
            "CREATE TRIGGER summary_import_immutable BEFORE UPDATE ON summary_result_imports "
            "FOR EACH ROW EXECUTE FUNCTION protect_summary_import_identity()"
        )


def downgrade():
    op.drop_table("summary_result_imports")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION protect_summary_import_identity()")
    with op.batch_alter_table("document_summaries") as batch:
        batch.drop_constraint("fk_summary_external_source", type_="foreignkey")
        batch.drop_column("structured_summary")
        batch.drop_column("source_request_id")
    with op.batch_alter_table("summary_api_requests") as batch:
        batch.drop_constraint("uq_summary_request_document", type_="unique")
