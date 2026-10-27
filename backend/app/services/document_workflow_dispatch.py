"""Durable publication for the summary/generation/validation attempts linked to a workflow."""

import logging
from datetime import timedelta
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import or_, select

from app.core.config import get_settings
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.document_workflows import WorkflowDispatch
from app.services.document_content import database_now, utc

logger = logging.getLogger(__name__)


async def enqueue_dispatch(db, workflow, *, kind, job_id=None, validation=None):
    dispatch = WorkflowDispatch(
        tenant_id=workflow.tenant_id,
        project_id=workflow.project_id,
        workflow_id=workflow.id,
        kind=kind,
        job_id=job_id,
        validation_id=validation.id if validation else None,
        wbs_version_id=validation.wbs_version_id if validation else None,
    )
    db.add(dispatch)
    await db.flush()
    return dispatch.id


async def publish_dispatch(
    tenant_id: UUID,
    dispatch_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    session_factory=SessionLocal,
) -> bool:
    # Imports stay here to avoid a worker/dispatcher import cycle.
    from app.models.domain import Job
    from app.services.dispatcher import dispatch_app

    settings = get_settings()
    from app.services.workflows import (
        process_document_summary,
        process_validation,
        process_wbs_generation,
    )

    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        record = await db.scalar(
            select(WorkflowDispatch)
            .where(
                WorkflowDispatch.id == dispatch_id,
                WorkflowDispatch.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if record is None or record.status == "PUBLISHED":
            return True
        now = await database_now(db)
        if record.lease_expires_at and utc(record.lease_expires_at) > now:
            return False
        record.attempts += 1
        attempt_number = record.attempts
        record.lease_expires_at = now + timedelta(seconds=60)
        kind = record.kind
        target = record.validation_id if kind == "validation" else record.job_id
        document_id = None
        if kind == "summary":
            job = await db.get(Job, target)
            document_id = UUID(job.request_payload["document_id"])
        await db.commit()
    handlers = {
        "summary": (process_document_summary, "wbs.generate_document_summary"),
        "generation": (process_wbs_generation, "wbs.generate_wbs"),
        "validation": (process_validation, "wbs.validate_wbs"),
    }
    handler, task_name = handlers[kind]
    args = [target, document_id] if kind == "summary" else [target]
    try:
        if settings.tasks_eager:
            background_tasks.add_task(handler, *args)
        else:
            dispatch_app.send_task(
                task_name,
                args=[str(value) for value in args],
                task_id=str(dispatch_id),
                serializer="json",
            )
    except Exception:
        logger.warning("Workflow task publication deferred to dispatch reconciliation")
        return False
    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        record = await db.get(WorkflowDispatch, dispatch_id, with_for_update=True)
        if record and record.attempts == attempt_number:
            record.status, record.lease_expires_at = "PUBLISHED", None
            await db.commit()
    return True


async def reconcile_dispatches(
    tenant_id: UUID, *, apply=False, limit=100, session_factory=SessionLocal
):
    if not 1 <= limit <= 1000:
        raise ValueError("Dispatch limit must be between 1 and 1000")
    async with session_factory() as db:
        await set_local_tenant_context(db, tenant_id)
        now = await database_now(db)
        ids = list(
            await db.scalars(
                select(WorkflowDispatch.id)
                .where(
                    WorkflowDispatch.tenant_id == tenant_id,
                    WorkflowDispatch.status == "PENDING",
                    or_(
                        WorkflowDispatch.lease_expires_at.is_(None),
                        WorkflowDispatch.lease_expires_at <= now,
                    ),
                )
                .order_by(WorkflowDispatch.created_at)
                .limit(limit)
            )
        )
    published = 0
    if apply:
        tasks = BackgroundTasks()
        for dispatch_id in ids:
            published += int(
                await publish_dispatch(
                    tenant_id, dispatch_id, tasks, session_factory=session_factory
                )
            )
        # Test/local eager tasks must actually execute; release mode publishes to Celery above.
        await tasks()
    return {"mode": "apply" if apply else "dry_run", "eligible": len(ids), "published": published}
