# Step 13: Complete lifecycle controls, operational limits, and observability

Status: planned. Depends on Steps 5-12.
Previous: [Step 12](step-12-summary-review-ui.md).
Next: [Step 14](step-14-evaluation-regression.md).

## Objective

Make the feature recoverable and bounded under document deletion, provider outage,
worker failure and limited VM resources, with useful operational evidence.

## Implementation tasks

1. Integrate workflow/revision/evidence/checkpoint cleanup into existing document
   deletion reconciliation. Hide derived summary/evidence access immediately when
   deletion starts, cancel pending work, stop new calls, and prevent late publishing.
   Clean owned derived records in FK-safe stages without weakening vector deletion.
2. Define the lifecycle for source re-ingestion: older revisions remain historical,
   are labelled stale when input activation changes, and cannot be approved or used
   downstream as current. Do not switch a running graph to another source run.
3. Extend cancellation and stale-lease reconciliation across outbox delivery,
   model requests and checkpoints. An already submitted provider call may finish
   or incur usage after cancellation; discard its late output and record the state.
4. Centralize per-call, per-run, per-tenant and per-provider budgets. Count retries,
   tool loops, schema repairs, evidence repairs and continuation tasks. Clamp user
   choices to operator maxima. Unknown/estimated token/cost usage must be labelled.
5. Preserve the one-slot model worker for the initial demo. Reuse process caches
   and read bounded batches. Load-test peak memory with ingestion/scanning, not
   just idle containers. Do not add another full embedding/reranker process or
   an Oracle-hosted 8B model without a separate capacity decision.
6. Add metrics for queue/run duration, node status, provider latency/errors/rate
   limits, calls/tokens, retries, budget stops, partial/blocked outcomes, processed
   coverage and citation validation failures. Avoid high-cardinality document/user
   labels and keep sensitive content out of metrics.
7. Audit connection changes, model selection, run start/cancel/retry, source/profile
   versions, human edits and approval. Expose concise step events, not hidden model
   reasoning or full prompts. External content tracing remains disabled by default.
8. Add readiness and operator diagnostics that distinguish disabled feature, missing
   encryption key, incompatible schema, broker/worker failure and invalid provider
   configuration. A transient provider outage must not automatically replace the
   tenant's model or make the whole unrelated API liveness endpoint fail.
9. Document recovery for secret-key loss/rotation, provider revocation, ambiguous
   timeouts, dead outbox records, worker restart and partial runs. Reuse existing
   retention policy controls; do not invent durations or enable destructive orphan
   cleanup/retention as an incidental part of this implementation.

## Proposed implementation targets

- Existing document lifecycle/reconciliation services plus workflow-specific cleanup.
- Worker/Beat reconciliation tasks, config bounds, readiness and observability.
- Sanitized operational runbook and lifecycle/fault-injection tests.

## Verification

Test deletion/cancellation at each graph stage, source activation during a run,
revoked credentials, stalled providers, expired leases and repeated delivery.
Check that deleted evidence is not retrievable even through old revision IDs.
Assert budgets persist over retries/restarts and diagnostics do not leak endpoints
with credentials, API keys, source text or signed URLs. Measure actual worker RSS,
queue latency and API responsiveness during the intended demo workload.

## Exit criteria

- [ ] Deletion/cancellation/staleness cannot be bypassed by retries or late callbacks.
- [ ] Total limits survive restarts and all nested model/tool paths.
- [ ] Operational signals are useful, bounded and content/credential-safe.
- [ ] Peak resource behavior is measured before concurrency is increased.
- [ ] Cleanup follows existing approved policy and includes the new derived records.
