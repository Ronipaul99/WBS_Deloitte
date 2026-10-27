# Step 11: Integrate summary APIs, revisions, and human approval

Status: planned. Depends on Steps 2 and 5-10.
Previous: [Step 10](step-10-verification-repair.md).
Next: [Step 12](step-12-summary-review-ui.md).

## Objective

Replace the existing placeholder summary path with durable grounded generation,
while protecting human edits and approval from concurrent or stale runs.

## Implementation tasks

1. Extend the existing `POST /tenants/{tenant}/documents/{document}/summary` under
   `/api/v1`. Accept a model-profile ID, expected completed processing-run ID and
   idempotency key. Derive requester/tenant/project scope from authorization.
   A compatible omitted profile may resolve the tenant default; no default means
   a clear configuration error, not a placeholder result.
2. Require summary-update plus model-use permission, an enabled qualified profile,
   readable current source, valid limits, and the feature gate. Store the pinned
   snapshot, job and outbox entry atomically; return 202 with job/run identity.
   Do not publish through the old unprotected post-commit dispatch path.
3. Scope idempotency to tenant/requester/document and request fingerprint. Same
   key/same inputs returns the original job; same key/different inputs returns 409.
   Regeneration with a new key creates a distinct run and preserves prior revisions.
4. Keep the currently visible summary while a new run is pending. On publication,
   compare the latest request sequence and expected active revision/version. A late
   completion must not replace a newer generation or intervening human edit. Save
   a valid competing draft to history with a review conflict rather than clobbering it.
5. Return typed sections, claims/requirements, source evidence, coverage, verification,
   provenance and revision identity on reads. Keep legacy field projections during
   migration, but reject edits that would silently discard structured relationships.
6. Add revision-specific edit/history/approval routes with expected-version checks.
   Editing creates a new immutable revision and invalidates active approval;
   stable claim/requirement IDs survive unchanged items. Mark human changes for review.
7. Approve only the exact current, non-stale revision with complete source coverage
   and no unresolved critical verification failures. Unknown fields can remain
   explicitly unknown after complete review. Store actor/time/decision in approval
   history. Enforce current source/lifecycle again inside the approval transaction.
8. Add a scoped evidence reader returning verified excerpts/locators and, when
   needed, a short-lived authorized document access mechanism. Check document
   permissions/deletion on every request; never expose a permanent public object URL.
9. Surface progress/cancellation/resume through scoped job/run APIs. Sanitize failures
   and distinguish missing configuration, provider failure, quality block, partial
   coverage and stale input. No API key or raw prompt transcript appears in responses.
10. Keep WBS generation/semantic validation deferred. Prevent the new summary flow
    from invoking the current placeholder WBS task via UI or direct API; use an
    explicit disabled capability until the later WBS implementation exists.

## Proposed implementation targets

- Existing summary routes, schemas, workflow handler and dispatcher integration.
- Revision/evidence routes and scoped summary repositories.
- Job/run schemas and `test_agent_summary_api.py`, revision/approval PostgreSQL tests.

## Verification

Test API authorization, default/selected/disabled profiles, stale run ID, duplicate
requests, broker failures, simultaneous generations, edits during generation,
wrong-revision approval, source re-ingestion/deletion, and citation access denial.
Assert invalid/partial output cannot be approved, old approved content survives a
failed regeneration, and no placeholder WBS is generated from the new flow.

## Exit criteria

- [ ] Summary generation invokes the real graph with durable input/outbox state.
- [ ] Late workers and concurrent users cannot overwrite newer edits/revisions.
- [ ] Approval binds exact source/revision identity and satisfies quality requirements.
- [ ] Legacy read compatibility does not fabricate verification or lose evidence.
- [ ] WBS remains clearly unavailable in this summary-only release.
