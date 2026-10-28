# External summary API integration implementation plan

Prepared: 2026-10-28 (Asia/Calcutta).

Status: planning only. No API calls, application changes, migrations, configuration changes or deployment have been performed for this plan.

Execution documents: [six-step implementation index](external-summary-api-integration-steps/README.md). The sections below provide design context; implementation is divided only into the six steps in that index.

## 1. Objective and fixed scope

Connect the existing **Generate summary** action to the supplied background summary service. Track its real job in the shared PostgreSQL database, display its status, step and progress, and display the validated completed result in the existing summary review screen. Preserve saved progress, duplicate-document behavior, document viewing and project navigation.

User-confirmed integration facts:

- The summary service and this backend use the **same PostgreSQL database and `jobs` table**.
- The service writes its finished response to **`jobs.result_payload` only**. It does not populate `document_summaries`.
- Submission is `POST https://caring-doormat-pounce.ngrok-free.dev/api/v2.1/project-summary` with JSON `{ "document_id": "<authorized-document-uuid>" }`.
- Required server-side headers are `Content-Type: application/json`, `ngrok-skip-browser-warning: true` and `X-API-Key: <secret>`.
- The external job-type identifier is exactly **`DOCUMENT_SUMMERIZATION`**, including that spelling.
- The initial response contains `job_id`, `document_id`, `job_type`, `status`, `progress`, `current_step`, attempt/error/timestamp metadata and a relative `result_url`.

This work does **not** implement the earlier multi-agent roadmap, change LLM models, generate WBS content, change ingestion/embeddings/question vectors, redesign authentication, or deploy anything. External summary text remains an AI draft requiring human review.

## 2. Current checkout findings

These are code-inspection findings at checkout `d19a5fd`; live database/service behavior has not been qualified.

| Area | Current implementation | Required integration change |
| --- | --- | --- |
| Summary submission | `backend/app/api/routes/summaries.py` creates an application-owned `DOCUMENT_SUMMARY` job and dispatches the local summary processor. | Select the external integration explicitly; do not create a second generation job or dispatch the placeholder processor for an external request. |
| Existing worker | `backend/app/services/workflows.py::process_document_summary` writes placeholder summary text, example requirements and a `{summary_id}` result. | Keep this handler out of the external execution path. Never fall back to it after an external-service failure. |
| Job storage | `Job` has tenant/project/workflow scope, request/result JSON, progress, step and timestamps. Its job type/status columns are strings. | Read the service-owned row using exact identity and trusted scope; preserve its original type/status/result. Confirm actual deployed schema before assuming compatibility. |
| Workflow recovery | `document_workflow_resume.py::_linked_job` currently expects `DOCUMENT_SUMMARY`; active statuses do not include external `RUNNING`. | Add summary-specific compatibility for external jobs without broadening unrelated job handling. |
| Summary recovery | A `DocumentSummary` is used to enter `SUMMARY_REVIEW`. | A completed external job must be validated and imported before review becomes available. Completion alone cannot stand in for a saved reviewable summary. |
| Progress UI | `WorkflowCheckpointScreen.tsx` polls workflow state, but only delivers terminal updates to the screen. | Update displayed summary status, step and percentage after each poll. |
| Review presentation | `workflowPresentation.ts::presentSummary` creates only three sections and hard-codes `confidenceScore: 85`. | Preserve the external seven-section response and show null confidence truthfully. |
| Review editing | Numeric IDs, a global 2,000-character limit, and `summaryUpdateFromSections` map edits by positions 1/2/3. | Use stable section keys/IDs, validated per-section limits and lossless structured saves. |
| Approval/generation | Existing review saves, approves and starts WBS generation. | Preserve human approval semantics; do not invent structured requirements to make the downstream button succeed. |
| Test setup | Shared `backend/tests/conftest.py` deletes `.test-data` on teardown. | Use an isolated test fixture/plugin and `--noconftest`; never run that destructive setup. |

