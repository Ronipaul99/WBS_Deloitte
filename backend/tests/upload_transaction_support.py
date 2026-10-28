"""Opt-in isolated fixtures: pytest --noconftest -p tests.upload_transaction_support.

Never imports the shared conftest or reads the application .env. SQLite enforces
the PostgreSQL helper's active-transaction precondition, but does not prove RLS.
"""

import os
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_temporary = tempfile.TemporaryDirectory(prefix="wbs-upload-transactions-")
ROOT = Path(_temporary.name)
os.environ.update(
    APP_ENV="test",
    AUTH_MODE="local",
    DATABASE_URL=f"sqlite+aiosqlite:///{(ROOT / 'test.db').as_posix()}",
    DIRECT_DATABASE_URL="",
    DATABASE_MIGRATION_ROLE_NAME="",
    DATABASE_USE_NULL_POOL="false",
    UPLOAD_ROOT=str(ROOT / "uploads"),
    STORAGE_BACKEND="local",
    TASKS_EAGER="true",
    AUTO_CREATE_TABLES="true",
    AUTH_JWT_SECRET="test-only-secret-that-is-at-least-thirty-two-characters-long",
    AUTH_AUDIT_SECRET="separate-test-only-audit-secret-that-is-also-long-enough",
    DEV_USER_PASSWORD="Correct-Horse-Battery-Staple-42",
    DOCUMENT_INGESTION_ENABLED="false",
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT="false",
    DOCUMENT_WORKFLOW_RESUME_ENABLED="true",
    DOCUMENT_UPLOAD_REUSE_ENABLED="true",
    EMBEDDING_MODEL_REVISION="a" * 40,
    PUBLIC_UI_URL="http://127.0.0.1:5173",
    CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173",
)

from app.core import config  # noqa: E402


@lru_cache
def isolated_settings():
    return config.Settings(_env_file=None)


config.get_settings = isolated_settings
_settings = isolated_settings()

from app.db import session  # noqa: E402

_original_scope = session.set_local_tenant_context


async def strict_scope(db, tenant_id):
    if not db.in_transaction():
        raise RuntimeError("Tenant context requires an active database transaction")
    await _original_scope(db, tenant_id)


if os.environ.get("UPLOAD_TEST_NATIVE_SCOPE") != "true":
    session.set_local_tenant_context = strict_scope

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/auth/login",
            json={"email": "developer@example.com", "password": _settings.dev_user_password},
        )
        assert response.status_code == 200, response.text
        test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        yield test_client


@pytest.fixture(scope="session")
def tenant_id():
    return str(_settings.dev_tenant_id)


def pytest_unconfigure():
    _temporary.cleanup()
