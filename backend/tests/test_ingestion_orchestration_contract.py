from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from app.core import observability
from app.core.config import get_settings
from app.models.domain import DocumentProcessingRun, JobDispatchOutbox
from app.services.ingestion.errors import (
    IngestionError,
    IngestionErrorCode,
    ingestion_error_to_job_failure,
)
from app.services.readiness import application_migration_heads

REVISION = "c8d4a1e72f09"
APPLICATION_HEAD = "e53c7a19b402"
PREVIOUS_REVISION = "b6e2f719c4d8"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / f"{REVISION}_add_ingestion_orchestration_outbox.py"
)


def test_step11_schema_has_two_phase_identity_and_scoped_outbox() -> None:
    nullable_identity = {
        "document_content_sha256",
        "extractor_name",
        "extractor_version",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
    }
    assert all(DocumentProcessingRun.__table__.c[name].nullable for name in nullable_identity)
    assert {
        "current_stage",
        "attempt_count",
        "last_heartbeat_at",
        "warning_codes",
    } <= set(DocumentProcessingRun.__table__.c.keys())
    assert {
        "tenant_id",
        "project_id",
        "document_id",
        "job_id",
        "processing_run_id",
        "task_name",
        "status",
        "available_at",
    } <= set(JobDispatchOutbox.__table__.c.keys())


def test_step11_migration_is_head_and_enforces_outbox_rls() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert application_migration_heads() == {APPLICATION_HEAD}
    assert f'down_revision: str | None = "{PREVIOUS_REVISION}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "runtime_database_role" in source
    assert "reviewed forward fix instead of downgrade" in source
    assert "DROP EXTENSION" not in source.upper()


def test_clean_upgrade_and_guarded_downgrade_rehearsal(tmp_path, monkeypatch) -> None:
    database = tmp_path / "step11-migration.db"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DIRECT_DATABASE_URL", url)
    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO document_processing_runs (
                    id, tenant_id, project_id, document_id, job_id, status,
                    document_content_sha256, extractor_name, extractor_version,
                    chunker_version, embedding_provider, embedding_model,
                    embedding_model_revision, embedding_dimensions,
                    embedding_formatting_version, page_count, worksheet_count,
                    block_count, chunk_count
                ) VALUES (?, ?, ?, ?, ?, 'COMPLETED', ?, 'legacy', '1.0', NULL,
                          'fastembed', 'BAAI/bge-small-en-v1.5', NULL, 384, NULL,
                          1, 0, 1, 1)
                """,
                (
                    *(uuid4().hex for _ in range(5)),
                    "a" * 64,
                ),
            )
            connection.commit()
        command.upgrade(config, "head")
        with sqlite3.connect(database) as connection:
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(job_dispatch_outbox)")
            }
            legacy_identity = connection.execute(
                "SELECT chunker_version, embedding_model_revision, "
                "embedding_formatting_version FROM document_processing_runs"
            ).fetchone()
        assert version == APPLICATION_HEAD
        assert {"processing_run_id", "available_at", "lease_expires_at"} <= columns
        assert legacy_identity == (None, None, None)

        with sqlite3.connect(database) as connection:
            connection.execute("DELETE FROM document_processing_runs")
            connection.commit()
        command.downgrade(config, PREVIOUS_REVISION)
        with sqlite3.connect(database) as connection:
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            outbox = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='job_dispatch_outbox'"
            ).fetchone()
        assert version == PREVIOUS_REVISION
        assert outbox is None
        command.upgrade(config, "head")
    finally:
        get_settings.cache_clear()


def test_api_route_contains_no_worker_processing_or_background_tasks() -> None:
    source = (BACKEND_ROOT / "app" / "api" / "routes" / "ingestions.py").read_text(encoding="utf-8")
    forbidden = (
        "BackgroundTasks",
        "prepare_document_input",
        "DocumentExtractor",
        "embed_canonical_chunks",
        "VectorPersistenceRepository",
        "FastEmbed",
        "ocrmypdf",
    )
    assert all(value not in source for value in forbidden)


def test_worker_delivery_contract_is_json_late_ack_and_non_eager() -> None:
    source = (BACKEND_ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    assert 'task_serializer="json"' in source
    assert 'accept_content=["json"]' in source
    assert "task_acks_late=True" in source
    assert "task_reject_on_worker_lost=True" in source
    assert "build_release_orchestrator" in source
    assert "BackgroundTasks" not in source


def test_ingestion_errors_and_metric_labels_are_fixed_and_safe(monkeypatch) -> None:
    observed = []

    class Metric:
        def labels(self, **labels):
            observed.append(labels)
            return self

        def inc(self):
            return None

    failure = ingestion_error_to_job_failure(
        IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)
    )
    assert failure.error_code == "DOCUMENT_INGESTION_STATE_INCONSISTENT"
    assert failure.retryable is False
    assert "tenant" not in failure.message.casefold()
    timeout = ingestion_error_to_job_failure(TimeoutError("private timeout detail"))
    assert timeout.error_code == "DOCUMENT_INGESTION_TIMEOUT"
    assert timeout.retryable is True
    assert "private" not in timeout.message

    monkeypatch.setattr(observability, "INGESTION_ATTEMPTS", Metric())
    observability.record_ingestion_attempt(
        outcome="raw customer state",
        error_code="private endpoint and document content",
    )
    assert observed == [{"outcome": "failed", "error_code": "INTERNAL_ERROR"}]
