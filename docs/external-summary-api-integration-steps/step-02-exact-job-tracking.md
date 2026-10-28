# Step 2: Exact `DOCUMENT_SUMMERIZATION` job tracking

Status: planned. Depends on Step 1's durable request, pinned scope and acknowledgement contracts.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), [Step 1](step-01-backend-submission-secret-handling.md), its code/artifacts and current job/workflow/RLS conventions first.

## 1. Objective

Track the exact externally created shared-database job and make a tenant-scoped status contract available to workflow recovery and Step 3. The service-owned row stays unchanged. This step does not import the result or display new UI.

## 2. Confirm the shared-row contract

The user confirmed a shared PostgreSQL database, but the following still require qualification:

- Acknowledgement `job_id` is the actual `jobs.id`.
- The service populates correct tenant/project/requester scope and compatible schema fields.
- `request_payload` contains a canonical matching document ID.
- The actual wire status vocabulary, case, `current_step` length and completion-write ordering.
- The external service's role/RLS behavior and any ownership of `Job.workflow_id`.

Record unavailable facts rather than filling them from the sample. Do not query the configured application database during implementation tests or grant owner privileges to bypass missing runtime access.

## 3. Exact repository lookup

Implement a dedicated scoped summary-job reader using the trusted Step 1 record:

```text
jobs.id = request.external_job_id
AND jobs.job_type = 'DOCUMENT_SUMMERIZATION'
AND jobs.tenant_id = request.tenant_id
AND jobs.project_id = request.project_id
AND jobs.request_payload.document_id = request.document_id
```

Before access, resolve the request by tenant/project/document/workflow authorization, not by a free-standing caller job UUID. Begin/join the correct short transaction, apply trusted tenant context and preserve RLS.

Rules:

1. Require a JSON object request payload with a valid canonical matching document UUID.
2. Never select the newest job by document, filename, project or job type. The acknowledged job ID is mandatory.
3. Reject rows with missing/wrong scope even when the job ID is known.
4. Never create a replacement row because an acknowledged row is temporarily invisible.
5. Read status metadata without loading large `result_payload` on every poll. Step 4 owns bounded result loading.
6. On fresh/pooled sessions, reapply tenant scope for each transaction. Do not remove the active-transaction guard or use session-global scope.

The exact external spelling is fixed. Compatibility with legacy `DOCUMENT_SUMMARY` belongs in an explicit summary-specific branch; it is not permission to treat arbitrary jobs as summaries.

## 4. Bind requests and workflows safely

After row ownership verification:

- Mark the request's acknowledgement as database-verified, recording identity/provenance without changing the external job's execution fields.
- Bind the authorized workflow's `summary_job_id` with source/checkpoint expectations and a guarded update.
- Keep application request identity in workflow recovery so submission-pending states survive before job visibility.
- Reuse compatible document/run requests across authorized template forks through explicit associations. A single `Job.workflow_id` is not a reason to overwrite another workflow's ownership.
- Attach only matching tenant/project/document/run requests. Historical outputs keep their original lineage.

Use the Step 1 persistence boundary. If association storage is missing, document the narrow gap and add only the necessary scoped extension/additive migration. Do not refactor general workflow or ingestion persistence.

## 5. Status normalization without database mutation

Define an explicit summary-specific normalization function, preserving both raw and application status:

| Database observation | Internal status / result readiness |
| --- | --- |
| Qualified queued value | `QUEUED`, result not ready. |
| `RUNNING` | `IN_PROGRESS`, result not ready. |
| Qualified completed value and progress exactly 100 | Execution complete, `IMPORT_PENDING`; not review-ready yet. |
| Completed value with progress below 100 | Inconsistent/finalization pending for a bounded grace, then explicit unavailable/error. |
| Running with progress 100 | Still in progress/finalizing. |
| Qualified failed value | `FAILED`, sanitized failure; no result import. |
| Qualified cancelled value | `CANCELLED`; no result import. |
| Unknown status, malformed progress or request data | Explicit unsupported/invalid state; never guessed success. |

