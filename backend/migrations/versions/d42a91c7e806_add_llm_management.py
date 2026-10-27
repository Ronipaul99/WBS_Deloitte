"""Step 6 optimistic management and document-free test persistence.

Revision ID: d42a91c7e806
Revises: b7e31d95a204
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d42a91c7e806"
down_revision = "b7e31d95a204"
branch_labels = None
depends_on = None


def _roles():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("Agent execution requires online role verification")
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
        raise RuntimeError("Separate verified migration/runtime roles required")
    if bind.scalar(
        sa.text("SELECT pg_has_role(:runtime,:owner,'MEMBER')"),
        {"runtime": runtime, "owner": owner},
    ):
        raise RuntimeError("Runtime must not inherit the migration role")
    if bind.scalar(
        sa.text("SELECT has_schema_privilege(:runtime,'public','CREATE')"), {"runtime": runtime}
    ):
        raise RuntimeError("Runtime must not create schema")


def upgrade():
    _roles()
    js = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    for table in ("llm_connections", "llm_model_profiles"):
        op.add_column(
            table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
    op.add_column(
        "llm_model_profile_versions",
        sa.Column("settings", js, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "llm_model_profile_versions", sa.Column("qualification_test_id", sa.Uuid(), nullable=True)
    )
    with op.batch_alter_table("jobs") as batch:
        batch.create_unique_constraint("uq_jobs_id_tenant", ["id", "tenant_id"])
    op.create_table(
        "llm_connection_tests",
        *[
            sa.Column(n, sa.Uuid(), nullable=False)
            for n in (
                "id",
                "tenant_id",
                "connection_id",
                "profile_id",
                "profile_version_id",
                "requested_by",
            )
        ],
        *[sa.Column(n, js, nullable=False) for n in ("configuration", "ledger", "result")],
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("delivery_state", sa.String(20), nullable=False),
        *[
            sa.Column(n, sa.Integer(), nullable=False)
            for n in ("fence", "delivery_fence", "delivery_attempts")
        ],
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_lease_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["id", "tenant_id"], ["jobs.id", "jobs.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"], ["llm_connections.id", "llm_connections.tenant_id"]
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id", "tenant_id", "profile_id", "connection_id"],
            [
                "llm_model_profile_versions.id",
                "llm_model_profile_versions.tenant_id",
                "llm_model_profile_versions.profile_id",
                "llm_model_profile_versions.connection_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_llm_test_scope"),
        sa.UniqueConstraint(
            "id", "tenant_id", "connection_id", "profile_id", name="uq_llm_test_profile_scope"
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','failed','unavailable')",
            name="ck_llm_test_state",
        ),
        sa.CheckConstraint(
            "delivery_state IN ('pending','publishing','published','retry','dead')",
            name="ck_llm_test_delivery",
        ),
        sa.CheckConstraint(
            "fence>=0 AND delivery_fence>=0 AND delivery_attempts BETWEEN 0 AND 5",
            name="ck_llm_test_counts",
        ),
    )
    op.create_index(
        "ix_llm_tests_delivery", "llm_connection_tests", ["tenant_id", "state", "available_at"]
    )
    with op.batch_alter_table("llm_model_profile_versions") as batch:
        batch.create_foreign_key(
            "fk_profile_qualification_test",
            "llm_connection_tests",
            ["qualification_test_id", "tenant_id", "connection_id", "profile_id"],
            ["id", "tenant_id", "connection_id", "profile_id"],
        )
    if op.get_bind().dialect.name == "postgresql":
        cfg = op.get_context().config.attributes
        q = op.get_bind().dialect.identifier_preparer.quote
        runtime, owner = q(cfg["runtime_database_role"]), q(cfg["migration_database_role"])
        op.execute("ALTER TABLE llm_connection_tests ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE llm_connection_tests FORCE ROW LEVEL SECURITY")
        scope = "tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid"
        op.execute("REVOKE ALL ON llm_connection_tests FROM PUBLIC")
        op.execute(f"REVOKE ALL ON llm_connection_tests FROM {runtime}")
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON llm_connection_tests TO {runtime}")
        op.execute(
            f"CREATE POLICY llm_test_scope ON llm_connection_tests TO {runtime} "
            f"USING ({scope}) WITH CHECK ({scope})"
        )
        op.execute(
            f"CREATE POLICY llm_test_owner ON llm_connection_tests TO {owner} "
            "USING (true) WITH CHECK (true)"
        )
        for column, bound in (("configuration", 65536), ("ledger", 32768), ("result", 65536)):
            op.create_check_constraint(
                f"ck_llm_test_{column}",
                "llm_connection_tests",
                f"jsonb_typeof({column})='object' AND agent_storage_json_safe({column}) "
                f"AND octet_length({column}::text)<={bound}",
            )
        op.create_check_constraint(
            "ck_llm_profile_settings_safe",
            "llm_model_profile_versions",
            "jsonb_typeof(settings)='object' AND agent_storage_json_safe(settings) "
            "AND octet_length(settings::text)<=16384",
        )
        op.execute("""CREATE FUNCTION llm_test_guard() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$ BEGIN
          IF OLD.state IN ('succeeded','failed','unavailable') OR
             (to_jsonb(NEW) - ARRAY['ledger','result','state','delivery_state','fence',
               'delivery_fence','delivery_attempts','available_at','lease_expires_at','delivery_lease_at',
               'error_code','updated_at']) IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['ledger','result','state','delivery_state','fence',
               'delivery_fence','delivery_attempts','available_at','lease_expires_at','delivery_lease_at',
               'error_code','updated_at']) OR
             NEW.fence < OLD.fence OR NEW.delivery_fence < OLD.delivery_fence OR
             NEW.delivery_attempts < OLD.delivery_attempts OR
             NEW.ledger->'deadline' IS DISTINCT FROM OLD.ledger->'deadline' OR
             (OLD.ledger->>'violated'='true' AND
                NEW.ledger->>'violated' IS DISTINCT FROM 'true') OR
             (NEW.ledger->>'calls')::int < (OLD.ledger->>'calls')::int OR
             (NEW.ledger->>'reserved_tokens')::int < (OLD.ledger->>'reserved_tokens')::int THEN
            RAISE EXCEPTION 'Test scope/accounting is immutable' USING ERRCODE='23514';
          END IF; RETURN NEW; END $$""")
        op.execute(
            "CREATE TRIGGER llm_test_guard BEFORE UPDATE ON llm_connection_tests "
            "FOR EACH ROW EXECUTE FUNCTION llm_test_guard()"
        )


def downgrade():
    _roles()
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM llm_connection_tests")):
        raise RuntimeError("refusing downgrade with test accounting/history")
    with op.batch_alter_table("llm_model_profile_versions") as batch:
        batch.drop_constraint("fk_profile_qualification_test", type_="foreignkey")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "ck_llm_profile_settings_safe", "llm_model_profile_versions", type_="check"
        )
        op.execute("DROP TRIGGER llm_test_guard ON llm_connection_tests")
        op.execute("DROP FUNCTION llm_test_guard()")
    op.drop_table("llm_connection_tests")
    op.drop_column("llm_model_profile_versions", "qualification_test_id")
    op.drop_column("llm_model_profile_versions", "settings")
    for table in ("llm_connections", "llm_model_profiles"):
        op.drop_column(table, "revision")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("uq_jobs_id_tenant", type_="unique")
