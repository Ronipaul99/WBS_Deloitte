from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import BackgroundTasks

from app.core.config import get_settings
from app.services.workflows import (
    process_document_summary,
    process_export,
    process_validation,
    process_wbs_generation,
)
from app.worker import (
    export_wbs_task,
    generate_document_summary_task,
    generate_wbs_task,
    validate_wbs_task,
)

settings = get_settings()


def _dispatch(
    background_tasks: BackgroundTasks,
    local_handler: Callable[..., Awaitable[None]],
    celery_handler: Callable[..., object],
    *args: UUID,
) -> None:
    if settings.tasks_eager:
        background_tasks.add_task(local_handler, *args)
    else:
        celery_handler.delay(*(str(value) for value in args))


def dispatch_summary(background_tasks: BackgroundTasks, job_id: UUID, document_id: UUID) -> None:
    _dispatch(
        background_tasks,
        process_document_summary,
        generate_document_summary_task,
        job_id,
        document_id,
    )


def dispatch_generation(background_tasks: BackgroundTasks, job_id: UUID) -> None:
    _dispatch(background_tasks, process_wbs_generation, generate_wbs_task, job_id)


def dispatch_validation(background_tasks: BackgroundTasks, validation_id: UUID) -> None:
    _dispatch(background_tasks, process_validation, validate_wbs_task, validation_id)


def dispatch_export(background_tasks: BackgroundTasks, export_id: UUID) -> None:
    _dispatch(background_tasks, process_export, export_wbs_task, export_id)
