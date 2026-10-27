# Step 7 persistence compatibility decision

The current Step 5 graph has one inventory-node completion and a bounded
one-megabyte artifact. A complete inventory can exceed that payload; emitting
multiple fake analyze completions would alter graph behavior and coverage.
The current PostgreSQL step-record allowlist also rejects evidence page kinds.

Use existing tenant/run-scoped AgentStepRun records for immutable evidence pages,
with separate reserved node identities and a manifest seal written last. Do not
advance the graph or invent processing runs. Repeated page writes must compare
the same input/artifact and completed records remain immutable. Existing RLS,
foreign keys, runtime-role separation and append-only rules remain in force.

The narrow additive migration extends only the step-record artifact allowlist
for Step 7 types and guards the new evidence-tool allowance inside the existing
execution JSON against resets. No new table, embedding change, graph redesign,
route or deployment is needed. The initial migration head is c29f4b8e710a.
The migration must be tested only on disposable databases; PostgreSQL runtime
qualification remains pending unless the opt-in tests are actually run.
