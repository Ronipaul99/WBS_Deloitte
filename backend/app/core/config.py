from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path, PurePosixPath, PureWindowsPath
from secrets import compare_digest
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "WBS Generator API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./wbs.db"
    direct_database_url: str | None = None
    # Non-secret role identity for development workers that do not hold migration credentials.
    database_migration_role_name: str | None = Field(default=None, max_length=63)
    database_use_null_pool: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 300
    redis_url: str = "redis://localhost:6379/0"
    tasks_eager: bool = True
    auto_create_tables: bool = True
    bootstrap_development_data: bool = True
    upload_root: Path = Path(".data/uploads")
    storage_backend: Literal["local", "s3"] = "local"
    object_storage_bucket: str = "assets"
    aws_endpoint_url_s3: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_region: str = "us-east-2"
    object_storage_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    object_storage_read_timeout_seconds: int = Field(default=60, ge=5, le=300)
    object_storage_max_attempts: int = Field(default=3, ge=1, le=5)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_bytes: int = 25 * 1024 * 1024
    max_request_body_bytes: int = 26 * 1024 * 1024
    forwarded_allow_ips: str = "127.0.0.1"
    readiness_require_migration_head: bool = False
    metrics_enabled: bool = False
    metrics_bearer_token: str = ""
    document_ingestion_enabled: bool = False
    document_workflow_resume_enabled: bool = False
    document_upload_reuse_enabled: bool = False
    document_upload_lease_seconds: int = Field(default=120, ge=15, le=3600)
    document_ingestion_local_development: bool = False
    embedding_provider: str = Field(default="fastembed", min_length=1, max_length=40)
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", min_length=1, max_length=160)
    embedding_dimensions: int = Field(default=384, ge=1, le=4096)
    embedding_batch_size: int = Field(default=32, ge=1, le=256)
    embedding_model_path: str = Field(
        default="/opt/wbs-models/bge-small-en-v1.5", min_length=1, max_length=1024
    )
    embedding_model_revision: str | None = Field(
        default=None,
        min_length=40,
        max_length=128,
        pattern=r"^[0-9a-f]{40,128}$",
    )
    embedding_model_manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    embedding_formatting_version: str = Field(
        default="bge-small-en-v1.5-format-v1",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    embedding_tokenizer_revision: str | None = Field(
        default=None,
        min_length=7,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    embedding_tokenizer_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    embedding_max_text_characters: int = Field(default=100_000, ge=1_000, le=1_000_000)
    embedding_max_concurrent_batches: int = Field(default=1, ge=1, le=8)
    embedding_cpu_threads: int = Field(default=2, ge=1, le=32)
    document_processing_timeout_seconds: int = Field(default=900, ge=60, le=3600)
    document_ingestion_max_attempts: int = Field(default=5, ge=1, le=10)
    document_ingestion_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    document_ingestion_retry_max_seconds: int = Field(default=300, ge=5, le=3_600)
    document_dispatch_publish_timeout_seconds: int = Field(default=10, ge=1, le=60)
    document_dispatch_lease_seconds: int = Field(default=60, ge=10, le=900)
    document_reconciliation_stale_seconds: int = Field(default=900, ge=60, le=7_200)
    document_reconciliation_batch_size: int = Field(default=100, ge=1, le=1_000)
    document_deletion_max_attempts: int = Field(default=5, ge=1, le=10)
    document_deletion_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    document_deletion_retry_max_seconds: int = Field(default=300, ge=5, le=3_600)
    document_deletion_lease_seconds: int = Field(default=60, ge=10, le=900)
    document_deletion_stale_seconds: int = Field(default=900, ge=60, le=86_400)
    document_lifecycle_batch_size: int = Field(default=100, ge=1, le=1_000)
    document_reconciliation_repairs_enabled: bool = False
    document_retention_enabled: bool = False
    document_retention_failed_run_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_cancelled_run_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_superseded_run_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_job_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_malware_event_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_tombstone_days: int | None = Field(default=None, ge=1, le=3650)
    document_retention_stale_workspace_hours: int | None = Field(default=None, ge=1, le=8760)
    document_orphan_cleanup_enabled: bool = False
    document_orphan_minimum_age_hours: int | None = Field(default=None, ge=24, le=8760)
    document_max_pdf_pages: int = Field(default=500, ge=1, le=2000)
    document_max_worksheets: int = Field(default=100, ge=1, le=500)
    document_max_rows_per_sheet: int = Field(default=100_000, ge=1, le=1_000_000)
    document_max_extracted_characters: int = Field(default=10_000_000, ge=1_000, le=50_000_000)
    document_max_extracted_blocks: int = Field(default=100_000, ge=1, le=1_000_000)
    document_max_block_characters: int = Field(default=100_000, ge=1, le=1_000_000)
    document_max_heading_depth: int = Field(default=16, ge=1, le=64)
    document_max_heading_label_characters: int = Field(default=500, ge=1, le=2_000)
    document_max_extraction_warnings: int = Field(default=100, ge=0, le=1_000)
    document_max_metadata_fields: int = Field(default=16, ge=0, le=64)
    document_max_metadata_depth: int = Field(default=3, ge=1, le=8)
    document_max_metadata_value_characters: int = Field(default=1_000, ge=1, le=10_000)
    document_max_metadata_list_items: int = Field(default=100, ge=0, le=1_000)
    document_max_sheet_name_characters: int = Field(default=160, ge=1, le=255)
    document_max_archive_entries: int = Field(default=10_000, ge=10, le=100_000)
    document_max_archive_compressed_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=4 * 1024,
        le=256 * 1024 * 1024,
    )
    document_max_archive_uncompressed_bytes: int = Field(
        default=200 * 1024 * 1024,
        ge=4 * 1024,
        le=2 * 1024 * 1024 * 1024,
    )
    document_max_archive_entry_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1_024,
        le=512 * 1024 * 1024,
    )
    document_max_archive_expansion_ratio: int = Field(default=100, ge=1, le=1_000)
    document_max_spreadsheet_columns: int = Field(default=1_000, ge=1, le=16_384)
    document_max_spreadsheet_cells: int = Field(default=1_000_000, ge=1, le=10_000_000)
    document_max_merged_ranges: int = Field(default=10_000, ge=0, le=100_000)
    document_max_csv_columns: int = Field(default=1_000, ge=1, le=10_000)
    document_max_csv_field_characters: int = Field(default=100_000, ge=1, le=1_000_000)
    pdf_max_content_stream_bytes: int = Field(
        default=16 * 1024 * 1024,
        ge=4 * 1024,
        le=256 * 1024 * 1024,
    )
    pdf_native_text_min_characters: int = Field(default=32, ge=1, le=10_000)
    pdf_repeated_margin_min_pages: int = Field(default=3, ge=3, le=100)
    pdf_repeated_margin_min_ratio: float = Field(default=0.8, ge=0.5, le=1.0)
    pdf_margin_band_ratio: float = Field(default=0.12, ge=0.01, le=0.25)
    pdf_repeated_margin_max_characters: int = Field(default=160, ge=1, le=1_000)
    pdf_parser_timeout_seconds: int = Field(default=120, ge=5, le=900)
    document_chunk_target_tokens: int = Field(default=400, ge=64, le=500)
    document_chunk_overlap_tokens: int = Field(default=50, ge=0, le=128)
    document_chunk_max_tokens: int = Field(default=480, ge=64, le=510)
    document_chunk_formatting_headroom_tokens: int = Field(default=32, ge=2, le=128)
    document_max_chunks: int = Field(default=100_000, ge=1, le=1_000_000)
    document_max_chunk_source_references: int = Field(default=2_048, ge=1, le=100_000)
    ocr_enabled: bool = True
    ocr_languages: str = Field(default="eng", min_length=3, max_length=64)
    ocr_timeout_seconds: int = Field(default=300, ge=5, le=1_800)
    ocr_max_output_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=4 * 1024,
        le=256 * 1024 * 1024,
    )
    ocr_max_temporary_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=4 * 1024,
        le=2 * 1024 * 1024 * 1024,
    )
    ocr_process_output_max_bytes: int = Field(default=64 * 1024, ge=1_024, le=1_048_576)
    ocr_cpu_limit_seconds: int = Field(default=300, ge=5, le=1_800)
    ocr_memory_limit_bytes: int = Field(
        default=2 * 1024 * 1024 * 1024,
        ge=128 * 1024 * 1024,
        le=16 * 1024 * 1024 * 1024,
    )
    ocrmypdf_expected_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$",
    )
    tesseract_expected_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$",
    )
    malware_scan_required: bool = True
    clamav_host: str | None = Field(default=None, max_length=255)
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    clamav_connect_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
    clamav_scan_timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    clamav_response_max_bytes: int = Field(default=4096, ge=64, le=65_536)
    document_processing_temp_root: str = Field(
        default="/var/lib/wbs/processing",
        min_length=1,
        max_length=1024,
    )
    refresh_session_retention_days: int = Field(default=30, ge=1, le=365)
    auth_event_retention_days: int = Field(default=365, ge=30, le=2555)
    oidc_state_retention_days: int = Field(default=7, ge=1, le=30)
    temporary_file_retention_hours: int = Field(default=24, ge=1, le=168)
    maintenance_batch_size: int = Field(default=1000, ge=100, le=10000)

    auth_mode: Literal["development", "local", "oidc", "hybrid"] = "development"
    auth_jwt_secret: str = ""
    auth_jwt_issuer: str = "wbs-generator-api"
    auth_jwt_audience: str = "wbs-generator-ui"
    auth_access_token_minutes: int = Field(default=15, ge=5, le=60)
    auth_access_token_seconds_override: int | None = Field(default=None, ge=1, le=30)
    auth_refresh_token_days: int = Field(default=7, ge=1, le=30)
    auth_refresh_cookie_name: str = "wbs_refresh"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_login_window_minutes: int = Field(default=15, ge=1, le=60)
    auth_login_subject_limit: int = Field(default=5, ge=1, le=100)
    auth_login_ip_limit: int = Field(default=20, ge=1, le=500)
    auth_audit_secret: str = ""
    password_recovery_enabled: bool = False
    public_ui_url: str | None = None
    password_reset_minutes: int = Field(default=30, ge=5, le=30)
    password_reset_window_minutes: int = Field(default=15, ge=1, le=60)
    password_reset_subject_limit: int = Field(default=3, ge=1, le=100)
    password_reset_ip_limit: int = Field(default=20, ge=1, le=500)
    password_reset_retention_days: int = Field(default=30, ge=1, le=365)
    tenant_invitations_enabled: bool = False
    tenant_invitation_hours: int = Field(default=72, ge=1, le=168)
    tenant_invitation_retention_days: int = Field(default=30, ge=1, le=365)
    tenant_invitation_resend_window_minutes: int = Field(default=60, ge=1, le=1440)
    tenant_invitation_resend_limit: int = Field(default=5, ge=1, le=50)
    email_provider: Literal["smtp", "test"] = "smtp"
    email_from: EmailStr | None = None
    email_delivery_timeout_seconds: int = Field(default=10, ge=3, le=30)
    email_delivery_retries: int = Field(default=2, ge=0, le=3)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    dev_user_password: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    oidc_discovery_url: str | None = None
    oidc_authorization_endpoint: str | None = None
    oidc_token_endpoint: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_state_secret: str = ""
    oidc_state_cookie_name: str = Field(default="wbs_oidc_state", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    oidc_state_minutes: int = Field(default=10, ge=3, le=15)
    oidc_provider_id: str = Field(default="enterprise_oidc", min_length=1, max_length=40)
    oidc_provider_tenant_id: str | None = None
    oidc_tenant_claim: str = "tid"
    oidc_email_claim: str = "email"
    oidc_email_verified_claim: str = "email_verified"
    oidc_name_claim: str = "name"
    oidc_scopes: str = "openid email profile"
    oidc_allowed_return_paths: str = Field(default="/sso/callback", max_length=1024)

    dev_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    dev_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.document_upload_reuse_enabled and not self.document_workflow_resume_enabled:
            raise ValueError(
                "Document upload reuse requires document workflow resume to be enabled"
            )
        if self.document_ingestion_local_development and self.app_env != "development":
            raise ValueError("DOCUMENT_INGESTION_LOCAL_DEVELOPMENT is allowed only in development")
        if self.auth_access_token_seconds_override is not None and self.app_env != "test":
            raise ValueError("AUTH_ACCESS_TOKEN_SECONDS_OVERRIDE is allowed only in test")
        if not self.bootstrap_development_data and self.app_env != "test":
            raise ValueError("BOOTSTRAP_DEVELOPMENT_DATA may be disabled only in test")
        if self.auth_mode in {"local", "oidc", "hybrid"}:
            if len(self.auth_jwt_secret.encode("utf-8")) < 32:
                raise ValueError(
                    "AUTH_JWT_SECRET must contain at least 32 bytes for authentication"
                )
            if len(self.auth_audit_secret.encode("utf-8")) < 32:
                raise ValueError(
                    "AUTH_AUDIT_SECRET must contain at least 32 bytes for authentication"
                )
            if compare_digest(self.auth_jwt_secret, self.auth_audit_secret):
                raise ValueError("AUTH_JWT_SECRET and AUTH_AUDIT_SECRET must be independent")
        if self.auth_mode in {"oidc", "hybrid"}:
            self._validate_oidc_settings()
        if self.storage_backend == "s3":
            required_storage = {
                "AWS_ENDPOINT_URL_S3": self.aws_endpoint_url_s3,
                "AWS_ACCESS_KEY_ID": self.aws_access_key_id,
                "AWS_SECRET_ACCESS_KEY": (
                    self.aws_secret_access_key.get_secret_value()
                    if self.aws_secret_access_key
                    else None
                ),
                "AWS_REGION": self.aws_region,
                "OBJECT_STORAGE_BUCKET": self.object_storage_bucket,
            }
            missing_storage = [name for name, value in required_storage.items() if not value]
            if missing_storage:
                raise ValueError(
                    "S3 object storage configuration is incomplete: " + ", ".join(missing_storage)
                )
            if not self._is_storage_endpoint(self.aws_endpoint_url_s3 or ""):
                raise ValueError(
                    "AWS_ENDPOINT_URL_S3 must be an HTTPS origin "
                    "(HTTP is allowed only for local development endpoints)"
                )
            if not self._is_valid_bucket_name(self.object_storage_bucket):
                raise ValueError("OBJECT_STORAGE_BUCKET is not a valid S3 bucket name")
        if self.app_env == "production":
            if self.auth_mode == "development":
                raise ValueError("AUTH_MODE=development is forbidden in production")
            if self.dev_user_password:
                raise ValueError("DEV_USER_PASSWORD is forbidden in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production")
            if self.auto_create_tables:
                raise ValueError("AUTO_CREATE_TABLES must be false in production")
            if self.tasks_eager:
                raise ValueError("TASKS_EAGER must be false in production")
            if not self.sqlalchemy_database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("DATABASE_URL must use PostgreSQL in production")
            if not self.direct_database_url:
                raise ValueError("DIRECT_DATABASE_URL is required in production")
            if not self.sqlalchemy_migration_url.startswith("postgresql+asyncpg://"):
                raise ValueError("DIRECT_DATABASE_URL must use PostgreSQL in production")
            if self.storage_backend != "s3":
                raise ValueError("STORAGE_BACKEND=s3 is required in production")
            if self.sqlalchemy_database_url == self.sqlalchemy_migration_url:
                raise ValueError(
                    "DATABASE_URL and DIRECT_DATABASE_URL must use separate production credentials"
                )
            if self.sqlalchemy_database_url == self.sqlalchemy_migration_url:
                raise ValueError(
                    "DATABASE_URL and DIRECT_DATABASE_URL must use separate production credentials"
                )
            if not self._database_url_requires_tls(self.sqlalchemy_database_url):
                raise ValueError("DATABASE_URL must require TLS in production")
            if not self._database_url_requires_tls(self.sqlalchemy_migration_url):
                raise ValueError("DIRECT_DATABASE_URL must require TLS in production")
            if not self.readiness_require_migration_head:
                raise ValueError("READINESS_REQUIRE_MIGRATION_HEAD must be true in production")
            if not self.metrics_enabled:
                raise ValueError("METRICS_ENABLED must be true in production")
            if len(self.metrics_bearer_token.encode("utf-8")) < 32:
                raise ValueError(
                    "METRICS_BEARER_TOKEN must contain at least 32 bytes in production"
                )
            if any(
                compare_digest(self.metrics_bearer_token, secret)
                for secret in (self.auth_jwt_secret, self.auth_audit_secret)
            ):
                raise ValueError(
                    "METRICS_BEARER_TOKEN must be independent from authentication secrets"
                )
            if any(
                compare_digest(self.metrics_bearer_token, secret)
                for secret in (self.auth_jwt_secret, self.auth_audit_secret)
            ):
                raise ValueError(
                    "METRICS_BEARER_TOKEN must be independent from authentication secrets"
                )
            if not self.public_ui_url:
                raise ValueError("PUBLIC_UI_URL is required in production")
            if not self._is_exact_origin(self.public_ui_url, require_https=True):
                raise ValueError("PUBLIC_UI_URL must be an exact HTTPS origin in production")
            if self.public_ui_url not in self.cors_origin_list:
                raise ValueError("PUBLIC_UI_URL must be present in CORS_ORIGINS")
            if not self.forwarded_allow_ip_list or "*" in self.forwarded_allow_ip_list:
                raise ValueError("FORWARDED_ALLOW_IPS must list trusted proxies in production")
            if not all(self._is_ip_network(value) for value in self.forwarded_allow_ip_list):
                raise ValueError("FORWARDED_ALLOW_IPS must contain only IP addresses or CIDRs")
            for origin in self.cors_origin_list:
                if not self._is_exact_origin(origin, require_https=True):
                    raise ValueError("CORS_ORIGINS must contain exact HTTPS origins in production")
        if self.document_ingestion_enabled:
            self._validate_document_ingestion_settings()
        elif self.document_retention_enabled or self.document_orphan_cleanup_enabled:
            raise ValueError(
                "Document retention and orphan cleanup require document ingestion to be enabled"
            )
        if self.password_recovery_enabled:
            if self.auth_mode not in {"local", "hybrid"}:
                raise ValueError("Password recovery requires local or hybrid authentication")
        if self.tenant_invitations_enabled and self.auth_mode == "development":
            raise ValueError("Tenant invitations require an authenticated mode")
        if self.password_recovery_enabled or self.tenant_invitations_enabled:
            if not self.public_ui_url:
                raise ValueError("PUBLIC_UI_URL is required when email authentication is enabled")
            parts = urlsplit(self.public_ui_url)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.netloc
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    "PUBLIC_UI_URL must be an HTTP(S) URL without credentials or query"
                )
            if self.app_env == "production" and parts.scheme != "https":
                raise ValueError("PUBLIC_UI_URL must use HTTPS in production")
            public_ui_origin = f"{parts.scheme}://{parts.netloc}"
            if public_ui_origin not in self.cors_origin_list:
                raise ValueError("PUBLIC_UI_URL origin must be present in CORS_ORIGINS")
            if not self.email_from:
                raise ValueError("EMAIL_FROM is required when email authentication is enabled")
            if self.email_provider == "test" and self.app_env != "test":
                raise ValueError("EMAIL_PROVIDER=test is allowed only when APP_ENV=test")
            if self.email_provider == "smtp" and not self.smtp_host:
                raise ValueError("SMTP_HOST is required for the SMTP email provider")
            if self.app_env == "production":
                if not self.smtp_username or not self.smtp_password:
                    raise ValueError(
                        "SMTP credentials are required for production email authentication"
                    )
                if self.smtp_security == "none":
                    raise ValueError("Encrypted SMTP is required in production")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None cookies must also be Secure")
        if "*" in self.cors_origin_list:
            raise ValueError("Wildcard CORS origins are forbidden when credentials are enabled")
        if self.max_request_body_bytes < self.max_upload_bytes:
            raise ValueError("MAX_REQUEST_BODY_BYTES cannot be smaller than MAX_UPLOAD_BYTES")
        for origin in self.cors_origin_list:
            if not self._is_exact_origin(origin, require_https=False):
                raise ValueError("CORS_ORIGINS must contain exact HTTP(S) origins")
        return self

    def _validate_document_ingestion_settings(self) -> None:
        if self.document_ingestion_retry_base_seconds > self.document_ingestion_retry_max_seconds:
            raise ValueError(
                "DOCUMENT_INGESTION_RETRY_BASE_SECONDS cannot exceed "
                "DOCUMENT_INGESTION_RETRY_MAX_SECONDS"
            )
        if self.document_dispatch_lease_seconds >= self.document_reconciliation_stale_seconds:
            raise ValueError(
                "DOCUMENT_DISPATCH_LEASE_SECONDS must be shorter than "
                "DOCUMENT_RECONCILIATION_STALE_SECONDS"
            )
        if self.document_deletion_retry_base_seconds > self.document_deletion_retry_max_seconds:
            raise ValueError(
                "DOCUMENT_DELETION_RETRY_BASE_SECONDS cannot exceed "
                "DOCUMENT_DELETION_RETRY_MAX_SECONDS"
            )
        if self.document_deletion_lease_seconds >= self.document_deletion_stale_seconds:
            raise ValueError(
                "DOCUMENT_DELETION_LEASE_SECONDS must be shorter than "
                "DOCUMENT_DELETION_STALE_SECONDS"
            )
        if self.document_retention_enabled:
            required_retention = {
                "DOCUMENT_RETENTION_FAILED_RUN_DAYS": self.document_retention_failed_run_days,
                "DOCUMENT_RETENTION_CANCELLED_RUN_DAYS": (
                    self.document_retention_cancelled_run_days
                ),
                "DOCUMENT_RETENTION_SUPERSEDED_RUN_DAYS": (
                    self.document_retention_superseded_run_days
                ),
                "DOCUMENT_RETENTION_JOB_DAYS": self.document_retention_job_days,
                "DOCUMENT_RETENTION_MALWARE_EVENT_DAYS": (
                    self.document_retention_malware_event_days
                ),
                "DOCUMENT_RETENTION_TOMBSTONE_DAYS": (self.document_retention_tombstone_days),
                "DOCUMENT_RETENTION_STALE_WORKSPACE_HOURS": (
                    self.document_retention_stale_workspace_hours
                ),
            }
            missing = sorted(name for name, value in required_retention.items() if value is None)
            if missing:
                raise ValueError(
                    "Document retention requires explicit approved values for: "
                    + ", ".join(missing)
                )
        if self.document_orphan_cleanup_enabled and self.document_orphan_minimum_age_hours is None:
            raise ValueError(
                "DOCUMENT_ORPHAN_MINIMUM_AGE_HOURS is required when orphan cleanup is enabled"
            )
        if self.document_max_archive_compressed_bytes > self.max_upload_bytes:
            raise ValueError("DOCUMENT_MAX_ARCHIVE_COMPRESSED_BYTES cannot exceed MAX_UPLOAD_BYTES")
        if self.document_max_archive_entry_bytes > self.document_max_archive_uncompressed_bytes:
            raise ValueError(
                "DOCUMENT_MAX_ARCHIVE_ENTRY_BYTES cannot exceed "
                "DOCUMENT_MAX_ARCHIVE_UNCOMPRESSED_BYTES"
            )
        if self.document_max_csv_columns > self.document_max_spreadsheet_columns:
            raise ValueError(
                "DOCUMENT_MAX_CSV_COLUMNS cannot exceed DOCUMENT_MAX_SPREADSHEET_COLUMNS"
            )
        if self.app_env == "development" and not self.document_ingestion_local_development:
            raise ValueError(
                "Document ingestion may be enabled only in production or test unless "
                "DOCUMENT_INGESTION_LOCAL_DEVELOPMENT is explicitly enabled"
            )
        if not self.sqlalchemy_database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use PostgreSQL when document ingestion is enabled")
        runtime_only_development = (
            self.document_ingestion_local_development and not self.direct_database_url
        )
        if not self.direct_database_url and not (
            runtime_only_development and self.database_migration_role_name
        ):
            raise ValueError("DIRECT_DATABASE_URL is required when document ingestion is enabled")
        if not self.sqlalchemy_migration_url.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DIRECT_DATABASE_URL must use PostgreSQL when document ingestion is enabled"
            )
        if not runtime_only_development and (
            self.sqlalchemy_database_url == self.sqlalchemy_migration_url
        ):
            raise ValueError(
                "Document ingestion requires separate runtime and migration database URLs"
            )
        migration_role = (
            self.database_migration_role_name
            if runtime_only_development
            else self.database_migration_role
        )
        if self.direct_database_url and self.database_migration_role_name and (
            self.database_migration_role_name != self.database_migration_role
        ):
            raise ValueError("DATABASE_MIGRATION_ROLE_NAME must match DIRECT_DATABASE_URL")
        if not self.database_runtime_role or not migration_role:
            raise ValueError("Document ingestion database URLs must include database roles")
        if self.database_runtime_role == migration_role:
            raise ValueError(
                "Document ingestion requires separate runtime and migration database roles"
            )
        if self.app_env == "production":
            if not self._is_neon_database_url(self.sqlalchemy_database_url, pooled=True):
                raise ValueError("DATABASE_URL must use a pooled Neon endpoint for ingestion")
            if not self._is_neon_database_url(self.sqlalchemy_migration_url, pooled=False):
                raise ValueError(
                    "DIRECT_DATABASE_URL must use a direct Neon endpoint for ingestion"
                )
        if self.storage_backend != "s3":
            raise ValueError("STORAGE_BACKEND=s3 is required for document ingestion")
        if self.tasks_eager:
            raise ValueError("TASKS_EAGER must be false for document ingestion")
        if self.auto_create_tables:
            raise ValueError("AUTO_CREATE_TABLES must be false for document ingestion")
        if self.document_ingestion_local_development:
            parts = urlsplit(self.redis_url)
            if (
                parts.scheme not in {"redis", "rediss"}
                or not parts.hostname
                or any(character.isspace() for character in parts.hostname)
                or parts.fragment
                or not parts.password
            ):
                raise ValueError(
                    "Local ingestion requires an authenticated redis:// or rediss:// URL"
                )
        elif not self._is_release_redis_url(self.redis_url):
            raise ValueError(
                "REDIS_URL must be a non-local redis:// or rediss:// URL for document ingestion"
            )
        if self.embedding_provider != "fastembed":
            raise ValueError("EMBEDDING_PROVIDER must be fastembed for document ingestion")
        if self.embedding_model != "BAAI/bge-small-en-v1.5":
            raise ValueError(
                "EMBEDDING_MODEL must be BAAI/bge-small-en-v1.5 for document ingestion"
            )
        if self.embedding_dimensions != 384:
            raise ValueError("EMBEDDING_DIMENSIONS must be 384 for document ingestion")
        if not self.embedding_model_revision:
            raise ValueError("EMBEDDING_MODEL_REVISION is required for document ingestion")
        if not self.embedding_model_manifest_sha256:
            raise ValueError("EMBEDDING_MODEL_MANIFEST_SHA256 is required for document ingestion")
        if self.embedding_formatting_version != "bge-small-en-v1.5-format-v1":
            raise ValueError(
                "EMBEDDING_FORMATTING_VERSION must use the approved BGE formatting policy"
            )
        if not self.embedding_tokenizer_revision or not self.embedding_tokenizer_sha256:
            raise ValueError("Pinned tokenizer revision and checksum are required")
        if self.embedding_tokenizer_revision != self.embedding_model_revision:
            raise ValueError("Tokenizer and embedding model revisions must match")
        if self.embedding_max_concurrent_batches != 1:
            raise ValueError(
                "EMBEDDING_MAX_CONCURRENT_BATCHES must be 1 until release capacity is approved"
            )
        if self.document_chunk_overlap_tokens >= self.document_chunk_target_tokens:
            raise ValueError(
                "DOCUMENT_CHUNK_OVERLAP_TOKENS must be smaller than DOCUMENT_CHUNK_TARGET_TOKENS"
            )
        if self.document_chunk_target_tokens > self.document_chunk_max_tokens:
            raise ValueError("DOCUMENT_CHUNK_TARGET_TOKENS cannot exceed DOCUMENT_CHUNK_MAX_TOKENS")
        if self.document_chunk_max_tokens + self.document_chunk_formatting_headroom_tokens > 512:
            raise ValueError(
                "DOCUMENT_CHUNK_MAX_TOKENS plus DOCUMENT_CHUNK_FORMATTING_HEADROOM_TOKENS "
                "must not exceed 512"
            )
        if not self._is_absolute_runtime_path(self.embedding_model_path):
            raise ValueError("EMBEDDING_MODEL_PATH must be an absolute path")
        if not self.ocr_enabled:
            raise ValueError("OCR_ENABLED must be true for document ingestion")
        if self.ocr_languages != "eng":
            raise ValueError("OCR_LANGUAGES must be eng for the initial document release")
        if self.ocr_max_temporary_bytes < self.ocr_max_output_bytes:
            raise ValueError("OCR_MAX_TEMPORARY_BYTES cannot be smaller than OCR_MAX_OUTPUT_BYTES")
        if not self.malware_scan_required:
            raise ValueError("MALWARE_SCAN_REQUIRED must be true for document ingestion")
        if not self._is_valid_service_host(self.clamav_host):
            raise ValueError("CLAMAV_HOST is required and must be a host name or IP address")
        if not self._is_absolute_runtime_path(self.document_processing_temp_root):
            raise ValueError("DOCUMENT_PROCESSING_TEMP_ROOT must be an absolute path")
        if self._is_filesystem_root(self.document_processing_temp_root):
            raise ValueError("DOCUMENT_PROCESSING_TEMP_ROOT cannot be a filesystem root")

    def _validate_oidc_settings(self) -> None:
        required = {
            "OIDC_ISSUER": self.oidc_issuer,
            "OIDC_AUDIENCE": self.oidc_audience,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
            "PUBLIC_UI_URL": self.public_ui_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"SSO configuration is incomplete: {', '.join(missing)}")
        if len(self.oidc_state_secret.encode("utf-8")) < 32:
            raise ValueError("OIDC_STATE_SECRET must contain at least 32 bytes")
        if any(
            compare_digest(self.oidc_state_secret, secret)
            for secret in (self.auth_jwt_secret, self.auth_audit_secret)
        ):
            raise ValueError("OIDC_STATE_SECRET must be independent from authentication secrets")
        approved_algorithms = {
            "RS256",
            "RS384",
            "RS512",
            "PS256",
            "PS384",
            "PS512",
            "ES256",
            "ES384",
        }
        if not self.oidc_algorithms or not set(self.oidc_algorithms) <= approved_algorithms:
            raise ValueError("OIDC_ALGORITHMS must contain only approved asymmetric algorithms")
        if not self.oidc_provider_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "OIDC_PROVIDER_ID must contain only letters, numbers, hyphens, or underscores"
            )
        if not self.oidc_tenant_claim.strip() or not self.oidc_email_claim.strip():
            raise ValueError("OIDC tenant and email claim names are required")
        if "openid" not in self.oidc_scope_list:
            raise ValueError("OIDC_SCOPES must include openid")

        issuer = urlsplit(self.oidc_issuer or "")
        redirect = urlsplit(self.oidc_redirect_uri or "")
        discovery = urlsplit(self.oidc_discovery_endpoint)
        public_ui = urlsplit(self.public_ui_url or "")
        for name, parts in (
            ("OIDC_ISSUER", issuer),
            ("OIDC_DISCOVERY_URL", discovery),
            ("OIDC_REDIRECT_URI", redirect),
        ):
            if (
                parts.scheme not in {"http", "https"}
                or not parts.netloc
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
            ):
                raise ValueError(
                    f"{name} must be an absolute HTTP(S) URL without credentials or query"
                )
        if issuer.path.endswith("/") and issuer.path != "/":
            raise ValueError("OIDC_ISSUER must not end with a slash")
        if redirect.path != f"{self.api_v1_prefix}/auth/sso/callback":
            raise ValueError("OIDC_REDIRECT_URI must use the configured SSO callback path")
        if (
            public_ui.scheme not in {"http", "https"}
            or not public_ui.netloc
            or public_ui.username
            or public_ui.password
            or public_ui.path not in {"", "/"}
            or public_ui.query
            or public_ui.fragment
        ):
            raise ValueError("PUBLIC_UI_URL must be an exact HTTP(S) origin for SSO")
        public_ui_origin = f"{public_ui.scheme}://{public_ui.netloc}"
        if public_ui_origin not in self.cors_origin_list:
            raise ValueError("PUBLIC_UI_URL origin must be present in CORS_ORIGINS for SSO")
        for path in self.oidc_return_path_list:
            parts = urlsplit(path)
            if (
                len(path) > 255
                or not path.startswith("/")
                or parts.scheme
                or parts.netloc
                or parts.query
                or parts.fragment
                or any(character not in "/_-" and not character.isalnum() for character in path)
            ):
                raise ValueError("OIDC_ALLOWED_RETURN_PATHS contains an unsafe relative path")
        if self.app_env == "production":
            if any(parts.scheme != "https" for parts in (issuer, discovery, redirect)):
                raise ValueError("OIDC endpoints must use HTTPS in production")
            if not self.oidc_client_secret:
                raise ValueError("OIDC_CLIENT_SECRET is required for production SSO")
            if not self.oidc_provider_tenant_id:
                raise ValueError("OIDC_PROVIDER_TENANT_ID is required for production SSO")
            if not all(
                (self.oidc_authorization_endpoint, self.oidc_token_endpoint, self.oidc_jwks_url)
            ):
                raise ValueError("Production SSO must pin authorization, token, and JWKS endpoints")
        if self.auth_cookie_samesite != "lax":
            raise ValueError("OIDC authorization code flow requires AUTH_COOKIE_SAMESITE=lax")
        for name, value in (
            ("OIDC_AUTHORIZATION_ENDPOINT", self.oidc_authorization_endpoint),
            ("OIDC_TOKEN_ENDPOINT", self.oidc_token_endpoint),
            ("OIDC_JWKS_URL", self.oidc_jwks_url),
        ):
            if not value:
                continue
            parts = urlsplit(value)
            if (
                parts.scheme not in {"http", "https"}
                or not parts.netloc
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
                or (self.app_env == "production" and parts.scheme != "https")
            ):
                raise ValueError(f"{name} must be a pinned absolute endpoint URL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def forwarded_allow_ip_list(self) -> list[str]:
        return [value.strip() for value in self.forwarded_allow_ips.split(",") if value.strip()]

    @property
    def oidc_discovery_endpoint(self) -> str:
        return self.oidc_discovery_url or (
            f"{(self.oidc_issuer or '').rstrip('/')}/.well-known/openid-configuration"
        )

    @property
    def oidc_scope_list(self) -> list[str]:
        return [value for value in self.oidc_scopes.split() if value]

    @property
    def oidc_return_path_list(self) -> list[str]:
        return [
            value.strip() for value in self.oidc_allowed_return_paths.split(",") if value.strip()
        ]

    @staticmethod
    def _is_exact_origin(value: str, *, require_https: bool) -> bool:
        parts = urlsplit(value)
        allowed_schemes = {"https"} if require_https else {"http", "https"}
        return bool(
            parts.scheme in allowed_schemes
            and parts.netloc
            and not parts.username
            and not parts.password
            and not parts.path
            and not parts.query
            and not parts.fragment
        )

    @staticmethod
    def _is_ip_network(value: str) -> bool:
        try:
            ip_network(value, strict=False)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_neon_database_url(value: str, *, pooled: bool) -> bool:
        hostname = (urlsplit(value).hostname or "").casefold()
        if not hostname.endswith(".neon.tech"):
            return False
        return ("-pooler." in hostname) is pooled

    @staticmethod
    def _is_release_redis_url(value: str) -> bool:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"redis", "rediss"}
            or not parts.hostname
            or parts.fragment
            or any(character.isspace() for character in parts.hostname)
        ):
            return False
        hostname = parts.hostname.casefold()
        if hostname in {"localhost", "localhost.localdomain"}:
            return False
        try:
            return not ip_address(hostname).is_loopback
        except ValueError:
            return True

    @staticmethod
    def _is_absolute_runtime_path(value: str) -> bool:
        return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()

    @staticmethod
    def _is_filesystem_root(value: str) -> bool:
        for candidate in (PurePosixPath(value), PureWindowsPath(value)):
            if candidate.is_absolute() and candidate.parent == candidate:
                return True
        return False

    @staticmethod
    def _is_valid_service_host(value: str | None) -> bool:
        if not value or value != value.strip():
            return False
        if any(character.isspace() for character in value):
            return False
        return not any(marker in value for marker in ("://", "/", "@", "?", "#"))

    def _is_storage_endpoint(self, value: str) -> bool:
        parts = urlsplit(value)
        if (
            not parts.netloc
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            return False
        if parts.scheme == "https":
            return True
        return bool(
            self.app_env != "production"
            and parts.scheme == "http"
            and parts.hostname in {"localhost", "127.0.0.1", "::1"}
        )

    @staticmethod
    def _is_valid_bucket_name(value: str) -> bool:
        if not 3 <= len(value) <= 63 or value.startswith("-") or value.endswith("-"):
            return False
        return all(
            character.islower() or character.isdigit() or character in ".-" for character in value
        )

    @staticmethod
    def _database_url_requires_tls(value: str) -> bool:
        tls_value = dict(parse_qsl(urlsplit(value).query)).get("ssl", "").casefold()
        return tls_value in {"require", "verify-ca", "verify-full", "true"}

    @staticmethod
    def _as_async_sqlalchemy_url(value: str) -> str:
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+asyncpg://", 1)
        elif value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)

        if not value.startswith("postgresql+asyncpg://"):
            return value

        parts = urlsplit(value)
        query = []
        for key, item in parse_qsl(parts.query):
            if key == "channel_binding":
                continue
            query.append(("ssl" if key == "sslmode" else key, item))
        return urlunsplit(parts._replace(query=urlencode(query)))

    @property
    def sqlalchemy_database_url(self) -> str:
        return self._as_async_sqlalchemy_url(self.database_url)

    @property
    def sqlalchemy_migration_url(self) -> str:
        return self._as_async_sqlalchemy_url(self.direct_database_url or self.database_url)

    @staticmethod
    def _database_role(value: str | None) -> str | None:
        if not value:
            return None
        username = urlsplit(value).username
        return unquote(username) if username else None

    @property
    def database_runtime_role(self) -> str | None:
        return self._database_role(self.database_url)

    @property
    def database_migration_role(self) -> str | None:
        return self._database_role(self.direct_database_url or self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
