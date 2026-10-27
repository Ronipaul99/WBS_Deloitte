from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.models.domain import Document, DocumentDeletionOutbox
from app.services.readiness import application_migration_heads

REVISION = "d4e7b2c91a63"
APPLICATION_HEAD = "c92e6b4a710d"
PREVIOUS_REVISION = "c8d4a1e72f09"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / f"{REVISION}_add_document_deletion_lifecycle.py"
)


def _config(database: Path, monkeypatch) -> Config:
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DIRECT_DATABASE_URL", url)
    monkeypatch.setenv("DOCUMENT_INGESTION_ENABLED", "false")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")
    get_settings.cache_clear()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


def test_step13_models_and_migration_define_scoped_durable_deletion() -> None:
    assert {
        "lifecycle_status",
        "deletion_job_id",
        "deletion_requested_at",
        "vectors_hidden_at",
        "deletion_completed_at",
        "deletion_error_code",
    } <= set(Document.__table__.c.keys())
    assert {
        "tenant_id",
        "project_id",
        "document_id",
        "job_id",
        "task_name",
        "status",
        "available_at",
    } <= set(DocumentDeletionOutbox.__table__.c.keys())

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert application_migration_heads() == {APPLICATION_HEAD}
    assert f'down_revision: str | None = "{PREVIOUS_REVISION}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "runtime_database_role" in source
    assert "reviewed forward fix" in source


def test_existing_documents_remain_active_after_upgrade(tmp_path, monkeypatch) -> None:
    database = tmp_path / "step13-existing.db"
    config = _config(database, monkeypatch)
    document_id = uuid4().hex
    try:
        command.upgrade(config, PREVIOUS_REVISION)
        with sqlite3.connect(database) as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, tenant_id, project_id, uploaded_by, kind, file_name,
                    content_type, size_bytes, storage_key
                ) VALUES (?, ?, ?, ?, 'PROJECT', 'synthetic.pdf',
                          'application/pdf', 10, ?)
                """,
                (
                    document_id,
                    uuid4().hex,
                    uuid4().hex,
                    uuid4().hex,
                    f"synthetic/{uuid4().hex}.pdf",
                ),
            )
            connection.commit()

        command.upgrade(config, "head")
        with sqlite3.connect(database) as connection:
            row = connection.execute(
                """
                SELECT lifecycle_status, deletion_job_id, deletion_requested_at,
                       vectors_hidden_at, deletion_completed_at
                FROM documents WHERE id = ?
                """,
                (document_id,),
            ).fetchone()
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert row == ("ACTIVE", None, None, None, None)
        assert version == (APPLICATION_HEAD,)
    finally:
        get_settings.cache_clear()


def test_clean_upgrade_and_safe_empty_downgrade(tmp_path, monkeypatch) -> None:
    database = tmp_path / "step13-clean.db"
    config = _config(database, monkeypatch)
    try:
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, PREVIOUS_REVISION)
        command.upgrade(config, "head")
        with sqlite3.connect(database) as connection:
            version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == (APPLICATION_HEAD,)
    finally:
        get_settings.cache_clear()