## 3. Architecture and ownership

```text
Browser: Generate summary
    -> Existing tenant-authorized backend summary boundary
    -> Commit durable submission intent with pinned document/run identity
    -> Existing worker submits to the fixed external HTTPS endpoint
    <- External service returns its job_id
    -> Validate and bind that exact row in the shared jobs table

External service worker
    -> Updates its jobs.status/current_step/progress/result_payload

Existing worker/reconciliation path
    -> Reads that exact scoped job
    -> Validates completed payload and source lineage
    -> Atomically imports the review draft into document_summaries
       and updates the matching workflow checkpoint

Browser: bounded status polling
    -> Our backend returns sanitized status/progress and import state
    -> Review Project Summary opens only after a valid draft is persisted
```

### Ownership rules

1. The external service owns its `jobs` execution row, including status, progress, step, attempts, errors, request payload and generated result payload. Our integration reads these fields; it must not replace the result with `{summary_id}` or normalize status by updating the stored row.
2. The application owns authorization, submission coordination, workflow association, validated result import, review edits and approval. A separate application request record may coordinate delivery; it is **not another summary generation job**.
3. The browser talks only to this backend. It receives neither the shared API key nor direct database access.
4. PostgreSQL is the job/result source of truth for this integration. The supplied `result_url` is not needed for polling or result retrieval and is not followed automatically.
5. Network calls happen outside database transactions. Short transactions apply transaction-local tenant scope before every protected read/write, including fresh worker/reconciler sessions.
6. Polling reads must not become hidden triggers for external submissions. Closing a browser must not stop durable result import.

## 4. Shared-contract qualification before enablement

Create a sanitized contract checklist, using service documentation or separately authorized synthetic verification. Do not submit the private RFP to qualify this integration.

Confirm:

- The returned `job_id` is exactly `jobs.id` in the shared database, not an unrelated upstream identifier.
- External rows have correct `tenant_id`, `project_id`, `created_by` and any required schema fields. A UUID supplied by the browser cannot establish tenant ownership.
- `request_payload` is a JSON object containing the exact canonical `document_id`; additional fields are permitted only by an explicit contract.
- Actual status values and case, including queued, active, completed, failed and cancellation states. The sample proves `RUNNING` only; do not invent other wire values.
- The external worker writes completion, progress and result atomically, or document the bounded visibility delay the importer must tolerate.
- The service's database role/grants/RLS and runtime migration compatibility are correct. Do not grant this application owner privileges to make integration work.
- Source processing selection: the returned `processing_run_id` must belong to the pinned completed document run. Submission accepts only `document_id`, so the application must detect source changes before submission and before import rather than claiming the remote API pins a run for us.
- Whether the upstream supports an idempotency header or client request correlation and lookup. This is **not established** by the sample.
- Whether upstream retry/cancellation APIs exist. Neither is established by the supplied contract.
- Whether the service itself mutates `Job.workflow_id`; do not overwrite another workflow's association during reuse.
- Maximum response size, section/content/quote counts, step/error lengths, generation duration and real step vocabulary.
- Whether manually edited summaries can coexist with a later external attempt; import must never silently overwrite approved or newer user work.

**Exit:** document confirmed facts and gaps. Missing identity, ownership or source-lineage guarantees block enablement, not independent implementation using synthetic fixtures.

## 5. Typed contracts and configuration

### External contracts

Introduce bounded Pydantic models for:

- Submission acknowledgement: UUID job/document identities, literal job type, supported status, integer progress 0–100, bounded current step, attempts, safe timestamps and errors.
- Result envelope: `status`, `message`, `data`; a success HTTP response is insufficient if the envelope says failure.
- Result data: project/document/run UUIDs, document information, summary sections, question-set ID and model label.
- Section: string `id`, integer `order`, stable `key`, title, badge, subtitle, content, `max_length`, source references, question ID, answer status, truncation indicator and citations.
- Citation: chunk UUID, quote, section-local positive citation number and positive physical page numbers.

