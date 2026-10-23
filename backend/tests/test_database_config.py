import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_values(**overrides):
    values = {
        "app_env": "production",
        "auth_mode": "local",
        "auth_jwt_secret": "a" * 48,
        "auth_audit_secret": "b" * 48,
        "auto_create_tables": False,
        "auth_cookie_secure": True,
        "dev_user_password": "",
        "password_recovery_enabled": False,
        "tenant_invitations_enabled": False,
        "email_provider": "smtp",
        "database_url": "postgresql://runtime:secret@db.example.com/wbs?sslmode=require",
        "direct_database_url": "postgresql://migrate:secret@db.example.com/wbs?sslmode=require",
        "readiness_require_migration_head": True,
        "metrics_enabled": True,
        "metrics_bearer_token": "m" * 48,
        "public_ui_url": "https://wbs.example.com",
        "cors_origins": "https://wbs.example.com",
        "forwarded_allow_ips": "10.0.0.0/8",
    }
    values.update(overrides)
    return values


def test_neon_urls_are_normalized_for_async_sqlalchemy() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql://app:secret@ep-example-pooler.us-east-2.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require"
        ),
        direct_database_url=(
            "postgres://app:secret@ep-example.us-east-2.aws.neon.tech/neondb?sslmode=require"
        ),
    )

    assert settings.sqlalchemy_database_url.startswith("postgresql+asyncpg://")
    assert "-pooler." in settings.sqlalchemy_database_url
    assert "ssl=require" in settings.sqlalchemy_database_url
    assert "sslmode" not in settings.sqlalchemy_database_url
    assert "channel_binding" not in settings.sqlalchemy_database_url
    assert settings.sqlalchemy_migration_url.startswith("postgresql+asyncpg://")
    assert "-pooler." not in settings.sqlalchemy_migration_url


def test_migration_url_falls_back_to_runtime_database() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///./local.db",
        direct_database_url=None,
    )

    assert settings.sqlalchemy_migration_url == settings.sqlalchemy_database_url


def test_production_rejects_development_authentication_bypass() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=development is forbidden"):
        Settings(
            _env_file=None,
            **production_values(auth_mode="development"),
        )


def test_production_local_auth_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE must be true"):
        Settings(
            _env_file=None,
            **production_values(auth_cookie_secure=False),
        )


def test_local_auth_requires_independent_jwt_and_audit_secrets() -> None:
    with pytest.raises(ValidationError, match="AUTH_AUDIT_SECRET must contain at least 32 bytes"):
        Settings(
            _env_file=None,
            auth_mode="local",
            auth_jwt_secret="a" * 48,
            auth_audit_secret="short",
        )

    shared_secret = "shared-secret-that-is-long-enough-for-validation"
    with pytest.raises(ValidationError, match="must be independent"):
        Settings(
            _env_file=None,
            auth_mode="local",
            auth_jwt_secret=shared_secret,
            auth_audit_secret=shared_secret,
        )


def test_production_rejects_development_seed_password() -> None:
    with pytest.raises(ValidationError, match="DEV_USER_PASSWORD is forbidden"):
        Settings(
            _env_file=None,
            **production_values(dev_user_password="not-allowed-in-production"),
        )


def test_fullstack_controls_are_restricted_to_the_test_environment() -> None:
    with pytest.raises(ValidationError, match="AUTH_ACCESS_TOKEN_SECONDS_OVERRIDE"):
        Settings(
            _env_file=None,
            app_env="development",
            auth_access_token_seconds_override=5,
        )

    with pytest.raises(ValidationError, match="BOOTSTRAP_DEVELOPMENT_DATA"):
        Settings(
            _env_file=None,
            app_env="development",
            bootstrap_development_data=False,
        )

    settings = Settings(
        _env_file=None,
        app_env="test",
        auth_access_token_seconds_override=5,
        bootstrap_development_data=False,
    )
    assert settings.auth_access_token_seconds_override == 5
    assert settings.bootstrap_development_data is False


def test_enabled_password_recovery_requires_complete_configuration() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_UI_URL is required"):
        Settings(
            _env_file=None,
            auth_mode="local",
            auth_jwt_secret="a" * 48,
            auth_audit_secret="b" * 48,
            password_recovery_enabled=True,
            public_ui_url=None,
        )


def test_enabled_tenant_invitations_require_email_configuration() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_UI_URL is required"):
        Settings(
            _env_file=None,
            auth_mode="local",
            auth_jwt_secret="a" * 48,
            auth_audit_secret="b" * 48,
            tenant_invitations_enabled=True,
            public_ui_url=None,
        )


