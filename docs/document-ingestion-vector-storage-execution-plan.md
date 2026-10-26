# Document Ingestion and Vector Storage Execution Plan

## Document Status

- Status: implementation ready
- Scope owner: WBS document ingestion
- Runtime target: release-grade services only
- Vector store: Neon PostgreSQL with pgvector
- Embedding runtime: FastEmbed with `BAAI/bge-small-en-v1.5`
- Embedding dimensions: 384
- Last updated: 2026-10-24

Detailed step-by-step execution documents are indexed in
`docs/document-ingestion-vector-storage-steps/README.md`.

## Outcome

A tenant-authorized user uploads a project document, the original file is stored privately in Neon
Object Storage, and a Celery worker securely downloads, scans, extracts, normalizes, chunks, embeds,
and stores the content in Neon pgvector. Every stored chunk retains enough source information to
trace it back to its document location.

The completed feature ends when the document has an active, successfully persisted vector ingestion.
Summary generation, WBS generation, and agentic behavior are explicitly outside this plan.

## Scope

### Included

- release-grade upload and processing of PDF, DOCX, XLSX, and CSV files;
- text extraction from text PDFs and OCR for scanned PDFs;
- source-aware extraction of Word paragraphs, headings, lists, and tables;
- source-aware extraction of Excel worksheets, headers, and row ranges;
- deterministic normalization and chunking;
- CPU embedding with FastEmbed in the release worker;
- tenant-, project-, and document-scoped vector persistence in Neon;
- asynchronous progress, retry, failure, reprocessing, and deletion behavior;
- application filtering and PostgreSQL Row-Level Security;
- unit, integration, security, browser, and release verification.

### Excluded

- LLM calls and summary generation;
- autonomous or tool-using agents;
- WBS generation and validation;
- public semantic-search or chat endpoints;
- `.doc` and `.xls` support unless a separately reviewed conversion service is approved;
- separate local storage, local database, eager-task, or alternate embedding behavior.

## Locked Architecture Decisions

1. All deployed environments use the same execution path. Environment-specific resources may be
   isolated, but runtime behavior must not change.
2. Original files are stored only in Neon S3-compatible object storage.
3. Runtime data and vectors are stored only in Neon PostgreSQL.
4. Database changes are applied only through Alembic.
5. Ingestion always runs through Celery and Redis. FastAPI `BackgroundTasks` is not a release
   ingestion runner.
6. FastEmbed runs inside the Celery worker image. The model is packaged at build time and is not
   downloaded when a request is processed.
7. `BAAI/bge-small-en-v1.5` produces 384-dimensional vectors, so the initial column type is
   `VECTOR(384)`.
8. Parser output and chunks are untrusted data. They never become executable instructions.
9. Tenant and project scope are mandatory on every chunk read, write, update, and delete.
10. Test doubles are allowed in automated tests, but they do not create a second deployed runtime.

## Current Repository Baseline

Already implemented:

- React accepts `.pdf` in `WBS_UI/src/views/CreateWbsScreen.tsx`;
- FastAPI accepts PDF, DOC/DOCX, XLS/XLSX, and CSV in
  `backend/app/api/routes/documents.py`;
- upload validation checks size, declared type, PDF signature, Office ZIP structure, legacy Office
  signature, and basic archive safety in `backend/app/services/storage.py`;
- S3-compatible upload and deletion use private generated tenant/project object keys;
- `Document`, `Job`, and `DocumentSummary` records already exist;
- Celery dispatch and job polling already exist;
- tenant authorization is applied to document and summary routes.

Not implemented:

- structural PDF parsing or scanned-PDF OCR;
- object download through the storage abstraction;
- DOCX, XLSX, or CSV extraction services;
- normalized source blocks and deterministic chunking;
- pgvector extension, vector columns, processing-run records, or chunk records;
- FastEmbed dependency, model packaging, batching, or health checks;
- ingestion-specific API, job type, statuses, retries, and UI presentation;
- RLS for extracted document content;
- deletion and reprocessing across object, chunk, and vector lifecycles;
- real-file integration tests for the complete pipeline.

