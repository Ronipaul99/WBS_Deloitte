# Step 3 implementation and verification

Date: 2026-10-28. Status: implemented and verified locally with synthetic metadata. Not live-qualified. The backend integration remains default-disabled.

## Baseline and scope

The initial checkout already contained uncommitted Steps 1–2 backend sources, migrations, tests and artifacts, and staged integration planning documents. Initial working/staged diffs and file hashes were captured in ignored `backend/.data/external-summary-step03/`. Comparing these hashes at completion confirmed that this step changed no existing backend or planning files. No repository AGENTS.md was found.

Step 2 already exposes every required metadata field through its scoped request-status endpoint and `WorkflowState.external_summary`. **No backend compatibility change, schema extension, migration, new route or dependency was necessary.** PostgreSQL, upstream protocol/TLS and deployed-worker qualification remain pending as recorded in Steps 1–2.

## Files and responsibilities

| File under WBS_UI | Change |
| --- | --- |
| `src/services/workflowTypes.ts` | Separate external submission/status contracts and explicit legacy/external response union; optional workflow metadata handoff. |
| `src/services/summariesApi.ts` | Validated submission union, authenticated scoped status GET with AbortSignal, supported metadata/bounds and document/workflow/request/job identity checks. |
| `src/services/polling.ts` | Optional per-response callback, sequential requests, total waiting deadline, request abortion, timer/listener cleanup and late-result rejection. Existing default intervals and terminal return behavior remain available. |
| `src/views/ExternalSummaryProgress.tsx` | Existing-design progress surface, truthful states, read-only Check status, last-known updates, permissions and accessible progress/status semantics. |
| `src/views/WorkflowCheckpointScreen.tsx` | Retain acknowledged request identity, prevent repeated submission clicks, abort in-flight submission on unmount, distinguish external execution, and offer read-only recovery after unconfirmed submission. Legacy submission/recovery remains available. |
| `src/App.tsx` | Key the checkpoint by tenant/document/workflow so changing scope discards old local observation state and aborts its operations. |
| `src/components/WorkflowSurfaces.css` | Narrow responsive styles for summary progress and metadata, using the existing workflow palette/surfaces. |
| `tests/external-summary-progress.spec.ts` | Production service/component browser coverage with synthetic metadata and existing authentication/workflow mocks. |

## Client contract and presentation

- The application `request_id` is never used as a legacy `JobResponse.id`. The exact external type remains `DOCUMENT_SUMMERIZATION`.
- POST is an explicit Generate summary action. Its response selects the execution branch; no browser feature flag or upstream configuration is added.
- Pending submission has no invented job or percentage. An acknowledged ID may be shown as **not verified**; progress/step display requires the backend's VERIFIED binding.
- Reads use only `GET /api/v1/tenants/{tenant}/documents/{document}/summary/requests/{request}?workflow_id={workflow}` through the existing API client. Unknown status vocabulary, unsupported readiness, malformed bounds or mismatched identities fail closed. Once observed, a non-null job ID cannot change, including after Check status.
- Application status and raw supported service status are separate. Current step, progress, attempts and timestamp come from metadata. No simulated progress, guessed processing stages, confidence or approval is added.
- RUNNING at 100 stays running. Backend-projected inconsistent completion remains explicitly waiting/unavailable. COMPLETED at 100 with IMPORT_PENDING displays Finalizing and stops automatic waiting. It never opens an older or placeholder review. This client does not support IMPORTED; Step 4 remains absent.
- Failed, cancelled, stale, unavailable, rejected and unknown-submission outcomes remain distinct. No generic job result/cancel/retry endpoint is used for an external request.

## Polling, cancellation and recovery

External polling reads immediately, then waits 2, 3, 4.5 and at most 5 seconds between sequential requests. A single loop owns the request; it delivers every validated response. The total browser wait is 120 seconds, including a stalled read. Terminal/unavailable/import-pending metadata stops automatic polling.

A deadline pauses observation without changing execution state. A read failure retains the last validated progress and explicitly labels it last known. Check status starts another bounded observation of the **same** request/job and never POSTs. It does not reset backend execution budgets or authorize a remote retry.

Unmount/navigation, logout, tenant changes and document/workflow changes abort the local requests/timers. Late results are rejected even when a test request ignores abortion. An aborted browser wait is not represented as remote cancellation. Status announcements contain stable status text rather than timestamps or polling ticks. The progressbar exposes real min/max/value and a readable percentage.

Existing browser hints remain unchanged and contain navigation IDs only. Reload restores the authoritative workflow. After lost storage, the project workspace and explicit document Go to workflow action recover the same external metadata. Project clicks, duplicate upload dialogs and document actions were not redesigned.

## Actual checks

From `WBS_UI`, using an ignored isolated Playwright/Vite configuration under `backend/.data/external-summary-step03/` (port 5193, mocked API routes):

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step03/playwright.config.mts
```

Final focused suite: **40 passed, 0 failed, 0 skipped** in 50.1 seconds. This includes 21 Step 3 tests and 19 existing duplicate/workflow-resume/navigation/dialog tests. The ignored configuration was subsequently extended to run existing ingestion/workflow compatibility suites separately; results are recorded below.

Additional existing-poller compatibility command:

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step03/playwright.config.mts ingestion-workflow.spec.ts workflow-integration.spec.ts
```