Validate unique IDs, keys and order positions, bounded arrays/strings/total bytes, required categories, supported answer statuses and consistent page/citation types. Preserve paragraph breaks and full content; reject unsupported overflow rather than truncate it. Unknown extensions must follow an explicit compatibility policy and cannot supply executable markup or authority.

Use the supplied result shape as a **schema example**, but create synthetic content and identifiers for committed fixtures. Do not commit the private tender passages or the supplied key.

### Internal execution contract

Keep request identity distinct from external job identity. The existing `POST /tenants/{tenant_id}/documents/{document_id}/summary` remains the product submission action, with an explicitly typed external response branch:

```json
{
  "execution_backend": "external_summary",
  "request_id": "<application-submission-request-id>",
  "job_id": "<external-job-id-or-null-until-acknowledged>",
  "document_id": "<authorized-document-id>",
  "job_type": "DOCUMENT_SUMMERIZATION",
  "submission_state": "SUBMIT_PENDING",
  "provider_status": null,
  "status": "QUEUED",
  "progress": 0,
  "current_step": "Waiting to submit summary request",
  "result_state": "NOT_READY",
  "summary_id": null
}
```

Once acknowledged, return the exact `job_id` and raw upstream status/step alongside the application's normalized status. Never put the request UUID into `job_id`. Preserve the legacy `JobResponse` branch for explicitly selected legacy behavior; update `summariesApi.ts` to handle this union rather than casting it to a generic job.

Add a tenant/document-scoped read endpoint such as `GET .../summary/requests/{request_id}` for this bounded integration status. Existing workflow responses should include enough request/job identity and import state to resume after reload. Job identity can be shown as supporting metadata or copied for troubleshooting.

### Configuration declarations

Proposed settings, default disabled or unset:

| Setting | Purpose |
| --- | --- |
| `EXTERNAL_SUMMARY_ENABLED=false` | Explicit selection of this integration; not the unfinished agentic feature gate. |
| `EXTERNAL_SUMMARY_BASE_URL=<approved-https-origin>` | Operator-controlled origin; exact supplied ngrok host for initial qualification. |
| `EXTERNAL_SUMMARY_API_KEY=<secret>` | Backend/worker secret only; reject missing value when enabled. |
| `EXTERNAL_SUMMARY_CONNECT_TIMEOUT_SECONDS` | Bounded connection establishment. |
| `EXTERNAL_SUMMARY_SUBMIT_TIMEOUT_SECONDS` | Bounded acknowledgement wait, not full generation duration. |
| `EXTERNAL_SUMMARY_MAX_RESPONSE_BYTES` | Bound acknowledgement/error bodies. |
| `EXTERNAL_SUMMARY_JOB_VISIBILITY_GRACE_SECONDS` | Bound delay before an acknowledged DB row is visible. |
| `EXTERNAL_SUMMARY_MAX_WAIT_SECONDS` | Operational stale/wait policy for generation, distinct from browser polling duration. |
| `EXTERNAL_SUMMARY_MAX_RESULT_BYTES` | Bound result validation/import and response sizes. |

Use existing HTTP dependencies, TLS verification, an exact HTTPS origin/path, redirects disabled, bounded responses and no environment-proxy bypass. Reject embedded credentials and arbitrary returned URLs. If a compatible shared secure transport exists in the implementation checkout, reuse it. Do not introduce a generic provider system for this fixed service.

Examples contain placeholders only. Never use `VITE_*` for the key, browser storage, query parameters, task messages or logs. The pasted key should be rotated through a separate authorized secret-provisioning action; this plan contains no key value.

## 6. Minimal durable coordination and review storage

### Submission record

Plan one narrowly scoped additive model/table, for example `summary_api_requests`, after checking whether equivalent storage already exists in the implementation checkout. Required logical fields:

