"""Restore an audited completed run using runtime credentials and explicit IDs."""

import argparse
import asyncio
from uuid import UUID

from app.db.session import SessionLocal, engine
from app.services.ingestion.repository import DocumentScope, VectorPersistenceRepository


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tenant", "project", "document", "target-run", "expected-active-run"):
        parser.add_argument("--" + name, type=UUID, required=True)
    parser.add_argument("--apply", action="store_true", help="Apply this explicit rollback")
    args = parser.parse_args()
    if not args.apply:
        print("No change made. Supply --apply after reviewing the explicit document and run IDs.")
        return
    try:
        await VectorPersistenceRepository(SessionLocal).restore_completed_run(
            DocumentScope(args.tenant, args.project, args.document),
            args.target_run,
            expected_active_run_id=args.expected_active_run,
        )
        print("Restored completed run; all historical rows retained.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
