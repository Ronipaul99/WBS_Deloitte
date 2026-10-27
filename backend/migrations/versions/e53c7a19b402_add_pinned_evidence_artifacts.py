"""Allow scoped Step 7 pages and protect durable evidence-tool allowances."""

import sqlalchemy as sa
from alembic import op

from migrations.versions.b7e31d95a204_add_durable_agent_execution import _roles

revision = "e53c7a19b402"
down_revision = "c29f4b8e710a"
branch_labels = None
depends_on = None

OLD = "'facts.v1','summary_content.v1','verification.v1','orchestration.v1'"
NEW = "'inventory_manifest.v1','inventory_page.v1','reading_batch.v1','coverage_page.v1'"


def kind_constraint(extra):
    return (
        "artifact->>'kind' IS NOT NULL AND "
        f"artifact->>'kind' IN ({OLD}{',' + NEW if extra else ''}) "
        "AND jsonb_typeof(artifact->'payload')='object'"
        + (
            f" AND (artifact->>'kind' NOT IN ({NEW}) OR "
            "(node='evidence:' || (artifact->>'kind') AND state='completed'))"
            if extra
            else ""
        )
    )


def upgrade():
    _roles()
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint("ck_agent_step_runs_artifact_kind", "agent_step_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_step_runs_artifact_kind", "agent_step_runs", kind_constraint(True)
    )
    op.execute("""CREATE FUNCTION agent_evidence_tools_monotonic() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
    DECLARE old_tools jsonb; new_tools jsonb; item jsonb;
    BEGIN
      old_tools := OLD.execution->'evidence_tools';
      new_tools := NEW.execution->'evidence_tools';
      IF jsonb_typeof(old_tools)='object' THEN
        IF jsonb_typeof(new_tools) IS DISTINCT FROM 'object' OR
           new_tools->'binding' IS DISTINCT FROM old_tools->'binding' OR
           new_tools->'policy' IS DISTINCT FROM old_tools->'policy' OR
           COALESCE((new_tools->>'calls')::int,-1) < (old_tools->>'calls')::int OR
           COALESCE((new_tools->>'reserved_bytes')::bigint,-1) <
             (old_tools->>'reserved_bytes')::bigint OR
           COALESCE((new_tools->>'reserved_tokens')::bigint,-1) <
             (old_tools->>'reserved_tokens')::bigint THEN
          RAISE EXCEPTION 'Evidence allowance cannot reset' USING ERRCODE='23514';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(old_tools->'requests') LOOP
          IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(new_tools->'requests') n
            WHERE n->>'request_sha256'=item->>'request_sha256'
            AND (n->>'count')::int >= (item->>'count')::int) THEN
            RAISE EXCEPTION 'Evidence request allowance cannot reset' USING ERRCODE='23514';
          END IF;
        END LOOP;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER agent_evidence_tools_monotonic BEFORE UPDATE ON agent_workflow_runs "
        "FOR EACH ROW EXECUTE FUNCTION agent_evidence_tools_monotonic()"
    )


def downgrade():
    _roles()
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM agent_step_runs WHERE node LIKE 'evidence:%'")):
        raise RuntimeError("refusing downgrade with evidence artifacts")
    if bind.dialect.name == "postgresql":
        if bind.scalar(
            sa.text(
                "SELECT count(*) FROM agent_workflow_runs "
                "WHERE jsonb_typeof(execution->'evidence_tools')='object'"
            )
        ):
            raise RuntimeError("refusing downgrade with evidence accounting")
        op.execute("DROP TRIGGER agent_evidence_tools_monotonic ON agent_workflow_runs")
        op.execute("DROP FUNCTION agent_evidence_tools_monotonic()")
        op.drop_constraint("ck_agent_step_runs_artifact_kind", "agent_step_runs", type_="check")
        op.create_check_constraint(
            "ck_agent_step_runs_artifact_kind", "agent_step_runs", kind_constraint(False)
        )
    else:
        for execution in bind.scalars(sa.text("SELECT execution FROM agent_workflow_runs")):
            import json

            if json.loads(execution).get("evidence_tools"):
                raise RuntimeError("refusing downgrade with evidence accounting")
