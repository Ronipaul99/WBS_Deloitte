"""Scoped agent persistence and permissions substrate.

Revision ID: f8c2a6d903b1
Revises: e71c4a9b203d

Frozen migration schema; never imports application metadata or reads .env files.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f8c2a6d903b1"
down_revision = "e71c4a9b203d"
branch_labels = None
depends_on = None

PROTECTED_TABLES = (
    "llm_connections",
    "llm_credential_versions",
    "llm_model_profiles",
    "llm_model_profile_versions",
    "agent_workflow_runs",
    "agent_step_runs",
    "agent_checkpoints",
    "workflow_dispatch_outbox",
    "summary_revisions",
    "summary_evidence",
    "summary_approval_events",
)
APPEND_ONLY = (
    "llm_model_profile_versions",
    "agent_checkpoints",
    "summary_revisions",
    "summary_evidence",
    "summary_approval_events",
)
JSON_COLUMNS = {
    "llm_connections": ("endpoint_policy",),
    "llm_model_profile_versions": ("snapshot",),
    "agent_workflow_runs": ("input_snapshot", "budget"),
    "agent_step_runs": ("artifact", "usage"),
    "agent_checkpoints": ("artifact",),
    "summary_revisions": ("content",),
    "summary_evidence": ("locator",),
}


def _security_roles():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return None
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("Agent schema requires online PostgreSQL role verification")
    runtime = context.config.attributes.get("runtime_database_role")
    owner = context.config.attributes.get("migration_database_role")
    actual = bind.scalar(sa.text("SELECT current_user"))
    role = (
        bind.execute(
            sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :runtime"),
            {"runtime": runtime},
        )
        .mappings()
        .one_or_none()
    )
    if (
        not runtime
        or not owner
        or owner != actual
        or runtime == owner
        or role is None
        or role["rolsuper"]
        or role["rolbypassrls"]
    ):
        raise RuntimeError(
            "Separate migration/runtime roles without runtime BYPASSRLS are required"
        )
    if bind.scalar(
        sa.text("SELECT pg_has_role(:runtime, :owner, 'MEMBER')"),
        {"runtime": runtime, "owner": owner},
    ):
        raise RuntimeError("Runtime must not inherit the migration role")
    if bind.scalar(
        sa.text("SELECT has_schema_privilege(:runtime, 'public', 'CREATE')"), {"runtime": runtime}
    ):
        raise RuntimeError("Runtime must not have schema creation privileges")
    return str(runtime), str(owner)


JSON_SAFETY_SQL = r"""
CREATE FUNCTION agent_storage_json_safe(value jsonb, depth integer DEFAULT 0)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog AS $$
DECLARE item record; child jsonb;
BEGIN
  IF depth > 16 THEN RETURN false; END IF;
  IF jsonb_typeof(value) = 'object' THEN
    FOR item IN SELECT * FROM jsonb_each(value) LOOP
      IF regexp_replace(lower(item.key), '[^a-z0-9]', '', 'g') = ANY(ARRAY[
        'apikey','secret','password','authorization','headers','credentials','credential',
        'accesstoken','refreshtoken','messages','prompt','prompts','transcript','rawresponse',
        'rawrequest','chainofthought','reasoning']) THEN RETURN false; END IF;
      IF NOT public.agent_storage_json_safe(item.value, depth + 1) THEN RETURN false; END IF;
    END LOOP;
  ELSIF jsonb_typeof(value) = 'array' THEN
    IF jsonb_array_length(value) > 100000 THEN RETURN false; END IF;
    FOR child IN SELECT * FROM jsonb_array_elements(value) LOOP
      IF NOT public.agent_storage_json_safe(child, depth + 1) THEN RETURN false; END IF;
    END LOOP;
  END IF;
  RETURN true;
