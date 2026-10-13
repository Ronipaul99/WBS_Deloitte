from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "WBS Generator API"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./wbs.db"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
