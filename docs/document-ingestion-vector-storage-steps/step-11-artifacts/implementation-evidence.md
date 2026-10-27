# Step 11 Implementation Evidence

## Status

The Step 11 repository implementation is complete as of 2026-10-26. The dedicated ingestion APIs,
two-phase run identity, transactional dispatch outbox, idempotent worker orchestration, durable
retry state, reconciliation, monotonic progress, safe status contract, authorization, cleanup, and
summary/WBS ready-run prerequisite are covered by repository tests.

Step 11 is not externally release-verified. This run did not have an isolated Neon branch with the
restricted runtime role, a real non-eager Redis/Celery deployment, private object storage, ClamAV,
the approved OCR/model worker image, or controlled process-restart infrastructure. SQLite and
injected boundaries below are not presented as evidence for those external controls. The dependency
audit also remains a release blocker.

## Changed Files

- `backend/app/models/domain.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/domain.py`
- `backend/app/core/config.py`
- `backend/app/core/permissions.py`
- `backend/app/core/observability.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/router.py`
- `backend/app/api/routes/ingestions.py`
- `backend/app/api/routes/documents.py`
- `backend/app/api/routes/helpers.py`
- `backend/app/api/routes/jobs.py`
- `backend/app/api/routes/summaries.py`
- `backend/app/api/routes/generations.py`
- `backend/app/services/dispatcher.py`
- `backend/app/services/readiness.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/services/ingestion/release_identity.py`
- `backend/app/services/ingestion/repository.py`
- `backend/app/services/ingestion/orchestrator.py`
- `backend/app/services/ingestion/reconciliation.py`
- `backend/app/worker.py`
- `backend/app/cli.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/c8d4a1e72f09_add_ingestion_orchestration_outbox.py`
- `backend/.env.example`
- `backend/README.md`
- `backend/tests/test_ingestion_api.py`
- `backend/tests/test_ingestion_dispatch.py`
- `backend/tests/test_ingestion_orchestrator.py`
- `backend/tests/test_ingestion_orchestration_contract.py`
- `backend/tests/test_ingestion_observability.py`
- Narrow workflow, migration-head, and PostgreSQL RLS regression-test updates
- The Step 11 execution document and this evidence file

No React file was changed for Step 11. No summary generation, RAG, LLM, agent, extraction,
normalization, chunking, embedding, vector-search, or WBS-generation algorithm was added or changed.

## Migration And Two-Phase Identity

- New revision: `c8d4a1e72f09`.
- Previous revision: `b6e2f719c4d8`.
- Jobs gain a stable error code, attempt count, and progress-range constraints.
- Processing runs gain stage, attempt count, heartbeat, and bounded warning-code state.
- A queued run may initially have all processing-identity fields null. After the trusted object is
  downloaded and scanned, the worker binds the complete content, extractor, chunker, and embedding
  identity in one scoped operation. Partial identity is rejected.
- Existing completed Step 10 rows retain unknown version fields as null; the migration does not
  fabricate provenance.
- `job_dispatch_outbox` stores only scoped opaque identifiers, a fixed task name, delivery state,
  attempts, availability, lease timestamps, and a stable error code.
- The outbox has composite ownership foreign keys, a unique delivery intent, a pending-work index,
  revoked public access, restricted runtime-role grants, and enabled/forced tenant RLS.
- Downgrade is allowed only when no orchestration state would be destroyed. Otherwise it instructs
  operators to use a reviewed forward fix.

## APIs And Authorization

`POST /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions` requires
`document:process`, accepts no body, validates the authenticated tenant/project/document, and
returns `202` with the established safe job contract. A matching active request returns the same
job. A completed run is reused only when its server-controlled content, extractor, chunker, model,
revision, dimensions, and formatting identity match the current release identity.

`GET /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions/current` requires
`document:read` and returns only stable status, stage, monotonic progress, attempts, bounded counts,
timestamps, allowlisted warnings, safe provenance, and a stable error. It excludes document text,
chunks, vectors, object keys, paths, broker IDs, endpoints, credentials, and exception text.

Viewer start attempts and cross-tenant access fail through existing tenant permission boundaries.
Generic retry/cancel does not enable ingestion retry or cancellation. Generic cancellation rejects
`DOCUMENT_INGESTION`, and no preview endpoint exists. Hard document deletion rejects documents with
ingestion history to avoid lifecycle and object-storage races.

## Lifecycle And Progress

The durable stage/progress contract is:

```text
QUEUED 0
SCANNING 10
EXTRACTING 30
CHUNKING 50
EMBEDDING 65
PERSISTING 80
ACTIVATING 95
COMPLETED 100
```

Retryable work enters `RETRY_WAIT` without lowering the recorded progress. Permanent failures enter
`FAILED`. Every worker delivery reloads and validates the job, run, document, project, and tenant,
then establishes transaction-local tenant context. Duplicate delivery either resumes the same
versioned run, repairs a stale completed job, or returns a safe duplicate result. A reprocessing
failure never clears the previous active completed-run pointer.

