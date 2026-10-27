# WBS Generator Backend

FastAPI boilerplate for the tenant-aware WBS generation workflow. It includes:

- async FastAPI and SQLAlchemy
- SQLite for zero-configuration local development
- Neon-ready pooled runtime and direct migration connections
- PostgreSQL and Redis through Docker Compose
- Celery worker wiring for long-running document and AI tasks
- Argon2id local passwords, short-lived JWT access tokens, and rotating refresh sessions
- backend-managed OIDC Authorization Code with PKCE and internal application sessions
- database-backed role permissions on every tenant-owned operation
- local development storage and private S3-compatible Neon Object Storage
- document summary, WBS generation, validation, and export placeholders
- OpenAPI documentation and end-to-end contract tests

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open:

- API documentation: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Readiness check: `http://127.0.0.1:8000/api/v1/health/ready`

Development mode automatically provisions this tenant ID:

```text
00000000-0000-0000-0000-000000000001
```

No bearer token is required while `AUTH_MODE=development`.

## Use Neon Object Storage

The document and WBS template upload endpoints use local disk by default. To use a private Neon
bucket, create a fresh storage credential and place these values only in the untracked `.env` file
or your deployment secret manager:

```dotenv
STORAGE_BACKEND=s3
OBJECT_STORAGE_BUCKET=assets
AWS_ENDPOINT_URL_S3=https://YOUR-ENDPOINT.storage.REGION.aws.neon.tech
AWS_ACCESS_KEY_ID=YOUR-NEW-KEY-ID
AWS_SECRET_ACCESS_KEY=YOUR-NEW-SECRET
AWS_REGION=us-east-2
```

Restart the API after changing storage settings. `GET /api/v1/health/ready` verifies access to the
configured bucket. Uploads continue through the authenticated API; the backend validates the
declared type, file signature, actual byte size, tenant/project ownership, and writes a generated
key such as `tenants/{tenant}/projects/{project}/documents/{uuid}.pdf`. Original filenames remain
database metadata and are never used as object keys. Do not make the bucket public and do not place
S3 credentials in `WBS_UI` environment variables.

The project-document release formats are PDF, DOCX, XLSX, and CSV. Legacy DOC and XLS formats are
rejected because no approved conversion path exists. A PDF declared as `application/octet-stream`
is accepted only when its `.pdf` extension, binary signature, and `pypdf` structure validation all
agree; stored PDF metadata is normalized to `application/pdf`. The upload request performs only
structure and encryption checks, not text extraction, rendering, OCR, or malware scanning.

Project upload failures use a stable `{"detail":{"code":"...","message":"..."}}` response:

| Code | HTTP status |
| --- | --- |
| `DOCUMENT_EMPTY` | 400 |
| `DOCUMENT_TOO_LARGE` | 413 |
| `UNSUPPORTED_DOCUMENT_FORMAT` | 415 |
| `DOCUMENT_TYPE_MISMATCH` | 415 |
| `PDF_MALFORMED` | 422 |
| `PDF_ENCRYPTED` | 422 |
| `OBJECT_STORAGE_UNAVAILABLE` | 503 |

These errors never contain storage keys, bucket names, provider diagnostics, private endpoints, or
parser exceptions. Database failure after an object write invokes bounded cleanup through the same
private storage abstraction before the original failure is propagated.

## Enable local authentication

Apply migrations, provision the first administrator, and then enable local authentication:

```powershell
cd backend
alembic current
alembic upgrade head
alembic check
python -m app.cli create-admin --email admin@example.com --display-name "WBS Admin" --tenant-slug default --tenant-name "Default Workspace"
```

The command prompts for the password without placing it in shell history. Use at least 12
characters. Then generate separate high-entropy values for `AUTH_JWT_SECRET` and
`AUTH_AUDIT_SECRET`, set `AUTH_MODE=local`, and restart the API. Never commit these values.
The API readiness endpoint returns `503` in local or hybrid mode until an active administrator has
an active tenant, an `ADMIN` membership, and a usable local identity.

If the email already belongs to a verified user, review that record first and explicitly add
`--link-existing-user`. The command otherwise refuses to attach a new password to an existing
account. All tenant, user, identity, and membership changes are committed as one transaction.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run the UI with `VITE_API_URL=http://127.0.0.1:8000/api/v1`. Access tokens remain in browser
memory; the rotating refresh credential is sent only as an HttpOnly cookie.

The `/me` response includes the current role and derived permission strings for every active tenant
membership. Tenant routes recalculate permissions from the database on every request, so a role
change or membership removal takes effect without waiting for the access token to expire. The
OpenAPI document lists the expected `401`, `403`, and non-disclosing `404` outcomes.

## Enable password recovery

Password recovery is off by default. Apply migration `d7f3c2a91e60`, configure a verified SMTP
sender, and set the public UI origin before enabling it:

```dotenv
PASSWORD_RECOVERY_ENABLED=true
PUBLIC_UI_URL=https://wbs.example.com
EMAIL_PROVIDER=smtp
EMAIL_FROM=no-reply@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=secret-managed-value
SMTP_PASSWORD=secret-managed-value
SMTP_SECURITY=starttls
```

