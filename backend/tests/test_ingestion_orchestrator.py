from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.domain import (
    DispatchStatus,
    Document,
    DocumentChunk,
    DocumentProcessingRun,
    DocumentProcessingStatus,
    IngestionStage,
    Job,
    JobDispatchOutbox,
    JobType,
    ProcessingStatus,
    Project,
    Tenant,
    User,
)
from app.services.ingestion.chunk_types import (
    CanonicalChunk,
    ChunkingPolicy,
    ChunkingResult,
    ChunkingStatistics,
    ChunkSourceReference,
    SourceReferenceRole,
)
from app.services.ingestion.embeddings.base import EmbeddingPolicy, EmbeddingVector
from app.services.ingestion.errors import ChunkingError, ChunkingErrorCode
from app.services.ingestion.orchestrator import (
    DocumentIngestionOrchestrator,
    IngestionDependencies,
    OrchestrationDisposition,
)
from app.services.ingestion.registry import ExtractorRegistry
from app.services.ingestion.release_identity import (
    RELEASE_CHUNKER_VERSION,
    release_extractor_identity,
)
from app.services.ingestion.repository import VectorPersistenceRepository
from app.services.ingestion.scanning import MalwareScanResult, MalwareScanStatus
from app.services.ingestion.types import (
    ConfirmedDocumentFormat,
    ExtractedBlock,
    ExtractedBlockType,
    ExtractionLimits,
    ExtractionMethod,
    ExtractionResult,
    ExtractionStatistics,
)
from app.services.storage import DownloadResult, StoredObjectMetadata

CONTENT = b"%PDF- synthetic ingestion boundary"
CONTENT_HASH = hashlib.sha256(CONTENT).hexdigest()


class FakeStorage:
    def __init__(self) -> None:
        self.download_count = 0

    async def stat_object(self, _storage_key: str) -> StoredObjectMetadata:
        return StoredObjectMetadata(
            size_bytes=len(CONTENT),
            content_type="application/pdf",
            checksum_sha256=CONTENT_HASH,
            entity_tag=None,
        )

    async def download_to_path(
        self,
        _storage_key: str,
        destination: Path,
        *,
        maximum_bytes: int,
    ) -> DownloadResult:
        assert len(CONTENT) <= maximum_bytes
        destination.write_bytes(CONTENT)
        self.download_count += 1
        return DownloadResult(byte_count=len(CONTENT), sha256=CONTENT_HASH)


class FakeScanner:
    def __init__(self, status: MalwareScanStatus) -> None:
        self.status = status
        self.scanned_paths: list[Path] = []

    async def scan(self, path: Path) -> MalwareScanResult:
        assert path.is_file()
        self.scanned_paths.append(path)
        return MalwareScanResult(self.status, "synthetic" if self.status == "infected" else None)

    async def check(self) -> None:
        return None


class PdfExtractor:
    name = "pypdf-ocrmypdf"
    version = release_extractor_identity(ConfirmedDocumentFormat.PDF)[1]
    format_name = ConfirmedDocumentFormat.PDF

    def __init__(self, limits: ExtractionLimits) -> None:
        self.limits = limits
        self.calls = 0

    def supports(self, confirmed_format: ConfirmedDocumentFormat) -> bool:
        return confirmed_format is self.format_name

    def extract(self, path: Path, limits: ExtractionLimits) -> ExtractionResult:
        assert path.read_bytes() == CONTENT
        assert limits is self.limits
        self.calls += 1
        block = ExtractedBlock(
            ordinal=0,
            text="Synthetic project scope",
            block_type=ExtractedBlockType.PARAGRAPH,
            page_number=1,
            extraction_method=ExtractionMethod.NATIVE,
            metadata={"source_kind": "synthetic"},
            limits=limits,
        )
        statistics = ExtractionStatistics(
            detected_format=self.format_name,
            page_count=1,
            worksheet_count=0,
            table_count=0,
            row_count=0,
            block_count=1,
            character_count=len(block.text),
            native_page_count=1,
            ocr_page_count=0,
            warning_codes=(),
            extractor_name=self.name,
            extractor_version=self.version,
            limits=limits,
        )
        return ExtractionResult(
            blocks=(block,),
            statistics=statistics,
            source_content_sha256=CONTENT_HASH,
            confirmed_format=self.format_name,
            limits=limits,
        )


