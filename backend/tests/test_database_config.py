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
        "tasks_eager": False,
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
        "storage_backend": "s3",
        "object_storage_bucket": "assets",
        "aws_endpoint_url_s3": "https://storage.example.com",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "aws_region": "us-east-2",
    }
    values.update(overrides)
    return values


def ingestion_values(**overrides):
    values = production_values(
        document_ingestion_enabled=True,
        database_url=(
            "postgresql://runtime:database-secret@"
            "ep-wbs-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
        ),
        direct_database_url=(
            "postgresql://migration:database-secret@"
            "ep-wbs.us-east-2.aws.neon.tech/neondb?sslmode=require"
        ),
        redis_url="rediss://worker:redis-secret@redis.internal.example.com:6380/0",
        embedding_model_path="/opt/wbs-models/bge-small-en-v1.5",
        embedding_model_revision="aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        embedding_model_manifest_sha256=(
            "609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0"
        ),
        embedding_tokenizer_revision="aa8f8b060edb00e03bfdd08813a2949946c8ba55",
        embedding_tokenizer_sha256=(
            "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
        ),
        clamav_host="clamav.internal.example.com",
    )
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


def test_s3_storage_requires_complete_secure_configuration() -> None:
    with pytest.raises(ValidationError, match="S3 object storage configuration is incomplete"):
        Settings(_env_file=None, storage_backend="s3")

    with pytest.raises(ValidationError, match="AWS_ENDPOINT_URL_S3"):
        Settings(
            _env_file=None,
            storage_backend="s3",
            aws_endpoint_url_s3="http://storage.example.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
        )

    settings = Settings(
        _env_file=None,
        storage_backend="s3",
        aws_endpoint_url_s3="https://storage.example.com",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
    )
    assert settings.object_storage_bucket == "assets"
    assert settings.aws_secret_access_key is not None
    assert "test-secret-key" not in repr(settings)


def test_production_requires_s3_object_storage() -> None:
    with pytest.raises(ValidationError, match="STORAGE_BACKEND=s3"):
        Settings(
            _env_file=None,
            **production_values(storage_backend="local"),
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


def test_valid_release_ingestion_configuration_is_accepted() -> None:
    settings = Settings(_env_file=None, **ingestion_values())

    assert settings.document_ingestion_enabled is True
    assert settings.database_runtime_role == "runtime"
    assert settings.database_migration_role == "migration"
    assert settings.embedding_provider == "fastembed"
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"
    assert settings.embedding_dimensions == 384
    assert settings.embedding_model_revision == "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
    assert settings.embedding_max_concurrent_batches == 1


def test_ingestion_requires_separate_runtime_and_migration_roles() -> None:
    with pytest.raises(ValidationError, match="separate runtime and migration database roles"):
        Settings(
            _env_file=None,
            **ingestion_values(
                direct_database_url=(
                    "postgresql://runtime:another-secret@"
                    "ep-wbs.us-east-2.aws.neon.tech/neondb?sslmode=require"
                )
            ),
        )


def test_ingestion_cannot_be_enabled_as_a_development_feature() -> None:
    with pytest.raises(ValidationError, match="only in production or test"):
        Settings(_env_file=None, **ingestion_values(app_env="development"))


def local_ingestion_values(**overrides):
    values = ingestion_values(
        app_env="development",
        auth_mode="development",
        document_ingestion_local_development=True,
        redis_url="redis://:tunnel-secret@127.0.0.1:16379/0",
    )
    values.update(overrides)
    return values


def test_local_ingestion_accepts_authenticated_ssh_tunnel() -> None:
    settings = Settings(_env_file=None, **local_ingestion_values())
    assert settings.document_ingestion_enabled
    assert settings.document_ingestion_local_development


def test_local_worker_does_not_need_migration_credentials() -> None:
    settings = Settings(
        _env_file=None,
        **local_ingestion_values(
            direct_database_url=None,
            database_migration_role_name="migration",
            redis_url="redis://:worker-secret@redis:6379/0",
        ),
    )
    assert settings.direct_database_url is None
    assert settings.database_runtime_role == "runtime"


@pytest.mark.parametrize("app_env", ["production", "test"])
def test_local_ingestion_opt_in_cannot_weaken_other_environments(app_env) -> None:
    with pytest.raises(ValidationError, match="allowed only in development"):
        Settings(_env_file=None, **local_ingestion_values(app_env=app_env))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"redis_url": "redis://127.0.0.1:16379/0"}, "authenticated"),
        ({"redis_url": "https://:secret@localhost"}, "authenticated"),
        ({"storage_backend": "local"}, "STORAGE_BACKEND=s3"),
        ({"tasks_eager": True}, "TASKS_EAGER must be false"),
        ({"auto_create_tables": True}, "AUTO_CREATE_TABLES must be false"),
        ({"malware_scan_required": False}, "MALWARE_SCAN_REQUIRED"),
        ({"embedding_tokenizer_sha256": None}, "Pinned tokenizer"),
        ({"direct_database_url": None}, "DIRECT_DATABASE_URL is required"),
        (
            {"direct_database_url": None, "database_migration_role_name": "runtime"},
            "separate runtime and migration database roles",
        ),
        ({"database_migration_role_name": "wrong-role"}, "must match DIRECT_DATABASE_URL"),
    ],
)
def test_local_ingestion_preserves_dependency_guards(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **local_ingestion_values(**overrides))