The current `process_document_summary()` creates placeholder content. This plan introduces a separate
document-ingestion workflow instead of adding extraction behavior to that placeholder.

## Target Flow

```text
React Create WBS screen
        |
        | POST multipart document
        v
FastAPI authorization and upload validation
        |
        | private generated object key
        v
Neon Object Storage + Document metadata
        |
        | POST document ingestion
        v
Celery job queued through Redis
        |
        v
Worker downloads to an isolated temporary directory
        |
        v
Malware scan -> structural validation -> format extractor/OCR
        |
        v
Normalized source blocks -> deterministic chunks
        |
        v
FastEmbed batch embedding -> 384-dimensional vectors
        |
        v
Transactional pgvector persistence -> activate processing run
        |
        v
Document READY_FOR_SUMMARY
```

## Functional Requirements

### Upload

- A user with `document:upload` can upload one project document to an authorized project.
- The original filename is display metadata only and is never used as a storage or temporary path.
- PDF selection must work through the picker and drag-and-drop.
- The server treats browser MIME type as advisory and accepts a generic binary MIME type only when
  the extension, signature, and structural parser all confirm the expected format.
- Unsupported, encrypted, empty, malformed, oversized, or unsafe files fail with a stable public
  error code and a non-sensitive message.

### Processing

- Upload and ingestion are separate operations so an uploaded object is not lost when processing
  must be retried.
- Only one active ingestion may run for a document at a time.
- Repeating an ingestion request for an identical completed document/model/extractor combination is
  idempotent and returns the completed run.
- A failed new run never replaces a previously completed active run.
- The UI can display queued, scanning, extracting, chunking, embedding, persisting, ready, and failed
  states.

### Extracted Content

- Every block and chunk preserves source order.
- PDF content includes page number and OCR status.
- DOCX content includes heading path and block/table position.
- XLSX content includes worksheet name and row range, with column headers repeated in each chunk.
- CSV content includes row range and normalized headers.
- Empty or near-empty extraction fails with `NO_EXTRACTABLE_CONTENT`.

### Vector Storage

- Every active chunk has one normalized 384-dimensional vector.
- Every chunk stores `tenant_id`, `project_id`, `document_id`, processing-run ID, content, ordinal,
  token count, content hash, and source metadata.
- Raw vectors are never returned by a public API.
- Reprocessing switches the active run atomically only after all chunks and vectors are persisted.
- Deleting a document removes active and historical chunks before or transactionally with metadata
  deletion, and schedules retryable object deletion.

## Release Tooling

| Concern | Selected tool | Usage |
| --- | --- | --- |
| Browser upload | React `File` and `FormData` | Selection, client validation, and progress UI |
| API | FastAPI `UploadFile` | Authorization, multipart parsing, and job creation |
| Object storage | Existing `boto3` S3 client | Private upload, streaming download, head, and delete |
| Queue | Celery and Redis | Durable asynchronous ingestion |
| PDF text | `pypdf` | Page-aware text extraction and structural checks |
| PDF OCR | OCRmyPDF and Tesseract | Searchable text for scanned/image-only PDFs |
| Word | `python-docx` | DOCX headings, paragraphs, lists, and tables |
| Excel | `openpyxl` | XLSX read-only, data-only worksheet iteration |
| CSV | Python `csv` | Delimited row extraction with explicit encoding rules |
| XML hardening | `defusedxml` | Safer XML parsing used by Office-related dependencies |
| Chunking | Application service | Deterministic source-aware splitting |
| Token counting | Hugging Face `tokenizers` with the packaged BGE tokenizer | Model-aligned chunk limit enforcement |
| Embeddings | `fastembed` | Batched CPU ONNX embeddings |
| Vector ORM | `pgvector` Python package | SQLAlchemy `Vector(384)` integration |
| Migrations | Alembic | Extension, tables, constraints, indexes, and policies |
| Malware scanning | ClamAV daemon/client | Scan downloaded files before parsing |
| Metrics | Existing Prometheus integration | Ingestion latency, failures, and volume |
| Verification | Pytest and Playwright | Unit, integration, security, and browser tests |

