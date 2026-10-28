# Step 1: Backend-only API submission and secret handling

Status: planned. Depends on current repository inspection; no live API access is required for local implementation.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), applicable repository instructions and current summary submission/dispatch/configuration code first.

## 1. Objective

Make the authorized Generate summary operation submit a document ID through the backend/worker boundary, using an operator-configured HTTPS endpoint and server-held secret. Persist enough intent and acknowledgement state to survive interruption without creating a second generation job or blindly replaying an ambiguous submission.

Step 1 ends with a validated external acknowledgement ready for exact shared-row binding in Step 2. It does not claim the acknowledged job has passed database ownership checks.

## 2. Inspect before changing code

Inspect:

- `backend/app/api/routes/summaries.py` and existing summary permissions.
- `backend/app/core/config.py`, HTTP dependencies, secret redaction and readiness patterns.
- `backend/app/services/dispatcher.py`, `document_workflow_dispatch.py`, worker registration and existing scheduler/reconciliation hooks.
- `backend/app/services/workflows.py::process_document_summary` and every entry point that can invoke it.
- `backend/app/db/session.py`, job/workflow/document models, current migrations and test isolation patterns.

Confirm the supplied external contract, without treating available credentials as permission to call it:

```text
POST https://caring-doormat-pounce.ngrok-free.dev/api/v2.1/project-summary
Content-Type: application/json
ngrok-skip-browser-warning: true
X-API-Key: <server-held-secret>

{"document_id":"<authorized-document-uuid>"}
```

The body accepts only the canonical document ID. Do not add tenant/run/prompt/model fields or an idempotency header unless the upstream explicitly supports them.

## 3. Typed contracts

Define bounded request/acknowledgement models using existing Pydantic conventions:

- Request: UUID document ID derived from an authorized persisted document.
- Acknowledgement: `job_id`, `document_id`, literal `DOCUMENT_SUMMERIZATION`, supported wire status, integer progress 0-100, bounded nullable `current_step`, nonnegative attempts, safe timestamps and sanitized error metadata.
- `result_url`: optional bounded relative-path metadata with an explicitly permitted shape. It confers no authority to perform another HTTP request.
- Application response: discriminate external execution from the existing legacy response. Include `request_id`, nullable external `job_id`, document identity, submission state, normalized status, raw provider status, progress, step and result state.

Keep request and job IDs separate. Before acknowledgement, `job_id` is null; never invent a job UUID or use the coordination record's ID in its place.

The sample establishes `RUNNING`. Inventory other actual statuses separately; unsupported values must not be interpreted as successful generation. Incomplete contract qualification blocks enablement, not synthetic contract tests.

## 4. Configuration and secret boundary

Add default-disabled declarations for the fixed integration, using master-plan names where compatible:

- `EXTERNAL_SUMMARY_ENABLED=false`.
- Approved HTTPS base origin and fixed submission path.
- API key from the backend/worker environment or the repository's existing secret-file convention.
- Bounded connect/acknowledgement timeouts and response/error-body byte limits.

Validation rules:

1. Disabled integration preserves existing startup behavior and legacy operation selection.
2. Enabled integration with a missing/invalid key or origin reports a truthful configuration error.
3. Reject URL user information, unsafe schemes and operator configurations outside the approved destination policy. Tenant/browser parameters cannot change host, port, path, headers or credentials.
4. Preserve TLS certificate/hostname verification; disable redirects and unchecked environment proxies.
5. Do not log request headers, secret-bearing client objects or raw error bodies. Bound and sanitize external error messages.
6. Use the existing HTTP dependency/compatible secure transport. Do not add a provider SDK or generic model adapter system.

Examples contain `<secret>` placeholders only. Do not edit actual `.env` files or copy the supplied key into code, examples, fixtures, task payloads or documentation. No frontend `VITE_*` secret is allowed. Actual key rotation/provisioning is a separate authorized operational action.

## 5. Minimal durable submission record

Inspect for an equivalent existing record first. If none exists, introduce only a narrowly scoped request model/table, such as `summary_api_requests`, and an additive migration based on the actual head.

Required logical data:

| Group | Data |
| --- | --- |
| Trusted scope | Tenant, project, document, requester and originating workflow identity. |
| Pinned inputs | Completed processing-run ID, source fingerprint, expected current summary revision, request/configuration contract version. |
| Duplicate coordination | Client idempotency identity, input fingerprint and active-request uniqueness for compatible tenant/document/run requests. |
| Delivery | State, lease/fencing token, bounded attempts, timestamps and next reconciliation time. |
| Acknowledgement | Nullable external job ID and bounded acknowledgement metadata; database verification is still pending. |
| Diagnostics | Sanitized error code/correlation metadata only. |

Use explicit scope predicates, foreign keys and RLS; transaction-local tenant context applies to every new worker transaction. Persist the delivery intent in the same transaction as request creation. Reuse the request record as that intent rather than adding another generic outbox platform.

At minimum distinguish `SUBMIT_PENDING`, `SUBMITTING`, `ACKNOWLEDGED`, `SUBMISSION_UNKNOWN` and explicit non-retryable rejection. An acknowledgement is not a completed summary or a verified shared job.

## 6. Implement the submission flow

1. Retain the existing tenant-authorized summary POST as the product boundary. Select external execution only through explicit server configuration.
2. Validate summary permission, workflow/document ownership, active lifecycle and a ready canonical ingestion run. Pin source/run identity server-side.
3. In a short transaction, reuse a compatible existing intent or create one with its durable delivery identity. Commit before broker/network calls.
4. Return a typed queued external response without pretending a remote job already exists.
5. Publish tenant/request identifiers only to the existing worker; add the narrow delivery/reconciliation hook to existing scheduling. No new worker service or Beat scheduler.
6. Claim the request with a lease/fence, recheck current authorization/lifecycle/pinned source/configuration, and commit before HTTP submission.
7. Send the fixed document-ID request with the server-held headers. Validate status/body bounds and acknowledgement identity.
8. Persist the acknowledgement only if the attempt still owns its fence. Leave external job binding to Step 2.

External mode must not create a local `DOCUMENT_SUMMARY` generation job, enqueue the old placeholder summary dispatch, or call `process_document_summary`. Failure cannot silently fall back to that handler.

## 7. Safe interruption rules

- A crash before submission is safe for a later claimed attempt to deliver.
- A timeout or crash after a request may have reached the service records `SUBMISSION_UNKNOWN`.
- Without qualified upstream idempotency/correlation, an unknown attempt is not automatically resubmitted. Preserve it for exact reconciliation/operator resolution.
- HTTP/server errors can be ambiguous too; do not assume every 5xx means no job was created.
- An expired worker cannot overwrite a newer claim. No database lock or transaction spans the HTTP call.
- A broker delivery/re-delivery never carries secrets or raw document content.

Step 6 expands failure injection and recovery verification; these minimum rules belong in Step 1 from the outset.

## 8. Scope boundary and handoff

Allowed: backend settings declarations, request/acknowledgement schemas, fixed-service transport, minimal durable intent storage/migration, authorized submission branch and narrow existing-worker delivery hooks.

Excluded: querying/binding the shared job, UI behavior, result schemas/import, seven-section review, generation agents, WBS behavior and any live environment changes. Step 2 receives the persisted trusted request and validated external job ID.

Keep routes default-disabled and fail truthfully while downstream integration is incomplete. Do not mark a workflow review-ready from an acknowledgement.

## 9. Verification and evidence

Use synthetic keys, fake transport and isolated fixtures. Test:

- Correct method/path/body/headers; browser cannot supply another document scope or destination.
- Permission denial, cross-tenant/workflow IDs, deleting/stale/incomplete documents.
- Missing configuration while enabled versus preserved startup while disabled.
- Bad TLS/redirect/proxy policy, oversized acknowledgements, invalid types/IDs and sanitized auth failures.
- Duplicate intent creation, competing claims, stale fences and crash/timeout ambiguity.
- No placeholder dispatch, local summary generation job or secret leakage in API/task/error serialization.
- Migration/RLS/locking with disposable PostgreSQL where available; local fakes do not establish these properties.

Run focused tests, existing summary-submission compatibility checks, lint and diff checks. Record actual results under `step-01-artifacts/`, including contract gaps and exact schema changes.

**Exit:** synthetic submission is authorized, durable, bounded and secret-safe; acknowledgement identity is preserved; ambiguity fails closed; external integration remains disabled. Live endpoint/idempotency/worker qualification may remain explicitly pending.