class FakeChunker:
    version = RELEASE_CHUNKER_VERSION

    def chunk(self, extraction: ExtractionResult) -> ChunkingResult:
        policy = ChunkingPolicy(
            target_tokens=60,
            overlap_tokens=10,
            maximum_content_tokens=80,
            formatting_headroom_tokens=32,
            maximum_chunks=10,
            maximum_source_references=10,
            maximum_characters=1_000,
            maximum_heading_depth=8,
            maximum_heading_label_characters=100,
            maximum_warnings=10,
        )
        content = extraction.blocks[0].text
        chunk = CanonicalChunk(
            ordinal=0,
            content=content,
            token_count=8,
            chunk_sha256=hashlib.sha256(content.encode()).hexdigest(),
            source_references=(
                ChunkSourceReference(
                    block_ordinal=0,
                    role=SourceReferenceRole.PRIMARY,
                    page_number=1,
                    sheet_name=None,
                    row_start=None,
                    row_end=None,
                    extraction_method=ExtractionMethod.NATIVE,
                ),
            ),
            heading_path=(),
            warning_codes=(),
            policy=policy,
        )
        statistics = ChunkingStatistics(
            input_block_count=1,
            retained_block_count=1,
            dropped_empty_block_count=0,
            chunk_count=1,
            forced_split_count=0,
            overlap_application_count=0,
            repeated_header_context_count=0,
            total_token_count=8,
            warning_codes=(),
        )
        return ChunkingResult(
            chunks=(chunk,),
            statistics=statistics,
            source_content_sha256=CONTENT_HASH,
            confirmed_format=ConfirmedDocumentFormat.PDF,
            chunker_version=self.version,
            tokenizer_name="BAAI/bge-small-en-v1.5",
            tokenizer_revision="synthetic-revision",
        )


class FakeEmbeddingProvider:
    provider_name = "fastembed"
    model_name = "BAAI/bge-small-en-v1.5"
    model_revision = "synthetic-model-revision"
    dimensions = 384
    formatting_version = "bge-small-en-v1.5-format-v1"

    def embed_documents(self, texts):
        return tuple(EmbeddingVector([1.0] + [0.0] * 383, dimensions=384) for _ in texts)

    def embed_query(self, _text):
        return EmbeddingVector([1.0] + [0.0] * 383, dimensions=384)