## Configuration Contract

Add release settings with validation in `backend/app/core/config.py` and examples without secret
values in `backend/.env.example`:

```dotenv
DOCUMENT_INGESTION_ENABLED=true
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
EMBEDDING_BATCH_SIZE=32
EMBEDDING_MODEL_PATH=/opt/wbs-models/bge-small-en-v1.5
DOCUMENT_PROCESSING_TIMEOUT_SECONDS=900
DOCUMENT_MAX_PDF_PAGES=500
DOCUMENT_MAX_WORKSHEETS=100
DOCUMENT_MAX_ROWS_PER_SHEET=100000
DOCUMENT_MAX_EXTRACTED_CHARACTERS=10000000
DOCUMENT_CHUNK_TARGET_TOKENS=400
DOCUMENT_CHUNK_OVERLAP_TOKENS=50
OCR_ENABLED=true
MALWARE_SCAN_REQUIRED=true
CLAMAV_HOST=<private-service-host>
CLAMAV_PORT=3310
```

Production validation must additionally reject:

- `STORAGE_BACKEND` other than `s3`;
- SQLite or a PostgreSQL URL without required TLS;
- missing direct migration URL;
- `TASKS_EAGER=true`;
- missing or local-only Redis configuration;
- embedding provider other than `fastembed` for this release;
- embedding dimensions other than 384;
- a missing or unreadable packaged model path;
- disabled malware scanning or OCR when the release declares those capabilities;
- `AUTO_CREATE_TABLES=true`.

The API and worker must expose readiness failure when required storage, database, Redis, scanner, or
model dependencies are unavailable. The API should not load the embedding model; only ingestion
workers require model readiness.

## Data Model

### Document changes

Add to `documents`:

- `content_sha256`: nullable until upload hashing is complete;
- `current_processing_run_id`: nullable foreign key to the active completed run;
- `processing_status`: uploaded, queued, processing, ready, failed, or deleting;
- `processed_at`: nullable timestamp;
- `processing_error_code`: nullable stable machine-readable code.

Add a uniqueness constraint on `(id, tenant_id, project_id)` so child records can enforce composite
tenant/project ownership.

### `document_processing_runs`

Required columns:

- `id` UUID primary key;
- `tenant_id`, `project_id`, and `document_id` UUIDs;
- `job_id` UUID;
- `status`;
- `content_sha256`;
- `extractor_name` and `extractor_version`;
- `embedding_provider`, `embedding_model`, and `embedding_dimensions`;
- `page_count`, `worksheet_count`, `block_count`, and `chunk_count`;
- `started_at`, `completed_at`, and `failed_at`;
- `error_code` and sanitized `error_message`;
- timestamps.

Constraints and indexes:

- composite foreign key to `(documents.id, documents.tenant_id, documents.project_id)`;
- foreign key to the ingestion job;
- index on `(tenant_id, project_id, document_id, created_at)`;
- unique idempotency key across document hash, extractor version, and embedding model;
- partial protection against more than one queued/in-progress run per document.

### `document_chunks`

Required columns:

- `id` UUID primary key;
- `processing_run_id`, `tenant_id`, `project_id`, and `document_id`;
- `ordinal` integer;
- `content` text;
- `token_count` integer;
- `content_sha256` string;
- `block_type` string;
- `page_number`, `sheet_name`, `row_start`, and `row_end` nullable source fields;
- `heading_path` JSON;
- `source_metadata` JSON;
- `embedding VECTOR(384)`;
- timestamps.

Constraints and indexes:

- composite ownership foreign keys;
- `UNIQUE(processing_run_id, ordinal)`;
- `UNIQUE(processing_run_id, content_sha256, ordinal)` or an equivalent deterministic key;
- B-tree index on `(tenant_id, project_id, document_id, processing_run_id)`;
- no HNSW index initially. Add it only after a measured filtered-search benchmark justifies it.

Use PostgreSQL JSONB rather than generic JSON for new PostgreSQL-only metadata columns.

