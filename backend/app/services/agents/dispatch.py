"""ID-only Celery publication adapter; SQL outbox owns all delivery retries."""

import asyncio
from uuid import UUID

from app.services.agents.storage import TASK


def celery_publisher(app):
    async def publish(task, args, identity):
        if (
            task != TASK
            or len(args) != 2
            or str(UUID(args[1])) != identity
            or any(str(UUID(value)) != value for value in args)
        ):
            raise ValueError("invalid agent delivery")
        # Cancelling the wait cannot undo a broker acceptance. Stable delivery IDs
        # plus SQL fencing handle late/ambiguous publication; no hidden Kombu retry.
        async with asyncio.timeout(10):
            await asyncio.to_thread(
                app.send_task,
                task,
                args=list(args),
                task_id=identity,
                serializer="json",
                ignore_result=True,
                retry=False,
            )

    return publish
