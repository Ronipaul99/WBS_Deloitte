# Remaining Step 7 verification

Step 7 is **partially complete**, with live model/summary features disabled.
Prior Steps 1–6 qualification gates remain pending; their unit tests were not
reclassified as live provider, PostgreSQL or deployed-worker evidence.

## Disposable PostgreSQL

Provision a fresh empty `wbs_step07_*` PostgreSQL database with pgvector, separate
migration/runtime roles, no runtime superuser/BYPASSRLS, migration-role inheritance
or public-schema CREATE. Supply securely to the test process:

```text
STEP07_POSTGRES_MIGRATION_URL
STEP07_POSTGRES_RUNTIME_URL
STEP07_POSTGRES_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE
```

Run the isolated runner in [test results](test-results.md), selecting
`tests/test_agent_evidence_postgres.py`. The fixture refuses partial/ambiguous
configuration, a nonempty database or a database without the required prefix.
It does not read application URLs or migrate through application `env.py`.
Never substitute configured application/Neon URLs or delete shared data.

The three initial opt-in checks cover pinned pgvector/lexical queries, tenant
isolation/pool reuse, evidence-artifact constraints/immutability and SQL allowance
reset protection, plus fixture up/down/up preservation of legacy/vector data.
They remain skipped without disposable access. They are not a complete production
concurrency/performance proof. Verify actual competing writes/reservations,
crashes before/after page/seal commits, authorization/lifecycle races, query plans,
large-document resource bounds and runtime grants/RLS with restricted roles.

## Private RFP and canonical identity

An existing local historical export contains 161 chunks for the 110-page RFP.
Step 7 validated every exported descriptor and a six-page inventory chain; the
local PDF hash matches that historical export. No application database or cloud
object was read. Results are in ignored `backend/.data/step07-local-rfp-audit.json`.

The newer quality audit reports 391 active chunks, but no matching complete chunk
export was used here. Obtain a securely produced, authorized local canonical
export for that exact newer run if it is to be audited. Do not label the historical
161-chunk check as current-run verification. No original tokenizer-dependent
chunker digest was recomputed; Step 7 retains those stored digests and computes
separate text/metadata identities. A PDF alone is insufficient to prove current
database chunk identities, activation or RLS.

## Runtime and later integration

- Qualify actual selected model context/output/tokenizer limits and protocol
  overhead. The fallback byte estimate is labeled and conservative; it is not
  actual model token usage. Unknown/unqualified limits must remain unavailable.
- Use only the existing verified query-embedding identity and loaded retrieval
  models. No models were downloaded or re-embedded in this task. Benchmark
  memory/latency on the actual single-slot ARM64 worker before release.
- Later analyst/controller nodes must persist page/seal/reading-plan artifacts,
  issue completion receipts only for validated untruncated completed work and
  use fresh sequence identities for immutable coverage snapshots. No real analyst
  node or summary route is wired here.
- Actual outbound attempts must retain Step 3/4 security and Step 5 admission.
  Later publication must call the inventory/lifecycle guard, validate current
  evidence and preserve partial/stale status plus human approval requirements.
- Exact within-chunk source-span/page/row/cell maps are not persisted by current
  ingestion. Citations therefore stay at supported chunk/source-reference
  precision; ambiguous rows/pages are not fabricated. Existing locator heading
  limits may reject unusually long metadata explicitly instead of truncating it.

No Step 8+ behavior, live feature enablement, provider calls, deployment or VM
changes were performed. Complete these checks before claiming release readiness.
