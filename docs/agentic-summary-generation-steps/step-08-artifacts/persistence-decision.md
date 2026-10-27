# Step 8 artifact compatibility decision

The initial repository migration head is `e53c7a19b402`. Step 7 already supports
immutable, scoped `orchestration.v1` checkpoints and WorkflowStore's atomic
artifact/checkpoint/continuation transaction. Its typed nested result union did
not yet contain extraction evidence or a completion receipt.

Step 8 adds `AnalystArtifact` to that nested union. It carries exactly one bounded
analyst batch, gap outcome, register page or register seal. A batch includes both
the validated extraction and its hash-bound BatchCompletion. Processed coverage
is derived from those same committed records, so no second independently
committed coverage record is necessary.

Database JSON roots remain `orchestration.v1`; no SQL artifact-kind allowlist,
table, RLS policy, grant, foreign key, checkpoint authorization rule or migration
needs changing. Existing completed-record immutability remains in force. New
schema setup is not performed at runtime.

Only CONSOLIDATE gains a self-continuation, for bounded gap rounds and one register
page per durable task. Existing cursor ceilings remain enforced. Batch artifacts
are restricted to ANALYZE at the matching batch index; gap/page/seal artifacts
are restricted to the appropriate CONSOLIDATE transitions.

Earlier-step changes are limited to this typed union/transition, the new analyst
response schema on the existing adapter interface, its envelope-cache capacity,
and allowing explicitly synthetic ContextBudget inputs for isolated tests.
Synthetic qualification cannot enable a profile or satisfy live-worker checks.
Existing fixture/schema snapshots reflect only these contract changes.

Actual PostgreSQL serialization, RLS, trigger and concurrent recovery verification
is pending. Local JSON/SQLite checks do not substitute for it.