Production startup rejects HTTP reset origins, missing SMTP credentials, unencrypted SMTP, and the
test email provider. The reset secret has 256 bits of entropy, expires within 30 minutes, is stored
only as a SHA-256 digest, and is carried in the email URL fragment so it is not sent to the UI web
server. A successful reset increments the user's auth version and revokes every refresh session.

Enable `VITE_PASSWORD_RECOVERY_ENABLED=true` only after the schema and backend configuration are
live. Also apply an edge rate limit to both recovery endpoints. Schedule this command daily to
remove only used or expired records older than `PASSWORD_RESET_RETENTION_DAYS`:

```powershell
python -m app.cli cleanup-password-reset-tokens
```

If email delivery fails, turn off the UI flag first and then `PASSWORD_RECOVERY_ENABLED`; never log
or display reset links as a fallback. Validate the sender domain, delivery, expiry, reuse rejection,
and spam handling in staging before production activation.

## Enable tenant invitations

Apply migration `e6b91f2c4a73`, configure the same verified email provider and public UI origin used
for recovery, and then enable invitations:

```dotenv
TENANT_INVITATIONS_ENABLED=true
TENANT_INVITATION_HOURS=72
TENANT_INVITATION_RETENTION_DAYS=30
TENANT_INVITATION_RESEND_WINDOW_MINUTES=60
TENANT_INVITATION_RESEND_LIMIT=5
```

Invitation secrets contain 256 bits of entropy, are stored only as SHA-256 digests, and travel in a
URL fragment that React removes immediately. New local users provide a display name and password;
existing users must authenticate as the invited email. An email delivery failure revokes the issued
invitation instead of exposing the link through logs or an operator fallback.

Schedule retained-record cleanup daily:

```powershell
python -m app.cli cleanup-tenant-invitations
```

Deploy the migration before the API and enable `TENANT_INVITATIONS_ENABLED` only after SMTP and the
`/accept-invitation` UI route are live. Disable the flag to stop new sends while retaining existing
member role and removal administration. Do not downgrade the invitation table after links are sent;
prefer a forward fix and revoke affected invitations.

## Run with PostgreSQL, Redis, and Celery

```powershell
cd backend
docker compose up --build
```

The API runs on port `8000`. The worker consumes Redis-backed Celery jobs. Uploaded files and
generated exports are stored in the shared `uploads` volume.

## Release-only document ingestion gate

Document ingestion is disabled by default and has no separate local implementation. Step 1 adds
only the release configuration and readiness gate; it does not add PDF parsing, extractors,
chunking, vector storage, FastEmbed integration, or ingestion jobs. Keep
`DOCUMENT_INGESTION_ENABLED=false` until those later steps and every external dependency are
approved for release.

An enabled release requires all existing production controls plus the following contract:

```dotenv
DOCUMENT_INGESTION_ENABLED=true
DATABASE_URL=postgresql://RUNTIME_USER:RUNTIME_PASSWORD@ep-EXAMPLE-pooler.REGION.aws.neon.tech/neondb?sslmode=require
DIRECT_DATABASE_URL=postgresql://MIGRATION_USER:MIGRATION_PASSWORD@ep-EXAMPLE.REGION.aws.neon.tech/neondb?sslmode=require
STORAGE_BACKEND=s3
OBJECT_STORAGE_BUCKET=RELEASE_BUCKET
AWS_ENDPOINT_URL_S3=https://RELEASE-ENDPOINT.storage.REGION.aws.neon.tech
AWS_ACCESS_KEY_ID=SECRET_MANAGED_VALUE
AWS_SECRET_ACCESS_KEY=SECRET_MANAGED_VALUE
AWS_REGION=us-east-2
REDIS_URL=rediss://USER:PASSWORD@PRIVATE_REDIS_HOST:6380/0
TASKS_EAGER=false
AUTO_CREATE_TABLES=false
EMBEDDING_PROVIDER=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
EMBEDDING_BATCH_SIZE=32
EMBEDDING_MODEL_PATH=/opt/wbs-models/bge-small-en-v1.5
EMBEDDING_MODEL_REVISION=aa8f8b060edb00e03bfdd08813a2949946c8ba55
EMBEDDING_MODEL_MANIFEST_SHA256=609e3f5b2f42b5c302c9fd86344b7c9f1cb498fa2f29826b1265da284dc18ca0
EMBEDDING_FORMATTING_VERSION=bge-small-en-v1.5-format-v1
EMBEDDING_TOKENIZER_REVISION=aa8f8b060edb00e03bfdd08813a2949946c8ba55
EMBEDDING_TOKENIZER_SHA256=d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66
EMBEDDING_MAX_TEXT_CHARACTERS=100000
EMBEDDING_MAX_CONCURRENT_BATCHES=1
EMBEDDING_CPU_THREADS=2
DOCUMENT_PROCESSING_TIMEOUT_SECONDS=900
DOCUMENT_MAX_PDF_PAGES=500
DOCUMENT_MAX_WORKSHEETS=100
DOCUMENT_MAX_ROWS_PER_SHEET=100000
DOCUMENT_MAX_EXTRACTED_CHARACTERS=10000000
DOCUMENT_CHUNK_TARGET_TOKENS=400
DOCUMENT_CHUNK_OVERLAP_TOKENS=50
DOCUMENT_CHUNK_MAX_TOKENS=480
DOCUMENT_CHUNK_FORMATTING_HEADROOM_TOKENS=32
DOCUMENT_MAX_CHUNKS=100000
DOCUMENT_MAX_CHUNK_SOURCE_REFERENCES=2048
OCR_ENABLED=true
OCR_LANGUAGES=eng
OCR_TIMEOUT_SECONDS=300
OCR_MAX_OUTPUT_BYTES=52428800
OCR_MAX_TEMPORARY_BYTES=268435456
OCR_PROCESS_OUTPUT_MAX_BYTES=65536
OCR_CPU_LIMIT_SECONDS=300
OCR_MEMORY_LIMIT_BYTES=2147483648
OCRMY_PDF_EXPECTED_VERSION=APPROVED_EXACT_VERSION
TESSERACT_EXPECTED_VERSION=APPROVED_EXACT_VERSION
MALWARE_SCAN_REQUIRED=true
CLAMAV_HOST=PRIVATE_CLAMAV_HOST
CLAMAV_PORT=3310
CLAMAV_CONNECT_TIMEOUT_SECONDS=3
CLAMAV_SCAN_TIMEOUT_SECONDS=60
CLAMAV_RESPONSE_MAX_BYTES=4096
DOCUMENT_PROCESSING_TEMP_ROOT=/var/lib/wbs/processing
```