- Tenant/project/document identity and originating workflow; requester identity.
- Client idempotency identity, request fingerprint and request/contract version.
- Pinned processing-run ID and source/configuration fingerprints.
- Submission/import state, external job ID once known, validated relative result-path metadata if retained.
- Lease/fencing identity, attempt timestamps, next reconciliation time and bounded sanitized errors.
- Imported summary identity/revision and imported result hash.
- Expected summary revision at start, to reject stale overwrites.

Enforce scoped foreign keys/RLS, uniqueness of the active document/run submission, exact acknowledged-job binding and one-time import identity. Repeated clicks and template forks sharing the same compatible document summary should attach to the same in-flight request. Keep an explicit association for each authorized workflow; do not steal `Job.workflow_id` from another workflow.

Where existing composite keys require new constraints, add only those needed for this table/association. Check the actual Alembic head at implementation time; do not rewrite historical migrations or use `stamp head`.

### Structured review storage

Preserve the unique-per-document `DocumentSummary` and its legacy fields. Add the minimum structured storage and provenance needed for lossless review, for example:

- Versioned `structured_summary` JSON containing the seven sections and document metadata.
- Scoped source-request reference, with external job/run/model/question-set provenance available through that request.
- Existing `revision`, `is_approved` and `approved_at` remain authoritative for review.

The original generated payload remains in the externally owned job. User edits are stored in the application review representation, never written back into that raw job result. Persist original citation metadata separately from edited text or mark its association as requiring review after edits.

If storage already supports these requirements, reuse it. Do not build a second summary-revision/agent platform. Existing summaries remain intact and use a legacy read/presentation branch.

## 7. Submission, exact job binding and recovery

1. Authorize the existing summary operation against the active tenant, project, document and requested workflow. Validate active lifecycle and the completed canonical ingestion run.
2. Under short scoped transaction/locking, reuse a compatible current request or persist a new submission intent with pinned inputs. Commit before broker/network I/O.
3. Deliver only request/tenant identifiers to the existing worker. Use the durable record as the narrow delivery intent; add a bounded reconciler hook to existing scheduling, not another worker service or Beat scheduler.
4. The worker claims the request, revalidates permissions/lifecycle/source identity and configuration, ends its DB transaction, and sends the exact document-ID POST with server-held headers.
5. Validate acknowledgement identity, exact job type and bounds before storing the returned external ID.
6. Query the shared row using **all** applicable predicates:

```text
jobs.id = acknowledged_job_id
AND jobs.job_type = 'DOCUMENT_SUMMERIZATION'
AND jobs.tenant_id = trusted_tenant_id
AND jobs.project_id = trusted_project_id
AND jobs.request_payload.document_id = pinned_document_id
```

7. Bind `workflow.summary_job_id` only after the row passes ownership checks. Protect every attached workflow's source/checkpoint expectations. A missing row can be visibility-pending for a bounded grace period; it is not permission to insert a fake row or select the latest job.
8. Do not call `dispatch_summary`, enqueue the old `summary` placeholder dispatch, or run `process_document_summary` for the external branch. Existing ingestion/generation dispatch semantics stay unchanged.

### Ambiguous submissions

A timeout, worker crash after submission, or a lost acknowledgement may mean the external job already exists. Record `SUBMISSION_UNKNOWN`; retain the original intent and do not automatically POST again without a qualified upstream idempotency/correlation contract.

If that contract is available, retry with the **same** upstream idempotency identity. Otherwise require a validated explicit job-ID reconciliation or operator resolution. Searching for an arbitrary newest document job is not reliable correlation. Never claim exactly-once provider execution or billing.

### Cancel/retry controls

The current generic job routes can mutate status or dispatch local handlers. External summary jobs must have an explicit branch that rejects unsupported cancel/retry operations. Do not mark the upstream job cancelled locally while its worker continues and may publish a result.

Navigation away stops browser polling only. An explicit application abandonment can block import without claiming remote cancellation. Regeneration/retry is separately authorized and must not overwrite newer edits or restart a possibly running ambiguous attempt.

