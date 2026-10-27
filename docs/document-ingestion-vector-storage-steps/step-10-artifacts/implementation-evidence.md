# Step 10 Implementation Evidence

## Status

The Step 10 repository implementation is complete as of 2026-10-26. Scoped repository behavior,
inactive staged batches, idempotent duplicate delivery, reconciliation, atomic pointer activation,
failed-reprocessing preservation, active ordered loading, safe deletion, error redaction, migration
ordering, and legacy-row behavior are repository-tested.

Step 10 is not externally release-verified. No isolated PostgreSQL/Neon branch or restricted runtime
role was supplied for this run, so real `VECTOR(384)` writes, cosine execution, FORCE RLS, pooled
tenant reset, row-lock concurrency, grants, and Neon transaction-duration behavior remain pending.
SQLite results below are not claimed as evidence for those PostgreSQL controls.

## Changed Files

- `backend/app/services/ingestion/repository.py`
- `backend/app/services/ingestion/errors.py`
- `backend/app/core/observability.py`
- `backend/app/models/domain.py`
- `backend/migrations/versions/b6e2f719c4d8_add_vector_persistence_identity.py`
- `backend/tests/vector_persistence_fixtures.py`
- `backend/tests/test_vector_persistence.py`
- `backend/tests/test_vector_persistence_contract.py`
- `backend/tests/test_vector_persistence_postgres.py`
- Narrow migration-head updates in the existing Step 3 schema/PostgreSQL tests
- `backend/README.md`
- The Step 10 execution document and this evidence file

No API route, React file, object-storage behavior, scanner, extractor, OCR runner, normalizer,
chunker, tokenizer, embedding provider, Celery task, retry executor, public vector search, summary,
RAG, LLM, agentic workflow, retention scheduler, or Step 11 functionality was added.

## Migration And Identity

- New revision: `b6e2f719c4d8`.
- Previous revision: `a4f9c2d18e76`.
- Added nullable legacy-safe `chunker_version`, `embedding_model_revision`, and
  `embedding_formatting_version` columns to `document_processing_runs`.
- Replaced only `uq_runs_idempotency` so it covers document content hash, extractor name/version,
  chunker version, embedding provider/model/revision/dimensions, and formatting-policy version.
- Existing rows retain `NULL` for unknown versioned metadata; no value is fabricated.
- `VECTOR(384)`, document chunks, RLS policies, grants, ownership constraints, active-run index,
  composite foreign keys, and run-to-chunk cascade are unchanged.
- Downgrade refuses to drop the new columns after versioned identities exist. It never drops the
  shared vector extension or chunk data.

## Repository Contract

All public repository operations require an immutable `DocumentScope` or `PersistenceScope`.
Job-bound operations validate the tenant, project, document, job, and processing run together. The
job must be `DOCUMENT_INGESTION`. PostgreSQL transactions call the existing transaction-local tenant
helper after the transaction begins. No get-by-ID-only method exists.

Run resolution row-locks the document, validates the persisted content hash, resolves the complete
processing identity, and returns a typed created/resumed/reused result. Failed or cancelled
same-task attempts are reset only after their inactive chunks are removed. A completed identical
active run is reused without adding chunks.

## Mapping And Staging

`EmbeddingBatchResult` is revalidated against the processing identity. Every canonical chunk maps
deterministically to one `DocumentChunk` with unchanged ordinal, token count, content, SHA-256,
heading path, source locations, and one float32-compatible 384-dimensional vector. Bounded JSON
metadata retains ordered source references, primary/overlap/header roles, page sets, source block
ranges, extraction methods, and stable warnings. It contains no tenant, object-storage, filename,
path, or raw parser data.

The selected strategy stages bounded batches in separate transactions under an inactive
`IN_PROGRESS` run. Existing ordinals are accepted only when every persisted canonical field,
metadata field, and float32 vector value matches. Conflicts fail closed. Partial staging can remain
for a retry but cannot be returned by active-document queries.

## Reconciliation And Activation

Reconciliation reloads the fully scoped run in ordinal order and requires exact expected count,
contiguous ordinals, complete canonical metadata, hashes, content, and vectors. Activation locks the
document and run, repeats identity and reconciliation checks, completes the run, updates accurate
statistics, and switches `documents.current_processing_run_id` in one transaction. Active reads
require that pointer and a `COMPLETED` run.

