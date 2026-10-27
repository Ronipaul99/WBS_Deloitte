from pathlib import Path
from uuid import UUID

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects import postgresql, sqlite

from app.db.session import set_local_tenant_context
from app.models.domain import Document, DocumentChunk, DocumentProcessingRun, Job
from app.services.readiness import application_migration_heads
from migrations.versions import a4f9c2d18e76_add_pgvector_ingestion_schema as migration

REVISION = "a4f9c2d18e76"
APPLICATION_HEAD = "c92e6b4a710d"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / f"{REVISION}_add_pgvector_ingestion_schema.py"
)


def _constraint_names(table) -> set[str]:
    return {constraint.name for constraint in table.constraints if constraint.name}


def test_ingestion_models_define_scoped_vector_schema() -> None:
    assert {
        "content_sha256",
        "current_processing_run_id",
        "processing_status",
        "processed_at",
        "processing_error_code",
    } <= set(Document.__table__.c.keys())
    assert "uq_documents_scope" in _constraint_names(Document.__table__)
    assert {
        "fk_runs_document_scope",
        "fk_runs_job_scope",
        "uq_runs_scope",
        "uq_runs_idempotency",
        "ck_runs_embedding_dimensions",
    } <= _constraint_names(DocumentProcessingRun.__table__)
    assert "uq_jobs_scope" in _constraint_names(Job.__table__)
    assert {
        "fk_chunks_run_scope",
        "uq_chunks_run_ordinal",
        "ck_chunks_token_count_positive",
    } <= _constraint_names(DocumentChunk.__table__)

    embedding_type = DocumentChunk.__table__.c.embedding.type
    postgres_type = embedding_type.dialect_impl(postgresql.dialect())
    sqlite_type = embedding_type.dialect_impl(sqlite.dialect())
    assert isinstance(postgres_type, Vector)
    assert postgres_type.dim == 384
    assert "JSON" in type(sqlite_type).__name__.upper()

    chunk_scope_fk = next(
        constraint
        for constraint in DocumentChunk.__table__.foreign_key_constraints
        if constraint.name == "fk_chunks_run_scope"
    )
    assert chunk_scope_fk.ondelete == "CASCADE"
    assert not any(
        index.dialect_options["postgresql"].get("using") in {"hnsw", "ivfflat"}
        for index in DocumentChunk.__table__.indexes
    )


def test_step3_migration_remains_in_history_and_contains_fail_closed_rls() -> None:
    assert application_migration_heads() == {APPLICATION_HEAD}
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "f2a84d719c35"' in source
    assert "CREATE EXTENSION IF NOT EXISTS vector" in source
    assert 'sa.Column("embedding", Vector(384)' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "WITH CHECK" in source
    assert "REVOKE ALL ON TABLE" in source
    assert "rolbypassrls" in source
    assert "DROP EXTENSION" not in source.upper()
    assert "hnsw" not in source.casefold()
    assert "ivfflat" not in source.casefold()


def test_extension_setup_failure_is_controlled_and_non_disclosing(monkeypatch) -> None:
    private_diagnostic = "private database endpoint and credential detail"
    bind = _Bind("postgresql")
    context = type("MigrationContext", (), {"as_sql": False})()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "get_context", lambda: context)

    def fail_extension(_statement: str) -> None:
        raise sa_exc.SQLAlchemyError(private_diagnostic)

    monkeypatch.setattr(migration.op, "execute", fail_extension)

    with pytest.raises(RuntimeError, match="extension setup failed") as error:
        migration._prepare_postgresql_security()

    assert private_diagnostic not in str(error.value)


def test_downgrade_refuses_to_destroy_ingestion_data(monkeypatch) -> None:
    bind = type("Bind", (), {"scalar": lambda self, _statement: True})()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="reviewed forward fix"):
        migration._assert_ingestion_tables_empty()


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = _Dialect(dialect_name)


class _RecordingSession:
    def __init__(self, dialect_name: str, *, in_transaction: bool) -> None:
        self.bind = _Bind(dialect_name)
        self.transaction_active = in_transaction
        self.executed: list[str] = []

    def get_bind(self):
        return self.bind

    def in_transaction(self) -> bool:
        return self.transaction_active

    async def execute(self, statement) -> None:
        self.executed.append(str(statement))


@pytest.mark.asyncio
async def test_tenant_context_uses_transaction_local_postgresql_setting() -> None:
    session = _RecordingSession("postgresql", in_transaction=True)
    tenant_id = UUID("00000000-0000-0000-0000-000000000123")

    await set_local_tenant_context(session, tenant_id)  # type: ignore[arg-type]

    assert session.executed == [f"SET LOCAL app.tenant_id = '{tenant_id}'"]


@pytest.mark.asyncio
async def test_tenant_context_rejects_invalid_or_nontransactional_use() -> None:
    invalid = _RecordingSession("postgresql", in_transaction=True)
    with pytest.raises(ValueError):
        await set_local_tenant_context(invalid, "not-a-uuid")  # type: ignore[arg-type]
    assert invalid.executed == []

    no_transaction = _RecordingSession("postgresql", in_transaction=False)
    with pytest.raises(RuntimeError, match="active database transaction"):
        await set_local_tenant_context(no_transaction, UUID("00000000-0000-0000-0000-000000000123"))  # type: ignore[arg-type]
    assert no_transaction.executed == []


@pytest.mark.asyncio
async def test_sqlite_tenant_context_is_a_regression_only_noop() -> None:
    session = _RecordingSession("sqlite", in_transaction=False)

    await set_local_tenant_context(session, UUID("00000000-0000-0000-0000-000000000123"))  # type: ignore[arg-type]

    assert session.executed == []
