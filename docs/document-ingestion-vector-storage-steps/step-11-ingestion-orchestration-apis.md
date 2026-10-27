# Step 11: Add Ingestion Orchestration and APIs

## Step Status

Repository implementation complete; external release verification pending.

## Objective

Coordinate download, scanning, extraction, normalization, chunking, embedding, persistence, retries,
and cancellation as one durable asynchronous workflow. Replace the current implicit jump from upload
to placeholder summary with a dedicated ingestion job and processing-run lifecycle.

## Prerequisites

- Steps 4 through 10 complete.
- `DOCUMENT_INGESTION` job type and processing states approved.
- Celery and Redis release services available with non-eager execution.
- Existing job polling and tenant authorization patterns reviewed.

## API Contract

### Start ingestion

```http
POST /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions
```

Returns `202 JobResponse`. Required behavior:

- require the approved update/process permission;
- verify document and project belong to authenticated tenant;
- return the existing queued/in-progress job for an idempotent duplicate request;
- return the completed run/job when the exact ingestion identity is already ready;
- create job and processing run transactionally before dispatch;
- never accept a storage key, model name, tenant ID, or project ID in the request body.

### Get current ingestion

```http
GET /api/v1/tenants/{tenant_id}/documents/{document_id}/ingestions/current
```

Returns safe run status, counts, timestamps, extractor/model identity, warnings, and stable failure
code. It does not return temporary paths, object keys, content, vectors, credentials, or internal
exception traces.

### Retry or cancel

Add only if product permissions and Celery cancellation semantics are approved. Retry creates or
resumes an idempotent versioned run. Cancellation is cooperative at durable stage boundaries and
must not terminate an unrelated task.

### Extraction preview

Optional and separately permissioned. Return paginated canonical chunk text and source metadata from
the active run, never embeddings. Apply response-size and rate limits.

## Worker Orchestration

The orchestration sequence is:

1. load job, run, and document under trusted tenant/project scope;
2. reject stale, cancelled, deleted, or already completed work safely;
3. mark scanning and commit progress;
4. download, hash, and scan inside a temporary workspace;
5. confirm content hash and idempotency identity;
6. mark extracting and invoke the registered extractor;
7. normalize and chunk;
8. embed in bounded batches;
9. persist inactive chunks/vectors;
10. atomically activate the run;
11. mark job completed with safe result identifiers;
12. clean temporary artifacts in `finally`.

Commit progress only at durable boundaries. Do not commit on every page, row, chunk, or vector.

## Retry Policy

Retryable:

- transient S3, Redis, scanner, database, or temporary-disk unavailability;
- worker interruption before activation;
- approved transient OCR/model runtime errors.

Permanent:

- malware detection;
- unsupported/encrypted/malformed file;
- configured resource limit exceeded;
- no extractable content;
- integrity mismatch requiring investigation;
- authorization or ownership mismatch.

Use bounded exponential backoff with jitter and a maximum attempt count. Record attempt count and
last safe error. Exhausted jobs enter failed/dead-letter handling rather than looping indefinitely.

## Reconciliation Rules

Handle dispatch failure between database commit and broker publication. Prefer an outbox or scheduled
reconciler that finds queued jobs without an active Celery delivery and republishes them idempotently.
Do not rely on an in-process request retry alone.

Reconcile contradictions such as:

- job queued but run absent;
- run processing but no live/recent task heartbeat;
- run completed but document pointer not activated;
- job completed but run not completed;
- cancelled/deleted document with active processing.

## Implementation Tasks

1. Add `DOCUMENT_INGESTION` to job types and schemas.
2. Add route module or document subroutes for ingestion operations.
3. Add permission mapping using existing role patterns.
4. Create job and processing run in one transaction.
5. Add Celery task and dispatch function with non-eager release enforcement.
6. Implement orchestration using services from Steps 4-10.
7. Implement monotonic progress and safe result payloads.
8. Implement retry classification, backoff, and max attempts.
9. Add dispatch outbox/reconciliation or equivalent durable solution.
10. Add cooperative cancellation if included.
11. Block summary/WBS generation without an active ready run.
12. Add job/run reconciliation command or scheduled task.
13. Add metrics, tracing spans, and safe audit events.

## Files Expected to Change

- `backend/app/models/domain.py`
- `backend/app/schemas/domain.py`
- new or updated ingestion routes
- `backend/app/api/router.py`
- `backend/app/services/dispatcher.py`
- `backend/app/services/ingestion/orchestrator.py`
- `backend/app/worker.py`
- summary/generation prerequisites
- API, worker, retry, and reconciliation tests

## Test Matrix

API and authorization:

- authorized start/current status;
- viewer or unauthorized role denied;
- cross-tenant document denied;
- unknown/deleted document;
- ingestion disabled/unready;
- duplicate start request returns consistent job/run.

Worker lifecycle:

- complete successful path with fakes for boundaries and real integration for critical services;
- each durable progress transition;
- transient retry at each external dependency;
- permanent failure at each parser/security condition;
- hard worker termination before/after persistence;
- duplicate Celery delivery;
- cancellation at each safe boundary;
- cleanup after every path.

Consistency:

- database commit succeeds but dispatch fails;
- reconciliation republishes once;
- completed run with stale job repaired safely;
- previous active run survives new failure;
- document deletion races with processing;
- service restart while jobs are queued/in progress.

## Security Checklist

- [x] Public payload cannot select storage, model, or scope identifiers.
- [x] Permissions apply to start and status; ingestion retry, cancel, and preview remain unavailable.
- [x] Worker reloads trusted scope from database.
- [x] Retry cannot bypass malware or integrity failures.
- [x] Result/error payloads exclude content and infrastructure details.
- [x] Celery serialization remains JSON-only.
- [x] Task payloads are bound to job/run IDs, and generic cancellation rejects ingestion jobs.
- [x] Summary/WBS operations require a ready active run.

## Observability

Expose safe metrics for queue age, stage duration, attempts, completion/failure, error category, and
reconciliation backlog. Trace by opaque job/run/document/project/tenant IDs without content. Alert on
queue-age, failure-rate, dead-letter, and reconciliation thresholds.

## Verification

Run API/worker suites with Redis and the release services. Stop and restart API and worker processes
during controlled jobs, simulate dispatch failure, and prove the job is recovered without duplicate
active chunks.

## Rollback

Disable new ingestion creation, allow or cooperatively stop in-flight jobs, and preserve original
objects plus previous active runs. Do not switch to eager FastAPI background tasks as a rollback.

## Exit Criteria

- [x] Dedicated ingestion API and Celery task replace the placeholder-summary trigger.
- [x] Job/run creation and dispatch are recoverable and idempotent.
- [x] Retryable and permanent failures are correctly separated.
- [x] Progress is monotonic and recoverable after process restart through persisted state.
- [x] Summary/WBS routes reject documents without a ready active run.
- [x] Repository authorization, retry, reconciliation, and restart-recovery tests pass.

## Handoff to Step 12

Provide stable API schemas, state/progress values, polling behavior, safe error codes, counts, and
retry/cancel capabilities. The React workflow must consume these contracts without manufacturing
client-side status.