Inject endpoints and credentials from the deployment secret manager. Do not commit them or expose
them through `VITE_*` variables. Startup rejects SQLite, local storage, eager tasks, automatic table
creation, missing or local Redis, incomplete ClamAV settings, a relative model path, and an
unapproved embedding provider, model, dimensions, or chunk window.

API and worker readiness intentionally have different responsibilities:

- `GET /api/v1/health/ready` checks database, migration, administrator, object storage, and Redis
  dispatch readiness. It neither imports FastEmbed nor inspects or loads worker model files.
- Before starting an ingestion worker, run `python -m app.cli check-ingestion-worker-readiness` in
  the worker image. It checks Redis, sends a minimal ClamAV `PING`, and verifies that the packaged
  model directory contains a readable file. It also requires exactly one real extractor for every
  release format. It does not load FastEmbed or parse a document during readiness.

The worker image must package `/opt/wbs-models/bge-small-en-v1.5` read-only. The directory must
contain the approved `tokenizer.json` plus `tokenizer-revision.txt`; deployment supplies the exact
revision and SHA-256 through secret-managed release configuration. The API image must not contain
the model or worker-only tokenizer runtime. Treat a nonzero worker preflight result as a deployment
failure and do not start
the worker. Readiness responses and command failures expose only safe dependency categories, never
credentials, private endpoints, or filesystem paths.

### Secure worker document input

Step 4 adds an internal worker-only input boundary; it does not add a download API, parser, OCR,
chunking, embedding, or ingestion task orchestration. The boundary accepts a persisted project
document and its authorized `DOCUMENT_INGESTION` job, validates their tenant/project/document
scope, obtains the private object key only from the document record, and then performs `HeadObject`,
bounded streaming, size reconciliation, SHA-256 verification, and mandatory ClamAV scanning.
Only a clean result yields a temporary path to the next processing step.

Provision `DOCUMENT_PROCESSING_TEMP_ROOT` as an existing absolute directory owned by the non-root
worker account with no group or world permissions. Each attempt uses an owner-only UUID child
directory and a generated `input.<suffix>` name. The context removes that directory after success,
failure, cancellation, timeout, or a later consumer exception. Do not use the upload filename as a
path, mount this root into the API image, or share it between worker replicas.

ClamAV must be reachable only through the approved private worker route. The client sends the
completed bounded file through the ClamAV `INSTREAM` protocol with configured connection, overall
scan, and response-size limits. A positive detection is permanent; scanner unavailability is
retryable; malformed, truncated, oversized, timed-out, or unknown responses fail closed. Do not
bypass scanning to restore throughput.

API readiness continues to check object-storage and dispatch dependencies without contacting
ClamAV or inspecting worker files. `python -m app.cli check-ingestion-worker-readiness` performs a
content-free ClamAV `PING` in the worker environment. Before release, separately smoke-test a
synthetic clean file, the standard antivirus test signature, scanner unavailability, and temporary
cleanup against the deployed private Neon bucket and approved ClamAV service.

### Extraction contract and registry

Step 5 defines immutable, bounded extraction contracts for confirmed `pdf`, `docx`, `xlsx`, and
`csv` formats. It adds no parser implementation and no parser dependency. Extractor selection uses
only the server-confirmed format, and registrations are provided explicitly through an immutable
registry. Uploaded filenames, MIME values, document content, and runtime module names never select
or load code.

