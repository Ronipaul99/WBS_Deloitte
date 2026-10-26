from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import health
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.services.storage import get_upload_storage


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


def test_ingestion_readiness_hides_internal_dependency_details(client, caplog, monkeypatch):
    private_endpoint = "private-redis.internal.example.test"
    release_secret = "redis-release-secret"
    settings = Settings(
        _env_file=None,
        app_env="test",
        document_ingestion_enabled=True,
        database_url="postgresql://runtime:secret@db.example.test/wbs",
        direct_database_url="postgresql://migration:secret@db.example.test/wbs",
        storage_backend="s3",
        object_storage_bucket="assets",
        aws_endpoint_url_s3="https://storage.example.test",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        redis_url=f"rediss://worker:{release_secret}@{private_endpoint}:6380/0",
        tasks_eager=False,
        auto_create_tables=False,
        embedding_model_path="/opt/wbs-models/bge-small-en-v1.5",
        embedding_model_revision="aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        embedding_model_manifest_sha256=(
            "609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0"
        ),
        embedding_tokenizer_revision="aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        embedding_tokenizer_sha256=(
            "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
        ),
        clamav_host="clamav.internal.example.test",
    )

    async def fail_safely(_settings):
        raise health.IngestionReadinessError("redis")

    class ReadyStorage:
        async def check(self):
            return None

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_upload_storage] = ReadyStorage
    monkeypatch.setattr(health, "api_ingestion_is_ready", fail_safely)
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_upload_storage, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "Service is not ready."}
    assert "redis unavailable" in caplog.text
    assert private_endpoint not in response.text
    assert private_endpoint not in caplog.text
    assert release_secret not in response.text
    assert release_secret not in caplog.text


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
