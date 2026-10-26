# Step 1: Release Configuration Gate

## Step Status

Repository implementation complete on 2026-10-24. External release-service and image verification
remain pending; document ingestion must stay disabled until those gates and later implementation
steps are complete.

## Objective

Define and enforce the only supported deployed ingestion configuration before adding parsers,
vectors, or workers. An unsafe or incomplete release configuration must fail at startup rather than
silently selecting local storage, SQLite, eager tasks, an external model download, or a disabled
security dependency.

## Execution Context

The backend already uses Pydantic settings in `backend/app/core/config.py`. Production validation
currently requires PostgreSQL, a direct migration URL, S3 storage, secure auth settings, migration
readiness, and metrics. It does not currently reject eager task execution, validate an ingestion
model, require scanning/OCR, or distinguish API readiness from ingestion-worker readiness.

`backend/.env.example` currently presents local SQLite, local storage, and eager tasks as defaults.
Those settings may remain relevant to unrelated legacy development, but the new ingestion feature
must never activate under them.

## Prerequisites

- Approved Neon runtime and direct migration URLs.
- Approved Neon Object Storage bucket and rotated credentials.
- Redis endpoint reachable by API dispatch and Celery workers.
- Release decision confirming ClamAV and OCR availability.
- Approved FastEmbed model: `BAAI/bge-small-en-v1.5`.
- Approved worker model directory: `/opt/wbs-models/bge-small-en-v1.5`.

## Functional Requirements

- Ingestion can be enabled only when all release dependencies are configured.
- API startup validates settings needed to accept and dispatch ingestion.
- Worker startup additionally validates scanner and embedding-model readiness.
- Public health endpoints reveal only dependency category and readiness, not credentials or internal
  addresses.
- Disabled ingestion returns a stable service-unavailable response and does not create a job.

## Configuration Additions

Add typed settings with bounded values:

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

Do not put real endpoints, credentials, or secret values in `.env.example`.

## Validation Rules

When `DOCUMENT_INGESTION_ENABLED=true`, require:

- `DATABASE_URL` resolves to PostgreSQL through the existing normalized SQLAlchemy URL;
- `DIRECT_DATABASE_URL` is present and distinct from the runtime URL;
- database URLs require TLS in production;
- `STORAGE_BACKEND=s3`;
- all S3 fields are present and the endpoint passes the existing HTTPS-origin validation;
- `TASKS_EAGER=false`;
- `AUTO_CREATE_TABLES=false`;
- a non-empty Redis URL using an approved scheme;
- `EMBEDDING_PROVIDER=fastembed`;
- exact approved model name and `EMBEDDING_DIMENSIONS=384`;
- chunk target plus overlap remain below the model sequence limit;
- model path is absolute and expected to be packaged in the worker;
- OCR and malware scanning are enabled for the declared release capability;
- page, row, character, batch, and timeout limits remain inside reviewed bounds.

Do not access the filesystem from a Pydantic model validator shared by the API and worker. Validate
model-file existence in worker readiness so the API image can remain independent from model loading.

## Implementation Tasks

1. Add typed settings and constraints to `backend/app/core/config.py`.
2. Add a cross-field validator for ingestion enablement and model/chunk compatibility.
3. Add explicit production rejection of `TASKS_EAGER=true`.
4. Add configuration properties for parsed or normalized values where useful.
5. Add an ingestion-disabled dependency guard for the future ingestion endpoint.
6. Extend readiness results with safe categories for Redis, scanner, storage, and migration state.
7. Create a worker readiness function that verifies model path readability and a minimal model load.
8. Update `.env.example` with release ingestion keys and warnings, without real secrets.
9. Update `backend/README.md` with release-only ingestion requirements and API/worker commands.
10. Ensure no `VITE_*` variable contains model, database, storage, scanner, or Redis secrets.

## Files Expected to Change

- `backend/app/core/config.py`
- `backend/app/services/readiness.py`
- `backend/app/api/routes/health.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/test_database_config.py`
- new readiness tests if existing tests are not sufficient

## Test Matrix

Positive cases:

- complete release configuration parses;
- approved bounds parse at minimum and maximum values;
- API readiness does not attempt to load FastEmbed;
- worker readiness recognizes a readable packaged model fixture.

Negative cases:

- eager tasks enabled;
- local storage selected;
- SQLite selected;
- missing direct database URL;
- missing Redis URL;
- wrong embedding provider, model, or dimension;
- target plus overlap exceeds the approved model limit;
- missing scanner configuration;
- OCR disabled while scanned-PDF support is declared;
- unreadable model directory in worker readiness;
- secrets accidentally included in safe readiness output.

## Security Checklist

- [x] Fail closed on incomplete ingestion configuration.
- [x] No secret defaults are introduced.
- [x] No secret value is logged in a validation error.
- [x] API readiness does not inspect or load worker model files.
- [ ] Worker model files are read-only at runtime. This remains an external image/deployment gate.
- [x] Production rejects eager tasks and local storage.
- [x] Health output does not reveal private endpoints.

## Verification

Run configuration and readiness tests, then start the release API and worker images with deliberately
invalid settings to confirm both processes fail before accepting work. Record safe error messages and
successful readiness output.

## Rollback

Keep `DOCUMENT_INGESTION_ENABLED=false` until dependent steps are complete. Rolling back this step
means disabling ingestion, not enabling a local fallback. Do not weaken existing production auth,
database, storage, or TLS validation.

## Exit Criteria

- [x] All ingestion settings are typed, bounded, and documented.
- [x] Release configuration fails with eager tasks, local storage, SQLite, or wrong model dimensions.
- [x] API and worker readiness responsibilities are separated.
- [x] No model is downloaded during request processing or API startup.
- [x] Configuration and readiness tests pass.
- [x] No credentials or private endpoints were committed.

## Handoff to Step 2

Provide the validated upload limits, accepted release formats, and enabled-ingestion dependency guard.
Step 2 uses these values to verify and complete the real PDF upload path.