## Isolation and Row-Level Security

Isolation hierarchy:

1. `tenant_id` is the mandatory security boundary.
2. `project_id` is the mandatory retrieval and correctness boundary.
3. `document_id` is the lifecycle, provenance, preview, and per-document processing boundary.
4. User-level vector isolation is not required while project access is inherited from tenant roles.

Application rules:

- derive tenant scope only from authenticated `TenantContext` or the trusted job record;
- verify project ownership before creating an ingestion;
- never accept tenant scope from document content, model output, or an unchecked payload;
- include tenant and project predicates in every repository method;
- never perform an unscoped nearest-neighbor query.

Database rules:

- use separate migration-owner and runtime database roles;
- ensure the runtime role does not own tables and does not have `BYPASSRLS`;
- enable and force RLS on processing-run and chunk tables;
- set `app.tenant_id` with `SET LOCAL` inside each request or worker transaction;
- make policies apply to both `USING` and `WITH CHECK`;
- fail closed when tenant context is absent or malformed;
- test connection reuse to prove a previous tenant context cannot leak through the pool.

## Processing State Machine

```text
UPLOADED
  -> QUEUED
  -> SCANNING
  -> EXTRACTING
  -> NORMALIZING
  -> CHUNKING
  -> EMBEDDING
  -> PERSISTING
  -> READY

Any processing state -> FAILED
FAILED -> QUEUED through an authorized retry
READY -> QUEUED for a versioned reprocessing run
Any non-deleting state -> DELETING -> DELETED
```

Suggested progress ranges:

- queued: 0-5;
- scanning: 5-15;
- extraction/OCR: 15-50;
- normalization and chunking: 50-65;
- embedding: 65-90;
- persistence and activation: 90-100.

Progress must be monotonic. Public failures expose a stable code; detailed exception text remains in
restricted logs after redaction.

## Step-by-Step Development

### Step 1: Establish the release configuration gate

Files expected to change:

- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/README.md`
- configuration tests

Tasks:

1. Add and validate the ingestion, parser, OCR, scanner, chunking, and embedding settings.
2. Reject eager tasks and non-S3 storage in production.
3. Validate that the configured embedding dimension is exactly 384.
4. Add a worker-specific readiness check for the packaged FastEmbed model.
5. Document that `.env` is illustrative only and release secrets come from the deployment secret
   manager.

Exit criteria:

- insecure or incomplete release configuration fails during process startup;
- no secret is added to source control or the Docker image;
- API and worker requirements are independently testable.

### Step 2: Verify and complete PDF upload support

Files expected to change:

- `WBS_UI/src/views/CreateWbsScreen.tsx`
- `backend/app/api/routes/documents.py`
- `backend/app/services/storage.py`
- upload tests and browser tests

Tasks:

1. Reproduce picker and drag-and-drop upload with a genuine text PDF.
2. Capture and display the actual API error instead of treating every failure as unsupported format.
3. Keep extension and signature validation, but treat MIME as advisory.
4. Accept `application/octet-stream` only when PDF signature and parser validation succeed.
5. Parse the trailer/xref structure after storage download before the file enters extraction.
6. Return stable error codes for encrypted, malformed, oversized, and unsupported files.
7. Remove `.doc` and `.xls` from UI and API allowlists for the initial release unless conversion is
   approved and implemented in the same release.

Exit criteria:

- real text and scanned PDFs upload successfully;
- renamed or spoofed files are rejected;
- corrupt and encrypted PDFs fail safely;
- upload permissions and tenant/project checks remain enforced.

### Step 3: Add pgvector and ingestion schema

Files expected to change:

- `backend/pyproject.toml`
- `backend/app/models/domain.py`
- `backend/app/models/__init__.py`
- a new Alembic migration
- database and migration tests

Tasks:

1. Add the `pgvector` Python package.
2. Create the PostgreSQL `vector` extension through Alembic using the migration credential.
3. Add processing-run and chunk models, enums, constraints, and indexes.
4. Add document processing fields and the active-run relationship.
5. Add RLS policies and grants for the runtime role.
6. Make downgrade remove application objects without dropping a shared extension unless operations
   explicitly approve extension removal.
7. Confirm migrations use the direct Neon URL and application queries use the pooled URL.

Exit criteria:

- a clean Neon branch migrates to head successfully;
- `VECTOR(384)` is visible and writable;
- an unauthorized tenant session cannot read or insert another tenant's chunks;
- schema downgrade/forward-fix behavior is documented.

### Step 4: Add secure object download and scanning

Files expected to change:

- `backend/app/services/storage.py`
- new malware-scanning service
- storage and scanner tests

Tasks:

1. Extend the storage protocol with streaming download to a generated temporary file.
2. Add S3 `head_object` checks for expected size and metadata before download.
3. Resolve temporary paths beneath a dedicated worker-owned directory.
4. Hash the downloaded bytes with SHA-256 while streaming.
5. Compare downloaded size and hash with persisted metadata when available.
6. Scan the completed file with ClamAV before invoking a parser.
7. Delete temporary input, OCR output, and intermediate artifacts in `finally`.
8. Distinguish retryable storage/scanner unavailability from permanent infected-file rejection.

Exit criteria:

- large files are streamed rather than loaded into memory;
- a scanner detection prevents parsing and embedding;
- temporary artifacts are removed on success, failure, cancellation, and worker timeout.

### Step 5: Build the extraction contract

New package structure:

```text
backend/app/services/ingestion/
  __init__.py
  types.py
  registry.py
  normalization.py
  chunking.py
  orchestrator.py
  extractors/
    pdf.py
    docx.py
    xlsx.py
    csv.py
  embeddings/
    base.py
    fastembed_provider.py
  repository.py
