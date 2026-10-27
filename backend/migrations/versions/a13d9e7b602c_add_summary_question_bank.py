"""Shared summary question templates, independent of pending agent deployment.

Revision ID: a13d9e7b602c
Revises: e71c4a9b203d
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "a13d9e7b602c"
down_revision = "e71c4a9b203d"
branch_labels = ("summary_question_bank",)
depends_on = None


def _roles() -> tuple[str, str] | None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("Question bank migration requires online role verification")
    runtime = context.config.attributes.get("runtime_database_role")
    owner = context.config.attributes.get("migration_database_role")
    role = (
        bind.execute(
            sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=:runtime"),
            {"runtime": runtime},
        )
        .mappings()
        .one_or_none()
    )
    if (
        not runtime
        or not owner
        or runtime == owner
        or role is None
        or role["rolsuper"]
        or role["rolbypassrls"]
        or owner != bind.scalar(sa.text("SELECT current_user"))
    ):
        raise RuntimeError("Separate migration and restricted runtime roles are required")
    if bind.scalar(
        sa.text("SELECT pg_has_role(:runtime,:owner,'MEMBER')"),
        {"runtime": runtime, "owner": owner},
    ):
        raise RuntimeError("Runtime must not inherit the migration role")
    if bind.scalar(
        sa.text("SELECT has_schema_privilege(:runtime,'public','CREATE')"),
        {"runtime": runtime},
    ):
        raise RuntimeError("Runtime must not create schema")
    return runtime, owner


def upgrade() -> None:
    roles = _roles()
    op.create_table(
        "rfp_question_bank",
        sa.Column("question_set_id", sa.String(80), nullable=False),
        sa.Column("question_id", sa.String(40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(160), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "extraction_instructions", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.Column("answer_type", sa.String(40), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("embedding", sa.JSON().with_variant(Vector(384), "postgresql"), nullable=False),
        sa.Column("embedding_provider", sa.String(40), nullable=False),
        sa.Column("embedding_model", sa.String(160), nullable=False),
        sa.Column("embedding_model_revision", sa.String(128), nullable=False),
        sa.Column("embedding_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_formatting_version", sa.String(80), nullable=False),
        sa.Column("query_prefix", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("question_set_id", "question_id"),
        sa.UniqueConstraint("question_set_id", "ordinal", name="uq_rfp_question_order"),
        sa.CheckConstraint("ordinal > 0", name="ck_rfp_question_ordinal"),
        sa.CheckConstraint("embedding_dimensions = 384", name="ck_rfp_question_dimensions"),
        sa.CheckConstraint(
            "answer_type IN ('structured_summary','structured_list')",
            name="ck_rfp_question_answer_type",
        ),
    )
    if roles:
        quote = op.get_bind().dialect.identifier_preparer.quote
        # Shared system templates contain no tenant/document data. All application
        # tenants may read them; only the migration owner can seed new versions.
        op.execute("REVOKE ALL ON rfp_question_bank FROM PUBLIC")
        op.execute(f"REVOKE ALL ON rfp_question_bank FROM {quote(roles[0])}")
        op.execute(f"GRANT SELECT ON rfp_question_bank TO {quote(roles[0])}")
        op.create_check_constraint(
            "ck_rfp_question_instructions",
            "rfp_question_bank",
            "jsonb_typeof(extraction_instructions)='array' "
            "AND jsonb_array_length(extraction_instructions) BETWEEN 1 AND 30",
        )
        op.create_check_constraint(
            "ck_rfp_question_unit_vector",
            "rfp_question_bank",
            "(embedding <#> embedding) BETWEEN -1.002001 AND -0.998001",
        )
        op.create_check_constraint(
            "ck_rfp_question_hashes",
            "rfp_question_bank",
            "content_sha256 ~ '^[0-9a-f]{64}$' AND embedding_manifest_sha256 ~ '^[0-9a-f]{64}$'",
        )


def downgrade() -> None:
    _roles()
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM rfp_question_bank")):
        raise RuntimeError("Refusing to drop a populated, versioned question bank")
    op.drop_table("rfp_question_bank")
