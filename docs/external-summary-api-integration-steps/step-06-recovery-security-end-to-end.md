# Step 6: Recovery, duplicate prevention, security and end-to-end tests

Status: planned. Depends on independently implemented Steps 1-5 and their actual evidence.

Read the [index](README.md), [master plan](../external-summary-api-integration-plan.md), every preceding contract/implementation/artifact, outstanding qualification and current test/process-safety conventions first.

## 1. Objective

Demonstrate and harden the complete Generate summary -> exact shared job -> progress -> validated saved draft -> edited review flow. Prove safe recovery under interrupted delivery, duplicate requests, stale sources, concurrent imports/edits and authorization changes.

This step consolidates safety required in earlier steps. It is not permission to add another orchestration platform, real provider calls, deployment or unrelated fixes.

## 2. Establish the actual baseline

Before edits or tests:

1. Capture git status/diff and preserve pre-existing/concurrent changes.
2. Inspect current Step 1-5 code and evidence; list incomplete handoffs and unverified claims.
3. Verify actual migration head, request/import states, ownership rules and deployed qualification status from available evidence without touching the application database.
4. Inspect `backend/tests/conftest.py` and test runners. Refuse cleanup against `.test-data`, configured application/Neon URLs or shared production resources.
5. Separate local fake-transport tests, disposable PostgreSQL, local full-stack browser checks, live external qualification and deployed-worker checks in reporting.

Fix only demonstrated gaps inside this integration. If an earlier contract/schema must change, document why and keep the change minimal/additive.

## 3. Recovery state inventory

Document every supported state and legal next transition for submission, execution observation and result import. Keep these independent concepts:

| Condition | Required recovery |
| --- | --- |
| Intent committed, task not delivered | Existing bounded reconciliation republishes identifiers; no lost request. |
| Task delivered twice | One current lease/fence; losing attempt cannot submit or commit. |
| Worker dies before HTTP submission | Safe ownership recovery after lease expiry. |
| Request may have reached service, acknowledgement lost | `SUBMISSION_UNKNOWN`; no blind remote replay. |
| Acknowledged job row not visible | Read the same ID within a bounded grace; no invented replacement job. |
| External worker runs after browser closes | Existing application worker/reconciler continues status/import work. |
| Job completes before result becomes visible | Import-pending grace on that exact row. |
| Import transaction fails | Retry the local import with the same identity; never resubmit generation. |
| Import already completed | Return existing imported revision without touching edits/approval. |
| Source deleted/replaced or attempt superseded | Reject late import; preserve historical provenance without activating output. |
| Browser wait expires | Stop waiting and offer status reads; do not declare generation failed. |

Classify failure boundaries conservatively. A server error, disconnect or timeout after send can be ambiguous. Automatic remote retry requires a separately qualified upstream idempotency/correlation contract, not a new in-memory allowance.

## 4. Duplicate-prevention invariants

Enforce and test:

1. Repeated Generate summary clicks and concurrent authorized submissions for the same compatible tenant/document/run share one active durable request.
2. A reused idempotency identity with different pinned inputs is rejected.
3. A template fork may attach to compatible document summary work without stealing a job/workflow association.
4. No local `DOCUMENT_SUMMARY` generation job/placeholder task is created for external execution.
5. Only the acknowledged `DOCUMENT_SUMMERIZATION` job may satisfy that request. A later unrelated job cannot replace it.
6. One request/result hash imports once; competing workers cannot create duplicate revisions or reset approval.
7. Current user edits/approved content cannot be overwritten by late imports or stale saves.
8. Deleting and re-uploading the same bytes creates a different document identity under existing upload rules; an old summary request cannot attach to the replacement.

Do not alter content-deduplication/ingestion semantics to make summary tests easier. Test existing boundaries, not a redesigned upload flow.

## 5. Security verification

### Authorization and tenant scope

- Submission/update/approval/status read enforce existing backend permissions, not just UI visibility.
- Known foreign request/job/workflow/chunk IDs remain inaccessible.
- Every job query includes exact ID/type/tenant/project/request-document predicates.
- Fresh transactions, pooled sessions and secondary worker sessions reapply transaction-local tenant context.
- Permissions revoked between enqueue, submission, poll, import and save prevent new unauthorized work at the appropriate boundary.
- Runtime-role RLS/grants are tested directly in disposable PostgreSQL; no owner/BYPASSRLS workaround.

### Network and secrets

- Fixed approved HTTPS origin/path; no tenant-selected URL, unsafe redirects or unchecked proxy bypass.
- Correct TLS verification and bounded HTTP/error responses.
- `result_url` cannot redirect the integration to another origin or authorize an arbitrary HTTP request.
- Synthetic API key never appears in API responses, browser requests/storage, bundles, task messages, audit metadata, exceptions or logs.
- Rotation uses the authorized server secret boundary; no actual secret file changes during implementation.

### Data and provenance

- Bound stored JSON/result/section/quote sizes, including hostile oversized input and malformed nesting.
- Preserve exact source/run identity and section-local evidence links.
- Render source/service/user text safely; prompt-looking content cannot alter scope, register tools or execute code.
- Null confidence stays unknown; invalid/missing evidence is not called verified.
- External job ownership remains intact: no local normalization writes, fake cancellation or overwritten raw result.

## 6. Fault-injection and concurrency matrix

Exercise production service boundaries with controlled failures:

