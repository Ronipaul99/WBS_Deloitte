import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE = Path(".test-wbs.db").resolve()
TEST_UPLOAD_ROOT = Path(".test-data/uploads").resolve()
TEST_DATABASE.unlink(missing_ok=True)

os.environ.update(
    {
        "APP_ENV": "test",
        "AUTH_MODE": "local",
        "AUTH_JWT_SECRET": "test-only-secret-that-is-at-least-thirty-two-characters-long",
        "AUTH_AUDIT_SECRET": "separate-test-only-audit-secret-that-is-also-long-enough",
        "PASSWORD_RECOVERY_ENABLED": "true",
        "TENANT_INVITATIONS_ENABLED": "true",
        "PUBLIC_UI_URL": "http://127.0.0.1:5173",
        "EMAIL_PROVIDER": "test",
        "EMAIL_FROM": "no-reply@example.com",
        "PASSWORD_RESET_SUBJECT_LIMIT": "3",
        "PASSWORD_RESET_IP_LIMIT": "100",
        "DEV_USER_PASSWORD": "Correct-Horse-Battery-Staple-42",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DATABASE.as_posix()}",
        "DIRECT_DATABASE_URL": "",
        "DATABASE_USE_NULL_POOL": "false",
        "UPLOAD_ROOT": str(TEST_UPLOAD_ROOT),
        "STORAGE_BACKEND": "local",
        "DOCUMENT_INGESTION_ENABLED": "false",
        "DOCUMENT_INGESTION_LOCAL_DEVELOPMENT": "false",
        "DATABASE_MIGRATION_ROLE_NAME": "",
        "TASKS_EAGER": "true",
        "AUTO_CREATE_TABLES": "true",
    }
)

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        login = test_client.post(
            "/api/v1/auth/login",
            json={
                "email": "developer@example.com",
                "password": "Correct-Horse-Battery-Staple-42",
            },
        )
        assert login.status_code == 200, login.text
        test_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        yield test_client


@pytest.fixture(scope="session")
def tenant_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


def pytest_sessionfinish() -> None:
    TEST_DATABASE.unlink(missing_ok=True)
    if TEST_UPLOAD_ROOT.parent.exists():
        import shutil

        shutil.rmtree(TEST_UPLOAD_ROOT.parent)
