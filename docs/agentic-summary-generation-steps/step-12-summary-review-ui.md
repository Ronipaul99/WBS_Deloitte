# Step 12: Build model selection, summary review, and citations in the UI

Status: planned. Depends on Steps 6 and 11.
Previous: [Step 11](step-11-summary-apis-approval.md).
Next: [Step 13](step-13-lifecycle-observability.md).

## Objective

Let a user generate, inspect, edit and approve a real summary with understandable
progress and evidence, without exposing keys or misleading quality indicators.

## Implementation tasks

1. Add an approved model-profile selector before summary generation/regeneration.
   Display the provider/model and availability. Use the tenant default when valid;
   show a useful configuration message when no profile is enabled. Only admins
   receive a link to manage connections. Never silently change the selected provider.
2. Send the profile ID, expected processing-run ID and idempotency key through the
   existing summary service. Poll durable run/job state with request cancellation
   and safe refresh/navigation recovery; do not keep a browser request open for
   an entire long-document Llama generation.
3. Show actual stages and counts: inventory, source batches processed, gap searches,
   writing, verification/repair and draft readiness. Distinguish worker queueing,
   provider outage, cancellation, stale input, partial coverage and quality blocks.
4. Replace the flattened three-textarea presentation with structured tender sections,
   requirements, critical values, alternatives, risks and open questions. Use stable
   IDs for selection/editing rather than array indices. Define appropriate field
   bounds instead of truncating every section to the old 2,000-character limit.
5. Remove the hard-coded `confidenceScore: 85` and its high-confidence prose. Display
   measured coverage and explicit verification findings with their definitions;
   never label retrieval scores or LLM self-ratings as summary confidence.
6. Add citation chips opening a drawer with exact quote, physical page, heading and
   table/row context. Retrieve through the scoped evidence API. If opening the PDF,
   use an authorized fetch or short-lived document URL and correct page locator;
   a new tab cannot magically inherit a bearer header from an ordinary hyperlink.
   Do not persist signed URLs, send them to telemetry, or embed a public bucket link.
7. Edit structured claims/requirements while preserving stable IDs and evidence.
   Show human-changed claims as needing review. Handle expected-version conflicts
   visibly and allow loading the current revision rather than losing another edit.
8. Separate Save, Approve Summary and Regenerate. Approval references the current
   revision/version; only permitted, eligible drafts can be approved. Show source,
   model/profile version, generation time, usage and revision history.
9. Keep future WBS actions clearly disabled/unavailable. The current review screen
   couples approval to `startGeneration`; remove that automatic placeholder call
   for this summary-only feature.
10. Render source/model text as data. Avoid raw HTML or executable model-authored
    links. Keep provider secrets, draft bodies and signed document links out of
    browser persistence unless explicitly designed and access-controlled.

## Proposed implementation targets

- `WBS_UI/src/views/ReviewProjectSummaryScreen.tsx` and its styles.
- Summary/job services, `workflowTypes.ts`, and `workflowPresentation.ts`.
- Model selector, citation drawer, revision/history and structured editor components.
- Playwright tests for summary generation/review, including admin/editor/viewer roles.

## Verification

Test choosing Mac/OpenAI profiles, no model configured, refresh during generation,
provider failure, partial results, citations and expired source URLs, stable IDs
after reorder/edit, approval conflicts, disabled WBS and permission-specific UI.
Check keyboard navigation, focus management and mobile layouts. Assert no provider
secret is in network responses, localStorage or frontend environment variables.

## Exit criteria

- [ ] Users can choose a model and follow real asynchronous progress.
- [ ] Every displayed citation resolves through current document authorization.
- [ ] Editing cannot shift evidence to a different requirement.
- [ ] Confidence/coverage/verification labels describe measured states accurately.
- [ ] Summary approval is a complete action without triggering placeholder WBS work.