The orchestration order is trusted download/hash/scan, server-confirmed format selection,
extraction, normalization/chunking, bounded embedding, inactive persistence, reconciliation, atomic
activation, and job completion. The Step 4 workspace boundary owns cleanup on success, failure,
timeout, cancellation, and consumer error.

## Outbox And Retry Semantics

The API commits the job, queued run, and unique outbox intent before publication. The dispatcher
leases the outbox row, publishes the JSON-only `{job_id, processing_run_id}` payload, and records
publication only after broker acknowledgement. A crash after publication can republish; worker
idempotency makes the at-least-once delivery safe.

Approved transient storage, scanner, Redis, database, OCR, model-runtime, timeout, and temporary
resource failures use bounded exponential backoff with jitter and a configured maximum attempt
count. Malware, integrity, authorization/scope, unsupported, encrypted, malformed, empty-content,
and configured-limit failures are permanent. Exhausted work is failed/dead rather than looped.
Only stable error codes and fixed safe messages are persisted or returned.

## Reconciliation And Operations

The bounded reconciler uses row locking and transaction-local tenant context. It repairs pending or
expired publication leases, stale processing heartbeats, queued jobs missing delivery, completed
runs with stale jobs, and safely classifies missing/inconsistent run state, deleted documents, and
exhausted attempts. It commits repaired state before attempting publication.

Celery is configured for JSON serialization, late acknowledgement, worker-loss rejection, one-item
prefetch, and fixed soft/hard task limits. Beat schedules reconciliation, and operators can invoke
one bounded pass with `python -m app.cli reconcile-document-ingestion`. Release configuration
rejects eager tasks. API readiness checks only the dispatch dependency; scanner, extractor, OCR,
tokenizer, and embedding runtime checks remain worker-only.

## Observability

Metrics cover queue age, stage duration, attempts, stable outcomes/errors, dispatch state, and
reconciliation backlog. Labels are fixed low-cardinality values. Tenant/project/document/job/run
IDs, content, chunks, vectors, object keys, filenames, paths, endpoints, credentials, raw protocol
responses, and exception text are not metric labels or public errors.

## Repository Verification

```text
Focused Step 11 tests: 27 passed, 5 warnings in 15.91s
Explicit Steps 4-10 regression selection: 305 passed, 3 skipped, 4 warnings
Complete backend suite: 514 passed, 6 skipped, 8 warnings in 78.75s
PostgreSQL/pgvector opt-in tests: 3 skipped because external URLs and disposable-database
  acknowledgement were not supplied
Ruff check (app, migrations, tests): passed
Ruff format --check: 144 files already formatted
Python compileall: passed
pip check: no broken requirements
git diff --check: passed; line-ending notices only
```

Warnings are the existing Starlette TestClient/httpx deprecation and Alembic `path_separator`
deprecation. The other skips are existing platform-specific or external PostgreSQL gates.

Disposable SQLite migration rehearsal passed for a clean upgrade to `c8d4a1e72f09`, current/head,
autogeneration drift check, guarded downgrade to `b6e2f719c4d8`, and forward upgrade. A Step 10
completed row was also upgraded without fabricated identity. This proves revision order and ORM
drift only, not PostgreSQL RLS, grants, pgvector, or locking.

`pip-audit` reported 59 advisory records across five existing packages: certifi, cryptography,
Pillow, pip, and development-only pytest. Step 11 adds no dependency. This audit gate remains failed
and must be remediated or formally dispositioned before release.

## External Verification Gates

- Apply through `c8d4a1e72f09` on an isolated Neon branch using the migration role.
- Inspect outbox ownership, grants, constraints, indexes, policy, and FORCE RLS state; verify the
  restricted pooled runtime role lacks ownership, superuser, and `BYPASSRLS` capabilities.
- Exercise transaction-local tenant isolation, pooled connection reuse, and PostgreSQL row-lock
  concurrency under the real runtime role.
- Run non-eager Redis/Celery publication, acknowledgement loss, broker outage, duplicate delivery,
  API/worker restart, worker loss, stale heartbeat, Beat, and reconciler recovery scenarios.
- Exercise real private Neon object storage, ClamAV clean/infected/unavailable paths, OCR, Office
  parsers, offline FastEmbed artifacts, pgvector persistence, and temporary-workspace cleanup in the
  approved non-root release worker image.
- Verify task timeouts, retry/backoff timing, memory/CPU/disk limits, throughput, and alert thresholds.
- Inspect release logs, metrics, traces, API responses, and readiness output for disclosure.
- Resolve or formally disposition the dependency-audit findings.

## Residual Risks

- Repository tests use SQLite and injected service boundaries for most orchestration paths; they do
  not prove PostgreSQL RLS/locking or external service behavior.
- At-least-once recovery depends on Celery Beat or an approved scheduler continuously running the
  reconciler.
- The configured timeouts, retry limits, batch sizes, and stale-heartbeat threshold remain bounded
  defaults until measured under the release workload.
- The release remains blocked until external service verification and the dependency-audit gate are
  complete.
