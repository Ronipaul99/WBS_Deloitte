"""Seed all seven summary questions using the configured direct migration connection."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow execution from any working directory without changing the environment file.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.services.agents.question_bank import (  # noqa: E402
    prepare_question_rows,
    seed_question_rows,
    verify_question_rows,
)
from question_doc.embedding import build_provider  # noqa: E402
from question_doc.question_bank import (  # noqa: E402
    QUERY_PREFIX,
    QUESTION_SET_ID,
    QUESTIONS,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, help="Local checksum-verified model directory")
    parser.add_argument("--verify-only", action="store_true", help="Compare without writing rows")
    args = parser.parse_args()
    overrides = {}
    if args.model_path:
        overrides["embedding_model_path"] = str(args.model_path.resolve(strict=True))
    settings = Settings(_env_file=ROOT / "backend" / ".env", **overrides)
    if not settings.direct_database_url or not settings.sqlalchemy_migration_url.startswith(
        "postgresql+asyncpg://"
    ):
        raise ValueError("DIRECT_DATABASE_URL must target the PostgreSQL migration role")
    provider = build_provider(settings)
    rows = await asyncio.to_thread(
        prepare_question_rows,
        QUESTION_SET_ID,
        QUESTIONS,
        provider=provider,
        manifest_sha256=settings.embedding_model_manifest_sha256,
        query_prefix=QUERY_PREFIX,
    )
    print(f"Generated {len(rows)} normalized {provider.dimensions}-dimensional query embeddings")
    engine = create_async_engine(
        settings.sqlalchemy_migration_url,
        poolclass=NullPool,
        connect_args={"timeout": 20},
        hide_parameters=True,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                current_role = await session.scalar(text("SELECT current_user"))
                if (
                    current_role != settings.database_migration_role
                    or current_role == settings.database_runtime_role
                ):
                    raise ValueError(
                        "A separate migration role is required to seed shared questions"
                    )
            if args.verify_only:
                async with session.begin():
                    await verify_question_rows(session, rows)
                result = {"verified": len(rows)}
            else:
                seeded = await seed_question_rows(session, rows)
                result = {"inserted": seeded.inserted, "unchanged": seeded.unchanged}
            print(
                json.dumps(
                    {
                        "table": "rfp_question_bank",
                        "question_set_id": QUESTION_SET_ID,
                        "embedding_model": provider.model_name,
                        "embedding_model_revision": provider.model_revision,
                        **result,
                    }
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        # Do not expose database URLs, credentials, or bound vector values in traces.
        print(f"Question seed failed ({type(error).__name__})", file=sys.stderr)
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
