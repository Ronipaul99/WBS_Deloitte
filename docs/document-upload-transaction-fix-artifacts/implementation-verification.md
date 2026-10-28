# Document upload transaction fix: implementation and verification

Date: 2026-10-28. Baseline: `94e4ca20189c645f1da2457c74f807c48b40ddc6`.
The initial checkout was clean. Earlier fixes and their test files were absent.
The actual Alembic head is `c92e6b4a710d` (`summary_question_bank`). No migration was changed.

## Cause and transaction boundaries

The reservation transaction ended before object storage I/O. Publication then called
`set_local_tenant_context` without a new transaction. PostgreSQL correctly rejected this.
Compensation repeated the error after rollback, masking the original failure.
Fresh heartbeat, backfill, reconciliation and workflow-dispatch sessions had the same
assumption. Response loading after commit and deletion requests on fresh sessions also
needed an explicit transaction boundary. Conflict rollback additionally expired ORM
tenant objects; recovery now carries the previously trusted scalar tenant ID instead.

`ensure_tenant_transaction` begins a transaction only when necessary, otherwise joins the
caller-owned transaction, then applies transaction-local tenant scope. It never commits.
The original strict PostgreSQL guard is unchanged. No session-global tenant settings or
dummy SQL queries were introduced. Existing SQL ownership predicates and RLS remain.

Reservation commits before storage save. Publication begins a new scoped transaction,
revalidates destination authorization and fences ownership. Compensation rolls back,
begins scoped work, verifies the attempt identity and checks references/other ownership,
then commits before deleting its object. Completion marking uses another scoped
transaction. A committed attempt is never compensated, including acknowledgment loss
after the database committed. The request retains/awaits its cleanup task; secondary
cleanup failures are sanitized and cannot replace the primary exception. Failed or
stopped heartbeat tasks block publication; heartbeat errors are observed and logged
without exception bodies. Durable attempts remain available to reconciliation when
compensation cannot finish.

Backfill and reconciliation use separate transactions around storage work. Workflow
dispatch closes the claim transaction before broker I/O and applies scope again for
acknowledgment. Workflow reads after commit and fork/template response construction
now begin/join a scoped transaction.

## Files and purpose

| File | Change |
| --- | --- |
| `backend/app/db/session.py` | Explicit begin-or-join helper; preserve strict guard. |
| `backend/app/main.py` | Explicitly permit the upload's `Idempotency-Key` CORS header. |
| `backend/app/services/document_content.py` | Transaction boundaries, scalar scope after rollback, ownership-safe compensation, original-error preservation and heartbeat checks. |
| `backend/app/services/document_workflow_resume.py` | Scoped transactions for authoritative document/workflow reads after commit. |
| `backend/app/services/document_workflow_backfill.py` | Scope fresh backfill/reconciliation sessions. |
| `backend/app/services/document_workflow_dispatch.py` | Scope claim, acknowledgment and reconciliation sessions. |
| `backend/app/services/document_lifecycle.py` | Begin/join transaction for deletion requests; existing explicit worker transactions stay intact. |
| `backend/tests/upload_transaction_support.py` | Opt-in temporary SQLite database, uploads and synthetic authenticated identities; no shared conftest or application `.env`. |
| `backend/tests/test_upload_transaction_lifecycle.py` | Transaction, CORS, lifecycle, response/commit failure, cancellation, heartbeat and backfill regressions. |
| `backend/tests/test_document_content_claims_postgres.py` | Require a named disposable database and restricted runtime role; begin the fixture's seed transaction before setting tenant scope. Live execution remains skipped. |
| `WBS_UI/scripts/run-fullstack.mjs` | Per-run Vite config/cache so tests do not overwrite a developer server's dependency cache. |
| `WBS_UI/tests/fullstack/document-workflows.spec.ts` | Actual browser PDF upload, custom-header preflight, workflow read and truthful disabled-ingestion response. Existing duplicate/resume scenario retained. |

## Reproduction and test discipline

Before changing production code, existing claim tests under the isolated strict fixture
reproduced the reported publication and compensation failures: **2 failed, 1 passed**
before stopping at `--maxfail=2`. Evidence: ignored local
`backend/.data/upload-transaction-fix/before.xml`.

The opt-in plugin enforces the PostgreSQL transaction precondition even for SQLite.
It uses a newly created temporary directory and never imports the destructive shared
`tests/conftest.py`. The original guard's PostgreSQL branch is also tested with a fake
SQL sink to assert that the guard remains strict and emits `SET LOCAL`; this is not RLS
or live PostgreSQL verification. `UPLOAD_TEST_NATIVE_SCOPE=true` runs separate schema
compatibility tests with their intended SQLite no-op behavior and cache-clearable
isolated settings. Fixture-only embedding identity is synthetic; no model is downloaded.

## Commands and results

Run backend commands from `backend` with `.venv/Scripts/python.exe`:

```text
-m pytest --noconftest -p tests.upload_transaction_support
  tests/test_upload_transaction_lifecycle.py
  tests/test_document_content_claims.py
  tests/test_document_deduplication_api.py
  tests/test_document_workflow_recovery.py
  tests/test_document_lifecycle.py
  tests/test_ingestion_dispatch.py
  tests/test_document_content_claims_postgres.py
  tests/test_hybrid_retrieval.py -q --tb=short
  --junitxml=.data/upload-transaction-fix/verified.xml
```