```

Define an `ExtractedBlock` containing:

- text;
- block type;
- source ordinal;
- page number;
- sheet name;
- row start/end;
- heading path;
- extraction method such as native or OCR;
- safe structured metadata.

Define an extractor protocol that accepts a trusted temporary path and configured limits, streams or
iterates content where possible, and returns ordered blocks plus extraction statistics.

Exit criteria:

- extractor selection is based on the server-confirmed format;
- all extractors produce the same normalized contract;
- unsupported formats fail before processing begins.

### Step 6: Implement PDF extraction and OCR

Tasks:

1. Open the PDF with `pypdf` under page, content-stream, memory, and task-time limits.
2. Extract native text page by page and preserve the page number.
3. Detect image-only or low-text pages using a documented threshold.
4. Run OCRmyPDF/Tesseract only when OCR is required.
5. Re-open OCR output and extract searchable text through the same block contract.
6. Avoid duplicate native and OCR text on mixed-content pages.
7. Remove repeated headers and footers only when the deterministic repetition threshold is met.
8. Reject password-protected PDFs without logging passwords or document content.

Tests:

- text PDF;
- multi-page PDF;
- scanned PDF;
- mixed native/scanned PDF;
- encrypted PDF;
- malformed xref/trailer;
- oversized page count;
- decompression/content-stream resource abuse.

Exit criteria:

- text and scanned PDFs produce ordered, page-referenced blocks;
- parser failures are bounded and do not crash the worker process;
- OCR intermediates are deleted.

### Step 7: Implement DOCX, XLSX, and CSV extraction

DOCX tasks:

1. Read paragraphs and tables in document order.
2. Track heading hierarchy and list context.
3. Convert tables into deterministic row-oriented text while preserving headers.
4. Ignore executable content and do not fetch external relationships.

XLSX tasks:

1. Use read-only and data-only workbook loading.
2. Enforce worksheet, row, column, and non-empty-cell limits.
3. Preserve worksheet name and row range.
4. Treat formulas as stored values only and never evaluate them.
5. Detect suspiciously incorrect worksheet dimensions and bound any correction.

CSV tasks:

1. Accept UTF-8 with optional BOM for the first release.
2. Detect delimiter from an allowlist and cap field/row lengths.
3. Preserve headers and row ranges.
4. Neutralize spreadsheet formula prefixes only in exported previews, not by silently changing
   canonical source text.

Exit criteria:

- supported files produce ordered, source-aware blocks;
- macro-enabled, legacy, encrypted, malformed, and over-limit documents fail safely;
- extraction never executes formulas, macros, links, or embedded objects.

### Step 8: Implement normalization and deterministic chunking

Tasks:

1. Normalize line endings, Unicode whitespace, and control characters without losing meaningful
   numbering or WBS codes.
2. Preserve headings, requirement identifiers, table headers, units, dates, and numeric values.
3. Drop empty blocks and record extraction warnings.
4. Split around 400 model tokens with approximately 50 tokens of overlap.
5. Never exceed the model's 512-token sequence limit after query/document formatting.
6. Prefer section, paragraph, table-row, and page boundaries over arbitrary token cuts.
7. Repeat spreadsheet/table headers in subsequent chunks.
8. Generate stable chunk ordinals and SHA-256 hashes.
9. Validate that concatenated non-overlap content covers all retained source blocks.

Exit criteria:

- repeated execution against the same extracted blocks produces identical chunks and hashes;
- no chunk exceeds the configured token ceiling;
- source locations remain traceable after overlap and splitting.

### Step 9: Package and integrate FastEmbed

Files expected to change:

- `backend/pyproject.toml`
- `backend/Dockerfile`
- new embedding-provider package
- worker readiness and embedding tests

Tasks:

1. Add a pinned compatible `fastembed` dependency.
2. Download the exact approved model revision during the builder stage.
3. Verify artifact checksums and copy the read-only model cache into the runtime image.
4. Ensure the non-root worker user can read but cannot modify packaged model files.
5. Initialize one model instance per worker process, not per chunk.
6. Batch chunks using the configured batch size and bound concurrency to worker capacity.
7. Verify every result is finite, normalized as expected, and exactly 384 dimensions.
8. Record provider, model, revision, and dimension on the processing run.
9. Disable runtime fallback to a network embedding provider.

Exit criteria:

- the worker starts without downloading artifacts;
- an offline worker can embed a known fixture;
- deterministic fixture input produces dimensionally valid vectors;
- missing/corrupt model artifacts fail worker readiness.

### Step 10: Implement transactional vector persistence

Tasks:

1. Create repository methods that require tenant, project, document, and processing-run scope.
2. Insert chunks in bounded batches within the new run.
3. Validate chunk and vector counts before activation.
4. Mark the processing run completed and update `documents.current_processing_run_id` in one
   transaction.
5. Roll back incomplete database batches on failure.
6. Retain a previous active run until the new run is successfully activated.
7. Schedule deletion of superseded runs according to the approved retention policy.
8. Add an internal verification query using exact cosine distance and mandatory tenant/project
   filters. Do not expose it publicly in this scope.

Exit criteria:

- partial runs never become active;
- a reprocessing failure preserves the previous active vectors;
- exact filtered retrieval returns only authorized project chunks;
- duplicate delivery of a Celery task does not duplicate active data.

### Step 11: Add ingestion orchestration and APIs

Backend API contract:

- `POST /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions` -> `202 JobResponse`;
- `GET /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions/current`;
- existing job status endpoint for progress polling;
- optional paginated extraction preview without embeddings.

Tasks:

1. Add `DOCUMENT_INGESTION` job type and Celery task.
2. Create the processing run and job transactionally before dispatch.
3. Make dispatch failure visible and retryable without creating orphaned runs.
4. Update job progress after durable stage boundaries rather than for every chunk.
5. Map internal exceptions to stable ingestion error codes.
6. Add authorized retry and cancellation behavior.
7. Prevent summary or WBS generation unless the document has an active ready run.

Exit criteria:

- API restart does not lose queued ingestion work;
- Celery retry is idempotent;
- unauthorized roles cannot start, inspect, retry, or cancel ingestion;
- job and processing-run states cannot contradict each other after reconciliation.

### Step 12: Integrate the React workflow

Files expected to change:

- `WBS_UI/src/services/documentsApi.ts`
- `WBS_UI/src/services/workflowApi.ts`
- workflow types and presentation helpers
- `CreateWbsScreen.tsx`
- processing screen and tests

Tasks:

1. Upload the document through the existing endpoint.
2. Start document ingestion instead of immediately calling the placeholder summary endpoint.
3. Poll the existing job status API with cancellation on unmount.
4. Present all ingestion states and actionable failure messages.
5. Show filename, size, detected format, extracted page/sheet count, and chunk count after completion.
6. Do not expose vectors, object keys, internal exception text, or tenant identifiers unnecessarily.
7. Decide the milestone behavior after readiness: display `Document processed` or continue to the
   future summary step only after summary implementation is available.

Exit criteria:

- a user can upload and observe PDF processing through vector persistence;
- refresh/re-entry restores status from the backend rather than restarting work;
- optional WBS template upload remains independent of project-document ingestion.

### Step 13: Implement deletion, retention, and reconciliation

Tasks:

1. Replace immediate hard deletion with a retryable deleting state or an outbox-backed cleanup.
2. Remove chunk and run records under tenant/project scope.
3. Delete the original object and any derived artifacts.
4. Reconcile orphaned objects, runs, chunks, and jobs on a schedule.
5. Define retention for failed and superseded runs.
6. Emit an audit event without including document text.

Exit criteria:

- deletion is complete or visibly retryable;
- no document can leave searchable vectors after authorized deletion completes;
- reconciliation is tenant-safe and idempotent.

## Test Plan

### Unit tests

- format detection and error mapping;
- each extractor with safe fixtures;
- normalization and stable chunk hashes;
- token ceilings and overlap;
- fake embedding provider for orchestration tests;
- 384-dimension validation;
- idempotency, retries, state transitions, and deletion logic;
- log redaction.

### PostgreSQL and pgvector integration tests

- clean Alembic migration on a disposable Neon branch or equivalent PostgreSQL with pgvector;
- vector insertion and exact cosine query;
- transaction rollback for partial batches;
- active-run switch during reprocessing;
- RLS read/write denial across tenants;
- project filter denial inside the same tenant;
- pooled connection tenant-context reset;
- cascade and cleanup behavior.

SQLite is not evidence for pgvector, RLS, PostgreSQL JSONB, or vector-query correctness.

### Object-storage integration tests

- private generated key;
- streaming download;
- size/hash mismatch;
- missing object;
- timeout and retry;
- delete and reconciliation;
- credentials never appear in logs.

### Full workflow tests

- PDF picker and drag-and-drop;
- text PDF from upload through active vectors;
- scanned PDF through OCR and vectors;
- DOCX with headings and tables;
- XLSX with multiple worksheets;
- CSV with headers and quoted delimiters;
- refresh while processing;
- worker retry and duplicate task delivery;
- cross-tenant and cross-project denial;
- document deletion removes vector visibility.

### Performance and abuse tests

- maximum allowed PDF pages;
- maximum allowed workbook size;
- high compression ratio Office archive;
- pathological PDF content stream;
- slow scanner, storage, and model dependencies;
- concurrent ingestion limit per tenant;
- worker memory and CPU limits;
- embedding batch throughput and total processing timeout.

## Security Requirements

- Rotate any previously exposed object-storage credentials before deployment.
- Keep object-storage, Redis, database, and deployment credentials in the approved secret manager.
- Use TLS for database, Redis when externally hosted, object storage, and public endpoints.
- Keep the bucket private and never expose permanent object URLs.
- Scan before parsing.
- Parse only allowlisted formats and reject macro-enabled or executable content.
- Run API and workers as non-root users with read-only application/model filesystems where possible.
- Bound parser CPU, memory, file size, page count, row count, extracted characters, and task duration.
- Treat extracted content as data, not instructions.
- Do not log document content, embeddings, cookies, tokens, credentials, or storage URLs.
- Enforce tenant and project scope in authorization, repository predicates, constraints, and RLS.
- Perform dependency, image, model-artifact, and license review before release.

## Observability

Metrics:

- ingestion requests by status and format;
- queue wait and total processing duration;
- scan, extraction, OCR, chunking, embedding, and persistence duration;
- pages, sheets, blocks, chunks, and embedded tokens;
- retry, timeout, cancellation, and failure counts by safe error code;
- worker memory/CPU saturation;
- storage, Redis, scanner, database, and model readiness.

Logs and traces use job, processing-run, document, project, and tenant opaque IDs. They must not
contain extracted text or raw vector values.

Alerts:

- sustained ingestion failure rate;
- queue age above target;
- malware detection;
- scanner or model readiness failure;
- storage or database outage;
- repeated RLS denial or unscoped-query assertion;
- orphan reconciliation backlog;
- worker out-of-memory or hard time-limit termination.

## Recommended Pull Request Sequence

1. Release configuration and dependency contract.
2. PDF upload verification and supported-format correction.
3. pgvector schema, ownership constraints, and RLS.
4. object download, hashing, malware scan, and temporary-file lifecycle.
5. extraction contracts plus PDF/OCR, DOCX, XLSX, and CSV extractors.
6. normalization, deterministic chunking, and unit tests.
7. FastEmbed model packaging and embedding provider.
8. transactional vector repository and idempotent ingestion orchestration.
9. API, Celery task, job progress, and React integration.
10. deletion/reconciliation, security tests, performance evidence, and release runbook.

Each pull request must leave migrations, tests, and release configuration internally consistent. Do
not merge a UI-advertised format before its upload and extraction path passes end-to-end tests.

## Release Sequence

1. Rotate and inject approved credentials.
2. Build immutable API and worker images, including pinned OCR packages and FastEmbed model files.
3. Produce dependency/model inventories and scan both images.
4. Verify Neon backup/restore point.
5. Apply Alembic migration with the restricted direct migration credential.
6. Verify pgvector extension, schema, grants, and RLS policies.
7. Deploy Redis, scanner, and worker dependencies.
8. Start workers and verify model/scanner/storage/database readiness.
9. Deploy the API and keep it out of traffic until readiness passes.
10. Deploy the UI.
11. Run the real-file smoke suite using an isolated release test tenant/project.
12. Enable a limited tenant cohort, monitor, and then expand.
13. Record migration, test, security-scan, and smoke-test evidence.

## Rollback and Forward-Fix

- Disable new ingestion creation while allowing active jobs to finish or cancel safely.
- Keep original uploaded objects and previously active processing runs.
- Do not switch documents to incomplete runs.
- Prefer a forward database fix after vector data has been written.
- If worker code is rolled back, it must understand or safely ignore the current job/status values.
- Never drop the pgvector extension or chunk tables as an automatic application rollback.

## Definition of Done

- [ ] Real PDF selection, drag-and-drop, upload, and storage pass in the release environment.
- [ ] Text and scanned PDFs produce page-referenced chunks.
- [ ] DOCX, XLSX, and CSV produce source-referenced chunks.
- [ ] Legacy `.doc` and `.xls` are either fully supported through an approved converter or removed
      from advertised formats.
- [ ] The release worker embeds chunks with packaged `BAAI/bge-small-en-v1.5` without network model
      download.
- [ ] Every stored vector has exactly 384 finite dimensions.
- [ ] New runs activate atomically and retries do not duplicate active chunks.
- [ ] Tenant and project isolation pass application and RLS negative tests.
- [ ] Deletion removes vector visibility and completes object cleanup or exposes a retryable state.
- [ ] API/UI processing states survive refresh and service restart.
- [ ] Resource limits, malware scanning, OCR cleanup, and log redaction are verified.
- [ ] Migration, release smoke, performance, and security evidence are recorded.
- [ ] No unresolved critical or high-severity release finding remains.

## Handoff to Summary Development

Summary development may begin only after a document exposes an active `READY` processing run. The
summary workflow must read all ordered chunks for that run rather than using a top-k similarity query.
Later WBS retrieval may use pgvector similarity search, but it must always include authenticated
tenant and authorized project filters.
