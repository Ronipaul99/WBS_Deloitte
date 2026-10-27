import asyncio
from uuid import UUID

from celery import Celery

from app.core.config import get_settings
from app.services.document_lifecycle import process_document_deletion
from app.services.document_maintenance import (
    reconcile_document_lifecycle,
    recover_document_deletion_dispatches,
)
from app.services.ingestion.orchestrator import build_release_orchestrator
from app.services.ingestion.reconciliation import reconcile_ingestion_dispatches
from app.services.workflows import (
    process_document_summary,
    process_export,
    process_validation,
    process_wbs_generation,
)

settings = get_settings()
celery_app = Celery("wbs", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
celery_app.conf.beat_schedule = {
    "reconcile-document-ingestion": {
        "task": "wbs.reconcile_document_ingestion",
        "schedule": 60.0,
    },
    "reconcile-document-lifecycle": {
        "task": "wbs.reconcile_document_lifecycle",
        "schedule": 300.0,
    },
    "recover-document-deletions": {
        "task": "wbs.recover_document_deletions",
        "schedule": 60.0,
    },
}

# No second scheduler or worker service. Disabled installs no new periodic work.
if settings.agentic_summary_enabled:
    celery_app.conf.worker_concurrency = 1
    celery_app.conf.beat_schedule["reconcile-agent-workflows"] = {
        "task": "wbs.reconcile_agent_workflows",
        "schedule": 30.0,
    }


@celery_app.task(name="wbs.advance_agent_workflow", acks_late=True, reject_on_worker_lost=True)
def advance_agent_workflow_task(run_id: str, delivery_id: str) -> None:
    from app.services.agents.worker_runtime import advance

    asyncio.run(advance(settings, UUID(run_id), UUID(delivery_id)))


@celery_app.task(name="wbs.reconcile_agent_workflows")
def reconcile_agent_workflows_task() -> None:
    from app.services.agents.worker_runtime import reconcile

    asyncio.run(reconcile(settings))


@celery_app.task(
    name="wbs.test_agent_connection", acks_late=True, reject_on_worker_lost=True, ignore_result=True
)
def test_agent_connection_task(request_id: str) -> None:
    from app.services.llm.test_worker import run_test, with_worker_sessions

    asyncio.run(
        with_worker_sessions(
            settings, lambda sessions: run_test(sessions, settings, UUID(request_id))
        )
    )


if settings.llm_connection_tests_enabled:
    celery_app.conf.worker_concurrency = 1
    celery_app.conf.beat_schedule["reconcile-llm-connection-tests"] = {
        "task": "wbs.reconcile_llm_connection_tests",
        "schedule": 15.0,
    }


@celery_app.task(name="wbs.reconcile_llm_connection_tests")
def reconcile_llm_connection_tests_task() -> None:
    from app.services.llm.test_worker import (
        celery_test_broker,
        reconcile_tests,
        with_worker_sessions,
    )

    async def publish(task, args, identity):
        await celery_test_broker(celery_app, task, args, identity)

    asyncio.run(
        with_worker_sessions(
            settings, lambda sessions: reconcile_tests(sessions, settings, publish)
        )
    )


@celery_app.task(
    name="wbs.process_document_ingestion",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=settings.document_processing_timeout_seconds,
    time_limit=settings.document_processing_timeout_seconds + 30,
)
def process_document_ingestion_task(job_id: str, processing_run_id: str) -> None:
    asyncio.run(build_release_orchestrator(settings).run(UUID(job_id), UUID(processing_run_id)))


@celery_app.task(
    name="wbs.cleanup_document_deletion",
    acks_late=True,
    reject_on_worker_lost=True,
)
def cleanup_document_deletion_task(job_id: str, document_id: str) -> None:
    asyncio.run(process_document_deletion(UUID(job_id), UUID(document_id), settings=settings))


@celery_app.task(name="wbs.reconcile_document_ingestion")
def reconcile_document_ingestion_task() -> None:
    asyncio.run(reconcile_ingestion_dispatches(settings=settings))


@celery_app.task(name="wbs.reconcile_document_lifecycle")
def reconcile_document_lifecycle_task() -> None:
    apply_changes = settings.document_reconciliation_repairs_enabled
    asyncio.run(
        reconcile_document_lifecycle(
            tenant_id=None,
            apply_changes=apply_changes,
            approved=apply_changes,
            settings=settings,
        )
    )


@celery_app.task(name="wbs.recover_document_deletions")
def recover_document_deletions_task() -> None:
    asyncio.run(recover_document_deletion_dispatches(settings=settings))


@celery_app.task(name="wbs.generate_document_summary")
def generate_document_summary_task(job_id: str, document_id: str) -> None:
    asyncio.run(process_document_summary(UUID(job_id), UUID(document_id)))


@celery_app.task(name="wbs.generate_wbs")
def generate_wbs_task(job_id: str) -> None:
    asyncio.run(process_wbs_generation(UUID(job_id)))


@celery_app.task(name="wbs.validate_wbs")
def validate_wbs_task(validation_id: str) -> None:
    asyncio.run(process_validation(UUID(validation_id)))


@celery_app.task(name="wbs.export_wbs")
def export_wbs_task(export_id: str) -> None:
    asyncio.run(process_export(UUID(export_id)))