END $$
"""

IMMUTABILITY_SQL = """
CREATE FUNCTION agent_storage_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
DECLARE key text; before_row jsonb; after_row jsonb;
BEGIN
  before_row := to_jsonb(OLD); after_row := to_jsonb(NEW);
  IF TG_ARGV[0] = 'append_only' THEN
    RAISE EXCEPTION 'Append-only agent record cannot be updated' USING ERRCODE = '23514';
  END IF;
  FOREACH key IN ARRAY ARRAY['id','tenant_id','connection_id','profile_id','workflow_run_id',
    'project_id','document_id','processing_run_id','job_id'] LOOP
    IF (before_row -> key) IS DISTINCT FROM (after_row -> key) THEN
      RAISE EXCEPTION 'Agent record scope is immutable' USING ERRCODE = '23514';
    END IF;
  END LOOP;
  IF TG_TABLE_NAME = 'agent_workflow_runs' THEN
    FOREACH key IN ARRAY ARRAY['input_snapshot','source_sha256','profile_version_id',
      'requested_by','budget','request_sequence'] LOOP
      IF (before_row -> key) IS DISTINCT FROM (after_row -> key) THEN
        RAISE EXCEPTION 'Workflow input is immutable' USING ERRCODE = '23514';
      END IF;
    END LOOP;
  ELSIF TG_TABLE_NAME = 'llm_connections' THEN
    IF (before_row -> 'provider', before_row -> 'protocol') IS DISTINCT FROM
       (after_row -> 'provider', after_row -> 'protocol') THEN
      RAISE EXCEPTION 'Connection protocol is immutable' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'llm_credential_versions' THEN
    IF (before_row - 'retired_at' - 'updated_at') IS DISTINCT FROM
       (after_row - 'retired_at' - 'updated_at') THEN
      RAISE EXCEPTION 'Credential version is immutable' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'agent_step_runs' AND before_row->>'state' = 'completed' THEN
    RAISE EXCEPTION 'Completed step is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$
