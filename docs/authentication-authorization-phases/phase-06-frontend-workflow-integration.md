# Phase 6: Complete Frontend and Workflow Integration

## Phase Status

Implemented and locally verified. Production workflow screens use focused tenant-scoped API modules;
mock route fixtures remain only in the fast Playwright component/integration suite.

## Outcome

The authenticated React application performs the complete tenant-scoped WBS workflow against live
FastAPI APIs. Mock workflow data is excluded from production execution.

## Execution Context

Existing frontend:

- `WBS_UI/src/services/apiClient.ts` manages memory access tokens and refresh;
- `WBS_UI/src/auth/AuthProvider.tsx` restores identity and selects a tenant;
- `WBS_UI/src/services/wbsService.ts` simulates jobs and results in memory;
- workflow views already model upload, processing, summary, analysis, result, and validation states;
- `WBS_UI/src/App.tsx` uses a state-based screen flow rather than URL routes.

Existing backend supports projects, documents, summaries, templates, jobs, generations, WBS,
validations, and exports. Before changing React, compare actual OpenAPI contracts to the frontend
types and document every gap.

## Required Decisions

- whether to introduce React Router for protected deep links and recovery links;
- polling intervals, maximum duration, and retry behavior;
- upload size/type UX and cancellation behavior;
- project creation naming behavior;
- whether tenant choice persists only for the session or through a non-sensitive preference;
- which mock-only result editing features need backend endpoints.

## Files Expected to Change

- `WBS_UI/src/services/wbsService.ts` or replacement API modules
- `WBS_UI/src/services/apiClient.ts`
- `WBS_UI/src/auth/authContext.ts`
- `WBS_UI/src/auth/AuthProvider.tsx`
- `WBS_UI/src/App.tsx`
- every workflow view consuming mock contracts
- frontend JSON mock data usage
- backend schemas/routes where contract gaps are confirmed
- backend workflow tests
- frontend Playwright tests
- environment and README documentation

## Contract Mapping

Map the existing UI journey to backend calls:

1. `POST /tenants/{tenant_id}/projects` creates the project.
2. `POST /tenants/{tenant_id}/projects/{project_id}/documents` uploads the required project file.
3. Optional template upload uses `POST /tenants/{tenant_id}/templates`.
4. Summary processing starts through the document-summary endpoint.
5. `GET /tenants/{tenant_id}/jobs/{job_id}` polls document processing.
6. Summary read/update/approve uses tenant document-summary endpoints.
7. Generation starts with document, approved summary, and optional template IDs.
8. Job polling waits for generation completion.
9. Latest WBS endpoint loads result data.
10. WBS update persists user edits where supported.
11. Validation endpoint starts and polls validation.
12. Export endpoint starts generation and returns a protected download URL.

Confirm exact paths and schemas from generated OpenAPI before implementation. Do not make React
types diverge silently from backend response models.

## Work Breakdown

### 1. Generate or define typed API contracts

Choose one approach:

- generate TypeScript types/client from FastAPI OpenAPI; or
- maintain narrowly scoped hand-written types with contract tests.

Generated code must be reproducible and reviewed. Do not edit generated files manually. If types are
hand-written, add backend/OpenAPI compatibility tests for critical responses.

### 2. Split workflow services by resource

Replace the large mock service with focused modules, for example:

- `projectsApi.ts`;
- `documentsApi.ts`;
- `summariesApi.ts`;
- `templatesApi.ts`;
- `jobsApi.ts`;
- `wbsApi.ts`;
- `validationsApi.ts`;
- `exportsApi.ts`.

Every module uses `apiRequest` and receives an explicit active tenant ID. No service reads a
hard-coded development tenant.

### 3. Introduce tenant-safe request state

- Include active tenant ID in query/cache keys.
- Abort outstanding requests and polling when tenant changes or user signs out.
- Clear project, job, summary, WBS, validation, and export state on tenant change.
- Reject calls when no active tenant exists.
- Do not persist tenant-owned response data to browser storage.

### 4. Implement upload flow

- Create project before document upload or define a documented combined backend operation.
- Validate file extension, MIME type, and size client-side for feedback.
- Keep server validation authoritative.
- Support optional template without blocking generation.
- Display upload progress only if transport supports accurate progress.
- Abort upload on sign-out or tenant switch.
- Never retry a non-idempotent upload automatically after an ambiguous network failure.