The extraction limits reuse the existing page, worksheet, row, and aggregate-character settings.
The additional `DOCUMENT_MAX_EXTRACTED_BLOCKS`, `DOCUMENT_MAX_BLOCK_CHARACTERS`, heading,
warning, metadata, and sheet-name settings bound every remaining contract collection and string.
The effective per-block character limit is capped at the aggregate character limit.

API readiness does not construct the extractor registry or invoke blocking parser work. Worker
readiness validates that exactly one explicitly registered real extractor exists for every required
release format and returns only the safe `extractor_registry` dependency category on failure.
Steps 6 and 7 register exactly one real implementation for `pdf`, `docx`, `xlsx`, and `csv`.
Unit tests may inject fake extractors; application release construction never imports them. API
readiness does not import the Office/CSV parser modules; worker registry construction imports them
only when worker readiness or extraction explicitly requests the release registry.

### DOCX, XLSX, and CSV extraction

Step 7 pins `python-docx==1.2.0`, `openpyxl==3.1.5`, and `defusedxml==0.7.1`. DOCX and XLSX files
pass a bounded ZIP/XML preflight before a format parser opens them. The preflight rejects encrypted
entries, duplicate or unsafe names, traversal, special files, macro and embedded executable parts,
DTD/entity declarations, excessive entries, oversized parts, excessive aggregate expansion, and
unsafe cell or merged-range counts. Relationships and workbook links are never fetched.

DOCX extraction processes body paragraphs and tables in their actual document order, records
heading paths and list levels, keeps table cell order, and excludes headers, footers, images, and
embedded objects. XLSX extraction uses read-only, data-only mode with `keep_links=False`, processes
visible sheets only, records one-based sheet/row provenance, uses the first populated row after a
blank boundary as a region header, and never evaluates formulas. Missing cached formula values and
skipped hidden sheets are stable warnings. Every opened workbook is closed in a `finally` block.

CSV extraction streams UTF-8 or UTF-8-BOM input, selects only comma, semicolon, tab, or pipe through
a bounded deterministic comparison, and preserves quoted delimiters, quoted newlines, and
formula-like prefixes. Blank and duplicate headers receive deterministic names with stable warning
codes. Field, column, row, block, byte, and aggregate-character limits remain enforced.

Release settings additionally bound archive entries, compressed and expanded bytes, individual
parts, expansion ratio, spreadsheet columns and cells, merged ranges, CSV columns, and CSV field
length. The release registry is repository-complete, but enabling ingestion still requires the
separate Neon, ClamAV, OCR-worker, embedding-model, container-resource, vulnerability, performance,
and operations checks documented in the phase evidence.

### Deterministic normalization and chunking

Step 8 converts validated extraction blocks into immutable, ordered canonical chunks without
rewriting or interpreting document meaning. It normalizes line endings, Unicode spacing, unsafe
controls, repeated blank lines, and table separators while preserving identifiers, numbering,
negation, scope statements, quantities, dates, units, currencies, headings, and source locations.

The chunker uses the exact local `BAAI/bge-small-en-v1.5` tokenizer. The worker verifies the
configured tokenizer revision and SHA-256 before loading `tokenizer.json`; it never calls a remote
model registry or trusts remote code. The default contract targets 400 tokens, applies up to 50
tokens of compatible overlap, caps canonical content at 480 tokens, and reserves 32 tokens beneath
the 512-token model limit. Table and worksheet headers are repeated as context while primary row
ranges remain distinct. Every retained block must have primary coverage, and canonical hashes use
a versioned deterministic payload containing content plus stable source provenance.

`GET /api/v1/health/ready` does not import the worker tokenizer package, inspect artifacts, or
construct the chunker. Worker readiness adds the safe `tokenizer_runtime` category and performs
only a bounded synthetic self-check. Step 8 does not load FastEmbed, produce embeddings, write
chunks or vectors, or add an ingestion task; those remain later steps. Keep ingestion disabled
until the approved tokenizer artifact, worker image, offline execution, resource bounds, and
performance gates have release evidence.

### Offline FastEmbed worker

Step 9 embeds canonical Step 8 chunks only inside the worker. `fastembed==0.9.0`, its runtime
dependency expectations, and `tokenizers==0.22.2` are exact worker-only pins. The API target
contains neither FastEmbed/ONNX nor model artifacts. Document passages are passed unchanged;
future retrieval queries receive the fixed BGE instruction under formatting policy
`bge-small-en-v1.5-format-v1`.

The checked-in model inventory pins the FastEmbed-compatible Qdrant ONNX snapshot at revision
`aa8f8b060edb00e03bfdd08813a2949946c8ba55`, records every expected file size and SHA-256, and
records the upstream MIT license. The Docker model-builder downloads only allowlisted immutable
URLs and fails if any byte differs. It then places the verified directory at
`/opt/wbs-models/bge-small-en-v1.5`; the worker receives root-owned read-only files, offline Hugging
Face settings, and a non-root build-time embedding check. No model binary is stored in this
repository and no runtime download or external embedding fallback exists.