def test_migration_role_name_does_not_replace_production_migration_url() -> None:
    with pytest.raises(ValidationError, match="DIRECT_DATABASE_URL is required"):
        Settings(
            _env_file=None,
            **ingestion_values(direct_database_url=None, database_migration_role_name="migration"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "embedding_batch_size": 1,
            "document_processing_timeout_seconds": 60,
            "document_max_pdf_pages": 1,
            "document_max_worksheets": 1,
            "document_max_rows_per_sheet": 1,
            "document_max_extracted_characters": 1_000,
            "document_chunk_target_tokens": 64,
            "document_chunk_overlap_tokens": 0,
        },
        {
            "embedding_batch_size": 256,
            "document_processing_timeout_seconds": 3_600,
            "document_max_pdf_pages": 2_000,
            "document_max_worksheets": 500,
            "document_max_rows_per_sheet": 1_000_000,
            "document_max_extracted_characters": 50_000_000,
            "document_chunk_target_tokens": 500,
            "document_chunk_overlap_tokens": 12,
            "document_chunk_max_tokens": 500,
            "document_chunk_formatting_headroom_tokens": 12,
        },
        {
            "document_chunk_target_tokens": 384,
            "document_chunk_overlap_tokens": 128,
        },
    ],
)
def test_ingestion_reviewed_bounds_are_accepted(overrides) -> None:
    settings = Settings(_env_file=None, **ingestion_values(**overrides))

    assert settings.document_ingestion_enabled is True


def test_production_rejects_eager_tasks() -> None:
    with pytest.raises(ValidationError, match="TASKS_EAGER must be false in production"):
        Settings(_env_file=None, **ingestion_values(tasks_eager=True))


def test_ingestion_rejects_local_storage() -> None:
    with pytest.raises(ValidationError, match="STORAGE_BACKEND=s3"):
        Settings(_env_file=None, **ingestion_values(storage_backend="local"))


def test_ingestion_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL must use PostgreSQL"):
        Settings(
            _env_file=None,
            **ingestion_values(database_url="sqlite+aiosqlite:///./wbs.db"),
        )


def test_ingestion_requires_direct_database_url() -> None:
    with pytest.raises(ValidationError, match="DIRECT_DATABASE_URL is required"):
        Settings(_env_file=None, **ingestion_values(direct_database_url=None))


@pytest.mark.parametrize(
    "redis_url",
    ["", "https://redis.internal.example.com", "redis://localhost:6379/0", "redis://bad host"],
)
def test_ingestion_rejects_missing_or_invalid_redis_url(redis_url: str) -> None:
    with pytest.raises(ValidationError, match="REDIS_URL must be a non-local"):
        Settings(_env_file=None, **ingestion_values(redis_url=redis_url))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"embedding_provider": "openai"}, "EMBEDDING_PROVIDER must be fastembed"),
        ({"embedding_model": "different/model"}, "EMBEDDING_MODEL must be"),
        ({"embedding_dimensions": 768}, "EMBEDDING_DIMENSIONS must be 384"),
    ],
)
def test_ingestion_rejects_unapproved_embedding_configuration(overrides, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **ingestion_values(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"embedding_model_revision": None}, "EMBEDDING_MODEL_REVISION is required"),
        (
            {"embedding_model_manifest_sha256": None},
            "EMBEDDING_MODEL_MANIFEST_SHA256 is required",
        ),
        (
            {"embedding_tokenizer_revision": "b" * 40},
            "Tokenizer and embedding model revisions must match",
        ),
        (
            {"embedding_formatting_version": "unapproved-v2"},
            "EMBEDDING_FORMATTING_VERSION must use the approved",
        ),
        (
            {"embedding_max_concurrent_batches": 2},
            "EMBEDDING_MAX_CONCURRENT_BATCHES must be 1",
        ),
    ],
)
def test_ingestion_rejects_unpinned_or_unapproved_embedding_runtime(
    overrides, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **ingestion_values(**overrides))


def test_ingestion_rejects_chunk_window_over_model_limit() -> None:
    with pytest.raises(ValidationError, match="must not exceed 512"):
        Settings(
            _env_file=None,
            **ingestion_values(
                document_chunk_max_tokens=500,
                document_chunk_formatting_headroom_tokens=13,
            ),
        )