@pytest_asyncio.fixture
async def orchestration_context(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'orchestration.db').as_posix()}"
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, project_id, document_id, job_id, run_id, user_id = (uuid4() for _ in range(6))
    async with sessions.begin() as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    external_subject="orchestration-user",
                    email="orchestration@example.test",
                    display_name="Orchestration",
                ),
                Tenant(
                    id=tenant_id,
                    name="Orchestration",
                    slug=f"orchestration-{tenant_id.hex}",
                ),
            ]
        )
        await session.flush()
        session.add(
            Project(
                id=project_id,
                tenant_id=tenant_id,
                created_by=user_id,
                name="Orchestration",
            )
        )
        await session.flush()
        session.add_all(
            [
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    uploaded_by=user_id,
                    kind="PROJECT",
                    file_name="synthetic.pdf",
                    content_type="application/pdf",
                    size_bytes=len(CONTENT),
                    storage_key=(
                        f"tenants/{tenant_id}/projects/{project_id}/documents/{uuid4()}.pdf"
                    ),
                ),
                Job(
                    id=job_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    created_by=user_id,
                    job_type=JobType.DOCUMENT_INGESTION.value,
                    status=ProcessingStatus.QUEUED.value,
                    progress=0,
                    current_step=IngestionStage.QUEUED.value,
                    request_payload={"document_id": str(document_id)},
                ),
            ]
        )
        await session.flush()
        session.add(
            DocumentProcessingRun(
                id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                job_id=job_id,
                status=DocumentProcessingStatus.QUEUED.value,
                current_stage=IngestionStage.QUEUED.value,
            )
        )
        await session.flush()
        session.add(
            JobDispatchOutbox(
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                job_id=job_id,
                processing_run_id=run_id,
                task_name="wbs.process_document_ingestion",
                status=DispatchStatus.PUBLISHED.value,
                attempt_count=1,
                available_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
        )
    try:
        yield sessions, (tenant_id, project_id, document_id, job_id, run_id), tmp_path
    finally:
        await engine.dispose()


def _limits() -> ExtractionLimits:
    return ExtractionLimits(
        maximum_pdf_pages=10,
        maximum_worksheets=5,
        maximum_rows_per_sheet=100,
        maximum_extracted_characters=5_000,
        maximum_blocks=100,
        maximum_characters_per_block=1_000,
        maximum_heading_depth=5,
        maximum_heading_label_characters=100,
        maximum_warnings=10,
        maximum_metadata_fields=10,
        maximum_metadata_depth=3,
        maximum_metadata_value_characters=200,
        maximum_metadata_list_items=10,
        maximum_sheet_name_characters=100,
        maximum_archive_entries=100,
        maximum_archive_compressed_bytes=1_000_000,
        maximum_archive_uncompressed_bytes=2_000_000,
        maximum_archive_entry_bytes=1_000_000,
        maximum_archive_expansion_ratio=100,
        maximum_spreadsheet_columns=100,
        maximum_spreadsheet_cells=1_000,
        maximum_merged_ranges=100,
        maximum_csv_columns=100,
        maximum_csv_field_characters=1_000,
    )


def _orchestrator(sessions, tmp_path, scanner, *, chunker=None):
    limits = _limits()
    storage = FakeStorage()
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(mode=0o700, exist_ok=True)
    policy = get_settings().model_copy(
        update={
            "document_ingestion_enabled": True,
            "tasks_eager": False,
            "malware_scan_required": True,
            "document_processing_temp_root": workspace_root,
            "document_ingestion_max_attempts": 2,
            "document_ingestion_retry_base_seconds": 1,
            "document_ingestion_retry_max_seconds": 2,
        }
    )
    dependencies = IngestionDependencies(
        settings=policy,
        storage=storage,
        scanner=scanner,
        registry=ExtractorRegistry((PdfExtractor(limits),)),
        extraction_limits=limits,
        chunker=chunker or FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        embedding_policy=EmbeddingPolicy(
            dimensions=384,
            batch_size=4,
            maximum_inputs=10,
            maximum_text_characters=1_000,
            maximum_aggregate_characters=5_000,
        ),
        persistence=VectorPersistenceRepository(sessions),
    )
    return DocumentIngestionOrchestrator(sessions, dependencies), storage


@pytest.mark.asyncio
async def test_successful_orchestration_is_durable_idempotent_and_cleans_workspace(
    orchestration_context,
    monkeypatch,
):
    from app.services.ingestion import orchestrator as orchestrator_module

    stages: list[str] = []

    def record_stage(*, stage: str, outcome: str = "success") -> None:
        assert outcome == "success"
        stages.append(stage)

    monkeypatch.setattr(orchestrator_module, "record_ingestion_stage", record_stage)
    sessions, ids, tmp_path = orchestration_context
    _, _, document_id, job_id, run_id = ids
    scanner = FakeScanner(MalwareScanStatus.CLEAN)
    orchestrator, storage = _orchestrator(sessions, tmp_path, scanner)

    result = await orchestrator.run(job_id, run_id)
    duplicate = await orchestrator.run(job_id, run_id)

    assert result.disposition is OrchestrationDisposition.COMPLETED
    assert duplicate.disposition is OrchestrationDisposition.COMPLETED
    assert storage.download_count == 1
    assert stages == [
        "SCANNING",
        "EXTRACTING",
        "CHUNKING",
        "EMBEDDING",
        "PERSISTING",
        "ACTIVATING",
        "COMPLETED",
    ]
    assert len(scanner.scanned_paths) == 1
    assert not scanner.scanned_paths[0].exists()
    workspace_root = tmp_path / "workspaces"
    assert not workspace_root.exists() or not tuple(workspace_root.iterdir())

    async with sessions() as session:
        document = await session.get(Document, document_id)
        job = await session.get(Job, job_id)
        run = await session.get(DocumentProcessingRun, run_id)
        assert document is not None and job is not None and run is not None
        assert document.current_processing_run_id == run_id
        assert document.content_sha256 == CONTENT_HASH
        assert run.status == DocumentProcessingStatus.COMPLETED.value
        assert run.current_stage == IngestionStage.COMPLETED.value
        assert run.chunk_count == 1
        assert job.status == ProcessingStatus.COMPLETED.value
        assert job.progress == 100
        assert job.result_payload == {
            "document_id": str(document_id),
            "processing_run_id": str(run_id),
            "chunk_count": 1,
        }


@pytest.mark.asyncio
async def test_transient_scanner_failure_retries_then_exhausts_and_cleans(
    orchestration_context,
):
    sessions, ids, tmp_path = orchestration_context
    _, _, _, job_id, run_id = ids
    scanner = FakeScanner(MalwareScanStatus.UNAVAILABLE)
    orchestrator, storage = _orchestrator(sessions, tmp_path, scanner)

    first = await orchestrator.run(job_id, run_id)
    async with sessions() as session:
        outbox = await session.scalar(
            select(JobDispatchOutbox).where(JobDispatchOutbox.job_id == job_id)
        )
        assert outbox is not None
        assert outbox.status == DispatchStatus.PENDING.value
        assert outbox.published_at is None
        assert outbox.available_at is not None
    second = await orchestrator.run(job_id, run_id)

    assert first.disposition is OrchestrationDisposition.RETRY
    assert first.retry_after_seconds is not None
    assert second.disposition is OrchestrationDisposition.FAILED
    assert second.error_code == "MALWARE_SCANNER_UNAVAILABLE"
    assert storage.download_count == 2
    assert all(not path.exists() for path in scanner.scanned_paths)
    async with sessions() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        job = await session.get(Job, job_id)
        assert run is not None and job is not None
        assert run.attempt_count == 2
        assert run.status == DocumentProcessingStatus.FAILED.value
        assert job.status == ProcessingStatus.FAILED.value


@pytest.mark.asyncio
async def test_late_transient_failure_restarts_without_decreasing_progress(
    orchestration_context,
):
    sessions, ids, tmp_path = orchestration_context
    _, _, _, job_id, run_id = ids

    class FailOnceChunker(FakeChunker):
        def __init__(self) -> None:
            self.calls = 0

        def chunk(self, extraction: ExtractionResult) -> ChunkingResult:
            self.calls += 1
            if self.calls == 1:
                raise ChunkingError(ChunkingErrorCode.DOCUMENT_CHUNKING_FAILED)
            return super().chunk(extraction)

    chunker = FailOnceChunker()
    orchestrator, _ = _orchestrator(
        sessions,
        tmp_path,
        FakeScanner(MalwareScanStatus.CLEAN),
        chunker=chunker,
    )

    first = await orchestrator.run(job_id, run_id)
    async with sessions() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        first_progress = job.progress
    second = await orchestrator.run(job_id, run_id)

    assert first.disposition is OrchestrationDisposition.RETRY
    assert first_progress == 50
    assert second.disposition is OrchestrationDisposition.COMPLETED
    assert chunker.calls == 2
    async with sessions() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.progress == 100
        assert job.progress >= first_progress


@pytest.mark.asyncio
async def test_malware_failure_is_permanent_and_does_not_activate_run(orchestration_context):
    sessions, ids, tmp_path = orchestration_context
    _, _, document_id, job_id, run_id = ids
    scanner = FakeScanner(MalwareScanStatus.INFECTED)
    orchestrator, _ = _orchestrator(sessions, tmp_path, scanner)

    result = await orchestrator.run(job_id, run_id)

    assert result.disposition is OrchestrationDisposition.FAILED
    assert result.error_code == "DOCUMENT_REJECTED_MALWARE"
    assert all(not path.exists() for path in scanner.scanned_paths)
    async with sessions() as session:
        document = await session.get(Document, document_id)
        run = await session.get(DocumentProcessingRun, run_id)
        assert document is not None and run is not None
        assert document.current_processing_run_id is None
        assert run.status == DocumentProcessingStatus.FAILED.value
        assert run.document_content_sha256 is None


@pytest.mark.asyncio
async def test_failed_reprocessing_preserves_previous_active_completed_run(
    orchestration_context,
):
    sessions, ids, tmp_path = orchestration_context
    tenant_id, project_id, document_id, job_id, run_id = ids
    previous_job_id, previous_run_id = uuid4(), uuid4()
    async with sessions.begin() as session:
        document = await session.get(Document, document_id)
        current_job = await session.get(Job, job_id)
        assert document is not None and current_job is not None
        session.add(
            Job(
                id=previous_job_id,
                tenant_id=tenant_id,
                project_id=project_id,
                created_by=current_job.created_by,
                job_type=JobType.DOCUMENT_INGESTION.value,
                status=ProcessingStatus.COMPLETED.value,
                progress=100,
                current_step=IngestionStage.COMPLETED.value,
            )
        )
        await session.flush()
        previous_run = DocumentProcessingRun(
            id=previous_run_id,
            tenant_id=tenant_id,
            project_id=project_id,
            document_id=document_id,
            job_id=previous_job_id,
            status=DocumentProcessingStatus.COMPLETED.value,
            document_content_sha256=CONTENT_HASH,
            extractor_name="pypdf-ocrmypdf",
            extractor_version="1.0.0",
            chunker_version="1.0.0",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_model_revision="previous-model-revision",
            embedding_dimensions=384,
            embedding_formatting_version="bge-small-en-v1.5-format-v1",
            page_count=1,
            block_count=1,
            chunk_count=1,
            current_stage=IngestionStage.COMPLETED.value,
        )
        session.add(previous_run)
        await session.flush()
        session.add(
            DocumentChunk(
                processing_run_id=previous_run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                document_id=document_id,
                ordinal=0,
                token_count=4,
                content="Previous safe scope",
                content_sha256="e" * 64,
                block_type="canonical",
                page_number=1,
                heading_path=[],
                source_metadata={},
                embedding=[0.0] * 384,
            )
        )
        document.content_sha256 = previous_run.document_content_sha256
        document.current_processing_run_id = previous_run_id
        document.processing_status = DocumentProcessingStatus.COMPLETED.value

    orchestrator, _ = _orchestrator(
        sessions,
        tmp_path,
        FakeScanner(MalwareScanStatus.INFECTED),
    )
    result = await orchestrator.run(job_id, run_id)

    assert result.disposition is OrchestrationDisposition.FAILED
    async with sessions() as session:
        document = await session.get(Document, document_id)
        previous = await session.get(DocumentProcessingRun, previous_run_id)
        failed = await session.get(DocumentProcessingRun, run_id)
        assert document is not None and previous is not None and failed is not None
        assert document.current_processing_run_id == previous_run_id
        assert previous.status == DocumentProcessingStatus.COMPLETED.value
        assert failed.status == DocumentProcessingStatus.FAILED.value


@pytest.mark.asyncio
async def test_duplicate_in_progress_delivery_does_not_execute_boundaries(orchestration_context):
    sessions, ids, tmp_path = orchestration_context
    _, _, _, job_id, run_id = ids
    async with sessions.begin() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        job = await session.get(Job, job_id)
        assert run is not None and job is not None
        run.status = DocumentProcessingStatus.IN_PROGRESS.value
        run.current_stage = IngestionStage.SCANNING.value
        job.status = ProcessingStatus.IN_PROGRESS.value
        job.current_step = IngestionStage.SCANNING.value
    orchestrator, storage = _orchestrator(
        sessions,
        tmp_path,
        FakeScanner(MalwareScanStatus.CLEAN),
    )

    result = await orchestrator.run(job_id, run_id)

    assert result.disposition is OrchestrationDisposition.DUPLICATE
    assert storage.download_count == 0


@pytest.mark.asyncio
async def test_worker_cancellation_cleans_workspace_and_leaves_recoverable_heartbeat(
    orchestration_context,
):
    sessions, ids, tmp_path = orchestration_context
    _, _, _, job_id, run_id = ids

    class CancellingScanner(FakeScanner):
        async def scan(self, path: Path) -> MalwareScanResult:
            self.scanned_paths.append(path)
            raise asyncio.CancelledError

    scanner = CancellingScanner(MalwareScanStatus.CLEAN)
    orchestrator, _ = _orchestrator(sessions, tmp_path, scanner)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.run(job_id, run_id)

    assert len(scanner.scanned_paths) == 1
    assert not scanner.scanned_paths[0].exists()
    async with sessions() as session:
        run = await session.get(DocumentProcessingRun, run_id)
        assert run is not None
        assert run.status == DocumentProcessingStatus.IN_PROGRESS.value
        assert run.last_heartbeat_at is not None
