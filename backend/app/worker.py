import asyncio
from uuid import UUID

from celery import Celery

from app.core.config import get_settings
from app.services.document_lifecycle import process_document_deletion
from app.services.document_maintenance import (
    reconcile_document_lifecycle,
    recover_document_deletion_dispatches,
)
from app.services.external_summary_import import reconcile_imports
from app.services.external_summary_submission import process_submission, reconcile_submissions
from app.services.external_summary_tracking import reconcile_tracking
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

if settings.external_summary_enabled:
    celery_app.conf.beat_schedule["reconcile-external-summary-submissions"] = {
        "task": "wbs.reconcile_external_summary_submissions",
        "schedule": 60.0,
    }
    celery_app.conf.beat_schedule["reconcile-external-summary-tracking"] = {
        "task": "wbs.reconcile_external_summary_tracking",
        "schedule": 60.0,
    }
    celery_app.conf.beat_schedule["reconcile-external-summary-imports"] = {
        "task": "wbs.reconcile_external_summary_imports",
        "schedule": 60.0,
    }


@celery_app.task(name="wbs.reconcile_external_summary_imports")
def reconcile_external_summary_imports_task() -> None:
    asyncio.run(reconcile_imports())


@celery_app.task(name="wbs.reconcile_external_summary_tracking")
def reconcile_external_summary_tracking_task() -> None:
    asyncio.run(reconcile_tracking())


@celery_app.task(name="wbs.submit_external_summary", acks_late=True, reject_on_worker_lost=True)
def submit_external_summary_task(tenant_id: str, request_id: str) -> None:
    asyncio.run(process_submission(UUID(tenant_id), UUID(request_id)))


@celery_app.task(name="wbs.reconcile_external_summary_submissions")
def reconcile_external_summary_submissions_task() -> None:
    asyncio.run(reconcile_submissions(settings=settings))


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