## 8. Status, progress and workflow state

Keep external wire status separate from normalized application status. Proposed mapping requires the qualified status inventory:

| External observation | Application presentation |
| --- | --- |
| Confirmed queued state | Queued; show reported step/progress. |
| `RUNNING` | In progress; show actual `current_step` and `progress`. |
| Confirmed completed status **and progress 100** | Generation completed; validate/import result next. |
| Completed status with progress below 100 | Inconsistent completion; bounded reconciliation, then explicit error if unresolved. |
| Running status with progress 100 | Still running/finalizing; not complete. |
| Failed | Failure with bounded sanitized error; do not open stale content as a new success. |
| Confirmed cancelled | Cancelled; no new import. |
| Unsupported/malformed status | Unsupported state; no guessed success. |
| Missing/wrong-scope/wrong-type row | Pending visibility only within grace, otherwise unavailable/scope failure. |

Completion comparisons use a documented canonical mapping for known values/case, not substring matching. Never use `progress >= 100` as the sole completion condition or simulate percentage movement.

Distinguish remote execution from local consumption: `NOT_READY`, `IMPORT_PENDING`, `IMPORTED`, `INVALID`, `STALE` and `IMPORT_FAILED`. Remote success remains unchanged in `jobs` even if local import fails.

Update summary-specific workflow recovery to understand `DOCUMENT_SUMMERIZATION` and normalized `RUNNING`, preserve existing `DOCUMENT_SUMMARY` history, and overlay pending submission/import states. Do not treat any arbitrary job type as a summary. A completed job with no imported summary must show finalizing/unavailable, not regress to “Generate summary” or trigger another POST.

The UI displays job status, current step and real progress on every polling response. Initially poll about every two seconds, back off to five seconds, cancel in-flight fetches on tenant/document navigation and bound the browser wait. A wait timeout means **stop waiting**, not that the external job failed. Provide **Check status** to resume reads of the same request/job.

The existing generic polling helper only exposes its terminal result. Add an optional update callback or a summary-specific wrapper, with regressions proving unchanged behavior for existing consumers. Do not rewrite every poller or rely on continuous browser activity for reconciliation.

## 9. Result validation and atomic import

When the exact scoped row reaches confirmed completion with progress 100:

1. Snapshot the bounded `result_payload`; require a successful envelope and a complete structurally valid result.
2. Match `data.document_id` and `data.project_id` against trusted scope. Match `data.processing_run_id` against the pinned completed run and revalidate current lifecycle/source compatibility.
3. Verify referenced chunks belong to that tenant/project/document/run. Check available canonical page/quote metadata without downloading the PDF or sending it elsewhere. Reject foreign chunks and forged references. If the worker's quote normalization differs from canonical text, record a compatibility failure to resolve; do not quietly label it verified.
4. Preserve section-level citation-number namespaces: `[1]` in Project Overview is distinct from `[1]` in Project Scope. Physical source pages are not inferred from filenames, section order or printed labels.
5. Retain `answer_status`, `evidence_context_truncated`, model/question-set/run identity, null confidence and all evidence links. A valid citation is not proof of semantic entailment or factual correctness.
6. In a short fenced transaction, revalidate source/request/current summary revision and create/update the review draft. Apply optimistic checks so a delayed import cannot overwrite a newer attempt, approved summary or saved user edits.
7. Store structured content and deterministic compatibility fields, set `is_approved=false`, clear approval time, update the matching workflow's summary identity/revision/checkpoint and mark the request imported with the result hash **atomically**.
8. Duplicate reconciliation of the same request/result returns the existing imported revision. It must not increment the summary revision again or reset later human edits/approval.

If completion and payload arrive separately, wait only within a configured import-grace policy. Persist explicit errors for missing/malformed/stale payloads. Reconciliation may retry a local import safely; that must never resubmit remote generation.

### Compatibility projection