def test_oidc_mode_requires_complete_independent_configuration() -> None:
    with pytest.raises(ValidationError, match="SSO configuration is incomplete"):
        Settings(
            _env_file=None,
            auth_mode="oidc",
            auth_jwt_secret="a" * 48,
            auth_audit_secret="b" * 48,
            oidc_state_secret="c" * 48,
        )

    shared_secret = "shared-secret-that-is-long-enough-for-validation"
    with pytest.raises(ValidationError, match="OIDC_STATE_SECRET must be independent"):
        Settings(
            _env_file=None,
            app_env="test",
            auth_mode="oidc",
            auth_jwt_secret=shared_secret,
            auth_audit_secret="b" * 48,
            oidc_state_secret=shared_secret,
            oidc_issuer="https://identity.example.test",
            oidc_audience="client",
            oidc_client_id="client",
            oidc_redirect_uri="http://testserver/api/v1/auth/sso/callback",
            public_ui_url="http://127.0.0.1:5173",
        )


def test_oidc_public_origin_and_return_paths_are_exactly_allowlisted() -> None:
    base = {
        "app_env": "test",
        "auth_mode": "oidc",
        "auth_jwt_secret": "a" * 48,
        "auth_audit_secret": "b" * 48,
        "oidc_state_secret": "c" * 48,
        "oidc_issuer": "https://identity.example.test",
        "oidc_audience": "client",
        "oidc_client_id": "client",
        "oidc_redirect_uri": "http://testserver/api/v1/auth/sso/callback",
        "public_ui_url": "http://127.0.0.1:5173",
    }
    with pytest.raises(ValidationError, match="CORS_ORIGINS for SSO"):
        Settings(_env_file=None, cors_origins="http://different.example", **base)
    with pytest.raises(ValidationError, match="unsafe relative path"):
        Settings(
            _env_file=None,
            cors_origins="http://127.0.0.1:5173",
            oidc_allowed_return_paths="/sso/callback,/\\attacker.example",
            **base,
        )


def test_production_password_recovery_requires_https_and_smtp_credentials() -> None:
    with pytest.raises(ValidationError, match="PUBLIC_UI_URL must be an exact HTTPS origin"):
        Settings(
            _env_file=None,
            **production_values(
                password_recovery_enabled=True,
                public_ui_url="http://ui.example.com",
                cors_origins="http://ui.example.com",
                email_provider="smtp",
                email_from="no-reply@example.com",
                smtp_host="smtp.example.com",
                smtp_username="user",
                smtp_password="password",
            ),
        )


def test_valid_production_baseline_is_accepted() -> None:
    settings = Settings(_env_file=None, **production_values())

    assert settings.app_env == "production"
    assert settings.sqlalchemy_database_url.startswith("postgresql+asyncpg://")
    assert settings.readiness_require_migration_head is True


def test_production_rejects_database_without_tls() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must require TLS"):
        Settings(
            _env_file=None,
            **production_values(database_url="postgresql://runtime:secret@db.example.com/wbs"),
        )


def test_production_requires_separate_runtime_and_migration_credentials() -> None:
    shared_url = "postgresql://shared:secret@db.example.com/wbs?sslmode=require"
    with pytest.raises(ValidationError, match="separate production credentials"):
        Settings(
            _env_file=None,
            **production_values(
                database_url=shared_url,
                direct_database_url=shared_url,
            ),
        )


def test_production_requires_independent_metrics_secret() -> None:
    shared_secret = "a" * 48
    with pytest.raises(ValidationError, match="independent from authentication secrets"):
        Settings(
            _env_file=None,
            **production_values(metrics_bearer_token=shared_secret),
        )


def test_production_rejects_wildcard_proxy_trust() -> None:
    with pytest.raises(ValidationError, match="FORWARDED_ALLOW_IPS"):
        Settings(_env_file=None, **production_values(forwarded_allow_ips="*"))


def test_request_limit_cannot_be_smaller_than_upload_limit() -> None:
    with pytest.raises(ValidationError, match="MAX_REQUEST_BODY_BYTES"):
        Settings(_env_file=None, max_upload_bytes=100, max_request_body_bytes=99)


def test_password_recovery_public_origin_must_be_cors_allowed() -> None:
    with pytest.raises(ValidationError, match="must be present in CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="test",
            auth_mode="local",
            auth_jwt_secret="a" * 48,
            auth_audit_secret="b" * 48,
            password_recovery_enabled=True,
            public_ui_url="https://ui.example.com/app",
            cors_origins="https://different.example.com",
            email_provider="test",
            email_from="no-reply@example.com",
        )
