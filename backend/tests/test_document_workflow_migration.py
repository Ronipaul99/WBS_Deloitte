import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_additive_migration_upgrades_and_downgrades_isolated_sqlite(tmp_path):
    database = tmp_path / "dedup-migration.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
        "DIRECT_DATABASE_URL": "",
        "AUTH_MODE": "local",
        "APP_ENV": "test",
    }
    root = Path(__file__).resolve().parents[1]
    for target in ["head", "e71c4a9b203d", "head"]:
        action = "downgrade" if target == "e71c4a9b203d" else "upgrade"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", action, target],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "document_content_claims",
            "document_upload_attempts",
            "document_workflows",
            "workflow_request_keys",
        } <= tables
        assert "upload_sha256" in {
            row[1] for row in connection.execute("PRAGMA table_info(documents)")
        }
        assert "workflow_id" in {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