- Build `summary_text` deterministically from the ordered section titles/content so legacy readers retain the full draft.
- Populate legacy `key_points`/`requirements` only from a documented trustworthy structured mapping. The supplied response does **not** contain a structured requirements array. Do not invent requirement identities or parse numbered prose as verified requirements.
- Never overwrite a prior structured requirements register with guessed items. Require an explicit revision policy when replacing an older summary.
- Preserve WBS generation behavior for legacy compatible summaries. For a new external summary lacking the downstream required contract, show a truthful disabled/unavailable Generate WBS action with a reason. Deriving WBS-ready requirements is a separate agreed scope, not hidden work in this integration.

## 10. Map the result into the existing review UI

Use the existing review layout and design tokens; this is a data/status integration, not another redesign.

| External field | Existing screen element / intended behavior |
| --- | --- |
| `summary_sections[].id` | Stable opaque section identity, such as `sec_1`; never a durable array index. |
| `order` | Sort order and display numbering only. |
| `key` | Stable semantic category and save mapping. |
| `title` | Left navigation label and active editor heading. |
| `badge`, `subtitle` | Plain-text draft badge/editor subtitle; restrict authority-like badges so external text cannot assert human approval. |
| `content` | Editable text preserving paragraph breaks and citation markers. Never render as HTML. |
| `max_length` | Validated per-section edit limit; show explicit over-limit state, never silently shorten an imported value. |
| `source_references.label`, `pages` | Source-reference caption and physical-page chips. |
| `evidence_citations` | Accessible expandable citation rows: citation number, quote and page numbers. Keep chunk IDs as provenance, not unexplained primary UI. |
| `answer_status` | Answered / Insufficient evidence / other confirmed states, without fabricated missing content. |
| `evidence_context_truncated` | Clear review notice that retrieved evidence context was limited. |
| `document_information.filename`, `file_size`, `file_type` | File metadata, checked against the authorized document; application file identity/size remain authoritative. |
| `extraction_confidence=null` | “Not recorded”; no percentage bar and no hard-coded 85%. Show bounded `confidence_status` explanation. |
| `question_set_id`, `llm_model`, `processing_run_id` | Supporting provenance details; model label does not imply qualification or accuracy. |

The expected seven categories are Project Overview, Project Scope, Key Deliverables, Assumptions, Constraints, Exclusions, and Milestones & Timeline. Preserve the service's actual stable IDs/order and explicitly reject or display schema changes according to the approved contract. Do not force these into the existing Overview/Key Points/Requirements positions.

### Edit/save/approval behavior

- Add a structured save branch to the existing summary update boundary. Whitelist editable fields; users may edit section content but not forge document/run/job identity, quotes, pages or generation provenance.
- Submit section IDs/keys and an expected summary revision. Reject stale writes and unknown/duplicate sections. Keep all untouched sections and original evidence metadata.
- Preserve original generated content/provenance and mark edited claims as requiring review; unchanged citation markers cannot certify edited prose.
- Successful save updates the UI's authoritative summary revision and structured representation. Reload/resume reproduces saved edits.
- Save resets approval; successful generation/import never grants approval. Approval remains an explicit authorized user action on the current revision.
- Keep legacy summaries editable through their existing contract. Do not change unrelated screens or WBS algorithms.

## 11. Lifecycle, security and operational boundaries

- Apply tenant/project/document/run predicates to submission lookup, exact job reads, import, status reads and review writes. Thread/job/request IDs alone grant no access.
- New transactions on fresh/reused pooled sessions must reapply tenant scope. Preserve RLS and the strict active-transaction helper guard.
- Recheck deletion/archive/source changes before submission and import. Once document deletion starts, block new submissions/imports and make local coordination terminal/ineligible.
- The remote service must tolerate deleted/stale sources; if it cannot cancel, its late result remains non-importable. Do not rewrite ingestion/deletion architecture or let old jobs attach to a re-uploaded document with a new UUID.
- Do not log secrets, upstream headers, raw response bodies, entire summary payloads or private citations. Use sanitized request/job IDs, status, duration, bounded error codes and correlation metadata.
- Return safe errors for auth failure, tunnel unavailable, timeout, invalid acknowledgement, scope mismatch, unknown job type/status, invalid result, changed source and stale edits. Never expose upstream stack traces or API-key-bearing request diagnostics.
- No direct browser call means the ngrok service does not need browser CORS exceptions or public database access. Keep TLS verification enabled.
- Placeholder processing remains excluded whenever external mode is selected. Missing configuration must fail truthfully; no fallback to mocked output.