"""

ROW_BINDING_SQL = """
CREATE FUNCTION agent_storage_bindings() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
DECLARE snapshot jsonb; source jsonb; profile jsonb; revision jsonb; canonical text;
BEGIN
  IF TG_TABLE_NAME = 'llm_model_profile_versions' THEN
    snapshot := NEW.snapshot;
    IF snapshot->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       snapshot->>'connection_id' IS DISTINCT FROM NEW.connection_id::text OR
       snapshot->>'profile_id' IS DISTINCT FROM NEW.profile_id::text OR
       snapshot->>'profile_version' IS DISTINCT FROM NEW.version::text THEN
      RAISE EXCEPTION 'Profile snapshot identity mismatch' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM llm_connections c WHERE c.id = NEW.connection_id
      AND c.tenant_id = NEW.tenant_id AND c.provider = snapshot->>'provider'
      AND c.protocol = snapshot->>'protocol') THEN
      RAISE EXCEPTION 'Profile protocol differs from connection' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'llm_model_profiles' AND (to_jsonb(NEW)->>'enabled')::boolean THEN
    SELECT v.snapshot INTO snapshot FROM llm_model_profile_versions v
      JOIN llm_connections c ON c.id = v.connection_id AND c.tenant_id = v.tenant_id
      WHERE v.id = NEW.active_version_id AND v.profile_id = NEW.id
        AND v.tenant_id = NEW.tenant_id AND c.enabled;
    IF snapshot IS NULL OR
       snapshot->'capabilities'->>'qualification' IS DISTINCT FROM 'live_worker' OR
       (snapshot->'capabilities'->>'context_tokens') IS NULL OR
       (snapshot->'capabilities'->>'output_tokens') IS NULL THEN
      RAISE EXCEPTION 'Enabled profile requires live qualification' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'agent_workflow_runs' THEN
    snapshot := NEW.input_snapshot; source := snapshot->'scope'; profile := snapshot->'profile';
    IF snapshot->>'workflow_run_id' IS DISTINCT FROM NEW.id::text OR
       snapshot->>'requested_by' IS DISTINCT FROM NEW.requested_by::text OR
       snapshot->>'processing_state' IS DISTINCT FROM 'completed' OR
       source->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       source->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
       source->>'document_id' IS DISTINCT FROM NEW.document_id::text OR
       source->>'processing_run_id' IS DISTINCT FROM NEW.processing_run_id::text OR
       source->>'source_sha256' IS DISTINCT FROM NEW.source_sha256 THEN
      RAISE EXCEPTION 'Workflow snapshot identity mismatch' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM llm_model_profile_versions v
      WHERE v.id = NEW.profile_version_id AND v.snapshot = profile
        AND v.tenant_id = NEW.tenant_id AND v.profile_id = NEW.profile_id
        AND v.connection_id = NEW.connection_id) THEN
      RAISE EXCEPTION 'Workflow profile snapshot mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' AND NOT EXISTS (
      SELECT 1 FROM document_processing_runs p JOIN documents d ON d.id = p.document_id
      JOIN jobs j ON j.id = NEW.job_id AND j.tenant_id = NEW.tenant_id
      WHERE p.id = NEW.processing_run_id AND p.tenant_id = NEW.tenant_id
        AND p.project_id = NEW.project_id AND p.document_id = NEW.document_id
        AND p.document_content_sha256 = NEW.source_sha256 AND p.status = 'COMPLETED'
        AND d.current_processing_run_id = p.id AND d.lifecycle_status = 'ACTIVE'
        AND j.job_type = 'DOCUMENT_SUMMARY') THEN
      RAISE EXCEPTION 'Source is stale, incomplete, or deleting' USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'summary_revisions' THEN
    snapshot := NEW.content; source := snapshot->'workflow'->'scope';
    IF snapshot->>'revision_id' IS DISTINCT FROM NEW.id::text OR
       snapshot->'workflow'->>'workflow_run_id' IS DISTINCT FROM NEW.workflow_run_id::text OR
       source->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       source->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
       source->>'document_id' IS DISTINCT FROM NEW.document_id::text OR
       source->>'processing_run_id' IS DISTINCT FROM NEW.processing_run_id::text OR
       snapshot->>'review_state' IS DISTINCT FROM 'draft' THEN
      RAISE EXCEPTION 'Revision content identity mismatch' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM agent_workflow_runs r WHERE r.id = NEW.workflow_run_id
       AND r.tenant_id = NEW.tenant_id AND r.input_snapshot = snapshot->'workflow') THEN
      RAISE EXCEPTION 'Revision provenance mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.quality = 'review_required' AND (
       snapshot->'verification'->>'verdict' IS DISTINCT FROM 'review_required' OR
       coalesce((snapshot->'coverage'->>'truncated')::boolean, true) OR
       coalesce(jsonb_array_length(snapshot->'coverage'->'unprocessed_chunk_ids'), 1) <> 0 OR
       coalesce(jsonb_array_length(snapshot->'coverage'->'failed_chunk_ids'), 1) <> 0) THEN
      RAISE EXCEPTION 'Unverified or partial revision cannot pass quality gate'
        USING ERRCODE = '23514';
    END IF;
  ELSIF TG_TABLE_NAME = 'summary_evidence' THEN
    snapshot := NEW.locator; source := snapshot->'scope';
    IF snapshot->>'evidence_id' IS DISTINCT FROM NEW.evidence_id::text OR
       snapshot->>'chunk_id' IS DISTINCT FROM NEW.chunk_id::text OR
       snapshot->>'chunk_sha256' IS DISTINCT FROM NEW.chunk_sha256 OR
       snapshot->>'offset_unit' IS DISTINCT FROM 'unicode_codepoint' OR
       source->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       source->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
       source->>'document_id' IS DISTINCT FROM NEW.document_id::text OR
       source->>'processing_run_id' IS DISTINCT FROM NEW.processing_run_id::text THEN
      RAISE EXCEPTION 'Evidence locator identity mismatch' USING ERRCODE = '23514';
    END IF;
    SELECT content INTO revision FROM summary_revisions WHERE id = NEW.revision_id
      AND tenant_id = NEW.tenant_id AND workflow_run_id = NEW.workflow_run_id;
    IF revision IS NULL OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
        coalesce(revision->'facts', '[]') || coalesce(revision->'requirements', '[]')) c
      WHERE coalesce(c->>'fact_id', c->>'requirement_id') = NEW.claim_id::text
        AND c->'evidence_ids' @> jsonb_build_array(NEW.evidence_id::text)) OR
       NOT (revision->'evidence' @> jsonb_build_array(snapshot)) THEN
      RAISE EXCEPTION 'Evidence must belong to revision claim' USING ERRCODE = '23514';
    END IF;
    SELECT content INTO canonical FROM document_chunks
      WHERE id = NEW.chunk_id AND tenant_id = NEW.tenant_id
        AND processing_run_id = NEW.processing_run_id AND content_sha256 = NEW.chunk_sha256;
    IF canonical IS NULL OR (snapshot->>'char_start')::integer < 0 OR
       (snapshot->>'char_end')::integer <= (snapshot->>'char_start')::integer OR
       substring(canonical FROM (snapshot->>'char_start')::integer + 1
         FOR (snapshot->>'char_end')::integer - (snapshot->>'char_start')::integer)
         IS DISTINCT FROM snapshot->>'exact_quote' THEN
      RAISE EXCEPTION 'Evidence does not match canonical chunk' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$
