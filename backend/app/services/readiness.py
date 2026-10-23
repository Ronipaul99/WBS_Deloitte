from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def application_migration_heads() -> set[str]:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config()
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def database_migration_heads(db: AsyncSession) -> set[str]:
    result = await db.execute(text("SELECT version_num FROM alembic_version"))
    return {str(row[0]) for row in result}


async def database_is_at_migration_head(db: AsyncSession) -> bool:
    return await database_migration_heads(db) == application_migration_heads()
