from collections.abc import AsyncIterator
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def _engine_options() -> dict[str, object]:
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": settings.database_pool_recycle_seconds,
    }
    if settings.database_use_null_pool:
        options["poolclass"] = NullPool
        if settings.sqlalchemy_database_url.startswith("postgresql+asyncpg://"):
            options["connect_args"] = {
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__"
            }
    elif not settings.sqlalchemy_database_url.startswith("sqlite"):
        options["pool_size"] = settings.database_pool_size
        options["max_overflow"] = settings.database_max_overflow
    return options


engine = create_async_engine(settings.sqlalchemy_database_url, **_engine_options())
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
