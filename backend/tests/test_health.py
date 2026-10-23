from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app


def test_health_endpoints(client):
    live = client.get("/api/v1/health/live")
    ready = client.get("/api/v1/health/ready")

    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert live.headers["X-Correlation-ID"]


def test_readiness_fails_closed_without_an_active_local_administrator(client, caplog):
    class MissingAdministratorSession:
        async def execute(self, _):
            return None

        async def scalar(self, _):
            return None

    async def override_database():
        yield MissingAdministratorSession()

    app.dependency_overrides[get_db] = override_database
    try:
        ready = client.get("/api/v1/health/ready")
        live = client.get("/api/v1/health/live")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert ready.status_code == 503
    assert ready.json() == {"detail": "Service is not ready."}
    assert "active local administrator is not provisioned" in caplog.text
    assert "@" not in caplog.text
    assert live.status_code == 200


def test_readiness_hides_database_failure_details(client, caplog):
    class UnavailableDatabaseSession:
        async def execute(self, _):
            raise SQLAlchemyError("credential-bearing database diagnostic")

    async def override_database():
        yield UnavailableDatabaseSession()

    app.dependency_overrides[get_db] = override_database
    try:
        ready = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert ready.status_code == 503
    assert ready.json() == {"detail": "Service is not ready."}
    assert "credential-bearing" not in ready.text
    assert "credential-bearing" not in caplog.text
    assert "database unavailable" in caplog.text


def test_development_identity(client, tenant_id):
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["email"] == "developer@example.com"
    assert response.json()["tenants"][0]["id"] == tenant_id


def test_metrics_are_hidden_when_disabled(client):
    response = client.get("/api/v1/health/metrics")

    assert response.status_code == 404


def test_metrics_require_bearer_authentication_and_do_not_cache(client):
    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_mode="local",
        auth_jwt_secret="a" * 48,
        auth_audit_secret="b" * 48,
        metrics_enabled=True,
        metrics_bearer_token="metrics-test-token-that-is-long-enough",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        denied = client.get("/api/v1/health/metrics", headers={"Authorization": "Bearer wrong"})
        response = client.get(
            "/api/v1/health/metrics",
            headers={"Authorization": "Bearer metrics-test-token-that-is-long-enough"},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert denied.status_code == 401
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "wbs_refresh_sessions" in response.text


def test_request_body_limit_is_enforced_before_route_parsing(client):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Content-Length": str(27 * 1024 * 1024)},
        content=b"",
    )

    assert response.status_code == 413
    assert response.headers["X-Content-Type-Options"] == "nosniff"
