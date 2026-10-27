from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from secrets import randbelow
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.observability import (
    record_ingestion_attempt,
    record_ingestion_queue_age,
    record_ingestion_stage,
    record_ingestion_stage_duration,
)
from app.db.session import SessionLocal, set_local_tenant_context
from app.models.domain import (
    DispatchStatus,
    Document,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    IngestionStage,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
)
from app.services.ingestion.chunk_types import ChunkingPolicy
from app.services.ingestion.chunking import DocumentChunker
from app.services.ingestion.embeddings.base import (
    EmbeddingPolicy,
    EmbeddingProvider,
    embed_canonical_chunks,
)
from app.services.ingestion.embeddings.fastembed_provider import get_process_embedding_provider
from app.services.ingestion.errors import (
    IngestionError,
    IngestionErrorCode,
    IngestionJobFailure,
    ingestion_error_to_job_failure,
)
from app.services.ingestion.input_preparation import prepare_document_input
from app.services.ingestion.registry import ExtractorRegistry, get_release_extractor_registry
from app.services.ingestion.release_identity import (
    RELEASE_CHUNKER_VERSION,
    release_extractor_identity,
)
from app.services.ingestion.repository import (
    PersistenceScope,
    ProcessingCounts,
    ProcessingIdentity,
    VectorPersistenceRepository,
)
from app.services.ingestion.scanning import ClamAVScanner, MalwareScanner
from app.services.ingestion.tokenizer import LocalBgeTokenizer
from app.services.ingestion.types import ExtractionLimits, confirmed_format_from_suffix
from app.services.storage import UploadObjectStorage, get_upload_storage

STAGE_PROGRESS = {
    IngestionStage.QUEUED: 0,
    IngestionStage.SCANNING: 10,
    IngestionStage.EXTRACTING: 30,
    IngestionStage.CHUNKING: 50,
    IngestionStage.EMBEDDING: 65,
    IngestionStage.PERSISTING: 80,
    IngestionStage.ACTIVATING: 95,
    IngestionStage.RETRY_WAIT: 95,
    IngestionStage.COMPLETED: 100,
    IngestionStage.FAILED: 100,
}


class OrchestrationDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    RETRY = "RETRY"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    disposition: OrchestrationDisposition
    attempt_count: int
    retry_after_seconds: int | None = None
    error_code: str | None = None
    job_id: UUID = field(repr=False, default=UUID(int=0))
    processing_run_id: UUID = field(repr=False, default=UUID(int=0))


@dataclass(frozen=True, slots=True)
class _WorkContext:
    tenant_id: UUID = field(repr=False)
    project_id: UUID = field(repr=False)
    document: Document = field(repr=False)
    job: Job = field(repr=False)
    run: DocumentProcessingRun = field(repr=False)
    attempt_count: int


@dataclass(frozen=True, slots=True)
class IngestionDependencies:
    settings: Settings = field(repr=False)
    storage: UploadObjectStorage = field(repr=False)
    scanner: MalwareScanner = field(repr=False)
    registry: ExtractorRegistry = field(repr=False)
    extraction_limits: ExtractionLimits = field(repr=False)
    chunker: DocumentChunker = field(repr=False)
    embedding_provider: EmbeddingProvider = field(repr=False)
    embedding_policy: EmbeddingPolicy = field(repr=False)
    persistence: VectorPersistenceRepository = field(repr=False)


