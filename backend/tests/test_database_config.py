from app.core.config import Settings


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