def test_ingestion_rejects_invalid_chunk_relationships() -> None:
    with pytest.raises(ValidationError, match="OVERLAP_TOKENS must be smaller"):
        Settings(
            _env_file=None,
            **ingestion_values(
                document_chunk_target_tokens=64,
                document_chunk_overlap_tokens=64,
            ),
        )
    with pytest.raises(ValidationError, match="TARGET_TOKENS cannot exceed"):
        Settings(
            _env_file=None,
            **ingestion_values(
                document_chunk_target_tokens=400,
                document_chunk_max_tokens=399,
            ),
        )


@pytest.mark.parametrize("clamav_host", [None, "", "https://clamav.internal.example.com"])
def test_ingestion_requires_valid_clamav_host(clamav_host: str | None) -> None:
    with pytest.raises(ValidationError, match="CLAMAV_HOST is required"):
        Settings(_env_file=None, **ingestion_values(clamav_host=clamav_host))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ocr_enabled": False}, "OCR_ENABLED must be true"),
        ({"malware_scan_required": False}, "MALWARE_SCAN_REQUIRED must be true"),
    ],
)
def test_ingestion_requires_declared_security_controls(overrides, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **ingestion_values(**overrides))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ocr_languages": "eng+deu"}, "OCR_LANGUAGES must be eng"),
        (
            {"ocr_max_output_bytes": 8192, "ocr_max_temporary_bytes": 4096},
            "OCR_MAX_TEMPORARY_BYTES cannot be smaller",
        ),
    ],
)
def test_ingestion_rejects_unsafe_pdf_ocr_configuration(overrides, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **ingestion_values(**overrides))


def test_pdf_ocr_settings_are_typed_and_bounded() -> None:
    settings = Settings(
        _env_file=None,
        ocrmypdf_expected_version="16.10.4",
        tesseract_expected_version="5.3.0",
    )
    assert settings.pdf_native_text_min_characters == 32
    assert settings.ocr_languages == "eng"
    assert settings.ocrmypdf_expected_version == "16.10.4"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, pdf_margin_band_ratio=0.5)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ocrmypdf_expected_version="unsafe version")


def test_ingestion_requires_absolute_model_path() -> None:
    with pytest.raises(ValidationError, match="EMBEDDING_MODEL_PATH must be an absolute path"):
        Settings(
            _env_file=None,
            **ingestion_values(embedding_model_path="models/bge-small-en-v1.5"),
        )


@pytest.mark.parametrize(
    ("database_url", "direct_database_url", "message"),
    [
        (
            "postgresql://runtime:secret@ep-wbs.us-east-2.aws.neon.tech/neondb?sslmode=require",
            "postgresql://migration:secret@ep-wbs-direct.us-east-2.aws.neon.tech/neondb?sslmode=require",
            "DATABASE_URL must use a pooled Neon endpoint",
        ),
        (
            "postgresql://runtime:secret@ep-wbs-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
            "postgresql://migration:secret@ep-wbs-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
            "DIRECT_DATABASE_URL must use a direct Neon endpoint",
        ),
    ],
)
def test_ingestion_requires_pooled_runtime_and_direct_neon_urls(
    database_url: str,
    direct_database_url: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(
            _env_file=None,
            **ingestion_values(
                database_url=database_url,
                direct_database_url=direct_database_url,
            ),
        )


def test_ingestion_validation_errors_hide_input_secrets() -> None:
    exposed_secret = "do-not-disclose-this-release-secret"

    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            **ingestion_values(
                embedding_provider="unapproved",
                redis_url=f"rediss://worker:{exposed_secret}@redis.internal.example.com:6380/0",
            ),
        )

    assert exposed_secret not in str(error.value)


def test_disabled_ingestion_preserves_local_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.document_ingestion_enabled is False
    assert settings.storage_backend == "local"
    assert settings.tasks_eager is True


@pytest.mark.parametrize("temp_root", ["relative/processing", "/", "C:\\\\"])
def test_ingestion_rejects_unsafe_processing_temp_root(temp_root: str) -> None:
    with pytest.raises(ValidationError, match="DOCUMENT_PROCESSING_TEMP_ROOT"):
        Settings(
            _env_file=None,
            **ingestion_values(document_processing_temp_root=temp_root),
        )


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


def test_document_retention_requires_an_explicit_complete_policy() -> None:
    with pytest.raises(ValidationError, match="retention requires explicit approved values"):
        Settings(
            _env_file=None,
            **ingestion_values(document_retention_enabled=True),
        )

    settings = Settings(
        _env_file=None,
        **ingestion_values(
            document_retention_enabled=True,
            document_retention_failed_run_days=30,
            document_retention_cancelled_run_days=30,
            document_retention_superseded_run_days=90,
            document_retention_job_days=90,
            document_retention_malware_event_days=365,
            document_retention_tombstone_days=365,
            document_retention_stale_workspace_hours=24,
        ),
    )
    assert settings.document_retention_enabled is True


def test_destructive_orphan_cleanup_requires_age_threshold() -> None:
    with pytest.raises(ValidationError, match="MINIMUM_AGE_HOURS is required"):
        Settings(
            _env_file=None,
            **ingestion_values(document_orphan_cleanup_enabled=True),
        )
