# Step 12: Integrate the React Ingestion Workflow

## Step Status

Repository implementation complete. Release-service verification pending.

## Objective

Give users an accurate, recoverable interface from document selection through vector readiness. The
UI must show server-owned state, preserve the existing project-first flow, keep the reference WBS
template optional, and stop calling the placeholder summary workflow during this milestone.

## Prerequisites

- Step 11 API schemas and states stable.
- Current project, upload, job polling, and processing screens reviewed.
- Product decision for the post-ingestion milestone state: processed confirmation or future summary
  continuation.
- Supported formats aligned with backend: PDF, DOCX, XLSX, and CSV.

## User Flow

```text
Project page
  -> Create new WBS
  -> Select required project document
  -> Optionally select reference template
  -> Upload document/template
  -> Start document ingestion
  -> Observe scanning/extraction/chunking/embedding/persistence
  -> Document processed successfully
```

Do not present summary or WBS completion before those later features exist.

## UI States

### Selection

- no file;
- valid selected file;
- unsupported type;
- oversized file;
- missing permission;
- optional template selected/removed.

### Upload

- submitting;
- uploaded;
- recoverable storage/network error;
- permanent validation error;
- browser cancellation.

### Ingestion

- queued;
- scanning;
- extracting;
- OCR in progress when available as a safe stage;
- normalizing/chunking;
- embedding;
- persisting;
- ready;
- retryable failed;
- permanently rejected;
- cancelled/deleting.

Use stable dimensions for progress controls so text changes do not shift layout. Provide accessible
status text in addition to visual progress.

## API Integration

Add service methods for:

- start ingestion;
- get current ingestion;
- poll existing job status;
- retry/cancel only when backend supports them;
- fetch optional extraction preview.

Update `startWorkflow()` so it:

1. uploads the project document;
2. optionally uploads the template;
3. starts document ingestion;
4. returns document, template, job, and processing-run context;
5. does not call `startSummary()` in this milestone.

## Refresh and Re-entry

- Persist only safe route/context identifiers already available from project state.
- On refresh, fetch backend document/current-ingestion/job status.
- Do not restart a completed or in-progress ingestion automatically.
- If the in-memory session is missing, reconstruct from project/document APIs.
- Abort polling on unmount, logout, tenant switch, or route change.
- Apply bounded polling/backoff and stop on terminal state.

## Error Presentation

Map stable backend error codes to concise user messages. Never show:

- Python exceptions or stack traces;
- object keys, bucket names, storage endpoints, or signed URLs;
- Redis/Celery/database details;
- raw document content or vectors;
- tenant identifiers beyond normal UI context.

Retry buttons appear only for backend-classified retryable failures and authorized users.

## Implementation Tasks

1. Add ingestion response/status types.
2. Add API service functions with `AbortSignal` support.
3. Update workflow session type with ingestion job/run identifiers.
4. Remove immediate placeholder-summary start from `startWorkflow()`.
5. Map server states to presentation steps and progress.
6. Update processing screen for all supported stages.
7. Restore state on refresh and project re-entry.
8. Preserve the optional template behavior and current permissions.
9. Align accepted extensions and hint text with backend.
10. Add actionable safe error messages and retry controls.
11. Ensure tenant switch cancels requests and clears stale project context.
12. Add component and Playwright tests across desktop/mobile viewports.

## Files Expected to Change

- `WBS_UI/src/services/documentsApi.ts`
- new or updated ingestion API service
- `WBS_UI/src/services/workflowApi.ts`
- `WBS_UI/src/services/workflowTypes.ts`
- `WBS_UI/src/services/workflowPresentation.ts`
- `WBS_UI/src/views/CreateWbsScreen.tsx`
- processing screen and styles
- React/unit tests and Playwright workflow fixtures

## Test Matrix

Selection/upload:

- PDF picker and drag-and-drop;
- DOCX, XLSX, and CSV;
- disallowed DOC/XLS;
- maximum size error;
- optional template omitted and included;
- Generate/Continue button activates with required document only;
- permission-denied states.

Processing:

- every state renders correct status;
- monotonic progress presentation;
- long filename and long error localization-safe layout;
- retryable versus permanent failure;
- polling cancellation;
- API timeout and authentication expiry;
- tenant switch during processing;
- refresh/re-entry while queued, processing, ready, and failed;
- duplicate click does not create duplicate jobs.

Responsive/accessibility:

- desktop and mobile screenshots;
- focus order and keyboard upload;
- status announcements;
- text does not overlap or escape controls;
- icon buttons have accessible names/tooltips where needed.

## Security Checklist

- [x] UI does not decide authorization or trusted scope.
- [x] Tenant/project/document IDs come from authenticated application state.
- [x] No secret or private storage detail enters frontend configuration.
- [x] Raw vectors and object keys are never requested or rendered.
- [x] Polling stops on logout/tenant switch.
- [x] Backend error text is mapped rather than rendered blindly.
- [x] File input restrictions are convenience only; server validation remains authoritative.

## Verification

Run frontend build/tests and Playwright against the release API configuration with controlled fixture
documents. Verify desktop/mobile screenshots, refresh recovery, optional template flow, and a genuine
PDF from selection through ready status.

## Rollback

Disable the create-WBS ingestion entry point or route users back to project view. Do not restore the
placeholder summary as if it were a successful extraction. Backend jobs and uploaded objects remain
recoverable.

## Exit Criteria

- [x] UI starts ingestion rather than placeholder summary.
- [x] All server states and safe errors render accurately.
- [x] Refresh/re-entry restores the active workflow.
- [x] Required project document and optional template behavior is correct.
- [x] No vectors, storage details, or internal exceptions reach the browser.
- [x] Build, component, accessibility, and Playwright tests pass.

## Handoff to Step 13

Provide the document/run lifecycle actions exposed to users, terminal-state behavior, and navigation
paths. Step 13 completes deletion and reconciliation without leaving stale UI-visible documents or
searchable vectors.