Keep actual wire values/case in a documented supported set. Use literal matching through that mapping, not substring checks or arbitrary uppercasing followed by permissive acceptance.

Do not rewrite the stored `RUNNING` to `IN_PROGRESS`, replace `current_step`, reset attempts or overwrite `result_payload`. The application status is a read projection.

Validate progress as an integer 0-100 and step as bounded plain text. Preserve safe real step labels, including `SUMMARY:QUEUED`; map friendly labels only where the vocabulary is confirmed. Unknown-but-safe step labels do not invent a phase.

## 6. Bounded status endpoint

Implement the Step 1 proposed read boundary, such as:

```text
GET /api/v1/tenants/{tenant_id}/documents/{document_id}/summary/requests/{request_id}
```

Response should include:

- Request/job/document identities and exact job type.
- Submission state and database-binding state.
- Normalized status plus raw provider status.
- Real `current_step`, progress, attempt count and update timestamp.
- Result/import state, nullable imported summary ID/revision.
- Sanitized error code/message and safe polling/retry capability metadata.

Require existing job/summary read authorization according to repository conventions and verify document ownership. Return metadata only, not upstream headers, request secrets, arbitrary JSON payloads or raw errors. Do not expose `result_payload` through this progress response.

GET performs no new external submission and no hidden HTTP fetch to `result_url`. The worker can reconcile/import independently of browser polling.

## 7. Workflow compatibility

Update only summary-related workflow recovery:

1. A persisted pending request yields truthful summary submission state before a job is verified.
2. A verified active external job yields `SUMMARIZING` with normalized status and real job metadata.
3. Remote completion with no imported summary remains finalizing/import-pending. Do not return to the Generate summary action or open an old draft as this attempt's success.
4. Failed/unknown/stale/import-failed states remain explicit.
5. Step 4 will move to `SUMMARY_REVIEW` after atomic import. Until then, leave review unavailable.
6. Existing legacy summary jobs and historical summaries remain readable and resumable.

The existing generic cancel/retry endpoints must explicitly refuse unsupported external-summary operations. They cannot mark the external row cancelled or send it to the legacy processor. This protection is required before returning actionable external job IDs.

## 8. Visibility and failure handling

- An acknowledged row may be temporarily invisible; use a configured grace period with bounded retries of reads only.
- Before grace expiry, show waiting-for-job visibility, not fake running progress.
- After expiry, record unavailable/reconciliation-required. Preserve the exact ID for later resolution; do not generate a new job.
- A row that exists but has the wrong tenant/type/document is a scope/contract failure, not an eventual-consistency success candidate.
- Lifecycle, source activation and authorization changes prevent further usable workflow progress even if the external job continues.

## 9. Verification and handoff

Test production repository/status boundaries with synthetic jobs:

- Correct row; wrong job/type/document/tenant/project and malformed request payload.
- Two jobs for one document where the newer row is not the acknowledged row.
- Known foreign job IDs and pooled tenant-scope reuse.
- Delayed/missing rows, visibility grace exhaustion and failed DB reads.
- Supported/unknown status values and all progress/completion combinations above.
- Cross-workflow compatible reuse without modifying `Job.workflow_id` ownership.
- GET performs no submission, payload fetch or legacy dispatch.
- External cancel/retry protection and legacy job compatibility.

Use disposable PostgreSQL for JSON predicates, RLS/grants and concurrency. Run focused Step 2 tests, Step 1 regressions, lint and diff checks. Record results and pending qualification under `step-02-artifacts/`.

**Exit:** the exact acknowledged row is tracked with trusted scope; metadata-only status/recovery is available; raw external data is preserved; completed results remain import-pending. Step 3 consumes the status contract; Step 4 consumes the verified request/job binding.
