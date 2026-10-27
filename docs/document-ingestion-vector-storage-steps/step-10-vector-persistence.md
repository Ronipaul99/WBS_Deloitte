# Step 10: Implement Transactional Vector Persistence

## Step Status

Repository implementation complete as of 2026-10-26. PostgreSQL/Neon pgvector, restricted-role RLS,
pooled-context, and concurrent activation verification remain external gates recorded in
`step-10-artifacts/implementation-evidence.md`.

## Objective

Persist chunks and FastEmbed vectors into Neon pgvector so that incomplete work never becomes active,
retries never create duplicate active data, previous successful runs survive failed reprocessing, and
every operation is tenant/project/document scoped.

## Prerequisites

- Step 3 schema and RLS complete.
- Step 8 stable chunks available.
- Step 9 ordered validated vectors available.
- Runtime session helper can set transaction-local tenant context.
- Batch-size and transaction-duration limits approved for Neon.

## Repository Contract

Create application-owned repository methods requiring explicit scope:

- create or resolve processing run;
- insert chunk/vector batch;
- finalize run statistics;
- atomically activate completed run;
- mark failed run with safe error;
- load active ordered chunks;
- internal exact similarity verification;
- list/delete superseded runs;
- reconcile run/chunk counts.

No repository method may infer tenant scope only from a document UUID or expose an unscoped query.

## Persistence Algorithm

1. Begin a transaction and set `app.tenant_id` locally.
2. Lock or otherwise serialize the target processing run/document activation path.
3. Confirm job, run, document, tenant, and project ownership.
4. Confirm the run remains in the expected persistence state.
5. Validate chunk count equals vector count and every vector has 384 finite values.
6. Insert bounded chunk batches with deterministic ordinals and hashes.
7. Verify persisted count and aggregate metadata.
8. Mark the run completed.
9. Set `documents.current_processing_run_id` and ready status.
10. Commit activation atomically.

If one transaction would exceed operational limits, stage batches under the inactive run in separate
transactions, then perform final count/hash validation and active-pointer switch in a final atomic
transaction. Inactive staged rows must never be returned by active-document queries.

## Idempotency and Concurrency

- Derive an idempotency identity from document content hash, extractor/chunker version, embedding
  provider/model/revision, and formatting policy.
- Re-delivery of the same task resolves the existing run.
- Existing persisted ordinals are checked rather than blindly duplicated.
- A completed identical run can be reused.
- Only one queued/in-progress run per document is allowed.
- A failed reprocessing run does not unset the previous current run.
- Concurrent activation attempts use row locking or equivalent database serialization.

## Exact Verification Query

Add an internal-only repository method using cosine distance. It must always include:

```sql
WHERE tenant_id = :tenant_id
  AND project_id = :project_id
  AND processing_run_id = :active_processing_run_id
```

Document-specific verification additionally filters `document_id`. Do not expose this method as a
public search API in this scope.

## Implementation Tasks

1. Implement scoped repository class/functions.
2. Add transaction-local tenant context at repository transaction boundaries.
3. Add chunk/vector batch validation.
4. Implement inactive batch inserts.
5. Implement final persisted-count and ordinal validation.
6. Implement atomic active-run switch.
7. Implement idempotent duplicate-delivery behavior.
8. Implement failure recording without overwriting previous active run.
9. Implement active ordered chunk loading for future summary work.
10. Implement internal exact cosine verification.
11. Add metrics for batch size, insert duration, activation, and rollback.

## Files Expected to Change

- `backend/app/services/ingestion/repository.py`
- `backend/app/db/session.py`
- domain models only if implementation reveals missing constraints
- PostgreSQL/pgvector integration tests
- orchestration fakes for later Step 11 tests

## Test Matrix

Successful persistence:

- one and multiple batches;
- correct source metadata and vector dimension;
- active pointer set only after count validation;
- active ordered chunks load correctly;
- exact similarity query returns expected ranking within scope.

Failure behavior:

- database failure in first/middle/final batch;
- wrong vector count or dimension;
- NaN/infinite vector;
- duplicate ordinal/hash;
- activation conflict;
- document removed during processing;
- stale job/run state;
- previous active run preserved after failure.

Isolation and concurrency:

- tenant A cannot persist or read tenant B chunks;
- project A cannot retrieve project B in the same tenant;
- missing tenant context fails closed;
- duplicate task delivery is idempotent;
- two concurrent activation attempts yield one consistent current run;
- pooled connection does not retain previous tenant context.

## Security Checklist

- [x] Every method requires tenant and project scope.
- [ ] RLS is active under the runtime role.
- [x] Active queries require the document's current run.
- [x] Raw vectors are not serialized into public responses or logs.
- [x] SQL uses bound parameters and SQLAlchemy expressions.
- [x] Failures cannot activate partial data.
- [x] Previous active data survives failed reprocessing.

## Verification

Run integration tests against an isolated Neon branch using the actual runtime role. Insert a fixture
document's chunks, activate the run, execute the exact scoped query, simulate reprocessing failure,
and verify the old run remains active.

## Rollback

Disable ingestion writes while retaining stored inactive and active runs. Prefer forward correction
after vectors exist. Do not drop tables or pgvector automatically. Superseded/inactive rows can be
removed later through Step 13 retention only after integrity is confirmed.

## Exit Criteria

- [ ] All chunks/vectors persist with source metadata and correct dimensions.
- [x] Partial data never becomes active.
- [x] Duplicate task delivery does not duplicate active data.
- [x] Failed reprocessing preserves the previous active run.
- [x] Exact query is always tenant/project/current-run scoped.
- [ ] RLS, concurrency, rollback, and Neon integration tests pass.

## Handoff to Step 11

Provide repository operations, state preconditions, idempotency identity, progress-safe batch
boundaries, and failure classifications. Step 11 coordinates the complete worker lifecycle around
these operations.