Final regression result: **51 passed, 3 skipped** (147.99 seconds), recorded in the
XML above. The three PostgreSQL tests are skipped because disposable connection
configuration is absent. The final focused suite separately passed **17 tests**;
these overlap the full run and are not additional unique tests. The PostgreSQL
fixture now requires a `wbs_upload_test_*` or `wbs_fullstack` database, checks that
the runtime role is neither superuser nor BYPASSRLS, and starts its seed transaction
before applying scope. Its checks have not been run against a live server here.

With process-local `UPLOAD_TEST_NATIVE_SCOPE=true`:

```text
-m pytest --noconftest -p tests.upload_transaction_support
  tests/test_document_lifecycle_contract.py tests/test_pgvector_schema.py
  -q --tb=short --junitxml=.data/upload-transaction-fix/schema.xml
```

Result: **10 passed**, six existing Alembic `path_separator` deprecation warnings.
This includes disposable SQLite upgrade/recovery and schema compatibility checks.

From `WBS_UI`: `npm.cmd run test:e2e:document-workflows:smoke`: **2 passed**.
This starts real FastAPI and Vite servers on isolated ports 8011/5187, migrates/seeds
only the per-run SQLite database, and uses actual Chromium HTTP requests. The first
attempt failed because the shared Vite cache could not be unlinked (`EPERM`); the
per-run cache change resolved it. There are no mocked browser API responses.

Frontend `npm.cmd run lint` passed. Normal `npm.cmd run build` failed to write the
existing `node_modules/.tmp/*.tsbuildinfo` files (`EPERM`). Equivalent type checking
and production bundling passed without changing permissions or production config:

```text
node node_modules/typescript/bin/tsc -p tsconfig.app.json --incremental
  --tsBuildInfoFile ../backend/.data/upload-transaction-fix/app.tsbuildinfo
node node_modules/typescript/bin/tsc -p tsconfig.node.json --incremental
  --tsBuildInfoFile ../backend/.data/upload-transaction-fix/node.tsbuildinfo
node node_modules/vite/bin/vite.js build --configLoader runner
  --outDir ../backend/.data/upload-transaction-fix/ui-dist
```

Ruff lint and format checks on all changed Python files passed. `pip check` reported
no broken requirements. `git diff --check` passed. Initial/final tracked-file hashes
and scope review are retained in ignored `.data/upload-transaction-fix/` artifacts.

## Lifecycle results and limits

| Scenario | Actual verification |
| --- | --- |
| New upload | API 201, fingerprint, stored bytes, committed attempt, READY claim and readable workflow. Actual browser PDF upload also 201. |
| Duplicate and renamed content | Reuses the original document; no second document/object. Different bytes with the same name create another document. Cross-project and cross-tenant behavior covered. |
| Idempotency | Replay reuses; changed content/key mismatch rejected. Response failure and commit-acknowledgment loss preserve the committed document and allow safe retry. |
| Deletion pending | Normal DELETE API returns 202. Same-content upload remains blocked while deletion is pending. |
| Deletion completion | Real deletion service executes against isolated storage, status API confirms DELETED, object removed and content claim released. Worker invocation is explicit in the test, not deployed Celery delivery. |
| Re-upload | Fresh request key creates a different document/workflow after deletion. Old key returns 410. Replaying old deletion work leaves replacement object/claim intact. |
| Failure/retry | Storage failure, primary/cleanup failure, lost ownership, expiry, heartbeat failure, cancellation, response failure, commit ambiguity and rollback conflict recovery covered. |
| Reconciliation/dispatch | Existing takeover cleanup and workflow dispatch/retry tests pass under strict fresh-session checks. Ingestion outbox compatibility tests pass with synthetic publishers. |
| Ingestion | Browser smoke correctly receives 503/DOCUMENT_INGESTION_DISABLED in its deliberately isolated disabled environment. No successful extraction or real embedding inference is claimed. |

## Outstanding live verification and cleanup

No Docker/PostgreSQL executable or disposable PostgreSQL URLs were available. Therefore
actual PostgreSQL RLS, separate-role grants, pooling and concurrent database recovery
remain unverified; the three live database checks were skipped rather than pointed at
the application database. The configured application uses PostgreSQL/S3 with ingestion
enabled and non-eager tasks, but its API at localhost:8000 could not be reached from
this session (`URLError`). Its S3, Redis/Celery, scanner and actual embedding/pgvector
flow were not exercised. No production/live-environment success is inferred from
SQLite, synthetic embeddings or fake publishers.

All created accounts, projects, documents and objects were confined to temporary test
databases/storage. The isolated test directories and owned API/UI processes were
cleaned up; ignored XML, baseline/scope metadata and build artifacts remain locally.
No application rows were truncated/deleted and no private documents or actual account
credentials were used. No `.env`, secrets, CI, Docker/Nginx, question bank or live VM
changes; no deployment, feature enablement, dependency upgrade, commit or push.

Restart the normal backend to load the code changes. No application migration or
configuration change is required. Old abandoned attempts from earlier failed requests
may still require the existing ownership-safe reconciliation after their grace period;
this task did not inspect or remove those application records.
