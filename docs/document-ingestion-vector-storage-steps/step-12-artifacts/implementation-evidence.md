# Step 12 Implementation Evidence

## Status

Repository implementation is complete. Verification against a release deployment of the Step 11
API, Redis/Celery workers, Neon, ClamAV, OCR, and the packaged embedding model remains pending.

## Changed Files

- `WBS_UI/src/auth/permissions.ts`
- `WBS_UI/src/services/documentsApi.ts`
- `WBS_UI/src/services/ingestionApi.ts`
- `WBS_UI/src/services/templatesApi.ts`
- `WBS_UI/src/services/workflowApi.ts`
- `WBS_UI/src/services/workflowPresentation.ts`
- `WBS_UI/src/services/workflowSessionStorage.ts`
- `WBS_UI/src/services/workflowTypes.ts`
- `WBS_UI/src/views/CreateWbsScreen.tsx`
- `WBS_UI/src/views/ProcessingProjectDocumentScreen.tsx`
- `WBS_UI/src/views/ProcessingProjectDocumentScreen.css`
- `WBS_UI/src/views/ProjectScreens.tsx`
- `WBS_UI/src/App.tsx`
- `WBS_UI/tests/auth-mocks.ts`
- `WBS_UI/tests/authorization.spec.ts`
- `WBS_UI/tests/create-wbs.spec.ts`
- `WBS_UI/tests/ingestion-workflow.spec.ts`
- `WBS_UI/tests/step12-visual.spec.ts`
- `WBS_UI/tests/workflow-integration.spec.ts`
- `WBS_UI/tests/workflow-mocks.ts`
- `WBS_UI/tests/fullstack/authorization-workflow.spec.ts`
- `docs/document-ingestion-vector-storage-steps/step-12-react-workflow-integration.md`
- `docs/document-ingestion-vector-storage-steps/step-12-artifacts/implementation-evidence.md`

No backend application, schema, migration, configuration, or backend-test file was changed for
Step 12.

## API Contracts

- `startIngestion()` sends an empty-body `POST` to the Step 11 ingestion start endpoint.
- `getCurrentIngestion()` reads the current document ingestion with `AbortSignal` support.
- `JobResponse` includes `error_code` and `attempt_count`.
- `IngestionStatusResponse` mirrors every field in the Step 11 backend schema.
- Workflow startup uploads the required document, uploads the optional template when selected,
  starts ingestion once, and obtains the processing-run identity from current status.
- Startup does not call the summary endpoint.

## State And Presentation

The UI allowlists `QUEUED`, `SCANNING`, `EXTRACTING`, `CHUNKING`, `EMBEDDING`, `PERSISTING`,
`ACTIVATING`, `RETRY_WAIT`, `COMPLETED`, and `FAILED`. Unknown status or stage values fail closed
into a safe status-unavailable state. The displayed progress is the maximum server progress observed
for the current mounted workflow and therefore cannot move backward.

`COMPLETED` ends at a document-processed confirmation with a route back to the project. `FAILED`
uses a stable error-code allowlist and never renders the backend error message. `RETRY_WAIT` is shown
as a server-managed automatic retry; the UI exposes neither an ingestion retry nor cancellation
operation. Transport recovery performs only another status read.

## Recovery Storage Contract

Session storage contains only a version marker and tenant, project, document, ingestion-job,
processing-run, and optional-template identifiers. Entries are namespaced by tenant and project and
validated before use. Recovery reloads the project, document, optional template, and current
ingestion from authenticated APIs. It never restarts ingestion.

Context is cleared on completed-flow navigation, logout, tenant switch, invalid ownership, or invalid
stored data. Leaving an active or failed workflow preserves identifiers so the project page can offer
`Resume document processing`.

## Security And Accessibility

- Starting ingestion requires both `document:upload` and `document:process`; `wbs:generate` is not
  treated as ingestion authorization.
- Project formats are PDF, DOCX, XLSX, and CSV. DOC and XLS remain unsupported. These browser checks
  are convenience checks only; server validation remains authoritative.
- API errors, object keys, storage details, endpoints, vectors, document content, credentials, and raw
  exceptions are neither persisted nor rendered.
- Requests and polling are aborted on unmount, navigation, logout, and tenant switch. Late responses
  are suppressed by the abort boundary.
- The processing heading receives route-entry focus, changing status is announced, and progress uses
  a labeled `progressbar` with stable dimensions.
- Keyboard file selection, responsive layouts, long filenames, and mobile controls are covered by
  Playwright.

## Repository Verification

- `npm.cmd run build`: passed (`tsc -b` and Vite production build).
- `npm.cmd run lint`: passed with no findings.
- Focused upload, authorization, ingestion, recovery, and visual Playwright tests: passed.
- Complete frontend Playwright suite: 71 passed, 0 failed, 0 skipped.
- Polling timeout, transport error, authentication refresh, navigation abort, tenant-switch abort,
  stale-response suppression, duplicate submission, and queued/processing/completed/failed recovery
  paths are covered.
- Desktop screenshot: `step12-desktop-processing.png`, 1440 x 980.
- Mobile screenshot: `step12-mobile-completed.png`, 390 x 844.
- Visual assertions found no horizontal overflow, console errors, or unexpected failed requests.
- `git diff --check`: passed with line-ending notices only and no whitespace errors.

The screenshots use mocked, synthetic frontend fixtures. They are not evidence that release services
processed a real document.

## External Gates

- The release full-stack Playwright suite was not run because approved release API and worker-service
  connectivity was not available in this repository verification session.
- Run the full-stack Playwright ingestion path against a release API with non-eager Celery and Redis.
- Verify a synthetic native PDF reaches `COMPLETED` through Neon storage, private ClamAV, extraction,
  chunking, the packaged FastEmbed model, and pgvector activation.
- Repeat with DOCX, XLSX, CSV, scanned PDF, and optional-template fixtures.
- Verify refresh and tenant switch while a real worker job is active.
- Inspect release logs, metrics, traces, browser requests, and storage for prohibited content or
  infrastructure disclosure.

## Residual Risks

- Mocked frontend tests cannot prove broker delivery, worker recovery, malware scanning, OCR,
  embedding-model packaging, Neon RLS, or vector activation.
- The production poll timeout and backoff are verified with browser clock control, but release network
  latency and proxy behavior still require deployment testing.
- Step 12 intentionally stops after document processing. Summary, WBS generation, vector search,
  deletion, and Step 13 lifecycle actions remain outside this implementation.
