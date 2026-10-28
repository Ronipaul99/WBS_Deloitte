# Step 6 implementation and verification

Date: 2026-10-29. Local synthetic implementation is verified to the extent reported below. **PostgreSQL, real upstream/TLS, extraction quality and deployed-worker qualification remain pending.**

## Baseline and scope

Read the Step 6/index/master plan, predecessor artifacts and current submission, tracking, import, review, permissions, transaction, lifecycle, worker and UI implementations. Inspected shared `backend/tests/conftest.py`: it deletes `.test-wbs.db` and `.test-data`, so it was not loaded. No applicable AGENTS.md was found. Current migration head, read from source without connecting to a database, is `f05c8e31b742`.

Initial working/staged diffs, status, relevant source snapshots and file hashes are retained in ignored `backend/.data/external-summary-step06/`. Steps 1–5 were already present as staged/unstaged work. Concurrent staging was observed and preserved; this implementation did not stage/reset/commit/push. Final source-hash comparison isolates Step 6 changes to the files listed below. Actual configuration, migrations and unrelated application source remain unchanged.

The demonstrated gap was recorded in [design-boundaries.md](design-boundaries.md). The state inventory, ownership, ambiguity policy and fault matrix are in [recovery-matrix.md](recovery-matrix.md).

## Confirmed defect and changes

**Defect reproduced:** after initial route authorization, membership could be revoked while a structured save/approval waited for locks. Both controlled route tests returned HTTP 200 instead of 403 before correction. Route admission alone did not revalidate current permission at acceptance.

| Files changed by Step 6 | Purpose |
| --- | --- |
| `backend/app/services/external_summary_review.py` | Fresh user/tenant/membership and auth-version check after awaited review locks. Sanitized denial; no auth policy redesign. |
| `backend/app/api/routes/summaries.py` | Apply that check to structured PATCH and approval only. Legacy branches retain behavior. |
| `backend/tests/test_external_summary_recovery.py` | Revocation interleavings, ADMIN/EDITOR success, intent rollback, broker acknowledgement ambiguity, safe retry/key rotation, lost database acknowledgement and nested-data tests. |
| `backend/tests/summary_fullstack_support/server.py` | Test-only real ASGI application, fake service sharing its disposable SQLite database, strict transaction preconditions and controlled delivery/reconciliation pump. Never loaded by production code. |
| `WBS_UI/scripts/run-external-summary-fullstack.mjs` | Launch isolated backend, fake HTTP service, actual UI and browser tests; reject unsafe cleanup paths; track/stop owned PIDs and verify port/resource cleanup. |
| `WBS_UI/tests/fullstack/external-summary.spec.ts` | Six actual backend/UI scenarios using normal routes, with no application status/result API interception. |
| `docs/external-summary-api-integration-steps/step-06-artifacts/*` | Actual boundaries, outcomes, fault/scenario matrix and pending qualification. |

No schema or dependency change was necessary. No migration was added or applied to the application database. Existing imported identity, original generated evidence, separate edits, revision fields and external Job ownership are preserved.

## Isolated full-stack architecture

Run from `WBS_UI`:

```text
node scripts/run-external-summary-fullstack.mjs
```

The runner starts owned loopback Uvicorn API and fake-service processes, Vite and Playwright. It generates a fresh synthetic tenant UUID, unique project/document markers and ephemeral test secrets. It inherits only necessary OS environment fields, constructs its own SQLite/storage paths, disables application env-file loading, and uses a separate Vite env directory. It never copies application/Neon URLs or existing credentials.

The actual UI calls the actual backend's login, project/upload, summary submission/status/read/PATCH/approve, workflow and deletion routes. The fake HTTP service creates realistic externally owned jobs in the **same isolated database**, then test controls advance stored status/step/progress/result. The production submission transport is exercised through its test-only injection point: an exact fixed-origin POST is mapped to loopback. Production destination and TLS policy are unchanged. The fake is not real upstream HTTPS qualification.

Synthetic canonical completed-ingestion records are seeded locally. No real extraction/embedding/model process runs. A controlled queue/pump invokes existing production submission, tracking/import reconciliation and deletion entry points. This establishes browser-independent application behavior; it **does not** establish actual Celery/broker interruption, Beat uniqueness, deployed routing or worker process restart.