**23 passed, 2 failed** in 55.7 seconds. Both failures expect the legacy project-page button `Resume document processing` after Back to project (ingestion-workflow.spec.ts lines 119 and 152). They occur before the later recovery assertions. The current project workspace does not expose that button.

To distinguish these from a Step 3 regression, a separate ignored Vite load overlay served the initial HEAD versions of the Step 3-modified frontend modules on port 5194, without changing the checkout. These modules had no pre-existing modifications at capture time. Running the same two tests with `baseline-playwright.config.mts --grep 'status recovery re-fetches|aborts status work on navigation'` reproduced **both identical failures**. These are existing test/navigation mismatches and were deliberately left outside scope. This evidence does not establish that their later, unreached assertions pass.

Final combined regression run, after the last source change (authoritative workflow metadata takes precedence over a retained submission acknowledgement):

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step03/playwright.config.mts --grep-invert 'status recovery re-fetches|aborts status work on navigation'
```

**63 passed, 0 failed** in 1.2 minutes, with the two independently reproduced baseline failures explicitly deselected. No tests were silently marked skipped or rewritten to hide those failures. This combined run includes all 21 Step 3 tests and 42 existing polling/workflow/ingestion/navigation/dialog checks.

The read-failure recovery test was then strengthened to focus Check status and press Enter; its focused rerun passed (1 passed, 5.8 seconds). A final source build to ignored `final-dist` and focused ESLint also passed after the last source/test edits.

Coverage includes each pending/visibility/running update; RUNNING 100; inconsistent completion; completed/import-pending; failed/cancelled/stale/unavailable/ambiguous states; unknown metadata and identity changes; read errors and browser deadline; repeated clicks; lost acknowledgement; refresh and lost hints; explicit document recovery; delayed reads across navigation/document/tenant changes and logout; legacy summary review; permissions; sequential polling and listener/deadline cleanup; browser traffic/storage/console secret exclusion. All provider/execution responses are fixtures, not actual upstream observations.

Earlier runs: 33 tests passed before coverage expansion. One expanded run had 19 passes and one **test-code** failure (`request.url()` used for a captured string property); that assertion was corrected before the passing final 40-test run. Initial sandboxed browser runs were interrupted during local web-server shutdown and are not counted as completed successes. The isolated suite completed with process permissions allowing it to stop its own Vite server. No user backend, VM or tunnel was stopped.

From `backend`:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_tracking.py tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py -q
```

**95 passed, 2 skipped, 2 warnings** in 55.76 seconds. The skips explicitly reserve disposable PostgreSQL qualification; the warnings are existing Alembic `path_separator` deprecations. Shared destructive `tests/conftest.py` was inspected and excluded. These isolated tests do not use the configured application/Neon database or delete `backend/.test-data`.

Frontend checks:

```text
npm.cmd run lint
node node_modules/typescript/bin/tsc -p tsconfig.app.json --incremental --tsBuildInfoFile ../backend/.data/external-summary-step03/app.tsbuildinfo
node node_modules/vite/bin/vite.js build --configLoader runner --outDir ../backend/.data/external-summary-step03/dist
git diff --check
git diff --cached --check
```

All passed. No formatter is configured in package.json; ESLint, existing source conventions and whitespace checks were used. The build warns that its ignored output directory is outside the UI root; this is intentional and no output-directory deletion was requested. A bundle marker scan found zero matches for `ngrok`, `X-API-Key` or `EXTERNAL_SUMMARY_API_KEY`. Existing legacy `result_payload` handling elsewhere in the application remains unchanged; the new status path does not load results.

Desktop/mobile images were visually inspected: [running at 100](summary-desktop.png), [finalizing/import pending](summary-mobile.png). They use synthetic IDs/data. Mobile width 390px was also checked for horizontal overflow. These screenshots do not establish live execution behavior or a full assistive-technology audit.

## Exit criteria and remaining qualification

Locally satisfied: typed backend handoff, separate request/job identities, visible intermediate responses, real accessible progress, bounded/cancellable sequential polling, read-only recovery, scope isolation and duplicate-click prevention, legacy compatibility, and explicit finalizing without premature review.

Pending: disposable PostgreSQL migration/RLS/pooling/concurrency verification from Steps 1–2; live status vocabulary/write timing and TLS/ngrok compatibility; actual deployed worker/Beat routing and progress; full screen-reader testing. Step 4 result import and Step 5 review editing remain intentionally unavailable. This is not an end-to-end live summary-generation qualification.

No Steps 4–6 functionality, result loading/import, document_summaries writes, seven-section editing, real summary-service calls, private uploads, feature enablement, actual environment/credential edits, deployment, CI/Docker/Nginx/VM changes, commits or pushes occurred. Existing/concurrent changes were preserved.
