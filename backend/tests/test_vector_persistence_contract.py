import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql

from app.core import observability
from app.core.config import get_settings
from app.models.domain import DocumentChunk, DocumentProcessingRun
from app.services.ingestion.errors import (
    PersistenceError,
    PersistenceErrorCode,
    map_unexpected_persistence_failure,
    persistence_error_to_job_failure,
)
from app.services.ingestion.repository import VectorPersistencePolicy
from app.services.readiness import application_migration_heads
from migrations.versions import b6e2f719c4d8_add_vector_persistence_identity as migration

REVISION = "b6e2f719c4d8"
APPLICATION_HEAD = "e71c4a9b203d"
PREVIOUS_REVISION = "a4f9c2d18e76"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / f"{REVISION}_add_vector_persistence_identity.py"
)


def test_processing_run_model_has_complete_versioned_identity() -> None:
    assert {
        "chunker_version",
        "embedding_model_revision",
        "embedding_formatting_version",
    } <= set(DocumentProcessingRun.__table__.c.keys())
    constraint = next(
        item
        for item in DocumentProcessingRun.__table__.constraints
        if item.name == "uq_runs_idempotency"
    )
    assert tuple(column.name for column in constraint.columns) == migration.IDENTITY_COLUMNS


def test_step10_migration_remains_in_history_and_preserves_vector_and_rls_schema() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert application_migration_heads() == {APPLICATION_HEAD}
    assert f'down_revision: str | None = "{PREVIOUS_REVISION}"' in source
    assert "uq_runs_idempotency" in source
    assert "DROP EXTENSION" not in source.upper()
    assert "document_chunks" not in source
    assert "ROW LEVEL SECURITY" not in source
    assert "Vector(" not in source
    assert "reviewed forward fix instead of downgrade" in source


def test_migration_downgrade_refuses_to_remove_used_identity(monkeypatch) -> None:
    bind = type("Bind", (), {"scalar": lambda self, _statement: True})()
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    with pytest.raises(RuntimeError, match="reviewed forward fix"):
        migration._assert_versioned_identity_is_empty()


def test_migration_preserves_legacy_run_without_fabricating_identity(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "legacy-step10.db"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DIRECT_DATABASE_URL", url)
    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "migrations"),
    )
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO document_processing_runs (
                    id, tenant_id, project_id, document_id, job_id, status,
                    document_content_sha256, extractor_name, extractor_version,
                    embedding_provider, embedding_model, embedding_dimensions,
                    page_count, worksheet_count, block_count, chunk_count
                ) VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, 'legacy', '1.0',
                          'fastembed', 'BAAI/bge-small-en-v1.5', 384, 1, 0, 1, 1)
                """,
                (
                    *(uuid4().hex for _ in range(5)),
                    "a" * 64,
                ),
            )
            connection.commit()

        command.upgrade(config, REVISION)
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                "SELECT chunker_version, embedding_model_revision, "
                "embedding_formatting_version FROM document_processing_runs"
            ).fetchone()
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert row == (None, None, None)
        assert version == REVISION
        command.downgrade(config, PREVIOUS_REVISION)
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("code", list(PersistenceErrorCode))
def test_persistence_errors_have_fixed_safe_job_mappings(code) -> None:
    error = PersistenceError(code)
    failure = persistence_error_to_job_failure(error)

    assert failure.error_code is code
    assert failure.retryable is error.retryable
    assert failure.message == str(error)
    assert "postgres" not in failure.message.casefold()
    assert "vector" not in failure.message.casefold()


def test_unexpected_persistence_error_redacts_raw_details(caplog) -> None:
    marker = "synthetic content /private/path object-key private.endpoint"

    with caplog.at_level("WARNING"):
        mapped = map_unexpected_persistence_failure(RuntimeError(marker))

    assert mapped.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_FAILED
    assert marker not in str(mapped)
    assert marker not in caplog.text


def test_persistence_policy_rejects_unbounded_values() -> None:
    with pytest.raises(ValueError):
        VectorPersistencePolicy(batch_size=1_001)
    with pytest.raises(ValueError):
        VectorPersistencePolicy(maximum_similarity_results=1_001)


def test_exact_similarity_sql_contains_every_scope_predicate() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "ingestion" / "repository.py"
    ).read_text(encoding="utf-8")

    assert ".cosine_distance(" in source
    for predicate in (
        "DocumentChunk.tenant_id == scope.tenant_id",
        "DocumentChunk.project_id == scope.project_id",
        "DocumentChunk.document_id == scope.document_id",
        "DocumentChunk.processing_run_id == document.current_processing_run_id",
    ):
        assert predicate in source
    assert "hnsw" not in source.casefold()
    assert "ivfflat" not in source.casefold()


def test_no_public_route_imports_vector_persistence_repository() -> None:
    routes = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
    source = "\n".join(path.read_text(encoding="utf-8") for path in routes.glob("*.py"))

    assert "VectorPersistenceRepository" not in source
    assert "exact_active_similarity" not in source


def test_persistence_metrics_allow_only_bounded_labels(monkeypatch) -> None:
    observed = []

    class Metric:
        def labels(self, **labels):
            observed.append(labels)
            return self

        def inc(self):
            return None

    monkeypatch.setattr(observability, "VECTOR_PERSISTENCE_EVENTS", Metric())
    observability.record_vector_persistence_event(
        operation="tenant-sensitive-operation",
        outcome="raw exception",
        error_code="private endpoint",
    )

    assert observed == [
        {
            "operation": "reconcile",
            "outcome": "failed",
            "error_code": "DOCUMENT_PERSISTENCE_FAILED",
        }
    ]


def test_similarity_expression_compiles_for_postgresql() -> None:
    expression = DocumentChunk.embedding.cosine_distance([0.0] * 384)
    compiled = str(expression.compile(dialect=postgresql.dialect()))
    assert "<=>" in compiled
