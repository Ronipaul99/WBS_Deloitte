# Step 6 baseline and demonstrated gaps

Entry migration head: f05c8e31b742. Steps 1–5 are pre-existing staged/unstaged work; initial status, both diffs, source snapshots and hashes are preserved under ignored backend/.data/external-summary-step06. No applicable AGENTS.md or relevant memory-registry hit was found. No verified disposable PostgreSQL target or local postgres/initdb/docker/redis-server command is available.

Reproduced before correction: two production API tests revoke membership after initial route authorization and before lock_review returns. Structured PATCH and approval both return 200 instead of 403. Current authorization must be rechecked after the document/workflow/summary guard, within the mutation transaction. This is a narrow review-boundary correction, not an authentication redesign. The controlled SQLite interleaving demonstrates stale application authorization, not PostgreSQL lock/race correctness.

The new full-stack harness uses normal UI/API routes, isolated SQLite/storage, a loopback fake HTTP service writing the same database, and existing submission/tracking/import entry points. A test-only transport maps the fixed production request to loopback; production origin/TLS policy is unchanged. Synthetic canonical ingestion records are fixtures, not ingestion/model qualification. A controlled delivery/reconciliation pump is explicitly not an actual Celery/broker restart test. New control/fake routes exist only in a test ASGI module, never in the production application package.

No schema change is currently justified. Full-stack failures must distinguish harness setup/fixture issues from production defects. PostgreSQL/RLS, actual Celery restart, upstream TLS/protocol and deployed scheduling remain external gates.