## Results by verification layer

### 1. Local backend/service tests

From `backend`:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_recovery.py tests/test_external_summary_review.py tests/test_external_summary_import.py tests/test_external_summary_tracking.py tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py tests/test_upload_transaction_lifecycle.py -q -W error::RuntimeWarning
```

Final broad run: **200 passed, 5 skipped, 3 warnings in 118.80 seconds**. The earlier broad run before the last three additional cases passed 197 tests. The warnings are existing Alembic `path_separator` deprecations. Five explicit skips reserve PostgreSQL verification; none is presented as passing.

Final focused recovery suite after adding positive role/intent-failure cases: **15 passed, 1 skipped in 15.52 seconds**. It uses the same isolated command/plugin with only `tests/test_external_summary_recovery.py` selected. No destructive shared conftest or application database was used. Strict active-transaction checks prevent SQLite's normal early return from hiding the original PostgreSQL precondition.

### 2. Mocked browser/component regressions

From `WBS_UI`, using an ignored Step 6 config with its own loopback Vite server:

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step06/mock-playwright.config.mts --grep-invert "status recovery re-fetches|aborts status work on navigation"
```

**81 passed, 0 failed, 0 skipped in 1.6 minutes.** Covers summary progress/review, legacy workflow integration, resume, project/document navigation, duplicate dialogs, workflow polish and unaffected ingestion presentation. This suite intercepts application APIs and is reported separately from full-stack tests.

The two previously documented ingestion-navigation failures were deliberately excluded, not changed or claimed fixed:

- `status recovery re-fetches without starting another ingestion`
- `aborts status work on navigation and suppresses its stale response`

### 3. Actual local synthetic full-stack

Final runner: **6 passed, 0 failed, 0 skipped in 45.8 seconds**, exit 0; owned processes stopped, all three ports released, temporary database/uploads removed. Earlier successful runs also passed six scenarios (48.6, 56.8 and 54.3 seconds); these are reruns, not additional independent scenarios.

| Requested scenario | Actual result and limit |
| --- | --- |
| A. New submission -> progress -> import | Passed. Explicit UI action, distinct request/job, stored 0/25/65/100 progress and real step labels, completed-100 -> one unapproved seven-section draft. |
| B. Duplicate submission | Passed in the local harness. Two concurrent compatible repeat API calls return the same request; one fake upstream call and zero local legacy summary jobs. This is not PostgreSQL uniqueness/locking proof. |
| C. Several jobs | Passed. A newer unrelated completed job cannot replace the acknowledged job. |
| D. Reload / lost storage | Passed. Reload and a fresh browser context resume saved workflow/review without a generation POST. |
| E. Browser closed | Passed. Closing the browser does not prevent controlled worker-side import; reopening sees the saved draft. |
| F. Worker restart | Partial. Pausing/resuming the test delivery/reconciliation pump preserves committed identity and imports; service tests preserve durable attempt counts. Actual Celery/broker process restart remains unverified. |
| G. Failure / unavailable / ambiguity | Failed-job and lost-acknowledgement cases pass through the real backend. Unavailable/configuration/status variants additionally pass service and mocked browser tests; no real service outage was induced. |
| H. Inconsistent completion / payload delay | Passed. RUNNING-100 never opens review; completed-99 does not import; missing payload waits; later same-row payload imports. Grace expiry is also covered at the service boundary. |
| I. Seven-section mapping | Real UI shows seven sections and null confidence; immutable generated content is retained. Detailed pages, citation namespaces, warnings, safe text and provenance mapping also pass mocked browser tests. |
| J. Edit/save/reload | Passed through real UI/API. Stable section content survives switching/save/reload; generated evidence and external result digest remain unchanged. |
| K. Mutation/no-op approval | Passed. No-op preserves approval/revision; actual later mutation clears approval. |
| L. Unseen revision | Passed through actual routes using controlled sequential conflicting requests. Stale save and approval return 409. True simultaneous PostgreSQL save/import/approval races remain pending. |
| M. Deletion / stale / re-upload | Passed. Changed canonical run rejects late import; ordinary deletion blocks upload while pending, completes through the existing deletion handler, then same bytes upload as a new document without old summary association. |
| N. Legacy / navigation / ingestion / WBS compatibility | Local service and mocked browser regressions pass for existing boundaries. Real full-stack upload/delete/re-upload passes. Actual ingestion/model workers and live WBS generation were not run. External WBS remains disabled. |