Provider initialization is lazy, locked, and PID-aware so a model is not inherited unsafely across
forked worker processes. Failed initialization is not cached. Inputs are bounded by count,
per-text characters, aggregate characters, configured batch size, CPU threads, and one concurrent
batch per process until release capacity measurements approve another limit. Every returned vector
must exist in input order, contain exactly 384 real finite values, and pair with the unchanged chunk
ordinal and SHA-256. Missing, extra, malformed, or partial output fails the whole handoff.

API readiness remains limited to the dispatch dependency and never imports FastEmbed or ONNX,
opens the model directory, or embeds text. Worker readiness adds `embedding_runtime`, verifies the
full artifact manifest, constructs the process-local CPU provider with `local_files_only=True`, and
embeds one fixed synthetic string. Readiness and metrics expose only bounded categories and numeric
measurements, never content, vectors, hashes, paths, filenames, endpoints, tenant data, or raw
runtime errors.

The committed revision and inventory are technically pinned release candidates, not evidence of
organizational approval. Keep `DOCUMENT_INGESTION_ENABLED=false` until the actual worker image is
built, scanned, approved, run offline as non-root, resource/performance tested, and its logs and
metrics reviewed in the release environment.

### PDF extraction and OCR worker

PDF extraction accepts only the clean trusted path produced by the worker input boundary. It uses
the pinned `pypdf` dependency for ordered native page text and a deterministic native, mixed, or
OCR-required page classification. Page count, input size, encoded and decoded content streams,
blocks, characters, parser duration, OCR output, child-process output, memory, CPU, and temporary
workspace usage are bounded. Encrypted, malformed, empty, timed-out, and over-limit inputs map to
stable extraction codes without exposing parser or command diagnostics.

OCR uses fixed `ocrmypdf` arguments, `shell=False`, the release-fixed `eng` language, server-created
paths, and the existing owner-only processing workspace. It validates exact configured OCRmyPDF and
Tesseract versions plus installed language data before invoking OCR. API readiness never performs
those checks; worker readiness reports only `ocr_runtime` if they fail. OCR intermediates are
removed by the extractor and the enclosing Step 4 workspace cleanup.

The API target remains `runtime` and contains no OCR packages. Build the distinct worker target only
after security review supplies exact package versions available from the approved package snapshot:

```powershell
docker build --target ocr-worker `
  --build-arg OCRMY_PDF_PACKAGE_VERSION=APPROVED_EXACT_VERSION `
  --build-arg TESSERACT_OCR_PACKAGE_VERSION=APPROVED_EXACT_VERSION `
  --build-arg TESSERACT_ENG_PACKAGE_VERSION=APPROVED_EXACT_VERSION `
  --build-arg GHOSTSCRIPT_PACKAGE_VERSION=APPROVED_EXACT_VERSION `
  --build-arg QPDF_PACKAGE_VERSION=APPROVED_EXACT_VERSION `
  -t wbs-ingestion-worker .
```

Set `OCRMY_PDF_EXPECTED_VERSION` and `TESSERACT_EXPECTED_VERSION` to the exact version strings
reported by that reviewed image. The worker target fails its build when a package version argument
is omitted or unavailable, runs as `wbs`, and keeps `/app` and its home directory read-only. Deploy
it with a read-only root filesystem and only the configured processing workspace writable. Do not
enable ingestion based on mocked OCR tests: image build, vulnerability scan, language data, process
limits, cleanup, throughput, memory, and temporary-disk behavior remain release-environment gates.

## pgvector ingestion schema

Migration `a4f9c2d18e76` adds the PostgreSQL-only release schema for versioned document processing.
It installs the shared `vector` extension if necessary, adds document processing state, and creates
tenant/project/document-scoped processing runs and chunks with `VECTOR(384)` embeddings. The
correctness baseline is exact filtered distance search; this migration deliberately creates no
HNSW or IVFFlat index and does not implement extraction, embedding generation, or ingestion jobs.

The migration derives the restricted application role from `DATABASE_URL` and the migration role
from `DIRECT_DATABASE_URL`. It fails closed unless the connected migration role matches the direct
URL and the runtime role exists, is different, is not a superuser, and lacks `BYPASSRLS`. The new
tables revoke public access, grant only CRUD access to the runtime role, and enable and force RLS.
The deployment must provision both roles and the required grants on the existing application tables
before applying the revision. Role names and credentials must not be placed in migration files.

Every runtime transaction that accesses processing runs or chunks must establish its tenant before
the first protected query:

```python
async with session.begin():
    await set_local_tenant_context(session, tenant_id)
    # Run tenant/project-scoped repository operations here.
```

`set_local_tenant_context` validates the UUID and uses PostgreSQL `SET LOCAL`, so pooled connections
cannot retain the tenant after the transaction ends. A missing setting returns no protected rows;
an invalid setting fails the statement. SQLite performs no RLS and remains regression coverage only.

Test the revision on an isolated, disposable PostgreSQL or Neon branch with both roles before
enabling ingestion. The opt-in integration suite requires `STEP3_POSTGRES_MIGRATION_URL`,
`STEP3_POSTGRES_RUNTIME_URL`, and
`STEP3_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE`. It validates pgvector,
dimensions, ownership constraints, grants, forced RLS, pooled tenant reset, and an exact filtered
cosine-distance query without printing the configured URLs.

