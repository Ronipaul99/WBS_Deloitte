import asyncio
from uuid import UUID

from celery import Celery

from app.core.config import get_settings
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
)


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