## 12. Expected implementation file scope

Exact new filenames can follow repository conventions, but every change must fit these responsibilities:

| Files / area | Allowed change |
| --- | --- |
| `backend/app/core/config.py` and example documentation | Default-disabled integration settings and placeholders only. |
| New summary integration schema/service modules | Fixed-service HTTP submission, exact-row reading, validation, import and durable request coordination. |
| `backend/app/models/` and one narrow additive migration if required | Submission request, structured review content and scoped provenance; no general agent persistence rewrite. |
| `backend/app/api/routes/summaries.py` | Authorized external submission/status and structured save/read branches. |
| `backend/app/api/routes/jobs.py` | Only external-summary cancel/retry safety and any explicitly needed status sanitization; no unrelated job refactor. |
| `document_workflow_resume.py`, workflow schemas | Summary-type/status compatibility and pending/import recovery. |
| Existing worker/scheduler/dispatch integration | Narrow request delivery and reconciliation hooks; no second scheduler/service. |
| Existing document lifecycle boundary | Only invalidate local summary requests/import eligibility where needed. |
| `WBS_UI/src/services/summariesApi.ts`, `workflowTypes.ts`, `workflowPresentation.ts`, `polling.ts` | Typed external execution/structured content, mapping and per-poll updates. |
| `WorkflowCheckpointScreen.tsx`, `ReviewProjectSummaryScreen.tsx` and related styles | Actual summary progress, seven sections, evidence, truthful confidence, safe editing and resume. |
| Summary/workflow tests and integration artifacts | Synthetic fixtures, isolated automated verification and actual evidence. |

Excluded: upload/deduplication rules, project/document-dialog navigation, ingestion/embedding configuration, auth semantics, unrelated agent code, question-bank data, actual `.env`/credentials, Docker/Nginx/CI, live VM changes, commit/push/deploy.

## 13. Verification plan and acceptance scenarios

Capture initial git status/diff; preserve unrelated and concurrent edits. Tests use synthetic fixtures, isolated storage and no application/Neon data. PostgreSQL verification uses only a verified disposable database with separate migration/runtime roles. SQLite/fakes do not prove RLS or live service compatibility.

### A. Contracts and job identity

- Valid acknowledgement with exact external type; malformed UUID/type/progress/status rejected.
- Wrong tenant/project/document/job ID/request payload denied, including a guessed known job UUID.
- Never select the latest unrelated job or use document ID alone as correlation.
- Delayed row visibility within/outside grace; missing scope fields fail closed.
- Completion requires both confirmed completed status and progress 100. Cover running-at-100, completed-at-80, failed-at-100, unknown status, missing payload and a non-success envelope.

### B. Submission and durability

- Repeated clicks/concurrent requests produce one active submission intent; no local placeholder job/task.
- Crash before send, after send before acknowledgement persistence, after job binding and before import.
- Unknown submission stays unknown without blind replay; only qualified idempotency permits automatic retry.
- Worker duplicate delivery, competing leases, stale fences and broker publication ambiguity.
- Browser refresh/reopen resumes the same request and job without a new external POST.
- Rotation of the server API key affects future attempts without exposing it; no key in frontend bundles, storage, URLs, task payloads or diagnostics.

### C. Import and review persistence