"""

SUMMARY_POINTER_SQL = """
CREATE FUNCTION agent_summary_pointer_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
DECLARE r record;
BEGIN
  IF TG_OP = 'UPDATE' AND (OLD.id, OLD.tenant_id, OLD.document_id) IS DISTINCT FROM
                          (NEW.id, NEW.tenant_id, NEW.document_id) THEN
    RAISE EXCEPTION 'Summary scope is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.active_revision_id IS NULL THEN
    IF TG_OP = 'UPDATE' AND OLD.active_revision_id IS NOT NULL THEN
      NEW.content_origin := 'legacy_unverified'; NEW.is_approved := false;
      NEW.approved_at := NULL; NEW.revision_version := OLD.revision_version + 1;
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.tenant_id::text IS DISTINCT FROM nullif(current_setting('app.tenant_id', true), '') THEN
    RAISE EXCEPTION 'Summary tenant context required' USING ERRCODE = '42501';
  END IF;
  SELECT v.*, w.request_sequence, d.current_processing_run_id, d.lifecycle_status
    INTO r FROM summary_revisions v JOIN agent_workflow_runs w ON w.id = v.workflow_run_id
    JOIN documents d ON d.id = v.document_id AND d.tenant_id = v.tenant_id
    WHERE v.id = NEW.active_revision_id AND v.tenant_id = NEW.tenant_id
      AND v.document_id = NEW.document_id AND v.summary_id = NEW.id;
  IF NOT FOUND OR r.workflow_run_id::text IS DISTINCT FROM
       nullif(current_setting('app.agent_workflow_run_id', true), '') OR
       r.current_processing_run_id IS DISTINCT FROM r.processing_run_id OR
       r.lifecycle_status <> 'ACTIVE' OR r.quality = 'stale' OR
       r.request_sequence <> NEW.latest_request_sequence THEN
    RAISE EXCEPTION 'Active revision is stale or outside scope' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'INSERT' OR OLD.active_revision_id IS DISTINCT FROM NEW.active_revision_id THEN
    IF TG_OP = 'INSERT' OR NEW.revision_version <> OLD.revision_version + 1 OR
       NEW.is_approved OR NEW.content_origin <> 'agent_draft' THEN
      RAISE EXCEPTION 'Active revision requires an unapproved versioned update'
        USING ERRCODE = '23514';
    END IF;
  ELSIF (NEW.summary_text, NEW.key_points::jsonb, NEW.requirements::jsonb) IS DISTINCT FROM
        (OLD.summary_text, OLD.key_points::jsonb, OLD.requirements::jsonb) THEN
    RAISE EXCEPTION 'Agent projection edits require a new revision or cleared pointer'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.is_approved AND NOT EXISTS (SELECT 1 FROM summary_approval_events a
    WHERE a.revision_id = NEW.active_revision_id AND a.summary_id = NEW.id
      AND a.tenant_id = NEW.tenant_id AND a.decision = 'approved'
      AND a.expected_version + 1 = NEW.revision_version) THEN
    RAISE EXCEPTION 'Revision-specific approval event required' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$
"""

APPROVAL_SQL = """
CREATE FUNCTION agent_summary_approval_insert() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
DECLARE affected integer;
BEGIN
  IF NEW.reviewer_id::text IS DISTINCT FROM nullif(current_setting('app.agent_user_id', true), '')
     OR NOT EXISTS (SELECT 1 FROM tenant_memberships m JOIN users u ON u.id = m.user_id
       WHERE m.tenant_id = NEW.tenant_id AND m.user_id = NEW.reviewer_id
         AND m.role IN ('ADMIN', 'EDITOR') AND u.is_active) THEN
    RAISE EXCEPTION 'Authorized reviewer required' USING ERRCODE = '42501';
  END IF;
  UPDATE document_summaries s SET revision_version = s.revision_version + 1,
    is_approved = (NEW.decision = 'approved'),
    approved_at = CASE WHEN NEW.decision = 'approved' THEN NEW.decided_at ELSE NULL END
    FROM summary_revisions v JOIN agent_workflow_runs w ON w.id = v.workflow_run_id
    WHERE s.id = NEW.summary_id AND s.tenant_id = NEW.tenant_id
      AND s.document_id = NEW.document_id AND s.active_revision_id = NEW.revision_id
      AND s.revision_version = NEW.expected_version AND v.id = NEW.revision_id
      AND v.tenant_id = NEW.tenant_id AND v.workflow_run_id = NEW.workflow_run_id
      AND w.request_sequence = s.latest_request_sequence
      AND (NEW.decision = 'rejected' OR v.quality = 'review_required');
  GET DIAGNOSTICS affected = ROW_COUNT;
  IF affected <> 1 THEN
    RAISE EXCEPTION 'Approval targets a stale or blocked revision' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$
