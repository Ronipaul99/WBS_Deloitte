from __future__ import annotations

import json
import math
import re
import struct
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from numbers import Real
from time import perf_counter
from types import MappingProxyType
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.observability import (
    record_vector_persistence_activation,
    record_vector_persistence_batch,
    record_vector_persistence_event,
)
from app.db.session import set_local_tenant_context
from app.models.domain import (
    Document,
    DocumentChunk,
    DocumentLifecycleStatus,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    Job,
    JobType,
)
from app.services.ingestion.embeddings.base import EmbeddingBatchResult, EmbeddingVector
from app.services.ingestion.errors import PersistenceError, PersistenceErrorCode

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_ACTIVE_STATUSES = {
    DocumentProcessingStatus.QUEUED.value,
    DocumentProcessingStatus.IN_PROGRESS.value,
}
_INACTIVE_DELETABLE_STATUSES = {
    DocumentProcessingStatus.COMPLETED.value,
    DocumentProcessingStatus.FAILED.value,
    DocumentProcessingStatus.CANCELLED.value,
}
_CANONICAL_BLOCK_TYPE = "canonical_chunk"


def _input_error() -> PersistenceError:
    return PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_INPUT_INVALID)


def _validated_uuid(value: UUID | str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise _input_error() from None


def _safe_identity(value: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or not _SAFE_IDENTITY.fullmatch(value)
    ):
        raise _input_error()
    return value


def _float32_vector(vector: EmbeddingVector | list[float] | tuple[float, ...]) -> tuple[float, ...]:
    values = vector.values if isinstance(vector, EmbeddingVector) else tuple(vector)
    if len(values) != 384:
        raise _input_error()
    converted: list[float] = []
    try:
        for value in values:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError
            result = struct.unpack("!f", struct.pack("!f", float(value)))[0]
            if not math.isfinite(result):
                raise ValueError
            converted.append(result)
    except (TypeError, ValueError, OverflowError, struct.error):
        raise _input_error() from None
    return tuple(converted)


@dataclass(frozen=True, slots=True, repr=False)
class DocumentScope:
    tenant_id: UUID
    project_id: UUID
    document_id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _validated_uuid(self.tenant_id))
        object.__setattr__(self, "project_id", _validated_uuid(self.project_id))
        object.__setattr__(self, "document_id", _validated_uuid(self.document_id))


@dataclass(frozen=True, slots=True, repr=False)
class PersistenceScope(DocumentScope):
    job_id: UUID

    def __post_init__(self) -> None:
        DocumentScope.__post_init__(self)
        object.__setattr__(self, "job_id", _validated_uuid(self.job_id))

    @property
    def document_scope(self) -> DocumentScope:
        return DocumentScope(self.tenant_id, self.project_id, self.document_id)


@dataclass(frozen=True, slots=True, repr=False)
class ProcessingIdentity:
    document_content_sha256: str
    extractor_name: str
    extractor_version: str
    chunker_version: str
    embedding_provider: str
    embedding_model: str
    embedding_model_revision: str
    embedding_dimensions: int
    embedding_formatting_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_content_sha256, str) or not _SHA256.fullmatch(
            self.document_content_sha256
        ):
            raise _input_error()
        for name, maximum in (
            ("extractor_name", 80),
            ("extractor_version", 40),
            ("chunker_version", 40),
            ("embedding_provider", 40),
            ("embedding_model", 160),
            ("embedding_model_revision", 128),
            ("embedding_formatting_version", 80),
        ):
            object.__setattr__(self, name, _safe_identity(getattr(self, name), maximum))
        if self.embedding_dimensions != 384 or isinstance(self.embedding_dimensions, bool):
            raise _input_error()


@dataclass(frozen=True, slots=True)
class ProcessingCounts:
    page_count: int
    worksheet_count: int
    block_count: int
    chunk_count: int

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise _input_error()
        if self.block_count <= 0 or self.chunk_count <= 0:
            raise _input_error()


@dataclass(frozen=True, slots=True)
class VectorPersistencePolicy:
    batch_size: int = 100
    maximum_chunks: int = 100_000
    maximum_source_metadata_bytes: int = 65_536
    maximum_similarity_results: int = 100
    maximum_superseded_results: int = 500

    def __post_init__(self) -> None:
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values
        ):
            raise ValueError("vector persistence policy values must be positive integers")
        if self.batch_size > 1_000 or self.maximum_similarity_results > 1_000:
            raise ValueError("vector persistence policy exceeds the approved bound")


