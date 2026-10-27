"""Step 5 execution ledger and fenced delivery, preserving Step 2 scope policies.

Revision ID: b7e31d95a204
Revises: f8c2a6d903b1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7e31d95a204"
down_revision = "f8c2a6d903b1"
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
    op.add_column(
        "agent_workflow_runs",
        sa.Column(
            "execution",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "workflow_dispatch_outbox",
        sa.Column(
            "fencing_token",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    with op.batch_alter_table("workflow_dispatch_outbox") as batch:
        batch.drop_constraint("ck_workflow_delivery_state", type_="check")
        batch.create_check_constraint(
            "ck_workflow_delivery_state",
            "status IN ('pending','claimed','publishing','published','retry','dead')",
        )
        batch.create_check_constraint("ck_workflow_fence", "fencing_token >= 0")
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_agent_execution_safe",
            "agent_workflow_runs",
            "jsonb_typeof(execution) = 'object' AND agent_storage_json_safe(execution) "
            "AND octet_length(execution::text) <= 131072",
        )
        for table in ("agent_step_runs", "agent_checkpoints"):
            op.drop_constraint(f"ck_{table}_artifact_kind", table, type_="check")
            op.create_check_constraint(
                f"ck_{table}_artifact_kind",
                table,
                "artifact->>'kind' IS NOT NULL AND artifact->>'kind' IN "
                "('facts.v1','summary_content.v1','verification.v1','orchestration.v1') "
                "AND jsonb_typeof(artifact->'payload') = 'object'",
            )
        op.execute("""
        CREATE FUNCTION agent_execution_monotonic() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public AS $$
        BEGIN
          IF OLD.execution <> '{}'::jsonb AND (
            NEW.execution->'deadline' IS DISTINCT FROM OLD.execution->'deadline' OR
            NEW.execution->'endpoint' IS DISTINCT FROM OLD.execution->'endpoint' OR
            (OLD.execution->>'binding' IS NOT NULL AND
              NEW.execution->'binding' IS DISTINCT FROM OLD.execution->'binding') OR
            COALESCE((NEW.execution->>'calls')::integer, -1) <
              (OLD.execution->>'calls')::integer OR
            COALESCE((NEW.execution->>'reserved_tokens')::bigint, -1) <
              (OLD.execution->>'reserved_tokens')::bigint OR
            COALESCE((NEW.execution->>'format_repairs')::integer, -1) <
              (OLD.execution->>'format_repairs')::integer OR
            COALESCE((NEW.execution->>'node_start_calls')::integer, -1) <
              (OLD.execution->>'node_start_calls')::integer OR
            COALESCE((NEW.execution->>'resumes')::integer, -1) <
              (OLD.execution->>'resumes')::integer OR
            COALESCE((NEW.execution->'cursor'->>'sequence')::integer, -1) <
              (OLD.execution->'cursor'->>'sequence')::integer OR
            COALESCE((NEW.execution->'cursor'->>'graph_repairs')::integer, -1) <
              (OLD.execution->'cursor'->>'graph_repairs')::integer OR
            (OLD.execution->>'violated' = 'true' AND
              NEW.execution->>'violated' IS DISTINCT FROM 'true')
          ) THEN
            RAISE EXCEPTION 'Execution ledger cannot reset' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$
        """)
        op.execute(
            "CREATE TRIGGER agent_execution_monotonic BEFORE UPDATE ON "
            "agent_workflow_runs FOR EACH ROW EXECUTE FUNCTION agent_execution_monotonic()"
        )


def downgrade():
    _roles()
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT count(*) FROM agent_workflow_runs WHERE execution <> '{}'")
    ) or bind.scalar(
        sa.text("SELECT count(*) FROM workflow_dispatch_outbox WHERE status IN ('claimed','retry')")
    ):
        raise RuntimeError("refusing downgrade with durable execution state")
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER agent_execution_monotonic ON agent_workflow_runs")
        op.execute("DROP FUNCTION agent_execution_monotonic()")
        for table in ("agent_step_runs", "agent_checkpoints"):
            op.drop_constraint(f"ck_{table}_artifact_kind", table, type_="check")
            op.create_check_constraint(
                f"ck_{table}_artifact_kind",
                table,
                "artifact->>'kind' IS NOT NULL AND artifact->>'kind' IN "
                "('facts.v1','summary_content.v1','verification.v1') "
                "AND jsonb_typeof(artifact->'payload') = 'object'",
            )
        op.drop_constraint("ck_agent_execution_safe", "agent_workflow_runs", type_="check")
    with op.batch_alter_table("workflow_dispatch_outbox") as batch:
        batch.drop_constraint("ck_workflow_delivery_state", type_="check")
        batch.drop_constraint("ck_workflow_fence", type_="check")
        batch.create_check_constraint(
            "ck_workflow_delivery_state", "status IN ('pending','publishing','published','dead')"
        )
        batch.drop_column("fencing_token")
    op.drop_column("agent_workflow_runs", "execution")