The downgrade is intentionally guarded: it succeeds only while processing runs and chunks are
empty, and it never drops the shared `vector` extension. Once ingestion data exists, use a reviewed
forward-fix migration rather than an application rollback that would destroy chunk data. Database
cascades remove chunks only when their processing run is deleted; they never remove source objects
from private object storage.

## Transactional vector persistence

Migration `b6e2f719c4d8` extends processing-run identity with nullable legacy-safe chunker version,
embedding model revision, and embedding formatting-policy version fields. New persistence writes
require all three values and the database idempotency constraint includes them. Historical rows are
not assigned fabricated values. Downgrade refuses to remove populated versioned identity fields;
after writes exist, use a reviewed forward fix.

`VectorPersistenceRepository` is an internal worker repository. Every method requires explicit
tenant/project/document scope, and job-bound writes also require the ingestion job ID. Each
PostgreSQL transaction establishes `app.tenant_id` locally before accessing the forced-RLS run and
chunk tables. There is no public persistence or vector-search route.

The repository uses staged transactions for bounded chunk/vector batches. Staged chunks remain
under an `IN_PROGRESS` run and active reads resolve exclusively through a completed
`documents.current_processing_run_id`. Final reconciliation checks count, contiguous ordinals,
canonical hashes and metadata, the complete versioned processing identity, and all 384 float32
vector values. Only then does one row-locked transaction complete the run and switch the document
pointer. Failed reprocessing records a safe stable error but never clears the previous pointer.

The exact cosine method is internal and always filters tenant, project, document, and the current
processing run. Superseded-run deletion re-locks the document, refuses current or active runs, and
relies on the database run-to-chunk cascade; it never touches private object storage.

The opt-in Step 10 integration test requires an isolated migrated PostgreSQL/Neon branch and:

```dotenv
STEP10_POSTGRES_MIGRATION_URL=postgresql://MIGRATION_ROLE:SECRET@DIRECT_HOST/DATABASE?sslmode=require
STEP10_POSTGRES_RUNTIME_URL=postgresql://RUNTIME_ROLE:SECRET@POOLED_HOST/DATABASE?sslmode=require
STEP10_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
```

Never point the test at a shared branch. SQLite verifies repository state transitions, mapping, and
migration ordering only; it is not evidence for pgvector dimensions, RLS, runtime-role grants,
row-lock concurrency, or pooled tenant reset.

## Durable document ingestion

Migration `c8d4a1e72f09` adds the Step 11 orchestration lifecycle and the tenant-isolated
`job_dispatch_outbox` table. A start request creates the ingestion job, an identity-unbound queued
processing run, and one dispatch intent in the same transaction. The source hash, extractor,
chunker, and embedding provenance remain null until the worker has downloaded and scanned the
trusted object. The worker then binds the complete server-controlled identity atomically; it never
fabricates provenance. Historical Step 10 rows with legacy identity remain readable but are not
treated as a current release-ready run.

The public ingestion endpoints are:

```text
POST /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions
GET  /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions/current
```

The start endpoint accepts no request body or client-selected storage, model, run, task, project,
or tenant identity. It returns the existing active job for duplicate starts and publishes only
after the database transaction commits. The status response contains only stable lifecycle state,
progress, bounded counts, validated warnings, safe errors, and extractor/embedding provenance.
Summary and WBS generation return `DOCUMENT_INGESTION_REQUIRED` until the document points to a
completed run whose persisted chunk count reconciles. Ingestion retry, cancellation, and extraction
preview are intentionally not public. Generic cancellation rejects ingestion jobs.

The worker uses these durable stages and monotonic progress values:

```text
QUEUED 0 -> SCANNING 10 -> EXTRACTING 30 -> CHUNKING 50 ->
EMBEDDING 65 -> PERSISTING 80 -> ACTIVATING 95 -> COMPLETED 100
```

Transient failures move the run to `RETRY_WAIT`, reset the existing outbox intent with bounded
exponential backoff and jitter, and are republished by the reconciler. Permanent malware,
integrity, authorization, malformed/encrypted/unsupported, empty-content, and configured-limit
failures do not retry. At-least-once delivery is expected: task payloads contain only job and run
UUIDs, every worker execution reloads trusted ownership, and duplicate delivery is idempotent. A
new run never clears the previous completed document pointer before atomic activation.

Release ingestion requires non-eager Celery and Redis. Run a worker and Celery Beat (or another
approved scheduler) as separate non-root worker processes:

```powershell
celery -A app.worker.celery_app worker --loglevel=INFO
celery -A app.worker.celery_app beat --loglevel=INFO
```

An operator can also run one bounded reconciliation pass:

```powershell
python -m app.cli reconcile-document-ingestion
```