### 4. Disposable PostgreSQL

Not run. No independently supplied verified disposable database/restricted runtime roles were available; local PostgreSQL/initdb/docker tools were unavailable. FORCE RLS/grants, actual migration chain execution on PostgreSQL, JSON byte admission, pooled scope, simultaneous claims/imports/saves/approval and lock behavior remain pending. SQLite migration/recovery tests do not establish these properties.

### 5. Live upstream

Not run, as required. No real summary/provider call, paid request, private document transfer, current credential use, actual TLS observation or upstream idempotency/cancellation qualification occurred. Fake-service success cannot establish extraction quality or real wire compatibility.

### 6. Deployed worker

Not run. Actual broker/Celery restart, worker routing, scheduler uniqueness and deployed reconciliation remain pending. No application/backend service or SSH tunnel was stopped or restarted.

## Quality checks and development failures

Passed:

```text
.venv/Scripts/python.exe -m ruff check app/services/external_summary_review.py app/api/routes/summaries.py tests/test_external_summary_recovery.py tests/summary_fullstack_support/server.py
.venv/Scripts/python.exe -m ruff format --check app/services/external_summary_review.py tests/test_external_summary_recovery.py tests/summary_fullstack_support/server.py
.venv/Scripts/python.exe -m pip check
npm.cmd ls --depth=0
npm.cmd run lint
node --check scripts/run-external-summary-fullstack.mjs
node node_modules/typescript/bin/tsc -p tsconfig.app.json --incremental --tsBuildInfoFile ../backend/.data/external-summary-step06/app.tsbuildinfo
node node_modules/vite/bin/vite.js build --configLoader runner --outDir ../backend/.data/external-summary-step06/dist
git diff --check
git diff --cached --check
```

`pip check` found no broken requirements; `npm ls --depth=0` completed successfully. The build emitted the expected notice that the ignored output directory is outside the UI root. A built-bundle marker scan found no upstream origin, ngrok, `X-API-Key` or backend secret setting strings. No dependencies changed. Git reports restricted access to a global ignore file; repository checks still complete successfully. Final hash comparison (`backend/.data/external-summary-step06/final-scope.json`) reports exactly two changed pre-existing production files and the seven new Step 6 test/runner/evidence files listed above; other initial file hashes remain unchanged.

Development results are not hidden: the pre-fix role tests failed as expected (200 vs 403). An initial harness run had six setup failures due to a missing test-only base URL; the production boundary failed closed. An expanded unit run exposed synthetic-user deactivation leaking between test cases and a nesting test aimed at the encoding helper rather than full result validation; fixture restoration and the correct production validation boundary fixed those tests. A test invocation using two stale IDE test filenames collected no tests; the actual lifecycle/CORS regression file was then selected. Final runs above supersede those development runs. No unrelated navigation tests were altered.

## Cleanup, remaining gates and exit status

Final ignored run evidence: `backend/.data/external-summary-step06/artifacts-run-1793214267160-8d2c63b87c1f/cleanup.json` and sanitized process logs. Cleanup verifies owned PIDs stopped, all owned ports released and run database/storage removed. Ignored baseline snapshots, sanitized synthetic logs, browser output/cache and build artifacts are intentionally retained for review; no synthetic application resources remain in a live database.

Locally verified: the implemented backend/UI integration traverses submission, exact job tracking, truthful progress, one-time import, persisted review, lossless editing and revision-safe explicit approval under controlled synthetic conditions. The reproduced review-authorization defect is fixed and covered. **The integration is not fully qualified** while PostgreSQL, actual Celery/deployed routing and real upstream/quality gates remain pending. Broader retention/tombstone hard-purge ordering noted in Step 4 remains outside this normal-lifecycle test scope.

No unrelated product behavior, generator/verifier/retrieval system, WBS algorithm, actual environment/secret configuration, deployment, feature enablement, application-database migration, real-service call, private-document access, commit or push occurred.
