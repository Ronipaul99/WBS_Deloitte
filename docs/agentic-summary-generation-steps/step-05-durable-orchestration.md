# Step 5: Build durable workflow orchestration

Status: partially implemented locally, 2026-10-27. PostgreSQL isolation/concurrency,
trusted worker routing and deployed recovery qualification remain pending. Depends on Steps 1-4.
See [implementation evidence](step-05-artifacts/implementation-evidence.md) and
[remaining inputs](step-05-artifacts/remaining-inputs.md).
Previous: [Step 4](step-04-provider-adapters.md).
Next: [Step 6](step-06-model-management-ui.md).

## Objective

Make workflow delivery, progress, recovery, and cancellation reliable before
connecting real agents to the existing summary endpoint.

## Implementation tasks

1. Build the explicit LangGraph state machine behind application contracts:
   validate/pin, inventory, analyze batches, consolidate/fill gaps, write, verify,
   optionally repair once, and publish draft. Placeholder node functions may be
   test fixtures only; the release feature remains disabled until real nodes exist.
2. Create workflow run/job/outbox records in one transaction. Use a new workflow
   outbox with its own constraints, not the ingestion-specific dispatch table.
   Publish run/step IDs only; keep credentials and document text out of Redis tasks.
3. Add claimed/publishing/published/retry/dead delivery states, bounded backoff,
   leases, reconciliation, and duplicate delivery handling. Persist continuation
   work with the completed node artifact in the same transaction.
4. Implement tenant-scoped checkpoints from the Step 1 spike. Each completed node
   has an input hash, version, validated artifact, usage and replay identity. A
   resumed graph reuses valid completed work and rejects incompatible state versions.
5. Use short SQL transactions around state changes, not provider calls. Lease/fencing
   tokens protect writes from an expired worker. Check current lifecycle, source
   activation, authorization, profile/connection availability and budgets before
   issuing a provider call and before committing/publishing output.
6. Schedule bounded batches/continuations on the existing model-enabled worker.
   Keep concurrency one initially, reuse process-level retrieval models, and avoid
   waiting synchronously for child tasks on that same single-slot worker.
7. Implement cancellation, heartbeat/stale-run recovery, safe retry/resume, and
   sanitized status events. Revoke/disable checks must also apply to resumed work.
   Enforce a total ceiling across transient retries, schema repairs and graph repairs.
8. Add the generic execution path for synthetic provider-connection tests so Step 6
   tests the worker's network path. Require credentials at execution time by ID.
   Do not make connection tests depend on a full summary or a private document.
9. Introduce a disabled-by-default agentic summary feature gate and truthful
   readiness/configuration errors. Never silently fall back to mock summary output.

## Proposed implementation targets

- `backend/app/services/agents/graph.py`, `state.py`, `checkpoints.py`, and `runner.py`.
- A workflow outbox publisher/reconciler, worker tasks, and job progress schemas.
- `backend/app/worker.py`, dispatcher integration, and release settings.
- `test_agent_recovery.py`, `test_agent_outbox.py`, and PostgreSQL checkpoint tests.

## Verification

Inject failures before/after DB commit, broker publish, node completion, checkpoint
write, and output publication. Deliver the same task twice; expire a lease while
an old attempt is running; cancel during a provider call; resume after worker loss.
Assert one active revision, no replay of completed nodes, accurate error/usage
state, and no late publication after deletion/cancellation. A timed-out external
call may still be billed; tests must not assert impossible provider exactly-once behavior.

## Exit criteria

- [ ] Commit/publish crashes are recoverable through the outbox.
- [ ] Duplicate or fenced attempts cannot create duplicate active outputs.
- [ ] Recovery preserves pinned inputs, completed work, and tenant isolation.
- [ ] Total budgets and cancellation/disable checks apply on every execution path.
- [ ] Worker deployment remains single-slot with no duplicate Beat scheduler.
