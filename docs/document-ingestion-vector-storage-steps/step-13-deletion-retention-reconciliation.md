# Step 13: Deletion, Retention, and Reconciliation

## Step Status

Repository implementation complete; external release and governance verification pending.

The deletion, reconciliation, UI, and fail-closed retention controls are implemented in the
repository. Destructive retention and orphan cleanup remain disabled because approved privacy
periods, release maintenance ownership, alert destinations, and accidental-deletion recovery have
not been supplied. Neon, restricted-role RLS, Redis/Celery restart, and private object-storage
verification remain external gates; see `step-13-artifacts/implementation-evidence.md`.

## Objective

Complete the document lifecycle so deletion reliably removes vector visibility and original/derived
artifacts, failed and superseded runs follow approved retention, and scheduled reconciliation repairs
or reports cross-service inconsistencies.

## Execution Context

The current document delete route removes the storage object first and then deletes the database
record. Once processing runs and chunks exist, a multi-system deletion can fail partway and must be
represented as a durable state rather than a single synchronous best-effort request.

## Prerequisites

- Steps 10 through 12 complete.
- Approved data-retention and privacy policy.
- Maintenance scheduler/worker ownership established.
- Audit and monitoring destinations approved.
- Recovery policy for accidental deletion documented.

## Deletion Design

Recommended stateful flow:

1. authorize deletion and lock the document lifecycle row;
2. set document status to deleting and prevent new ingestion/summary/WBS operations;
3. cancel or mark active ingestion for cooperative cancellation;
4. transactionally remove or make all chunk/run rows non-active and non-queryable;
5. commit database state so vectors are no longer visible;
6. enqueue object/derived-artifact deletion through an outbox;
7. delete the original object and any derived artifacts idempotently;
8. record completion and hard-delete or retain a minimal tombstone according to policy;
9. emit a safe audit event.

The API may return `202 Accepted` while cleanup continues. Do not report deletion complete while
vectors remain queryable.

## Retention Categories

Define approved durations for:

- failed processing runs;
- cancelled runs;
- superseded completed runs;
- job records and sanitized errors;
- malware detection events;
- document tombstones/audit events;
- temporary artifacts, which should normally be immediate cleanup rather than retention.

Do not encode unapproved legal/privacy periods in code defaults. Settings must be bounded and owned.

## Reconciliation Responsibilities

The scheduled reconciler must detect:

- database document references with missing objects;
- objects under managed prefixes with no document record;
- queued jobs never dispatched;
- processing runs without a viable job/heartbeat;
- completed runs with invalid chunk/vector counts;
- documents pointing to missing or non-completed runs;
- deleting documents with remaining active vectors or objects;
- expired failed/superseded runs;
- stale temporary-workspace directories.

Each repair must be idempotent, tenant-scoped, bounded by batch size, observable, and safe to stop and
resume. Destructive orphan cleanup should require age threshold and, where risk warrants, operator
approval.

## Implementation Tasks

1. Add deleting/deleted/tombstone lifecycle representation.
2. Add a deletion outbox or reuse a reviewed durable outbox abstraction.
3. Update delete API to initiate lifecycle deletion and return accurate status.
4. Prevent new processing once deletion starts.
5. Implement idempotent chunk/run cleanup under RLS scope.
6. Implement idempotent S3 and derived-artifact deletion.
7. Add maintenance retention settings and validation.
8. Implement bounded retention cleanup.
9. Implement reconciliation reports and safe automatic repairs.
10. Add operator commands for dry-run and approved repair modes.
11. Add metrics, alerts, audit events, and runbook.
12. Update UI/project lists to represent deleting and remove completed deletions.

## Files Expected to Change

- document model and migration if lifecycle fields are missing
- document delete route/service
- ingestion repository/orchestrator cancellation checks
- maintenance/reconciliation service and CLI/scheduled task
- storage cleanup service
- UI project/document presentation
- deletion, retention, reconciliation, and browser tests
- operations runbook

## Test Matrix

Deletion:

- ready document deletion;
- uploaded but unprocessed document;
- queued/processing document;
- failed document;
- document with previous/superseded runs;
- storage unavailable after vectors are hidden;
- database failure before vectors are hidden;
- duplicate deletion request;
- cross-tenant deletion denied;
- service restart during cleanup.

Retention:

- records before/at/after cutoff;
- bounded batches and pagination;
- active/current run never removed;
- legal/hold marker if included by policy;
- repeated cleanup is idempotent;
- safe dry-run report.

Reconciliation:

- every inconsistency category listed above;
- no cross-tenant repair;
- orphan age threshold;
- partial batch failure and resume;
- false-positive prevention for active work;
- metrics and alerts on unrepairable state.

## Security Checklist

- [x] Authorization is rechecked when deletion starts.
- [x] Vectors become non-queryable before external cleanup is reported complete.
- [x] Cleanup operations remain tenant/project/document scoped.
- [x] Recursive filesystem cleanup validates the exact target root.
- [x] Object deletion uses persisted generated keys only.
- [x] Audit events exclude document content and credentials.
- [ ] Reconciler runtime role has only required permissions.
- [x] Destructive orphan cleanup has age/approval safeguards.

## Observability and Alerts

Metrics:

- deletion requested/completed/failed;
- deletion age and retry count;
- objects/chunks/runs removed;
- retention batches and failures;
- reconciliation findings by safe category;
- repair success/failure and backlog age.

Alert when vectors remain visible for a deleting document, deletion exceeds its target age, orphan
backlog grows, cleanup repeatedly fails, or reconciliation detects ownership inconsistencies.

## Verification

Run deletion and reconciliation tests against an isolated Neon branch and release object bucket
prefix. Interrupt cleanup at controlled points and prove restart resumes safely. Confirm an authorized
exact vector query returns no chunks immediately after the database visibility-removal transaction.

## Rollback

Disable new deletion requests if cleanup is defective, but continue safe retries for already hidden
documents. Never restore vector visibility automatically. Accidental deletion recovery must follow the
approved Neon/object-storage restore runbook and tenant-consistency validation.

## Exit Criteria

- [ ] Deletion is durable, idempotent, and accurately represented.
- [ ] Vector visibility ends before deletion is reported complete.
- [ ] Object and derived-artifact cleanup retries safely.
- [ ] Retention never removes an active/current run.
- [ ] Reconciliation detects and handles every defined inconsistency.
- [ ] Cross-tenant, interruption, restart, and release-environment tests pass.
- [ ] Operations runbook, alerts, and ownership are recorded.

## Final Handoff

The ingestion feature is ready for summary development only after all thirteen steps meet their exit
criteria. The summary workflow consumes every ordered chunk from the document's active ready run. It
must not use a top-k vector query to produce a complete document summary.