The reconciler repairs stale processing heartbeats, missing dispatch intents, completed runs with
stale jobs, inconsistent terminal states, and expired publication leases. It republishes from the
outbox only after commit. The API readiness path checks configuration and Redis only; ClamAV, OCR,
extractor, tokenizer, model, and embedding checks remain worker-only. Do not use eager execution or
FastAPI background tasks as a release fallback.

Before release, apply the migration on an isolated Neon branch and verify the outbox owner, grants,
forced RLS policy, runtime-role isolation, and PostgreSQL locking behavior. Then exercise real Redis
publication failure, worker restart, duplicate delivery, stale reconciliation, ClamAV/OCR/model
dependencies, and temporary-workspace cleanup in the release worker image. SQLite and mocks are
repository regression evidence only.

## Durable document deletion and lifecycle maintenance

Migration `d4e7b2c91a63` adds the `ACTIVE`, `DELETING`, and `DELETED` document lifecycle and the
forced-RLS `document_deletion_outbox`. `DELETE /api/v1/tenants/{tenant_id}/documents/{document_id}`
returns `202 Accepted`. In its first database transaction it rechecks tenant authorization, locks
the document, cancels active ingestion, clears the active-run pointer, deletes document chunks,
marks vectors hidden, creates a deletion job, and writes one dispatch intent. Object cleanup occurs
after commit and is idempotent. A storage outage leaves the document hidden in `DELETING` and uses
bounded outbox recovery; it never restores vector visibility.

The status endpoint is safe to poll:

```text
GET /api/v1/tenants/{tenant_id}/documents/{document_id}/deletion
```

It exposes only lifecycle state, stable stages/codes, progress, attempts, and timestamps. It never
returns a filename, object key, document content, vector, broker identifier, endpoint, or raw
provider error. Completed cleanup retains a minimal scrubbed tombstone until an approved retention
policy removes it.

Celery Beat schedules bounded deletion dispatch recovery and lifecycle reconciliation. Operators
can run the same controls directly:

```powershell
# Dry-run report; tenant-id is optional for an explicitly authorized global pass.
python -m app.cli reconcile-document-lifecycle --tenant-id TENANT_UUID

# Mutating repair requires the exact confirmation string.
python -m app.cli reconcile-document-lifecycle --tenant-id TENANT_UUID `
  --repair --confirm APPLY_DOCUMENT_REPAIRS

# Republish pending or stale deletion dispatches.
python -m app.cli recover-document-deletions --tenant-id TENANT_UUID

# Retention defaults to dry-run. Execution is disabled until all policy periods are configured.
python -m app.cli run-document-retention --tenant-id TENANT_UUID
python -m app.cli run-document-retention --tenant-id TENANT_UUID `
  --execute --confirm APPLY_DOCUMENT_RETENTION
```

`DOCUMENT_RETENTION_ENABLED` and `DOCUMENT_ORPHAN_CLEANUP_ENABLED` default to `false`. No legal or
privacy duration is encoded as a default. Enabling retention requires explicit bounded durations for
failed/cancelled/superseded runs, jobs, malware events, tombstones, and stale workspaces. Orphan
object deletion additionally requires a minimum age plus approved repair mode. Current runs are
never retention candidates. Dead deletion dispatches are reported for operator action and are not
silently reset into an infinite retry loop.

Before release, apply the migration on an isolated Neon branch and prove immediate vector
invisibility using the restricted runtime role. Exercise real private object deletion, broker
failure, worker restart, duplicate delivery, retry exhaustion, and reconciler recovery. Approve and
record privacy retention periods, maintenance ownership, alert routing, and accidental-deletion
restore procedures before enabling destructive retention or orphan cleanup. See the Step 13
operations runbook and implementation evidence for the remaining release gates.

## Test and lint

```powershell
python -m pytest
ruff check .
```

The release browser suite is launched from `WBS_UI`:

```powershell
cd ..\WBS_UI
npm.cmd run test:e2e:fullstack
```

## Production operations

Before promotion, validate the injected production environment without printing secrets:

```powershell
python -m app.cli check-production-config
```

Production readiness checks the database migration revision in addition to connectivity and the
administrator invariant. Metrics are disabled locally; production requires `METRICS_ENABLED=true`
and a separate secret-managed `METRICS_BEARER_TOKEN`. Scrape `/api/v1/health/metrics` only through a
private monitoring path.

Schedule the unified maintenance command daily and alert on failure or a missing success:

```powershell
python -m app.cli run-maintenance
```

The command removes only records beyond configured retention periods, stale failed-export objects,
and old `.part`/`.tmp` files. It is batched and safe to rerun. The Docker Compose maintenance profile
can exercise the same command locally with `docker compose --profile maintenance run --rm maintenance`.

Targeted and environment-wide containment commands require exact confirmation strings:

```powershell
python -m app.cli revoke-user-sessions --email admin@example.com --confirm REVOKE_USER_SESSIONS
python -m app.cli revoke-all-sessions --confirm REVOKE_ALL_SESSIONS
```

Use these only under the Phase 8 incident runbooks. The production Dockerfiles, edge reference,
secret inventory, alert catalog, deployment/restore runbook, and readiness record are linked from
`docs/authentication-authorization-phases/phase-08-artifacts/implementation-evidence.md`.

