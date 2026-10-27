"""Rehearse the Neon-reported migration lineage on disposable SQLite only."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
HEAD = "c92e6b4a710d"


def run_alembic(database, *arguments, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "DIRECT_DATABASE_URL": "",
            "APP_ENV": "test",
            "AUTH_MODE": "local",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
    return result


def test_both_original_migrations_remain_ancestors_of_one_head():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD]
    assert script.get_revision("a13d9e7b602c").down_revision == "e71c4a9b203d"
    assert script.get_revision("f31a0d8c72e9").down_revision == "e71c4a9b203d"


@pytest.mark.parametrize("starting_revision", ["a13d9e7b602c", "f31a0d8c72e9"])
def test_upgrade_from_either_branch_preserves_existing_tables(tmp_path, starting_revision):
    database = tmp_path / "migration-merge.db"
    run_alembic(database, "upgrade", starting_revision)
    if starting_revision == "a13d9e7b602c":
        with sqlite3.connect(database) as connection:
            connection.execute(
                """INSERT INTO rfp_question_bank (
                question_set_id, question_id, ordinal, category, question_text,
                extraction_instructions, answer_type, content_sha256, embedding,
                embedding_provider, embedding_model, embedding_model_revision,
                embedding_manifest_sha256, embedding_dimensions,
                embedding_formatting_version, query_prefix
            ) VALUES ('test-set','Q1',1,'scope','Keep existing question?',
                '[]','structured_summary',?, '[]','test','test','test',?,384,'test','')""",
                ("a" * 64, "b" * 64),
            )
            before = connection.execute("SELECT * FROM rfp_question_bank").fetchall()
    run_alembic(database, "upgrade", "head")
    run_alembic(database, "check")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(HEAD,)]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"rfp_question_bank", "document_workflows", "document_content_claims"} <= tables
        if starting_revision == "a13d9e7b602c":
            assert connection.execute("SELECT * FROM rfp_question_bank").fetchall() == before
    if starting_revision == "a13d9e7b602c":
        # Reverting only the deduplication branch must keep the populated bank intact.
        run_alembic(database, "downgrade", "a13d9e7b602c")
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT * FROM rfp_question_bank").fetchall() == before
        run_alembic(database, "upgrade", "head")
        result = run_alembic(database, "downgrade", "e71c4a9b203d", success=False)
        assert (
            "Refusing to drop a populated, versioned question bank" in result.stdout + result.stderr
        )


def test_schema_check_still_detects_other_unmapped_tables(tmp_path):
    database = tmp_path / "unmapped.db"
    run_alembic(database, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unexpected_test_table (id INTEGER PRIMARY KEY)")
    result = run_alembic(database, "check", success=False)
    assert "unexpected_test_table" in result.stdout + result.stderr
