# ruff: noqa: E402
"""Isolated ASGI app only, no production startup and no shared conftest."""

import os
from uuid import UUID

os.environ.update(
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    DIRECT_DATABASE_URL="",
    AUTO_CREATE_TABLES="false",
    DOCUMENT_INGESTION_ENABLED="false",
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT="false",
)
from app.core.config import Settings

Settings.model_config["env_file"] = None

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from test_llm_management import manager as management_fixture  # noqa: F401
from test_llm_management import saved

from app.api.dependencies import get_current_user
from app.api.routes.llm_settings import get_management, router
from app.core.config import get_settings
from app.db.session import get_db
from app.models.domain import User
from app.services.agents.scoped_storage import StorageAccess
from app.services.llm.management import ModelManagement


@pytest.fixture
def api(manager):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    actor = {"id": 9}

    async def db():
        async with manager.sessions() as session:
            yield session

    async def user():
        async with manager.sessions() as session:
            return await session.scalar(select(User).where(User.id == UUID(int=actor["id"])))

    from fastapi import Depends

    from app.api.dependencies import require_tenant_member

    member_dependency = Depends(require_tenant_member)

    def service(context=member_dependency):
        return ModelManagement(
            manager.sessions,
            StorageAccess(context.tenant.id, context.user.id),
            manager.endpoints,
            manager.keys,
            tests_enabled=True,
        )

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = user
    app.dependency_overrides[get_management] = service
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        auth_audit_secret="synthetic-test-audit-phrase-with-forty-characters",
        app_env="test",
    )
    return app, actor


@pytest.mark.asyncio
async def test_api_admin_metadata_and_validation_excludes_secret(manager, api):
    from llm_security_fixtures import SENTINEL

    c, _ = await saved(manager)
    app, _ = api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        prefix = "/api/v1/tenants/00000000-0000-0000-0000-000000000001/llm"
        response = await client.get(prefix + "/connections")
        assert response.status_code == 200, response.text
        assert SENTINEL not in response.text and "ciphertext" not in response.text
        assert response.headers["cache-control"] == "no-store"
        response = await client.post(
            prefix + "/connections",
            json={
                "name": "x",
                "provider": "openai_compatible",
                "approval_id": "bad",
                "credential": {"action": "replace", "secret": SENTINEL},
            },
        )
        assert (
            response.status_code == 422
            and SENTINEL not in response.text
            and "input" not in response.text
        )
        response = await client.patch(
            prefix + "/connections/" + c["id"], json={"expected_revision": 999}
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "llm_stale_revision"


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [19, 29, 109])
async def test_api_mutations_denied_to_editor_viewer_and_other_tenant(manager, api, actor):
    app, identity = api
    identity["id"] = actor
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        prefix = "/api/v1/tenants/00000000-0000-0000-0000-000000000001/llm"
        response = await client.post(
            prefix + "/connections",
            json={
                "name": "x",
                "provider": "openai_compatible",
                "approval_id": "00000000-0000-0000-0000-000000000046",
            },
        )
        assert response.status_code == 403, response.text
        catalog = await client.get(prefix + "/usable-profiles")
        assert catalog.status_code == (200 if actor == 19 else 403)


@pytest.mark.asyncio
async def test_api_gate_disabled_is_unavailable_without_enabling_summary(manager, api):
    app, _ = api
    app.dependency_overrides.pop(get_management)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/tenants/00000000-0000-0000-0000-000000000001/llm/connections"
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "llm_management_disabled"
