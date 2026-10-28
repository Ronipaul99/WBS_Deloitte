# Step 3: Live status, step and progress display

Status: planned. Depends on Steps 1-2 submission identity, scoped status API and workflow recovery metadata.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), preceding implementation/artifacts and current frontend polling/workflow conventions first.

## 1. Objective

Display the external job's real status, `current_step` and progress while generation runs. A reload or navigation back resumes the same request/job. The browser never submits directly to ngrok and never starts another job merely to refresh status.

This step adds progress behavior only. Completed content remains unavailable until Step 4 imports it and Step 5 maps it for review.

## 2. Inspect existing frontend boundaries

Inspect:

- `WBS_UI/src/services/summariesApi.ts`, `workflowTypes.ts`, `jobsApi.ts` and `apiClient.ts`.
- `WBS_UI/src/services/polling.ts`, `workflowApi.ts` and workflow session storage.
- `WorkflowCheckpointScreen.tsx`, existing processing/review navigation and the current Generate summary action.
- Existing progress, loading, error, accessibility and responsive styles.
- Steps 1-2 API schemas, supported states and readiness behavior.

The current generic poller returns a terminal response only. Do not conclude that polling is working visually just because requests appear in the network log.

## 3. Frontend contracts and services

Add typed external-summary execution/status responses matching the backend contracts:

- `request_id` and nullable exact external `job_id` remain distinct.
- Preserve `job_type: 'DOCUMENT_SUMMERIZATION'` and trusted document identity.
- Include submission/binding/import states, normalized status, provider status, step, progress, attempts, update timestamp and sanitized errors.
- Readiness means an imported summary is available, not merely that the remote job completed.

Update `startSummary` to consume the explicit legacy/external response union. Do not force external responses into the legacy `JobResponse.id` convention. Add a scoped status-read function with an abort signal.

If Step 2's workflow response already includes the needed status projection, reuse it consistently. Otherwise use the request-status endpoint and reconcile terminal navigation through the authoritative workflow boundary. Avoid two competing polling loops for one summary attempt.

No service function may contain the upstream origin/key, call the upstream result URL, query PostgreSQL, or introduce a public CORS workaround.

## 4. Generate summary and progress transitions

Implement this sequence:

1. User explicitly clicks Generate summary after authorized ingestion readiness.
2. Disable the action during submission, invoke the existing backend summary boundary once and retain the returned request identity.
3. Render submission-pending state with truthful text while external job identity is still null.
4. After exact binding, display the acknowledged job identity and database-backed status/step/progress.
5. Update the screen after every valid polling response.
6. When remote completion is confirmed, show finalizing/import pending until the backend says `IMPORTED` and supplies a matching summary identity.
7. Refresh authoritative workflow state and navigate to review only after matching import readiness. Before Step 4 exists, remain in finalizing/unavailable state; do not mock a review response.

Do not dispatch the local placeholder processor, start ingestion, start WBS generation, or invoke another summary POST from any completion handler.

## 5. Per-poll updates and bounded waiting

Either add an optional `onUpdate` callback to `pollResource` or introduce a small summary-specific wrapper. Preserve existing helper behavior for other consumers.

Required semantics:

- Deliver every successfully validated response to the progress view, including the initial response.
- Use sequential reads so slow responses do not overlap or arrive out of order.
- Start around two seconds and back off to five seconds; enforce a bounded browser wait through existing configurable conventions.
- Abort requests/timers on unmount, tenant/document/request change, logout and explicit navigation away.
- Reject a response that no longer matches the active request/job/document identity.
- A browser wait timeout pauses waiting and provides Check status. It does not mark the database job failed and does not POST a replacement.
- A transient read error preserves last-known progress with an explicit unavailable/stale status. It cannot be shown as fresh running data indefinitely.
- Reset a resumed browser wait only for read observation; never reset submission idempotency or worker execution policy.

Test timer/listener cleanup; do not introduce a general polling rewrite outside this use case.

## 6. UI mapping

| Status data | UI |
| --- | --- |
| Normalized status | Queued / Running / Finalizing / Failed / Cancelled / Unavailable. |
| Raw `provider_status` | Supporting service-status text where useful; never an approval badge. |
| `current_step` | Primary current-step line, such as `SUMMARY:QUEUED`; use a friendly label only for a confirmed vocabulary. |
| `progress` | Accessible real percentage/progress bar; never a simulated timer. |
| `job_id`, `job_type` | Secondary details/copy control after acknowledgement/binding. |
| `attempt_count` | Supporting attempt metadata; do not suggest the user should resubmit blindly. |
| `updated_at` | Last-known update timestamp, formatted consistently in the user's locale. |
| Sanitized error | Actionable failure/unavailable message without raw service diagnostics. |
| `result_state` | Generation completed versus result validating/importing versus review ready. |

Use existing workflow design components and status surfaces. Provide `role="progressbar"` with value bounds, readable percentage text and a polite status region. Avoid announcing unchanged status or every polling tick unnecessarily. Keep focus on the user's action unless a deliberate screen transition occurs.

A `RUNNING` job at 100 remains finalizing/running. A completed job below 100 or with an invalid result remains unavailable/pending according to Step 2; neither opens review.

## 7. Resume and error behavior

- Store only navigation identifiers in the existing session hint. The backend record remains authoritative after browser storage is lost.
- Opening the project still shows the project workspace. Go to workflow explicitly restores the current summary stage.
- Reopening a running summary resumes status reads; it never repeats Generate summary.
- Keep separate handling for submission error, unknown submission, job-read error, remote generation failure, import failure and browser wait timeout.
- Check status always reads the same request/job. Show unsupported retry/cancel as unavailable; do not call the generic endpoints for external jobs.
- A stopped browser is not remote cancellation. Late responses from a previous tenant/document cannot update the current screen.

## 8. Scope boundary

Allowed: summary client/types, narrow polling update hook, workflow progress/navigation mapping and directly relevant styles/tests. A backend response adjustment is allowed only for a demonstrated missing status field, documented in artifacts.

Excluded: result import/persistence, seven-section editing, generic job route redesign, new provider integrations, document navigation redesign, upload/ingestion behavior and any live settings/deployment changes.

## 9. Verification and exit criteria

Use controlled response sequences rather than real service calls:

1. Submission pending -> job visible -> running 0/20/75 -> completed 100/import pending. Assert each step/percentage actually renders.
2. Import readiness unavailable: no review navigation or placeholder content.
3. Running at 100, inconsistent completion, failed/cancelled/unknown states and delayed binding.
4. Read failures, wait timeout, Check status and reconnect without another POST.
5. Reload, lost storage, project reopening and explicit Go to workflow resume the same attempt.
6. Switch tenant/document while a response is delayed; assert cancellation and no stale UI update.
7. Accessible progress/status/errors, keyboard actions, desktop/mobile layouts and no secret in requests/storage/logs.
8. Regression tests for existing poller consumers, legacy summaries and project/document/duplicate dialogs.

Run focused frontend/browser tests, lint, TypeScript/build and Step 1-2 contract regressions as needed. Record commands, screenshots, results and unavailable live qualification under `step-03-artifacts/`.

**Exit:** actual intermediate state changes are visible; polling is bounded/cancellable; resume is read-only; import readiness controls review navigation. Canned response tests do not prove deployed worker or service progress behavior.