Failure recording stores only a stable code and fixed bounded message. It marks the attempted run
failed and records the latest document processing failure while leaving the previous current run
pointer and chunks intact.

## Exact Query And Deletion

The internal cosine method validates a finite 384-dimensional query vector and always filters
tenant, project, document, and the document's current processing run. It also requires the run to be
completed, bounds the result count, and applies ordinal/ID tie ordering. No public route or
approximate index was added.

Superseded listing excludes the current pointer. Deletion locks the document and run again, permits
only inactive completed/failed/cancelled runs, rejects current or queued/in-progress runs, and relies
on the existing database cascade. It never calls object storage.

## Errors And Observability

Persistence errors use stable fixed messages and explicit retryability for invalid input, scope,
state, idempotency, reconciliation, activation, database availability, and safe unexpected failure.
Job mappings contain only the stable code, retryability, and safe message. Metrics use allowlisted
operation/outcome/error labels plus numeric batch size and duration. IDs, content, hashes, vectors,
paths, endpoints, SQL, roles, and raw exception text are not labels.

## Repository Verification

Final command results are recorded after the complete verification pass:

```text
Focused Step 10 tests: 34 passed, 1 skipped, 4 warnings in 9.76s
Step 3 regression: 7 passed, 2 skipped, 1 warning
Step 8 regression: 20 passed, 1 warning
Step 9 regression: 49 passed, 1 skipped, 1 warning
Complete backend suite: 492 passed, 6 skipped, 4 warnings in 49.46s
```

The Step 10 skip and two Step 3 skips are restricted PostgreSQL integration gates. The remaining
skips are existing Windows symlink gates. Warnings are the existing Starlette TestClient/httpx
warning plus Alembic's existing missing `path_separator` configuration warning.

Quality and dependency checks:

```text
ruff check: passed
ruff format --check: 11 files already formatted
python compileall: passed
pip check: no broken requirements
git diff --check: passed; existing line-ending notices only
alembic heads: b6e2f719c4d8 (head)
```

`pip-audit` reported the same 59 advisory records in five packages already recorded by Step 9:
certifi, cryptography, Pillow, pip, and development-only pytest. Step 10 adds no dependency. The
audit gate remains failed and must be resolved or formally dispositioned before release.

Disposable SQLite migration rehearsal:

```text
clean upgrade through b6e2f719c4d8: passed
alembic current: b6e2f719c4d8 (head)
alembic check: No new upgrade operations detected
downgrade to a4f9c2d18e76 on empty versioned data: passed
forward upgrade to b6e2f719c4d8: passed
legacy processing run retained with all new identity fields NULL: passed
```

This validates revision order, ORM drift, guarded downgrade, and legacy-row handling only. It is not
PostgreSQL, pgvector, RLS, grants, locking, or Neon evidence.

## External Verification Gates

- Apply revisions through `b6e2f719c4d8` on an isolated Neon branch using the direct migration role.
- Verify existing rows, constraints, `VECTOR(384)`, policies, FORCE RLS, grants, owners, and the
  runtime role's non-superuser/non-`BYPASSRLS` state.
- Run the opt-in Step 10 integration test using the restricted pooled runtime role.
- Verify real vector insertion, exact cosine ranking, and rejection of invalid dimensions.
- Verify cross-tenant and same-tenant cross-project read/write denial.
- Verify missing tenant context and pooled connection reuse fail closed.
- Run concurrent resolution, duplicate batch, and activation attempts under PostgreSQL row locks.
- Simulate first/middle/final batch and activation database failures.
- Measure approved Neon batch size, transaction duration, pool behavior, and configured-maximum
  document persistence time.
- Inspect release logs, metrics, traces, and errors for disclosure.

## Residual Risks And Step 11 Handoff

- PostgreSQL-specific vector comparison, exact cosine execution, RLS, and locking remain unexecuted
  in this workspace.
- Batch size `100` is a bounded conservative repository default, not measured Neon approval.
- Staged inactive rows intentionally survive a later batch failure for idempotent reconciliation;
  Step 11 must decide whether to retry, mark failed, or cancel using the stable error classification.
- Step 11 must pass the already-authorized scope, processing identity, counts, and
  `EmbeddingBatchResult`; react to created/resumed/reused state; stage; reconcile; activate; and mark
  failure. It must not bypass repository scope or expose inactive rows.