### 5. Implement job polling

Create one reusable polling utility with:

- fixed or bounded backoff interval;
- maximum duration;
- cancellation via `AbortController`;
- terminal success/failure/cancel handling;
- no overlap between polls;
- one auth refresh coordinated by `apiClient`;
- cleanup on unmount, navigation, sign-out, and tenant change.

Do not infer completion from UI timers. Use backend job status.

### 6. Integrate summary and generation

- Load backend summary after processing completes.
- Persist edits before approval.
- Do not start generation until the server confirms approval.
- Submit `template_id` only when a template exists.
- Preserve backend job and resource IDs in React state without using them as authorization proof.
- Handle resource conflicts and stale versions explicitly.

### 7. Integrate results, validation, and export

- Render backend WBS response instead of mock JSON.
- Persist edits through the WBS update endpoint.
- Start and poll validations using backend IDs.
- Download exports through authenticated API handling or a short-lived protected URL.
- Validate download content type and filename.
- Never render backend text as unsafe HTML.

### 8. Add protected routing or equivalent boundaries

If React Router is introduced:

- define login, recovery, tenant selection, Settings, and workflow routes;
- use auth loading state before redirect decisions;
- preserve only safe intended destinations;
- disallow arbitrary external redirect targets;
- handle direct reset/invitation links securely.

If the state machine remains, document deep-link limitations and ensure browser back/forward behavior
does not expose stale protected content.

### 9. Remove production mock paths

- Delete unused mock-only imports from production services.
- Retain fixtures under tests when useful.
- Ensure the production build cannot fall back silently to mock data on API failure.
- Show a real error state when the backend is unavailable.

## Error Handling Contract

- `401`: shared client attempts one refresh; failure clears auth and protected state.
- `403`: show Access Denied, refetch `/me`, and do not retry the mutation.
- `404`: show resource unavailable within the selected tenant.
- `409`: show stale/conflict state and offer a safe reload.
- `413`: show upload-size guidance.
- `422`: map field errors without rendering raw HTML.
- `429`: show retry guidance and honor `Retry-After` when present.
- `5xx/network`: preserve recoverable local form state where safe and offer retry.

## Test Plan

Contract tests:

- frontend request and response types match OpenAPI;
- optional template remains optional;
- error response normalization is stable.

Integration tests:

- project/document/summary/generation/WBS/validation/export happy path;
- permission denial by Viewer;
- expired access token during polling;
- tenant switch during a request;
- sign-out during polling;
- job failure and timeout;
- upload rejection and ambiguous network failure;
- server conflict during summary or WBS edit.

Browser tests:

- real login and one-tenant entry;
- multiple-tenant selection;
- full required-document-only flow;
- full flow with optional template;
- refresh while on a protected result screen;
- no cross-tenant data after switching workspace;
- responsive and keyboard behavior.

## Security Review Checklist

- [x] Every workflow call uses the selected tenant route and bearer token.
- [x] Tenant ID is never treated as proof of access.
- [x] Mock data cannot appear in production on API failure.
- [x] Polling and uploads stop on auth loss or tenant change.
- [x] Backend text is rendered safely.
- [x] Files receive server-side type, size, and storage validation.
- [x] Protected data is not stored in browser storage.
- [x] Redirect destinations are allowlisted and local.

## Rollout and Rollback

Integrate one resource group at a time behind an explicit development feature flag if needed. The
flag must default to real APIs in staging and production. Do not use a hidden automatic mock fallback.

Rollback may restore the prior UI build while keeping backward-compatible APIs. Preserve newly
created backend data and job records. Avoid removing endpoints in the same release that switches UI
clients.

## Exit Criteria

- [x] Production UI contains no mock workflow fallback.
- [x] Complete WBS journey uses live FastAPI and tenant authorization.
- [x] Active tenant scopes requests, state, and caches.
- [x] Job polling is cancellable and backend-driven.
- [x] Permission and auth errors follow the shared contract.
- [x] Optional template behavior remains correct.
- [x] Full integration and browser tests pass.

## Handoff

Provide OpenAPI/client generation decision, final API modules, mock removal evidence, polling
behavior, tenant-state design, contract test results, and a stable full workflow seed for Phase 7.
