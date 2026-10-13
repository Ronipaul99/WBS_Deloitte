import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_DATABASE = Path(".test-wbs.db").resolve()
TEST_UPLOAD_ROOT = Path(".test-data/uploads").resolve()

os.environ.update(
    {
        "APP_ENV": "test",
        "AUTH_MODE": "development",
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DATABASE.as_posix()}",
        "DIRECT_DATABASE_URL": "",
        "DATABASE_USE_NULL_POOL": "false",
        "UPLOAD_ROOT": str(TEST_UPLOAD_ROOT),
        "TASKS_EAGER": "true",
        "AUTO_CREATE_TABLES": "true",
    }
)

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def tenant_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


def pytest_sessionfinish() -> None:
    TEST_DATABASE.unlink(missing_ok=True)
    if TEST_UPLOAD_ROOT.parent.exists():
        import shutil

        shutil.rmtree(TEST_UPLOAD_ROOT.parent)
