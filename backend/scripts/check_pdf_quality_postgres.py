"""Create, migrate, test, and remove a uniquely named disposable PostgreSQL DB.

Uses local migration/runtime credentials without logging or transferring them.
The existing configured database is only used to issue CREATE/DROP DATABASE.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings


def database_url(url, name):
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + name))


async def main():
    settings = Settings()
    if not settings.direct_database_url:
        raise ValueError("A migration connection is required")
    name = "wbs_pdf_quality_" + uuid4().hex
    assert re.fullmatch(r"wbs_pdf_quality_[0-9a-f]{32}", name)
    admin = create_async_engine(
        settings.sqlalchemy_migration_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        print("Created isolated test database:", name, flush=True)
        migration = database_url(settings.direct_database_url, name)
        runtime = database_url(settings.database_url, name)
        # These existing fixtures use normal connection pools. Test database/RLS
        # mechanics against the direct endpoint using the same restricted role;
        # pooled production connections have their own NullPool/name safeguards.
        parts = urlsplit(runtime)
        if (parts.hostname or "").endswith(".neon.tech"):
            prefix, separator, hostport = parts.netloc.rpartition("@")
            hostport = hostport.replace(parts.hostname, parts.hostname.replace("-pooler.", "."), 1)
            runtime = urlunsplit(parts._replace(netloc=prefix + separator + hostport))
        env = {
            **os.environ,
            "DATABASE_URL": runtime,
            "DIRECT_DATABASE_URL": migration,
            "DOCUMENT_INGESTION_ENABLED": "false",
            "DOCUMENT_INGESTION_LOCAL_DEVELOPMENT": "false",
        }
        for step in ("STEP3", "STEP10"):
            env[f"{step}_POSTGRES_MIGRATION_URL"] = migration
            env[f"{step}_POSTGRES_RUNTIME_URL"] = runtime
            env[f"{step}_POSTGRES_DISPOSABLE_ACK"] = "I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE"
        commands = [
            ["-m", "alembic", "upgrade", "head"],
            ["-m", "alembic", "downgrade", "d4e7b2c91a63"],
            ["-m", "alembic", "upgrade", "head"],
            [
                "-m",
                "pytest",
                "tests/test_pgvector_postgres.py",
                "tests/test_vector_persistence_postgres.py",
                "-q",
                "--tb=short",
            ],
        ]
        for command in commands:
            result = await asyncio.to_thread(subprocess.run, [sys.executable, *command], env=env)
            if result.returncode:
                raise RuntimeError("Disposable database validation failed")
    finally:
        if created:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
            print("Removed isolated test database:", name, flush=True)
        await admin.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("validation_error_type", type(error).__name__, flush=True)
        raise SystemExit(1) from None
