from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "WBS Generator API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./wbs.db"
    direct_database_url: str | None = None
    database_use_null_pool: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_recycle_seconds: int = 300
    redis_url: str = "redis://localhost:6379/0"
    tasks_eager: bool = True
    auto_create_tables: bool = True
    upload_root: Path = Path(".data/uploads")
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_bytes: int = 25 * 1024 * 1024

    auth_mode: Literal["development", "oidc"] = "development"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])

    dev_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    dev_tenant_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