| Boundary | Assertion |
| --- | --- |
| Before/after request-intent commit | No half-created workflow/request association; committed intent remains recoverable. |
| Before/after broker publish/ack | Duplicate delivery is safe and no request is silently lost. |
| Claim/lease renewal/expiry | Only a current fenced owner can submit/import; stale attempts cannot overwrite state. |
| Before send/after send/before acknowledgement persistence | Safe delivery versus explicit ambiguity is distinguished. |
| Acknowledgement stored/before exact row binding | Same job ID reconciles after restart; no latest-job search. |
| Completion/payload write split | No premature review, replacement POST or false completion. |
| Validation/summary write/workflow update/import marker | Atomicity or recoverable rollback; no half-published draft. |
| Concurrent import/edit/approval | One authoritative revision, stale writer denial and preserved human work. |
| Source/authorization change during generation | Late result is ineligible rather than reattached to current source. |
| Browser navigation with delayed response | No stale state leak into another tenant/document. |

Use controllable clocks, fake broker/network boundaries and explicit barriers for concurrency rather than flaky fixed sleeps. Never infer actual worker recovery from fakes alone.

## 7. Local full-stack end-to-end scenarios

Use a new uniquely marked synthetic tenant/project/document in isolated resources and a controlled fake external HTTP service. The fake service should write realistic external job rows to the **same disposable database** used by the test backend, exercising real lookup/import code.

| Scenario | Expected end-to-end outcome |
| --- | --- |
| New summary | One intent/submission; exact job type/ID; queued/running step/progress changes visible; completed 100 imports one draft. |
| Repeated submission | Same active request/job; no second external call or placeholder dispatch. |
| Several jobs for one document | UI/import follow the acknowledged ID, even if another job is newer. |
| Browser reload/lost storage | Explicit workflow navigation resumes the same request without POST. |
| Browser closed/worker restart | Durable work/import finishes independently and is visible on return. |
| Remote failure/unavailable/unknown submission | Truthful state and safe recovery; no fallback summary or blind replay. |
| Inconsistent completion | Running-at-100/completed-below-100/missing payload never opens review early. |
| Seven sections | All content, citations, pages, flags and null confidence render correctly. |
| Edit/save/reload | Stable-key edits survive, untouched evidence preserved, approval reset on real changes. |
| Approval conflict | User cannot approve a revision changed since it was reviewed. |
| Stale/deleted source | Late result blocked; old work cannot attach to re-uploaded document. |
| Legacy compatibility | Existing summaries, uploads, duplicate dialog, document preview, project workspace and WBS polling remain correct. |

Ensure local tests use the backend containing the changes. Identify test-owned processes and resources; clean up only those created by the harness. Do not stop unrelated local processes or SSH tunnels.

## 8. Disposable PostgreSQL and migration verification

Use an explicitly verified disposable target, not a URL copied from application settings. Verify:

- Migration upgrade from the actual previous head and a safe recovery path, with synthetic legacy ingestion/workflow/summary rows preserved.
- Separate migration/runtime roles, grants and RLS on added request/review associations.
- Exact JSON document-ID lookup, row visibility and payload-size admission.
- Active-request uniqueness, scoped foreign keys, concurrent claim/import locking and stale-fence updates.
- Pooled-connection scope reuse and cancellation/rollback behavior.
- Re-import/save/approval transactions preserve all-or-nothing state.

If unavailable, finish independent local checks and mark PostgreSQL/RLS/concurrency verification pending. SQLite or mocked dialect results are not substitutes.

## 9. Live qualification is separate

Do not contact ngrok or make paid generation calls as part of this implementation step. A later explicitly authorized smoke test needs:

- Approved target/endpoint and securely provisioned current key.
- One authorized synthetic completed document; no private RFP.
- Request/time/cost limits and a known cleanup/observation plan.
- Verified shared schema/role scope and exact returned job ID.
- Actual status/step vocabulary, completion/payload write behavior and citation normalization observations.
- Actual deployed worker routing/reconciliation and scheduler uniqueness evidence.
- Upstream idempotency/correlation/cancellation/retry capability evidence where claimed.

These are qualification items within Step 6, not additional implementation steps. Credentials existing locally do not authorize their use. Missing live qualification remains a clearly named gate; no deployment/feature enablement is performed here.

## 10. Checks and evidence

Run the relevant isolated backend suites for all six steps, frontend unit/browser suites, local full-stack harness, lint, formatting, TypeScript/build, migration checks and final diff review. Use repository-supported commands after inspection; do not invent test paths or successful counts.

Record evidence under `step-06-artifacts/`:

- Actual state/transition ownership and duplicate/idempotency guarantees.
- Failure-injection/concurrency results and unresolved ambiguity cases.
- Permission/RLS/secret-exclusion findings with sanitized metadata.
- Commands, pass/fail/skip counts and screenshots where useful.
- Separate local synthetic, disposable PostgreSQL, live-network and deployed-worker results.
- Schema/prerequisite compatibility changes and reasons.
- Test resources/process cleanup and any resources intentionally left behind.
- Remaining contract, infrastructure and qualification gates.

No raw private payloads, secrets or internal endpoint credentials belong in committed evidence. Do not modify actual `.env`, Docker/Nginx, CI, production services, question-bank data or the live VM; do not commit/push/deploy.

## 11. Final acceptance

The integration is locally complete only when:

1. Backend-only durable submission follows one exact externally owned summary job.
2. Status/step/progress are real, visible and resumable without duplicate generation.
3. Confirmed completion at 100 produces one validated, saved unapproved draft.
4. Seven-section review/edit/save retains evidence, original provenance, null confidence and optimistic revision safety.
5. Failures, ambiguity, stale sources, revocation and concurrency fail safely without corrupting other work.
6. Existing project/document/upload/ingestion/legacy-summary behavior remains compatible.

Report live readiness separately. Do not claim actual extraction quality, PostgreSQL isolation, upstream idempotency, live TLS compatibility or deployed-worker recovery from local fake-service success.
