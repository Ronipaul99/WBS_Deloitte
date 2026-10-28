from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from sqlalchemy import text
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


async def set_local_tenant_context(session: AsyncSession, tenant_id: UUID | str) -> None:
    """Set the PostgreSQL RLS tenant only for the active transaction."""
    validated_tenant_id = UUID(str(tenant_id))
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not session.in_transaction():
        raise RuntimeError("Tenant context requires an active database transaction")
    await session.execute(text(f"SET LOCAL app.tenant_id = '{validated_tenant_id}'"))


async def ensure_tenant_transaction(session: AsyncSession, tenant_id: UUID | str) -> None:
    """Join a caller transaction or begin one, then apply transaction-local scope.

    The caller still owns commit/rollback. Never use this to span external I/O.
    Keep set_local_tenant_context strict for callers that own explicit transactions.
    """
    validated_tenant_id = UUID(str(tenant_id))
    if not session.in_transaction():
        await session.begin()
    await set_local_tenant_context(session, validated_tenant_id)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