class DocumentIngestionOrchestrator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        dependencies: IngestionDependencies,
    ) -> None:
        self._session_factory = session_factory
        self._dependencies = dependencies

    async def run(self, job_id: UUID, processing_run_id: UUID) -> OrchestrationResult:
        claimed = await self._claim(job_id, processing_run_id)
        if isinstance(claimed, OrchestrationResult):
            outcome = {
                OrchestrationDisposition.COMPLETED: "success",
                OrchestrationDisposition.DUPLICATE: "duplicate",
                OrchestrationDisposition.FAILED: "failed",
                OrchestrationDisposition.RETRY: "retry",
            }[claimed.disposition]
            record_ingestion_attempt(
                outcome=outcome,
                error_code=claimed.error_code or "none",
            )
            return claimed
        context = claimed
        record_ingestion_stage(stage=IngestionStage.SCANNING.value)
        try:
            result = await self._execute(context)
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            failure = ingestion_error_to_job_failure(exc)
            return await self._record_failure(context, failure)
        record_ingestion_attempt(outcome="success")
        return result

    async def _execute(self, context: _WorkContext) -> OrchestrationResult:
        dependencies = self._dependencies
        async with prepare_document_input(
            context.document,
            context.job,
            storage=dependencies.storage,
            scanner=dependencies.scanner,
            settings=dependencies.settings,
            processing_run=context.run,
        ) as trusted:
            confirmed_format = confirmed_format_from_suffix(trusted.suffix)
            await self._set_stage(context, IngestionStage.EXTRACTING)
            extractor = dependencies.registry.select(confirmed_format)
            expected_extractor = release_extractor_identity(confirmed_format)
            if (extractor.name, extractor.version) != expected_extractor:
                raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)
            extraction = extractor.extract(trusted.path, dependencies.extraction_limits)
            if extraction.source_content_sha256 != trusted.sha256:
                raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID)

            await self._set_stage(context, IngestionStage.CHUNKING)
            chunking = dependencies.chunker.chunk(extraction)
            if (
                chunking.source_content_sha256 != trusted.sha256
                or chunking.chunker_version != RELEASE_CHUNKER_VERSION
            ):
                raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)

            await self._set_stage(context, IngestionStage.EMBEDDING)
            embedded = embed_canonical_chunks(
                chunking.chunks,
                provider=dependencies.embedding_provider,
                policy=dependencies.embedding_policy,
            )
            identity = ProcessingIdentity(
                document_content_sha256=trusted.sha256,
                extractor_name=extraction.statistics.extractor_name,
                extractor_version=extraction.statistics.extractor_version,
                chunker_version=chunking.chunker_version,
                embedding_provider=embedded.metadata.provider_name,
                embedding_model=embedded.metadata.model_name,
                embedding_model_revision=embedded.metadata.model_revision,
                embedding_dimensions=embedded.metadata.dimensions,
                embedding_formatting_version=embedded.metadata.formatting_version,
            )
            counts = ProcessingCounts(
                page_count=extraction.statistics.page_count,
                worksheet_count=extraction.statistics.worksheet_count,
                block_count=extraction.statistics.block_count,
                chunk_count=len(embedded.items),
            )
            scope = PersistenceScope(
                context.tenant_id,
                context.project_id,
                context.document.id,
                context.job.id,
            )
            resolution = await dependencies.persistence.create_or_resolve_run(
                scope,
                identity,
                counts,
            )
            if resolution.run_id != context.run.id:
                raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)

            await self._set_stage(context, IngestionStage.PERSISTING)
            await dependencies.persistence.stage_embeddings(
                scope,
                context.run.id,
                embedded,
                identity,
            )
            await dependencies.persistence.reconcile_run(
                scope,
                context.run.id,
                embedded,
                identity,
            )
            await self._set_stage(context, IngestionStage.ACTIVATING)
            activation = await dependencies.persistence.activate_run(
                scope,
                context.run.id,
                embedded,
                identity,
                counts,
            )
            warning_codes = tuple(
                dict.fromkeys(
                    [code.value for code in extraction.statistics.warning_codes]
                    + [code.value for code in chunking.statistics.warning_codes]
                )
            )
            await self._complete(context, counts, warning_codes, activation.chunk_count)
            return OrchestrationResult(
                OrchestrationDisposition.COMPLETED,
                context.attempt_count,
                job_id=context.job.id,
                processing_run_id=context.run.id,
            )

    async def _claim(
        self,
        job_id: UUID,
        processing_run_id: UUID,
    ) -> _WorkContext | OrchestrationResult:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if job is None or job.job_type != JobType.DOCUMENT_INGESTION.value:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID)
                await set_local_tenant_context(session, job.tenant_id)
                run = await session.scalar(
                    select(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.id == processing_run_id,
                        DocumentProcessingRun.job_id == job.id,
                        DocumentProcessingRun.tenant_id == job.tenant_id,
                        DocumentProcessingRun.project_id == job.project_id,
                    )
                    .with_for_update()
                )
                if run is None or job.project_id is None:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID)
                document = await session.scalar(
                    select(Document)
                    .where(
                        Document.id == run.document_id,
                        Document.tenant_id == run.tenant_id,
                        Document.project_id == run.project_id,
                    )
                    .with_for_update()
                )
                if document is None:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID)
                if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value:
                    return OrchestrationResult(
                        OrchestrationDisposition.FAILED,
                        run.attempt_count,
                        error_code=IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT.value,
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                if run.status == DocumentProcessingStatus.COMPLETED.value:
                    run.current_stage = IngestionStage.COMPLETED.value
                    run.last_heartbeat_at = now
                    self._complete_job_from_run(job, run)
                    return OrchestrationResult(
                        OrchestrationDisposition.COMPLETED,
                        run.attempt_count,
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                if job.status == ProcessingStatus.CANCELLED.value:
                    return OrchestrationResult(
                        OrchestrationDisposition.FAILED,
                        run.attempt_count,
                        error_code=IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT.value,
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                if run.status == DocumentProcessingStatus.IN_PROGRESS.value:
                    return OrchestrationResult(
                        OrchestrationDisposition.DUPLICATE,
                        run.attempt_count,
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                if run.status != DocumentProcessingStatus.QUEUED.value:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT)
                run.attempt_count += 1
                job.attempt_count = run.attempt_count
                run.status = DocumentProcessingStatus.IN_PROGRESS.value
                run.current_stage = IngestionStage.SCANNING.value
                run.started_at = run.started_at or now
                run.last_heartbeat_at = now
                run.error_code = None
                run.error_message = None
                job.status = ProcessingStatus.IN_PROGRESS.value
                job.current_step = IngestionStage.SCANNING.value
                job.progress = max(job.progress, STAGE_PROGRESS[IngestionStage.SCANNING])
                job.error_code = None
                job.error_message = None
                document.processing_status = DocumentProcessingStatus.IN_PROGRESS.value
                document.processing_error_code = None
                record_ingestion_queue_age(
                    duration_seconds=(now - self._as_utc(job.created_at)).total_seconds()
                )
                return _WorkContext(
                    job.tenant_id,
                    job.project_id,
                    document,
                    job,
                    run,
                    run.attempt_count,
                )

    async def _set_stage(self, context: _WorkContext, stage: IngestionStage) -> None:
        progress = STAGE_PROGRESS[stage]
        now = datetime.now(UTC)
        previous_stage = IngestionStage.QUEUED.value
        duration_seconds = 0.0
        async with self._session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, context.tenant_id)
                job = await session.scalar(
                    select(Job)
                    .where(
                        Job.id == context.job.id,
                        Job.tenant_id == context.tenant_id,
                        Job.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                run = await session.scalar(
                    select(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.id == context.run.id,
                        DocumentProcessingRun.job_id == context.job.id,
                        DocumentProcessingRun.tenant_id == context.tenant_id,
                        DocumentProcessingRun.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                if job is None or run is None:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)
                if (
                    job.status != ProcessingStatus.IN_PROGRESS.value
                    or run.status != DocumentProcessingStatus.IN_PROGRESS.value
                ):
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT)
                previous_stage = run.current_stage or IngestionStage.QUEUED.value
                if run.last_heartbeat_at is not None:
                    duration_seconds = (now - self._as_utc(run.last_heartbeat_at)).total_seconds()
                job.progress = max(job.progress, progress)
                job.current_step = stage.value
                run.current_stage = stage.value
                run.last_heartbeat_at = now
        record_ingestion_stage_duration(
            stage=previous_stage,
            duration_seconds=duration_seconds,
        )
        record_ingestion_stage(stage=stage.value)

    async def _complete(
        self,
        context: _WorkContext,
        counts: ProcessingCounts,
        warning_codes: tuple[str, ...],
        persisted_count: int,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, context.tenant_id)
                job = await session.scalar(
                    select(Job)
                    .where(
                        Job.id == context.job.id,
                        Job.tenant_id == context.tenant_id,
                        Job.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                run = await session.scalar(
                    select(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.id == context.run.id,
                        DocumentProcessingRun.job_id == context.job.id,
                        DocumentProcessingRun.tenant_id == context.tenant_id,
                        DocumentProcessingRun.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document)
                    .where(
                        Document.id == context.document.id,
                        Document.tenant_id == context.tenant_id,
                        Document.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                if (
                    job is None
                    or run is None
                    or document is None
                    or document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value
                    or run.status != DocumentProcessingStatus.COMPLETED.value
                    or persisted_count != counts.chunk_count
                ):
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_INCONSISTENT)
                run.current_stage = IngestionStage.COMPLETED.value
                run.last_heartbeat_at = now
                run.warning_codes = list(warning_codes)
                self._complete_job_from_run(job, run)
        record_ingestion_stage(stage=IngestionStage.COMPLETED.value)

    @staticmethod
    def _complete_job_from_run(job: Job, run: DocumentProcessingRun) -> None:
        job.status = ProcessingStatus.COMPLETED.value
        job.progress = 100
        job.current_step = IngestionStage.COMPLETED.value
        job.error_code = None
        job.error_message = None
        job.result_payload = {
            "document_id": str(run.document_id),
            "processing_run_id": str(run.id),
            "chunk_count": run.chunk_count,
        }

    async def _record_failure(
        self,
        context: _WorkContext,
        failure: IngestionJobFailure,
    ) -> OrchestrationResult:
        attempts_exhausted = (
            context.attempt_count >= self._dependencies.settings.document_ingestion_max_attempts
        )
        retryable = failure.retryable and not attempts_exhausted
        retry_delay = self._retry_delay(context.attempt_count) if retryable else None
        stage = IngestionStage.RETRY_WAIT if retryable else IngestionStage.FAILED
        status = ProcessingStatus.QUEUED if retryable else ProcessingStatus.FAILED
        run_status = (
            DocumentProcessingStatus.QUEUED if retryable else DocumentProcessingStatus.FAILED
        )
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await set_local_tenant_context(session, context.tenant_id)
                job = await session.scalar(
                    select(Job)
                    .where(
                        Job.id == context.job.id,
                        Job.tenant_id == context.tenant_id,
                        Job.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                run = await session.scalar(
                    select(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.id == context.run.id,
                        DocumentProcessingRun.job_id == context.job.id,
                        DocumentProcessingRun.tenant_id == context.tenant_id,
                        DocumentProcessingRun.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                document = await session.scalar(
                    select(Document)
                    .where(
                        Document.id == context.document.id,
                        Document.tenant_id == context.tenant_id,
                        Document.project_id == context.project_id,
                    )
                    .with_for_update()
                )
                if job is None or run is None or document is None:
                    raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_SCOPE_INVALID)
                if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value:
                    if run.status != DocumentProcessingStatus.COMPLETED.value:
                        run.status = DocumentProcessingStatus.CANCELLED.value
                        run.current_stage = IngestionStage.FAILED.value
                        run.error_code = "DOCUMENT_DELETION_REQUESTED"
                        run.error_message = (
                            "Document ingestion stopped because deletion was requested."
                        )
                    job.status = ProcessingStatus.CANCELLED.value
                    job.current_step = IngestionStage.FAILED.value
                    job.error_code = "DOCUMENT_DELETION_REQUESTED"
                    job.error_message = "Document ingestion stopped because deletion was requested."
                    return OrchestrationResult(
                        OrchestrationDisposition.FAILED,
                        context.attempt_count,
                        error_code="DOCUMENT_DELETION_REQUESTED",
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                if run.status == DocumentProcessingStatus.COMPLETED.value:
                    run.current_stage = IngestionStage.COMPLETED.value
                    run.last_heartbeat_at = now
                    self._complete_job_from_run(job, run)
                    return OrchestrationResult(
                        OrchestrationDisposition.COMPLETED,
                        context.attempt_count,
                        job_id=job.id,
                        processing_run_id=run.id,
                    )
                job.status = status.value
                job.current_step = stage.value
                job.error_code = failure.error_code
                job.error_message = failure.message
                job.result_payload = {
                    "document_id": str(document.id),
                    "processing_run_id": str(run.id),
                    "attempt_count": context.attempt_count,
                }
                run.status = run_status.value
                run.current_stage = stage.value
                run.error_code = failure.error_code
                run.error_message = failure.message[:500]
                run.last_heartbeat_at = now
                if not retryable:
                    run.failed_at = now
                document.processing_status = run_status.value
                document.processing_error_code = failure.error_code
                if failure.error_code == "DOCUMENT_REJECTED_MALWARE":
                    from app.services.document_content import record_content_rejection

                    await record_content_rejection(session, document, failure.error_code)
                if retryable:
                    outbox = await session.scalar(
                        select(JobDispatchOutbox)
                        .where(
                            JobDispatchOutbox.tenant_id == context.tenant_id,
                            JobDispatchOutbox.project_id == context.project_id,
                            JobDispatchOutbox.document_id == context.document.id,
                            JobDispatchOutbox.job_id == context.job.id,
                            JobDispatchOutbox.processing_run_id == context.run.id,
                        )
                        .with_for_update()
                    )
                    if outbox is not None:
                        outbox.status = DispatchStatus.PENDING.value
                        outbox.available_at = now + timedelta(seconds=retry_delay or 0)
                        outbox.lease_expires_at = None
                        outbox.published_at = None
                        outbox.last_error_code = failure.error_code
        record_ingestion_stage(stage=stage.value, outcome="retry" if retryable else "failed")
        if retryable:
            result = OrchestrationResult(
                OrchestrationDisposition.RETRY,
                context.attempt_count,
                retry_after_seconds=retry_delay,
                error_code=failure.error_code,
                job_id=context.job.id,
                processing_run_id=context.run.id,
            )
            record_ingestion_attempt(outcome="retry", error_code=failure.error_code)
            return result
        result = OrchestrationResult(
            OrchestrationDisposition.FAILED,
            context.attempt_count,
            error_code=failure.error_code,
            job_id=context.job.id,
            processing_run_id=context.run.id,
        )
        record_ingestion_attempt(outcome="failed", error_code=failure.error_code)
        return result

    def _retry_delay(self, attempt_count: int) -> int:
        policy = self._dependencies.settings
        exponent = min(max(attempt_count - 1, 0), 10)
        base = min(
            policy.document_ingestion_retry_base_seconds * (2**exponent),
            policy.document_ingestion_retry_max_seconds,
        )
        return min(
            base + randbelow(policy.document_ingestion_retry_base_seconds + 1),
            policy.document_ingestion_retry_max_seconds,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_release_orchestrator(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> DocumentIngestionOrchestrator:
    policy = settings or get_settings()
    if not policy.document_ingestion_enabled or policy.tasks_eager:
        raise IngestionError(IngestionErrorCode.DOCUMENT_INGESTION_STATE_CONFLICT)
    tokenizer = LocalBgeTokenizer.from_settings(policy)
    chunker = DocumentChunker(
        tokenizer=tokenizer,
        policy=ChunkingPolicy.from_settings(policy),
    )
    dependencies = IngestionDependencies(
        settings=policy,
        storage=get_upload_storage(),
        scanner=ClamAVScanner(policy),
        registry=get_release_extractor_registry(policy),
        extraction_limits=ExtractionLimits.from_settings(policy),
        chunker=chunker,
        embedding_provider=get_process_embedding_provider(policy),
        embedding_policy=EmbeddingPolicy.from_settings(policy),
        persistence=VectorPersistenceRepository(session_factory),
    )
    return DocumentIngestionOrchestrator(session_factory, dependencies)