class RunResolution(StrEnum):
    CREATED = "created"
    RESUMED = "resumed"
    REUSED = "reused"


@dataclass(frozen=True, slots=True, repr=False)
class RunResolutionResult:
    run_id: UUID
    resolution: RunResolution
    status: DocumentProcessingStatus


@dataclass(frozen=True, slots=True)
class StagingResult:
    inserted_count: int
    reused_count: int
    persisted_count: int


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    persisted_count: int
    first_ordinal: int
    last_ordinal: int


@dataclass(frozen=True, slots=True, repr=False)
class ActivationResult:
    run_id: UUID
    activated: bool
    chunk_count: int


@dataclass(frozen=True, slots=True, repr=False)
class PersistedChunk:
    id: UUID
    processing_run_id: UUID
    ordinal: int
    token_count: int
    content: str = field(repr=False)
    content_sha256: str = field(repr=False)
    heading_path: tuple[str, ...]
    source_metadata: Mapping[str, Any] = field(repr=False)
    vector: EmbeddingVector = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class SimilarityMatch:
    chunk_id: UUID
    processing_run_id: UUID
    ordinal: int
    cosine_distance: float


@dataclass(frozen=True, slots=True, repr=False)
class SupersededRun:
    run_id: UUID
    status: DocumentProcessingStatus
    chunk_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class _ChunkRecord:
    ordinal: int
    token_count: int
    content: str
    content_sha256: str
    page_number: int | None
    worksheet_name: str | None
    row_start: int | None
    row_end: int | None
    heading_path: list[str]
    source_metadata: dict[str, Any]
    embedding: tuple[float, ...]


class VectorPersistenceRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        policy: VectorPersistencePolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy or VectorPersistencePolicy()

    @asynccontextmanager
    async def _transaction(
        self,
        tenant_id: UUID,
        *,
        integrity_code: PersistenceErrorCode = (
            PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT
        ),
    ):
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await set_local_tenant_context(session, tenant_id)
                    yield session
        except PersistenceError:
            raise
        except IntegrityError:
            raise PersistenceError(integrity_code) from None
        except (OperationalError, DBAPIError):
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_UNAVAILABLE) from None
        except SQLAlchemyError:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_FAILED) from None

    async def create_or_resolve_run(
        self,
        scope: PersistenceScope,
        identity: ProcessingIdentity,
        counts: ProcessingCounts,
    ) -> RunResolutionResult:
        if counts.chunk_count > self._policy.maximum_chunks:
            raise _input_error()
        try:
            result = await self._create_or_resolve_once(scope, identity, counts)
        except PersistenceError as error:
            if error.code is not PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT:
                self._record_error("resolve", error)
                raise
            result = await self._resolve_after_constraint_race(scope, identity)
            if result is None:
                self._record_error("resolve", error)
                raise
        record_vector_persistence_event(
            operation="resolve",
            outcome="reused" if result.resolution is RunResolution.REUSED else "success",
        )
        return result

    async def _create_or_resolve_once(
        self,
        scope: PersistenceScope,
        identity: ProcessingIdentity,
        counts: ProcessingCounts,
    ) -> RunResolutionResult:
        async with self._transaction(scope.tenant_id) as session:
            document = await self._locked_document(session, scope.document_scope)
            await self._validate_job(session, scope)
            self._bind_document_hash(document, identity.document_content_sha256)
            active = await session.scalar(
                select(DocumentProcessingRun)
                .where(
                    DocumentProcessingRun.tenant_id == scope.tenant_id,
                    DocumentProcessingRun.project_id == scope.project_id,
                    DocumentProcessingRun.document_id == scope.document_id,
                    DocumentProcessingRun.status.in_(_ACTIVE_STATUSES),
                )
                .with_for_update()
            )
            if active is not None and active.job_id == scope.job_id:
                if self._run_identity_is_unbound(active):
                    self._bind_run_identity(active, identity, counts)
                    return RunResolutionResult(
                        active.id,
                        RunResolution.RESUMED,
                        DocumentProcessingStatus.IN_PROGRESS,
                    )
                if self._run_matches_identity(active, identity):
                    return await self._resume_or_reuse(session, document, active, scope, counts)
                raise PersistenceError(
                    PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT
                )
            existing = await self._identity_run(session, scope.document_scope, identity, lock=True)
            if existing is not None:
                return await self._resume_or_reuse(session, document, existing, scope, counts)
            if active is not None:
                raise PersistenceError(PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT)
            now = datetime.now(UTC)
            run = DocumentProcessingRun(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                document_id=scope.document_id,
                job_id=scope.job_id,
                status=DocumentProcessingStatus.IN_PROGRESS.value,
                document_content_sha256=identity.document_content_sha256,
                extractor_name=identity.extractor_name,
                extractor_version=identity.extractor_version,
                chunker_version=identity.chunker_version,
                embedding_provider=identity.embedding_provider,
                embedding_model=identity.embedding_model,
                embedding_model_revision=identity.embedding_model_revision,
                embedding_dimensions=identity.embedding_dimensions,
                embedding_formatting_version=identity.embedding_formatting_version,
                page_count=counts.page_count,
                worksheet_count=counts.worksheet_count,
                block_count=counts.block_count,
                chunk_count=counts.chunk_count,
                started_at=now,
            )
            session.add(run)
            document.processing_status = DocumentProcessingStatus.IN_PROGRESS.value
            document.processing_error_code = None
            await session.flush()
            return RunResolutionResult(
                run.id,
                RunResolution.CREATED,
                DocumentProcessingStatus.IN_PROGRESS,
            )

    @staticmethod
    def _run_identity_is_unbound(run: DocumentProcessingRun) -> bool:
        return all(
            value is None
            for value in (
                run.document_content_sha256,
                run.extractor_name,
                run.extractor_version,
                run.chunker_version,
                run.embedding_provider,
                run.embedding_model,
                run.embedding_model_revision,
                run.embedding_dimensions,
                run.embedding_formatting_version,
            )
        )

    @staticmethod
    def _bind_run_identity(
        run: DocumentProcessingRun,
        identity: ProcessingIdentity,
        counts: ProcessingCounts,
    ) -> None:
        run.document_content_sha256 = identity.document_content_sha256
        run.extractor_name = identity.extractor_name
        run.extractor_version = identity.extractor_version
        run.chunker_version = identity.chunker_version
        run.embedding_provider = identity.embedding_provider
        run.embedding_model = identity.embedding_model
        run.embedding_model_revision = identity.embedding_model_revision
        run.embedding_dimensions = identity.embedding_dimensions
        run.embedding_formatting_version = identity.embedding_formatting_version
        run.page_count = counts.page_count
        run.worksheet_count = counts.worksheet_count
        run.block_count = counts.block_count
        run.chunk_count = counts.chunk_count
        run.status = DocumentProcessingStatus.IN_PROGRESS.value
        run.started_at = run.started_at or datetime.now(UTC)
        run.failed_at = None
        run.completed_at = None
        run.error_code = None
        run.error_message = None

    async def _resolve_after_constraint_race(
        self,
        scope: PersistenceScope,
        identity: ProcessingIdentity,
    ) -> RunResolutionResult | None:
        async with self._transaction(scope.tenant_id) as session:
            existing = await self._identity_run(session, scope.document_scope, identity, lock=True)
            if existing is None or existing.job_id != scope.job_id:
                return None
            status = DocumentProcessingStatus(existing.status)
            if status is DocumentProcessingStatus.COMPLETED:
                return RunResolutionResult(existing.id, RunResolution.REUSED, status)
            if status in {
                DocumentProcessingStatus.QUEUED,
                DocumentProcessingStatus.IN_PROGRESS,
            }:
                return RunResolutionResult(
                    existing.id,
                    RunResolution.RESUMED,
                    DocumentProcessingStatus.IN_PROGRESS,
                )
            return None

    async def _resume_or_reuse(
        self,
        session: AsyncSession,
        document: Document,
        run: DocumentProcessingRun,
        scope: PersistenceScope,
        counts: ProcessingCounts,
    ) -> RunResolutionResult:
        if run.job_id != scope.job_id:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT)
        status = DocumentProcessingStatus(run.status)
        if status is DocumentProcessingStatus.COMPLETED:
            return RunResolutionResult(run.id, RunResolution.REUSED, status)
        if status in {DocumentProcessingStatus.FAILED, DocumentProcessingStatus.CANCELLED}:
            await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.tenant_id == scope.tenant_id,
                    DocumentChunk.project_id == scope.project_id,
                    DocumentChunk.document_id == scope.document_id,
                    DocumentChunk.processing_run_id == run.id,
                )
            )
            run.failed_at = None
            run.completed_at = None
            run.error_code = None
            run.error_message = None
            run.started_at = datetime.now(UTC)
        run.status = DocumentProcessingStatus.IN_PROGRESS.value
        run.page_count = counts.page_count
        run.worksheet_count = counts.worksheet_count
        run.block_count = counts.block_count
        run.chunk_count = counts.chunk_count
        document.processing_status = DocumentProcessingStatus.IN_PROGRESS.value
        document.processing_error_code = None
        return RunResolutionResult(
            run.id,
            RunResolution.RESUMED,
            DocumentProcessingStatus.IN_PROGRESS,
        )

    async def stage_embeddings(
        self,
        scope: PersistenceScope,
        run_id: UUID | str,
        result: EmbeddingBatchResult,
        identity: ProcessingIdentity,
    ) -> StagingResult:
        validated_run_id = _validated_uuid(run_id)
        records = self._validated_records(result, identity)
        inserted = reused = 0
        for start in range(0, len(records), self._policy.batch_size):
            batch = records[start : start + self._policy.batch_size]
            began = perf_counter()
            try:
                batch_inserted, batch_reused = await self._stage_batch(
                    scope,
                    validated_run_id,
                    batch,
                    identity,
                    len(records),
                )
            except PersistenceError as error:
                record_vector_persistence_batch(
                    duration_seconds=perf_counter() - began,
                    batch_size=len(batch),
                    outcome="failed",
                )
                self._record_error("batch", error)
                raise
            inserted += batch_inserted
            reused += batch_reused
            record_vector_persistence_batch(
                duration_seconds=perf_counter() - began,
                batch_size=len(batch),
                outcome="success",
            )
        return StagingResult(inserted, reused, inserted + reused)

    async def _stage_batch(
        self,
        scope: PersistenceScope,
        run_id: UUID,
        records: tuple[_ChunkRecord, ...],
        identity: ProcessingIdentity,
        expected_count: int,
    ) -> tuple[int, int]:
        async with self._transaction(scope.tenant_id) as session:
            document = await self._locked_document(session, scope.document_scope)
            self._require_document_hash(document, identity.document_content_sha256)
            run = await self._locked_run(session, scope, run_id)
            self._validate_staging_run(run, identity, expected_count)
            ordinals = tuple(record.ordinal for record in records)
            existing_rows = (
                (
                    await session.execute(
                        select(DocumentChunk).where(
                            DocumentChunk.tenant_id == scope.tenant_id,
                            DocumentChunk.project_id == scope.project_id,
                            DocumentChunk.document_id == scope.document_id,
                            DocumentChunk.processing_run_id == run_id,
                            DocumentChunk.ordinal.in_(ordinals),
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing = {row.ordinal: row for row in existing_rows}
            inserted = reused = 0
            for record in records:
                row = existing.get(record.ordinal)
                if row is not None:
                    if not self._row_matches(row, record):
                        raise PersistenceError(
                            PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT
                        )
                    reused += 1
                    continue
                session.add(
                    DocumentChunk(
                        processing_run_id=run_id,
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        document_id=scope.document_id,
                        ordinal=record.ordinal,
                        token_count=record.token_count,
                        content=record.content,
                        content_sha256=record.content_sha256,
                        block_type=_CANONICAL_BLOCK_TYPE,
                        page_number=record.page_number,
                        worksheet_name=record.worksheet_name,
                        row_start=record.row_start,
                        row_end=record.row_end,
                        heading_path=record.heading_path,
                        source_metadata=record.source_metadata,
                        embedding=list(record.embedding),
                    )
                )
                inserted += 1
            await session.flush()
            return inserted, reused

    async def reconcile_run(
        self,
        scope: PersistenceScope,
        run_id: UUID | str,
        result: EmbeddingBatchResult,
        identity: ProcessingIdentity,
    ) -> ReconciliationResult:
        validated_run_id = _validated_uuid(run_id)
        records = self._validated_records(result, identity)
        try:
            async with self._transaction(scope.tenant_id) as session:
                document = await self._locked_document(session, scope.document_scope, lock=False)
                self._require_document_hash(document, identity.document_content_sha256)
                run = await self._locked_run(session, scope, validated_run_id)
                self._validate_staging_run(run, identity, len(records), allow_completed=True)
                rows = await self._chunk_rows(session, scope.document_scope, validated_run_id)
                reconciliation = self._reconcile_rows(rows, records)
        except PersistenceError as error:
            self._record_error("reconcile", error)
            raise
        record_vector_persistence_event(operation="reconcile", outcome="success")
        return reconciliation

    async def activate_run(
        self,
        scope: PersistenceScope,
        run_id: UUID | str,
        result: EmbeddingBatchResult,
        identity: ProcessingIdentity,
        counts: ProcessingCounts,
    ) -> ActivationResult:
        validated_run_id = _validated_uuid(run_id)
        records = self._validated_records(result, identity)
        if counts.chunk_count != len(records):
            raise _input_error()
        began = perf_counter()
        try:
            async with self._transaction(
                scope.tenant_id,
                integrity_code=PersistenceErrorCode.DOCUMENT_ACTIVATION_CONFLICT,
            ) as session:
                document = await self._locked_document(session, scope.document_scope)
                self._require_document_hash(document, identity.document_content_sha256)
                run = await self._locked_run(session, scope, validated_run_id)
                if (
                    run.status == DocumentProcessingStatus.COMPLETED.value
                    and document.current_processing_run_id == run.id
                ):
                    rows = await self._chunk_rows(session, scope.document_scope, run.id)
                    reconciliation = self._reconcile_rows(rows, records)
                    result_value = ActivationResult(run.id, False, reconciliation.persisted_count)
                else:
                    self._validate_staging_run(run, identity, len(records))
                    rows = await self._chunk_rows(session, scope.document_scope, run.id)
                    reconciliation = self._reconcile_rows(rows, records)
                    now = datetime.now(UTC)
                    run.status = DocumentProcessingStatus.COMPLETED.value
                    run.page_count = counts.page_count
                    run.worksheet_count = counts.worksheet_count
                    run.block_count = counts.block_count
                    run.chunk_count = reconciliation.persisted_count
                    run.completed_at = now
                    run.failed_at = None
                    run.error_code = None
                    run.error_message = None
                    document.current_processing_run_id = run.id
                    document.processing_status = DocumentProcessingStatus.COMPLETED.value
                    document.processed_at = now
                    document.processing_error_code = None
                    await session.flush()
                    result_value = ActivationResult(run.id, True, reconciliation.persisted_count)
        except PersistenceError as error:
            record_vector_persistence_activation(
                duration_seconds=perf_counter() - began,
                outcome="failed",
            )
            self._record_error("activate", error)
            raise
        record_vector_persistence_activation(
            duration_seconds=perf_counter() - began,
            outcome="success" if result_value.activated else "reused",
        )
        record_vector_persistence_event(
            operation="activate",
            outcome="success" if result_value.activated else "reused",
        )
        return result_value

    async def mark_run_failed(
        self,
        scope: PersistenceScope,
        run_id: UUID | str,
        error: PersistenceError,
    ) -> None:
        if not isinstance(error, PersistenceError):
            raise _input_error()
        validated_run_id = _validated_uuid(run_id)
        try:
            async with self._transaction(scope.tenant_id) as session:
                document = await self._locked_document(session, scope.document_scope)
                run = await self._locked_run(session, scope, validated_run_id)
                if run.status not in _ACTIVE_STATUSES:
                    raise PersistenceError(PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT)
                run.status = DocumentProcessingStatus.FAILED.value
                run.failed_at = datetime.now(UTC)
                run.completed_at = None
                run.error_code = error.code.value
                run.error_message = str(error)[:500]
                document.processing_status = DocumentProcessingStatus.FAILED.value
                document.processing_error_code = error.code.value
        except PersistenceError as repository_error:
            self._record_error("fail", repository_error)
            raise
        record_vector_persistence_event(
            operation="fail",
            outcome="success",
            error_code=error.code.value,
        )

    async def load_active_ordered_chunks(
        self,
        scope: DocumentScope,
    ) -> tuple[PersistedChunk, ...]:
        async with self._transaction(scope.tenant_id) as session:
            document = await self._locked_document(session, scope, lock=False)
            if document.current_processing_run_id is None:
                return ()
            run = await session.scalar(
                select(DocumentProcessingRun).where(
                    DocumentProcessingRun.id == document.current_processing_run_id,
                    DocumentProcessingRun.tenant_id == scope.tenant_id,
                    DocumentProcessingRun.project_id == scope.project_id,
                    DocumentProcessingRun.document_id == scope.document_id,
                    DocumentProcessingRun.status == DocumentProcessingStatus.COMPLETED.value,
                )
            )
            if run is None:
                raise PersistenceError(
                    PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED
                )
            rows = await self._chunk_rows(session, scope, run.id)
            return tuple(self._persisted_chunk(row) for row in rows)

    async def exact_active_similarity(
        self,
        scope: DocumentScope,
        query_vector: EmbeddingVector,
        *,
        limit: int,
    ) -> tuple[SimilarityMatch, ...]:
        if not isinstance(query_vector, EmbeddingVector) or (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or limit > self._policy.maximum_similarity_results
        ):
            raise _input_error()
        vector = _float32_vector(query_vector)
        async with self._transaction(scope.tenant_id) as session:
            document = await self._locked_document(session, scope, lock=False)
            if document.current_processing_run_id is None:
                return ()
            distance = DocumentChunk.embedding.cosine_distance(list(vector)).label(
                "cosine_distance"
            )
            statement = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.processing_run_id,
                    DocumentChunk.ordinal,
                    distance,
                )
                .join(
                    DocumentProcessingRun,
                    and_(
                        DocumentProcessingRun.id == DocumentChunk.processing_run_id,
                        DocumentProcessingRun.tenant_id == DocumentChunk.tenant_id,
                        DocumentProcessingRun.project_id == DocumentChunk.project_id,
                        DocumentProcessingRun.document_id == DocumentChunk.document_id,
                    ),
                )
                .where(
                    DocumentChunk.tenant_id == scope.tenant_id,
                    DocumentChunk.project_id == scope.project_id,
                    DocumentChunk.document_id == scope.document_id,
                    DocumentChunk.processing_run_id == document.current_processing_run_id,
                    DocumentProcessingRun.status == DocumentProcessingStatus.COMPLETED.value,
                )
                .order_by(distance, DocumentChunk.ordinal, DocumentChunk.id)
                .limit(limit)
            )
            rows = (await session.execute(statement)).all()
            return tuple(SimilarityMatch(*row) for row in rows)

    async def list_superseded_runs(
        self,
        scope: DocumentScope,
        *,
        limit: int = 100,
    ) -> tuple[SupersededRun, ...]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or limit > self._policy.maximum_superseded_results
        ):
            raise _input_error()
        async with self._transaction(scope.tenant_id) as session:
            document = await self._locked_document(session, scope, lock=False)
            statement = (
                select(DocumentProcessingRun)
                .where(
                    DocumentProcessingRun.tenant_id == scope.tenant_id,
                    DocumentProcessingRun.project_id == scope.project_id,
                    DocumentProcessingRun.document_id == scope.document_id,
                    DocumentProcessingRun.status.in_(_INACTIVE_DELETABLE_STATUSES),
                )
                .order_by(DocumentProcessingRun.created_at.desc(), DocumentProcessingRun.id)
                .limit(limit)
            )
            if document.current_processing_run_id is not None:
                statement = statement.where(
                    DocumentProcessingRun.id != document.current_processing_run_id
                )
            runs = (await session.execute(statement)).scalars().all()
            return tuple(
                SupersededRun(
                    run.id,
                    DocumentProcessingStatus(run.status),
                    run.chunk_count,
                    run.created_at,
                )
                for run in runs
            )

    async def delete_superseded_run(
        self,
        scope: DocumentScope,
        run_id: UUID | str,
    ) -> bool:
        validated_run_id = _validated_uuid(run_id)
        try:
            async with self._transaction(scope.tenant_id) as session:
                document = await self._locked_document(session, scope)
                run = await session.scalar(
                    select(DocumentProcessingRun)
                    .where(
                        DocumentProcessingRun.id == validated_run_id,
                        DocumentProcessingRun.tenant_id == scope.tenant_id,
                        DocumentProcessingRun.project_id == scope.project_id,
                        DocumentProcessingRun.document_id == scope.document_id,
                    )
                    .with_for_update()
                )
                if run is None:
                    return False
                if (
                    document.current_processing_run_id == run.id
                    or run.status not in _INACTIVE_DELETABLE_STATUSES
                ):
                    raise PersistenceError(PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT)
                await session.delete(run)
        except PersistenceError as error:
            self._record_error("delete", error)
            raise
        record_vector_persistence_event(operation="delete", outcome="success")
        return True

    async def _locked_document(
        self,
        session: AsyncSession,
        scope: DocumentScope,
        *,
        lock: bool = True,
    ) -> Document:
        statement = select(Document).where(
            Document.tenant_id == scope.tenant_id,
            Document.project_id == scope.project_id,
            Document.id == scope.document_id,
        )
        if lock:
            statement = statement.with_for_update()
        document = await session.scalar(statement)
        if document is None:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH)
        if document.lifecycle_status != DocumentLifecycleStatus.ACTIVE.value:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT)
        return document

    async def _validate_job(self, session: AsyncSession, scope: PersistenceScope) -> Job:
        job = await session.scalar(
            select(Job)
            .where(
                Job.id == scope.job_id,
                Job.tenant_id == scope.tenant_id,
                Job.project_id == scope.project_id,
            )
            .with_for_update()
        )
        if job is None or job.job_type != JobType.DOCUMENT_INGESTION.value:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH)
        return job

    async def _locked_run(
        self,
        session: AsyncSession,
        scope: PersistenceScope,
        run_id: UUID,
    ) -> DocumentProcessingRun:
        run = await session.scalar(
            select(DocumentProcessingRun)
            .where(
                DocumentProcessingRun.id == run_id,
                DocumentProcessingRun.tenant_id == scope.tenant_id,
                DocumentProcessingRun.project_id == scope.project_id,
                DocumentProcessingRun.document_id == scope.document_id,
                DocumentProcessingRun.job_id == scope.job_id,
            )
            .with_for_update()
        )
        if run is None:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH)
        return run

    async def _identity_run(
        self,
        session: AsyncSession,
        scope: DocumentScope,
        identity: ProcessingIdentity,
        *,
        lock: bool,
    ) -> DocumentProcessingRun | None:
        statement = select(DocumentProcessingRun).where(
            DocumentProcessingRun.tenant_id == scope.tenant_id,
            DocumentProcessingRun.project_id == scope.project_id,
            DocumentProcessingRun.document_id == scope.document_id,
            *self._identity_predicates(identity),
        )
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    @staticmethod
    def _identity_predicates(identity: ProcessingIdentity) -> tuple[Any, ...]:
        return (
            DocumentProcessingRun.document_content_sha256 == identity.document_content_sha256,
            DocumentProcessingRun.extractor_name == identity.extractor_name,
            DocumentProcessingRun.extractor_version == identity.extractor_version,
            DocumentProcessingRun.chunker_version == identity.chunker_version,
            DocumentProcessingRun.embedding_provider == identity.embedding_provider,
            DocumentProcessingRun.embedding_model == identity.embedding_model,
            DocumentProcessingRun.embedding_model_revision == identity.embedding_model_revision,
            DocumentProcessingRun.embedding_dimensions == identity.embedding_dimensions,
            DocumentProcessingRun.embedding_formatting_version
            == identity.embedding_formatting_version,
        )

    @staticmethod
    def _bind_document_hash(document: Document, content_sha256: str) -> None:
        if document.content_sha256 is None:
            document.content_sha256 = content_sha256
        elif document.content_sha256 != content_sha256:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH)

    @staticmethod
    def _require_document_hash(document: Document, content_sha256: str) -> None:
        if document.content_sha256 != content_sha256:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_SCOPE_MISMATCH)

    @staticmethod
    def _run_matches_identity(
        run: DocumentProcessingRun,
        identity: ProcessingIdentity,
    ) -> bool:
        return all(
            (
                run.document_content_sha256 == identity.document_content_sha256,
                run.extractor_name == identity.extractor_name,
                run.extractor_version == identity.extractor_version,
                run.chunker_version == identity.chunker_version,
                run.embedding_provider == identity.embedding_provider,
                run.embedding_model == identity.embedding_model,
                run.embedding_model_revision == identity.embedding_model_revision,
                run.embedding_dimensions == identity.embedding_dimensions,
                run.embedding_formatting_version == identity.embedding_formatting_version,
            )
        )

    def _validate_staging_run(
        self,
        run: DocumentProcessingRun,
        identity: ProcessingIdentity,
        expected_count: int,
        *,
        allow_completed: bool = False,
    ) -> None:
        allowed = set(_ACTIVE_STATUSES)
        if allow_completed:
            allowed.add(DocumentProcessingStatus.COMPLETED.value)
        if run.status not in allowed:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT)
        if not self._run_matches_identity(run, identity) or run.chunk_count != expected_count:
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT)

    def _validated_records(
        self,
        result: EmbeddingBatchResult,
        identity: ProcessingIdentity,
    ) -> tuple[_ChunkRecord, ...]:
        if not isinstance(result, EmbeddingBatchResult) or not result.items:
            raise _input_error()
        if len(result.items) > self._policy.maximum_chunks:
            raise _input_error()
        metadata = result.metadata
        if (
            metadata.provider_name != identity.embedding_provider
            or metadata.model_name != identity.embedding_model
            or metadata.model_revision != identity.embedding_model_revision
            or metadata.dimensions != identity.embedding_dimensions
            or metadata.formatting_version != identity.embedding_formatting_version
        ):
            raise _input_error()
        if tuple(item.ordinal for item in result.items) != tuple(range(len(result.items))):
            raise _input_error()
        return tuple(self._record(item) for item in result.items)

    def _record(self, item) -> _ChunkRecord:
        chunk = item.chunk
        source_metadata = {
            "schema_version": 1,
            "source_references": [reference.to_jsonable() for reference in chunk.source_references],
            "primary_source_block_ordinals": list(chunk.primary_source_block_ordinals),
            "overlap_source_block_ordinals": list(chunk.overlap_source_block_ordinals),
            "context_source_block_ordinals": list(chunk.context_source_block_ordinals),
            "source_block_ordinal_start": chunk.source_block_ordinal_start,
            "source_block_ordinal_end": chunk.source_block_ordinal_end,
            "page_numbers": list(chunk.page_numbers),
            "extraction_methods": [method.value for method in chunk.extraction_methods],
            "warning_codes": [code.value for code in chunk.warning_codes],
        }
        try:
            encoded = json.dumps(
                source_metadata,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise _input_error() from None
        if len(encoded) > self._policy.maximum_source_metadata_bytes:
            raise _input_error()
        return _ChunkRecord(
            ordinal=chunk.ordinal,
            token_count=chunk.token_count,
            content=chunk.content,
            content_sha256=chunk.chunk_sha256,
            page_number=chunk.page_numbers[0] if len(chunk.page_numbers) == 1 else None,
            worksheet_name=chunk.sheet_name,
            row_start=chunk.row_start,
            row_end=chunk.row_end,
            heading_path=list(chunk.heading_path),
            source_metadata=source_metadata,
            embedding=_float32_vector(item.vector),
        )

    @staticmethod
    def _row_matches(row: DocumentChunk, record: _ChunkRecord) -> bool:
        try:
            stored_vector = _float32_vector(tuple(row.embedding))
        except PersistenceError:
            return False
        return all(
            (
                row.ordinal == record.ordinal,
                row.token_count == record.token_count,
                row.content == record.content,
                row.content_sha256 == record.content_sha256,
                row.block_type == _CANONICAL_BLOCK_TYPE,
                row.page_number == record.page_number,
                row.worksheet_name == record.worksheet_name,
                row.row_start == record.row_start,
                row.row_end == record.row_end,
                list(row.heading_path) == record.heading_path,
                dict(row.source_metadata) == record.source_metadata,
                stored_vector == record.embedding,
            )
        )

    @staticmethod
    async def _chunk_rows(
        session: AsyncSession,
        scope: DocumentScope,
        run_id: UUID,
    ) -> list[DocumentChunk]:
        return list(
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.tenant_id == scope.tenant_id,
                        DocumentChunk.project_id == scope.project_id,
                        DocumentChunk.document_id == scope.document_id,
                        DocumentChunk.processing_run_id == run_id,
                    )
                    .order_by(DocumentChunk.ordinal)
                )
            )
            .scalars()
            .all()
        )

    def _reconcile_rows(
        self,
        rows: list[DocumentChunk],
        records: tuple[_ChunkRecord, ...],
    ) -> ReconciliationResult:
        if len(rows) != len(records):
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED)
        if tuple(row.ordinal for row in rows) != tuple(range(len(records))):
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED)
        if any(
            not self._row_matches(row, record) for row, record in zip(rows, records, strict=True)
        ):
            raise PersistenceError(PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED)
        return ReconciliationResult(len(rows), 0, len(rows) - 1)

    @staticmethod
    def _persisted_chunk(row: DocumentChunk) -> PersistedChunk:
        try:
            vector = EmbeddingVector(tuple(row.embedding), dimensions=384)
        except Exception:
            raise PersistenceError(
                PersistenceErrorCode.DOCUMENT_PERSISTENCE_RECONCILIATION_FAILED
            ) from None
        return PersistedChunk(
            id=row.id,
            processing_run_id=row.processing_run_id,
            ordinal=row.ordinal,
            token_count=row.token_count,
            content=row.content,
            content_sha256=row.content_sha256,
            heading_path=tuple(row.heading_path),
            source_metadata=_freeze_json(dict(row.source_metadata)),
            vector=vector,
        )

    @staticmethod
    def _record_error(operation: str, error: PersistenceError) -> None:
        if error.code in {
            PersistenceErrorCode.DOCUMENT_PERSISTENCE_IDEMPOTENCY_CONFLICT,
            PersistenceErrorCode.DOCUMENT_PROCESSING_STATE_CONFLICT,
            PersistenceErrorCode.DOCUMENT_ACTIVATION_CONFLICT,
        }:
            outcome = "conflict"
        elif error.code is PersistenceErrorCode.DOCUMENT_PERSISTENCE_UNAVAILABLE:
            outcome = "unavailable"
        else:
            outcome = "failed"
        record_vector_persistence_event(
            operation=operation,
            outcome=outcome,
            error_code=error.code.value,
        )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value