It uses `backend/docker-compose.fullstack.yml` to create an isolated PostgreSQL 16 database, applies
all Alembic revisions, verifies schema drift, seeds a unique role/tenant matrix, and removes the
database volume after the run. It never reads the backend `.env` database URL over the generated
test-process environment. Do not point the suite at a shared Neon branch.

## Database migrations

### Connect Neon

In the Neon dashboard, copy both connection strings. Use the pooled URL for API traffic and the
direct URL for schema migrations. Do not commit either credential.

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@ep-EXAMPLE-pooler.REGION.aws.neon.tech/neondb?sslmode=require
DIRECT_DATABASE_URL=postgresql://USER:PASSWORD@ep-EXAMPLE.REGION.aws.neon.tech/neondb?sslmode=require
DATABASE_USE_NULL_POOL=true
AUTO_CREATE_TABLES=false
```

The application converts standard Neon `postgresql://` URLs to SQLAlchemy's asyncpg dialect. The
pooled URL is used only by the running API; Alembic deliberately uses the direct URL.

Apply the checked-in migrations to a new Neon branch or database before starting the API:

```powershell
alembic upgrade head
```

### Make a schema change

Use this process for every database change:

1. Create a Neon development branch from the current production branch.
2. Point `DIRECT_DATABASE_URL` at that development branch.
3. Update the SQLAlchemy models in `app/models/domain.py`.
4. Generate a migration:

```powershell
alembic revision --autogenerate -m "describe the model change"
```

5. Review the generated file in `migrations/versions/`. Autogeneration must not be accepted
   without checking column types, nullability, defaults, indexes, constraints, and data backfills.
6. Apply and verify it on the Neon development branch:

```powershell
alembic upgrade head
alembic check
python -m pytest
```

7. Commit the model and migration together. In deployment, run `alembic upgrade head` before
   starting the new API version.

Use `alembic downgrade -1` only while testing a reversible migration. For production failures,
prefer a reviewed forward-fix migration when rolling back would risk losing data.

`AUTO_CREATE_TABLES=true` remains available only for throwaway local SQLite tests. Keep it `false`
for Neon so every schema change has a migration history.

## Authentication and tenancy

Enterprise SSO uses a backend-managed Authorization Code flow with PKCE. Set `AUTH_MODE=hybrid`
during rollout, configure every `OIDC_*` value documented in `.env.example`, and register the exact
`OIDC_REDIRECT_URI`. The callback validates discovery metadata and pinned endpoints, signature,
issuer, audience, algorithm, times, nonce, verified email, and provider directory. Provider tokens
never enter application JavaScript; the callback creates the same rotating WBS refresh session used
by local authentication.

New SSO identities require an active invitation whose normalized email matches the provider's
verified email. Existing links use the immutable, directory-namespaced provider subject. Provider
claims never create tenant access on their own. Apply migration `f2a84d719c35`, keep a reviewed
local break-glass administrator in `hybrid` mode, and enable the UI with:

```dotenv
VITE_AUTH_MODE=hybrid
VITE_SSO_ENABLED=true
VITE_SSO_PROVIDER_LABEL=Enterprise SSO
```

Provider registration, claims, endpoint pins, outage handling, and rollout evidence are described
in `docs/authentication-authorization-phases/phase-09-artifacts/`.

The tenant ID in a route never grants access by itself. `require_tenant_member` verifies that the
authenticated user belongs to the tenant before a tenant-owned query runs.

See `SECURITY.md` for the threat model, security controls, and deployment checklist.
See the [authentication and authorization specification](../docs/authentication-authorization-functional-technical-spec.md)
for the phased functional and technical work required to complete the feature end to end.
The [phase execution pack](../docs/authentication-authorization-phases/README.md) contains the
implementation sequence, verification gates, and handoff evidence for each phase.

## Processor integration points

Replace the placeholder implementations in `app/services/workflows.py` with:

1. PDF, DOCX, XLSX, and XML extraction.
2. LLM-based summary and requirement extraction.
3. WBS generation from the approved summary and selected template.
4. Primavera P6-specific validation and export logic.

Keep the job lifecycle and persisted result contracts stable so the React UI can poll jobs without
depending on the underlying AI provider.


## Document content reuse and saved workflows

Verified SHA-256 reuse and durable workflow recovery are controlled by the default-off
`DOCUMENT_WORKFLOW_RESUME_ENABLED` and `DOCUMENT_UPLOAD_REUSE_ENABLED` settings. Reuse requires
resume; resume enabled with reuse disabled pauses new uploads while preserving saved-work reads.
The current migration head is `c92e6b4a710d`, merging the recovered question-bank history
(`a13d9e7b602c`) and deduplication schema (`f31a0d8c72e9`). No revision stamping is needed.
The additive schema, bounded backfill/cleanup commands, test evidence, external release gates and
rollback order are documented in the
[implementation evidence and runbook](../docs/document-deduplication-workflow-resume-implementation-evidence.md).
Do not enable this feature before verifying the PostgreSQL migration, tenant backfill and
object-storage behavior in isolated resources.