- All seven sections and evidence survive import, read, edit, save and reload.
- Imported source/run/chunk ownership and available canonical quote/page metadata checked; wrong or stale lineage denied.
- Duplicate import produces one revision. Late import cannot overwrite newer edits/approval or a newer attempt.
- Atomic failure injection around summary write, workflow update and imported marker; rollback leaves a recoverable import state.
- Null confidence remains null; insufficient evidence and truncation flags remain visible.
- Unicode, multiline text, section-local citation numbering, long content and invalid references are handled without truncation or HTML execution.
- Structured content cannot manufacture WBS requirements, human approval or a confidence percentage.

### D. Browser behavior

- Generate summary -> actual queued/running step text and reported progress -> finalizing/import -> review.
- Multiple progress responses update the screen, not just the terminal response.
- Failure/unavailable/stale/timeout states are accessible and actionable; Check status does not resubmit.
- Tenant/project/document navigation aborts browser requests and prevents late responses painting another document's screen.
- Section selection/edit limits/citation details work on desktop and mobile; saved keys never appear in browser traffic.
- Project clicks still open the project workspace; duplicate uploads still show the duplicate dialog; View document / Go to workflow remain intact.

### E. Compatibility and real qualification

- Legacy summary read/edit/approval and workflow resume remain valid.
- Existing ingestion/upload/duplicate/delete/re-upload and WBS job polling regressions pass.
- External cancel/retry cannot mutate the job or invoke the legacy processor without a supported contract.
- Run isolated backend tests, focused browser/full-stack tests, lint, TypeScript/build, migration checks and `git diff --check`.
- A separately authorized live smoke test uses one synthetic completed document, bounded submission/cost/time limits and read-only observation of that exact shared job. Confirm service origin, role/RLS, payload mapping and deployed worker routing; do not test by uploading a private RFP.
- Do not enable features or deploy during implementation verification. If live access/disposable PostgreSQL is unavailable, record those checks as pending.

## 14. Delivery order and completion criteria

Implement only these six steps, in order:

1. [Backend-only API submission and secret handling](external-summary-api-integration-steps/step-01-backend-submission-secret-handling.md).
2. [Exact `DOCUMENT_SUMMERIZATION` job tracking](external-summary-api-integration-steps/step-02-exact-job-tracking.md).
3. [Live status, step and progress display](external-summary-api-integration-steps/step-03-live-status-step-progress.md).
4. [Completed-result validation and persistence](external-summary-api-integration-steps/step-04-completed-result-validation-persistence.md).
5. [Seven-section UI mapping, citations and draft editing](external-summary-api-integration-steps/step-05-seven-section-review-editing.md).
6. [Recovery, duplicate prevention, security and end-to-end tests](external-summary-api-integration-steps/step-06-recovery-security-end-to-end.md).

Contract checks, minimal persistence/migrations, configuration and prerequisite verification belong inside the step that requires them. The design sections above do not add implementation steps.

Record implementation evidence in `docs/external-summary-api-integration-steps/step-NN-artifacts/` for the corresponding step: file changes, migration head, contract decisions, commands/counts, skipped verification and sanitized synthetic job lifecycle. Do not put keys or private payloads in artifacts.

Accept this integration only when:

1. Authorized submission creates/reuses a durable request and follows the **exact external job** without running placeholder generation.
2. Job status, `current_step` and real `progress` update correctly and recover after browser/worker restart.
3. Confirmed completion with progress 100 imports a valid matching `result_payload` once, with full structured data and source provenance.
4. The existing review UI displays and safely saves all seven sections, citations, limits, gaps and unknown confidence.
5. Tenant/source isolation, stale-write protection, late-result rejection and secret exclusion are verified at the appropriate layer.
6. Approval remains human-controlled, downstream WBS readiness is truthful, and existing upload/project/document navigation remains unchanged.

Current outstanding qualification: upstream idempotency/correlation, actual full job/status/write contract, deployed role/RLS compatibility, exact citation normalization, service time/size limits and authorized live synthetic verification. No success in these areas is claimed by this plan.