"""


def _create_tables():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "llm_connections",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("protocol", sa.String(length=24), nullable=False),
        sa.Column(
            "endpoint_policy",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active_credential_id", sa.Uuid(), nullable=True),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(provider = 'openai' AND protocol = 'responses') OR "
            "(provider = 'anthropic' AND protocol = 'anthropic_messages') OR "
            "(provider = 'openai_compatible' AND protocol = 'chat_completions')",
            name="ck_llm_protocol",
        ),
        sa.CheckConstraint(
            "length(CAST(endpoint_policy AS TEXT)) <= 8192", name="ck_llm_endpoint_policy_size"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_llm_connection_scope"),
    )
    op.create_index(
        "ix_llm_connections_tenant", "llm_connections", ["tenant_id", "enabled"], unique=False
    )
    op.create_table(
        "llm_credential_versions",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=80), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("length(ciphertext) BETWEEN 16 AND 16384", name="ck_llm_ciphertext"),
        sa.CheckConstraint("length(nonce) BETWEEN 12 AND 32", name="ck_llm_nonce"),
        sa.CheckConstraint("version > 0", name="ck_llm_credential_version"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["llm_connections.id", "llm_connections.tenant_id"],
            name="fk_llm_credential_connection",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "version", name="uq_llm_credential_version"),
        sa.UniqueConstraint("id", "tenant_id", "connection_id", name="uq_llm_credential_scope"),
    )
    op.create_table(
        "llm_model_profiles",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("NOT is_default OR enabled", name="ck_llm_default_enabled"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["llm_connections.id", "llm_connections.tenant_id"],
            name="fk_llm_profile_connection",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", "connection_id", name="uq_llm_profile_scope"),
    )
    op.create_index(
        "ix_llm_profiles_tenant", "llm_model_profiles", ["tenant_id", "enabled"], unique=False
    )
    op.create_index(
        "uq_llm_default_profile",
        "llm_model_profiles",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
        sqlite_where=sa.text("is_default"),
    )
    op.create_table(
        "llm_model_profile_versions",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "length(CAST(snapshot AS TEXT)) <= 16384", name="ck_llm_profile_snapshot_size"
        ),
        sa.CheckConstraint("version > 0", name="ck_llm_profile_version"),
        sa.ForeignKeyConstraint(
            ["profile_id", "tenant_id", "connection_id"],
            [
                "llm_model_profiles.id",
                "llm_model_profiles.tenant_id",
                "llm_model_profiles.connection_id",
            ],
            name="fk_llm_version_profile",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", "profile_id", "connection_id", name="uq_llm_profile_version_scope"
        ),
        sa.UniqueConstraint("profile_id", "version", name="uq_llm_profile_version"),
    )
    op.create_table(
        "agent_workflow_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "input_snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "budget",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("request_sequence", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'review_required', 'partial', "
            "'quality_blocked', 'stale', 'failed', 'cancelled')",
            name="ck_agent_workflow_state",
        ),
        sa.CheckConstraint("length(CAST(budget AS TEXT)) <= 4096", name="ck_agent_budget_size"),
        sa.CheckConstraint(
            "length(CAST(input_snapshot AS TEXT)) <= 32768", name="ck_agent_input_size"
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_agent_source_hash"),
        sa.CheckConstraint(
            "request_sequence > 0 AND fencing_token >= 0", name="ck_agent_run_counters"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "project_id"],
            ["documents.id", "documents.tenant_id", "documents.project_id"],
            name="fk_agent_document",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id", "project_id"],
            ["jobs.id", "jobs.tenant_id", "jobs.project_id"],
            name="fk_agent_job",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_agent_requester_membership",
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id", "tenant_id", "project_id", "document_id"],
            [
                "document_processing_runs.id",
                "document_processing_runs.tenant_id",
                "document_processing_runs.project_id",
                "document_processing_runs.document_id",
            ],
            name="fk_agent_processing_run",
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id", "tenant_id", "profile_id", "connection_id"],
            [
                "llm_model_profile_versions.id",
                "llm_model_profile_versions.tenant_id",
                "llm_model_profile_versions.profile_id",
                "llm_model_profile_versions.connection_id",
            ],
            name="fk_agent_profile",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "request_sequence", name="uq_agent_request_sequence"),
        sa.UniqueConstraint("id", "tenant_id", "job_id", name="uq_agent_run_job"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "project_id",
            "document_id",
            "processing_run_id",
            name="uq_agent_run_source",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_agent_run_tenant"),
        sa.UniqueConstraint("job_id", name="uq_agent_workflow_job"),
    )
    op.create_index(
        "ix_agent_runs_document",
        "agent_workflow_runs",
        ["tenant_id", "document_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "agent_step_runs",
        sa.Column("node", sa.String(length=80), nullable=False),
        sa.Column("batch", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column(
            "artifact",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "usage",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'completed', 'failed')", name="ck_agent_step_state"
        ),
        sa.CheckConstraint("batch >= 0 AND attempt BETWEEN 1 AND 10", name="ck_agent_step_attempt"),
        sa.CheckConstraint(
            "length(CAST(artifact AS TEXT)) <= 1048576", name="ck_agent_step_artifact_size"
        ),
        sa.CheckConstraint("length(CAST(usage AS TEXT)) <= 2048", name="ck_agent_step_usage_size"),
        sa.CheckConstraint("length(input_sha256) = 64", name="ck_agent_step_input_hash"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id"],
            ["agent_workflow_runs.id", "agent_workflow_runs.tenant_id"],
            name="fk_agent_step_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id", "node", "batch", "attempt", name="uq_agent_step_identity"
        ),
    )
    op.create_index(
        "ix_agent_steps_run",
        "agent_step_runs",
        ["tenant_id", "workflow_run_id", "node", "batch"],
        unique=False,
    )
    op.create_table(
        "agent_checkpoints",
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=80), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "artifact",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "length(CAST(artifact AS TEXT)) <= 1048576", name="ck_agent_checkpoint_size"
        ),
        sa.CheckConstraint("length(input_sha256) = 64", name="ck_agent_checkpoint_input_hash"),
        sa.CheckConstraint("sequence > 0", name="ck_agent_checkpoint_sequence"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id"],
            ["agent_workflow_runs.id", "agent_workflow_runs.tenant_id"],
            name="fk_agent_checkpoint_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "sequence", name="uq_agent_checkpoint_sequence"),
    )
    op.create_index(
        "ix_agent_checkpoints_run",
        "agent_checkpoints",
        ["tenant_id", "workflow_run_id", "sequence"],
        unique=False,
    )
    op.create_table(
        "workflow_dispatch_outbox",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("continuation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'dead')",
            name="ck_workflow_delivery_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND continuation >= 0", name="ck_workflow_delivery_counts"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id", "job_id"],
            [
                "agent_workflow_runs.id",
                "agent_workflow_runs.tenant_id",
                "agent_workflow_runs.job_id",
            ],
            name="fk_workflow_outbox_run_job",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id", "task_name", "continuation", name="uq_workflow_delivery"
        ),
    )
    op.create_index(
        "ix_workflow_outbox_pending",
        "workflow_dispatch_outbox",
        ["tenant_id", "status", "available_at", "created_at"],
        unique=False,
    )
    op.create_table(
        "summary_revisions",
        sa.Column("summary_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "content",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("quality", sa.String(length=24), nullable=False),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "quality IN ('review_required', 'partial', 'quality_blocked', 'stale')",
            name="ck_summary_revision_quality",
        ),
        sa.CheckConstraint(
            "length(CAST(content AS TEXT)) <= 8388608", name="ck_summary_revision_content_size"
        ),
        sa.CheckConstraint("version > 0", name="ck_summary_revision_version"),
        sa.ForeignKeyConstraint(
            ["summary_id", "tenant_id", "document_id"],
            [
                "document_summaries.id",
                "document_summaries.tenant_id",
                "document_summaries.document_id",
            ],
            name="fk_revision_summary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id", "project_id", "document_id", "processing_run_id"],
            [
                "agent_workflow_runs.id",
                "agent_workflow_runs.tenant_id",
                "agent_workflow_runs.project_id",
                "agent_workflow_runs.document_id",
                "agent_workflow_runs.processing_run_id",
            ],
            name="fk_revision_source",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "document_id",
            "summary_id",
            "workflow_run_id",
            name="uq_summary_revision_approval",
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", "document_id", "summary_id", name="uq_summary_revision_scope"
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "workflow_run_id",
            "project_id",
            "document_id",
            "processing_run_id",
            name="uq_summary_revision_source",
        ),
        sa.UniqueConstraint("summary_id", "version", name="uq_summary_revision_version"),
    )
    op.create_index(
        "ix_summary_revision_history",
        "summary_revisions",
        ["tenant_id", "summary_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "summary_evidence",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("processing_run_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "locator",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "length(CAST(locator AS TEXT)) <= 65536", name="ck_summary_evidence_size"
        ),
        sa.CheckConstraint("length(chunk_sha256) = 64", name="ck_summary_evidence_hash"),
        sa.ForeignKeyConstraint(
            ["chunk_id", "tenant_id", "project_id", "document_id", "processing_run_id"],
            [
                "document_chunks.id",
                "document_chunks.tenant_id",
                "document_chunks.project_id",
                "document_chunks.document_id",
                "document_chunks.processing_run_id",
            ],
            name="fk_summary_evidence_chunk",
        ),
        sa.ForeignKeyConstraint(
            [
                "revision_id",
                "tenant_id",
                "workflow_run_id",
                "project_id",
                "document_id",
                "processing_run_id",
            ],
            [
                "summary_revisions.id",
                "summary_revisions.tenant_id",
                "summary_revisions.workflow_run_id",
                "summary_revisions.project_id",
                "summary_revisions.document_id",
                "summary_revisions.processing_run_id",
            ],
            name="fk_summary_evidence_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id", "claim_id", "evidence_id", name="uq_summary_claim_evidence"
        ),
    )
    op.create_index(
        "ix_summary_evidence_revision",
        "summary_evidence",
        ["tenant_id", "revision_id", "claim_id"],
        unique=False,
    )
    op.create_table(
        "summary_approval_events",
        sa.Column("summary_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
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
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_summary_approval_decision"
        ),
        sa.CheckConstraint("expected_version >= 0", name="ck_summary_approval_version"),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "tenant_id", "document_id", "summary_id", "workflow_run_id"],
            [
                "summary_revisions.id",
                "summary_revisions.tenant_id",
                "summary_revisions.document_id",
                "summary_revisions.summary_id",
                "summary_revisions.workflow_run_id",
            ],
            name="fk_summary_approval_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_summary_approval_reviewer",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id"],
            ["agent_workflow_runs.id", "agent_workflow_runs.tenant_id"],
            name="fk_summary_approval_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_id", "expected_version", name="uq_summary_approval_version"),
    )
    # ### end Alembic commands ###


def _protect(roles):
    if roles is None:
        return
    runtime, owner = (op.get_bind().dialect.identifier_preparer.quote(name) for name in roles)
    op.execute(JSON_SAFETY_SQL)
    op.execute(IMMUTABILITY_SQL)
    op.execute(ROW_BINDING_SQL)
    op.execute(SUMMARY_POINTER_SQL)
    op.execute(APPROVAL_SQL)
    tenant = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    for table in PROTECTED_TABLES:
        expression = tenant
        if table == "agent_workflow_runs":
            expression += (
                " AND id = NULLIF(current_setting('app.agent_workflow_run_id', true), '')::uuid"
            )
        elif table not in {
            "llm_connections",
            "llm_credential_versions",
            "llm_model_profiles",
            "llm_model_profile_versions",
        }:
            expression += (
                " AND workflow_run_id = "
                "NULLIF(current_setting('app.agent_workflow_run_id', true), '')::uuid"
            )
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON TABLE {table} FROM {runtime}")
        privileges = "SELECT, INSERT" if table in APPEND_ONLY else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f"GRANT {privileges} ON TABLE {table} TO {runtime}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_scope ON {table} FOR ALL TO {runtime} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
        # Explicit owner policy permits migration safety inspections under FORCE RLS;
        # the runtime is verified not to inherit this privileged migration role.
        op.execute(
            f"CREATE POLICY {table}_migration_owner ON {table} FOR ALL TO {owner} "
            "USING (true) WITH CHECK (true)"
        )
        mode = "append_only" if table in APPEND_ONLY else "scope"
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION agent_storage_guard('{mode}')"
        )
        for column in JSON_COLUMNS.get(table, ()):
            maximum = {
                "content": 8388608,
                "snapshot": 16384,
                "input_snapshot": 32768,
                "budget": 4096,
                "usage": 2048,
                "locator": 65536,
                "endpoint_policy": 8192,
            }.get(column, 1048576)
            op.create_check_constraint(
                f"ck_{table}_{column}_safe",
                table,
                f"jsonb_typeof({column}) = 'object' AND agent_storage_json_safe({column}) "
                f"AND octet_length({column}::text) <= {maximum}",
            )
    for table in (
        "llm_model_profiles",
        "llm_model_profile_versions",
        "agent_workflow_runs",
        "summary_revisions",
        "summary_evidence",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_bindings BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION agent_storage_bindings()"
        )
    for table in ("agent_step_runs", "agent_checkpoints"):
        op.create_check_constraint(
            f"ck_{table}_artifact_kind",
            table,
            "artifact->>'kind' IS NOT NULL AND "
            "artifact->>'kind' IN ('facts.v1','summary_content.v1','verification.v1') AND "
            "jsonb_typeof(artifact->'payload') = 'object' AND "
            "artifact ? 'kind' AND artifact ? 'payload'",
        )
    op.create_check_constraint(
        "ck_agent_step_completion",
        "agent_step_runs",
        "(state = 'completed') = (completed_at IS NOT NULL)",
    )
    op.execute(
        "CREATE TRIGGER agent_summary_pointer BEFORE INSERT OR UPDATE ON document_summaries "
        "FOR EACH ROW EXECUTE FUNCTION agent_summary_pointer_guard()"
    )
    op.execute(
        "CREATE TRIGGER agent_summary_approval AFTER INSERT ON summary_approval_events "
        "FOR EACH ROW EXECUTE FUNCTION agent_summary_approval_insert()"
    )


def upgrade():
    roles = _security_roles()
    with op.batch_alter_table("documents") as batch:
        batch.create_unique_constraint("uq_documents_tenant", ["id", "tenant_id"])
    with op.batch_alter_table("document_chunks") as batch:
        batch.create_unique_constraint(
            "uq_chunks_full_scope",
            ["id", "tenant_id", "project_id", "document_id", "processing_run_id"],
        )
    with op.batch_alter_table("document_summaries") as batch:
        batch.add_column(sa.Column("active_revision_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("revision_version", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column("latest_request_sequence", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "content_origin", sa.String(24), server_default="legacy_unverified", nullable=False
            )
        )
        batch.create_unique_constraint(
            "uq_document_summary_scope", ["id", "tenant_id", "document_id"]
        )
        batch.create_foreign_key(
            "fk_summary_document_tenant",
            "documents",
            ["document_id", "tenant_id"],
            ["id", "tenant_id"],
        )
        batch.create_check_constraint(
            "ck_summary_revision_counters", "revision_version >= 0 AND latest_request_sequence >= 0"
        )
        batch.create_check_constraint(
            "ck_summary_content_origin", "content_origin IN ('legacy_unverified', 'agent_draft')"
        )
        batch.create_check_constraint(
            "ck_summary_revision_origin",
            "(active_revision_id IS NULL AND content_origin = 'legacy_unverified') OR "
            "(active_revision_id IS NOT NULL AND content_origin = 'agent_draft')",
        )
    _create_tables()
    with op.batch_alter_table("llm_connections") as batch:
        batch.create_foreign_key(
            "fk_llm_active_credential",
            "llm_credential_versions",
            ["active_credential_id", "tenant_id", "id"],
            ["id", "tenant_id", "connection_id"],
        )
    with op.batch_alter_table("llm_model_profiles") as batch:
        batch.create_foreign_key(
            "fk_llm_active_profile_version",
            "llm_model_profile_versions",
            ["active_version_id", "tenant_id", "id", "connection_id"],
            ["id", "tenant_id", "profile_id", "connection_id"],
        )
    with op.batch_alter_table("document_summaries") as batch:
        batch.create_foreign_key(
            "fk_summary_active_revision",
            "summary_revisions",
            ["active_revision_id", "tenant_id", "document_id", "id"],
            ["id", "tenant_id", "document_id", "summary_id"],
        )
    _protect(roles)


def _assert_empty():
    for table in PROTECTED_TABLES:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Agent records exist; use a reviewed forward fix instead")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_summaries WHERE "
            "active_revision_id IS NOT NULL OR revision_version <> 0 "
            "OR latest_request_sequence <> 0)"
        )
    ):
        raise RuntimeError("Agent summary metadata exists; use a reviewed forward fix instead")


def downgrade():
    roles = _security_roles()
    _assert_empty()
    if roles is not None:
        op.execute("DROP TRIGGER agent_summary_pointer ON document_summaries")
        op.execute("DROP TRIGGER agent_summary_approval ON summary_approval_events")
    with op.batch_alter_table("document_summaries") as batch:
        batch.drop_constraint("fk_summary_active_revision", type_="foreignkey")
    with op.batch_alter_table("llm_connections") as batch:
        batch.drop_constraint("fk_llm_active_credential", type_="foreignkey")
    with op.batch_alter_table("llm_model_profiles") as batch:
        batch.drop_constraint("fk_llm_active_profile_version", type_="foreignkey")
    for table in reversed(PROTECTED_TABLES):
        op.drop_table(table)
    if roles is not None:
        for function in (
            "agent_summary_approval_insert()",
            "agent_summary_pointer_guard()",
            "agent_storage_bindings()",
            "agent_storage_guard()",
            "agent_storage_json_safe(jsonb, integer)",
        ):
            op.execute(f"DROP FUNCTION {function}")
    with op.batch_alter_table("document_summaries") as batch:
        for name, kind in (
            ("fk_summary_document_tenant", "foreignkey"),
            ("uq_document_summary_scope", "unique"),
            ("ck_summary_revision_counters", "check"),
            ("ck_summary_content_origin", "check"),
            ("ck_summary_revision_origin", "check"),
        ):
            batch.drop_constraint(name, type_=kind)
        for name in (
            "content_origin",
            "latest_request_sequence",
            "revision_version",
            "active_revision_id",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("document_chunks") as batch:
        batch.drop_constraint("uq_chunks_full_scope", type_="unique")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_documents_tenant", type_="unique")
