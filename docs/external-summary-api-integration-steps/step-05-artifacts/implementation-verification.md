# Step 5: seven-section review and editing

Date: 2026-10-28. Implemented locally with synthetic fixtures. PostgreSQL and live/runtime qualification remain pending; this is not a fully qualified deployment.

## Baseline and scope

Read the step, implementation index/master plan, predecessor artifacts, current storage/routes/workflow/frontend code and destructive shared conftest. No applicable AGENTS.md was found. Initial status, staged/working diffs and tracked/untracked file fingerprints are preserved in ignored `backend/.data/external-summary-step05/`. Existing staged and unstaged Steps 1–4 work was preserved; nothing was staged, reset, committed or pushed.

The demonstrated storage gap and design were recorded in [design-boundaries.md](design-boundaries.md). Existing `structured_summary` JSON can carry a bounded separate edit overlay. **No migration was added.** The actual migration head remains `f05c8e31b742`; migrations were not applied to the application database. No application/Neon database, upstream service, VM or private document was accessed.

## Files and compatibility changes

| Files | Purpose |
| --- | --- |
| `backend/app/schemas/external_summary_result.py` | Strict section-edit/PATCH/approval contracts; compatible current-content overlay; truthful review/WBS capabilities. Original generated-result validators remain intact. |
| `backend/app/services/external_summary_review.py` (new) | Bounded scoped reads, pinned source eligibility, revision/lock guards, lossless edits, projection and atomic workflow updates. |
| `backend/app/api/routes/summaries.py` | Reuse existing GET/PATCH/approve routes with explicit legacy/structured branches. Sanitize edit/approval validation errors without echoing draft inputs. |
| `backend/app/services/external_summary_submission.py` | Extract the existing source fingerprint into a shared pure helper so review checks do not require a new submission or secret lookup. Submission behavior is unchanged. |
| `backend/app/services/document_workflow_resume.py` | Allow matching committed imports into review; retain pending/stale guards and prohibit external WBS/retry actions. Historical generated workflows retain their lineage. |
| `WBS_UI/src/services/workflowTypes.ts`, `summariesApi.ts`, `workflowPresentation.ts` | One compatible legacy/structured presentation, stable IDs/order, validated status/read contracts, structured partial saves and explicit approval. |
| `WBS_UI/src/views/ExternalSummaryProgress.tsx`, `WorkflowCheckpointScreen.tsx` | Continue bounded reads through import-pending; refresh workflow and matching persisted summary before review. No completion handler submits generation. |
| `WBS_UI/src/views/ReviewProjectSummaryScreen.tsx` and CSS | Seven sections, current/original evidence semantics, stable edits, conflicts, confidence, separate approval, disabled WBS and accessible responsive controls. |
| `WBS_UI/src/App.tsx` | Scope-key the editor, pass expected external identity and a review-only unsaved-navigation guard. Logout/workspace teardown bypass draft warnings. Existing clean project/dialog navigation is preserved. |
| `backend/tests/test_external_summary_review.py` (new), `WBS_UI/tests/external-summary-review.spec.ts` (new) | Synthetic production API/component tests for the implemented review boundary. |
| Existing `test_external_summary_import.py`, `external-summary-progress.spec.ts` | Replace only the former checkpoint-only/import-pending-stop expectations with the implemented Step 5 handoff. No unrelated navigation tests were changed. |

Legacy responses are explicitly serialized as `SummaryResponse` before the response union, preventing deferred structured JSON from being probed through synchronous ORM attribute validation. Legitimate legacy save/approval/generation requests retain their behavior. Legacy PATCH rejects unknown fields so malformed structured patches cannot silently downgrade to a legacy update.

## Storage, editing and approval contracts

The original `generated_result`, canonical citations, source references, model/question-set/run provenance, imported digest and imported revision remain unchanged. Existing stored documents without edit fields receive compatible defaults. The separate `section-edits-v1` overlay stores only changed `id`, category `key` and current plain-text content. Returning to original content removes that override. `content_state` distinguishes original generated content from edited content requiring review; human approval remains a separate authoritative field.

PATCH uses `format=external_summary_v1`, strict positive `expected_revision` and at most seven partial edits. Omitted sections preserve existing content. Duplicate/unknown identities, mismatched keys, raised limits and attempted provenance/citation mutations are rejected. Current text has its own validation and is not forced through the original generated inline-citation rules. Unknown edited markers remain visible with warnings.

Character counts use Unicode code points on server and client. Each edit must fit its persisted section limit, up to 20,000 characters. Unsupported NUL/unpaired-surrogate content is rejected safely. The deterministic complete legacy projection is limited to 50,000 characters. Structured reads are admitted with the existing SQL byte-size CASE boundary plus 600,000 bytes for bounded edit overlays. Saves also enforce that storage ceiling conservatively using escaped JSON size. Overflow is rejected without truncation or partial persistence. Requirements and key points remain empty for this format; no requirements are inferred from prose.

Lock order is document guard -> sorted same-document workflow locks -> summary lock. The document guard serializes review with import/deletion and existing writers. Protected operations apply transaction-local tenant context before reads. Current active/completed canonical run, release identity and the pinned source fingerprint are checked again inside the mutation transaction. No database transaction spans provider/broker I/O; review makes neither call.

Revision comparison precedes mutation. An actual accepted content change advances revision once and clears approval/time. Empty/equivalent saves preserve revision and approval. Only verified request associations with matching summary/job/run/current revision and no generated history advance their workflow checkpoints atomically. A stale or unassociated workflow is not silently rewritten. Summary, overlay, projection, approval reset and compatible checkpoints commit together; injected failures roll back all changes.

Structured approval is a separate existing-route action requiring `summary:approve`, the current expected revision and current source eligibility. Approval does not increment content revision. Repeated approval preserves timestamp/checkpoint. A save after approval resets it; stale approval cannot approve newer unseen text. The UI disables approval while local edits are unsaved. Canonical citation validation and extraction confidence are not human approval or semantic verification.

The external Job and immutable import record are never edited by review. Import replay returns the original import identity and cannot overwrite current edits or approval.

## UI and imported readiness

The existing review layout renders all seven persisted categories sorted by validated order. Selection, baseline, edits and partial PATCH use opaque IDs/keys, never positions. Authoritative document records supply filename/size/type. Service filenames do not establish identity. Badge/editor authority is application-controlled and plain text.

Each section shows its own limit/count, source caption/physical page chips, generated answer status, truncation notice and expandable original citations. Citation `[1]` links only to that section's original `[1]`. Unknown edited markers remain text with a warning. Pages describe canonical chunk coverage, not exact quote offsets or printed-page labels. No PDF viewer/navigation, retrieval or semantic verifier was added. Text resembling HTML remains text.

Null extraction confidence displays **Not recorded**, with no bar or invented percentage. Valid supplied numbers remain extraction metadata, explicitly distinct from accuracy/approval. Model, question set and run are supporting provenance. Edited content retains original evidence and warns that unchanged markers do not establish support for edited claims.

IMPORTED is accepted only with valid completed/100 metadata, verified request/job identity and a persisted summary ID/revision. The progress handoff refreshes authoritative workflow metadata and fetches that exact summary before review. The review load repeats scope/request/job/summary/revision checks. Pending/running/completed-but-unimported states cannot open older or placeholder content. Legacy review avoids the extra external refresh, preserving its existing navigation reads.

Polling stays sequential at about 2–5 seconds, within the existing 120-second browser allowance. Import-pending now remains observable until committed import, terminal failure or the same bounded pause. Check status is GET-only and retains request identity. Navigating away aborts browser observation without claiming remote cancellation.

Unsaved edits survive section switches and failed saves. Revision conflict retains local text and requires explicit refresh/review, with a discard confirmation. Clean navigation remains unchanged; unsaved ordinary navigation uses the existing dialog pattern. Logout/workspace teardown clears state and aborts requests. Late load/save responses cannot repaint the next scoped editor. Native keyboard controls, semantic status/error messages, focus-managed dialogs and mobile layout have synthetic browser coverage.

Structured review is available; external WBS remains unavailable with `REQUIREMENTS_CONTRACT_UNAVAILABLE`. Approval cannot enable WBS. The existing backend generation safeguard remains in place. Legacy compatible summaries retain generation behavior.

Screenshots were visually inspected at desktop and 390-pixel mobile widths: [desktop](review-desktop.png), [mobile](review-mobile.png). The initial mobile stepper overlap was corrected within review CSS. These are synthetic UI evidence, not a full screen-reader or real-service qualification.

## Verification

All backend tests use `--noconftest -p tests.upload_transaction_support`, isolated temporary SQLite/storage, synthetic credentials and enforced active-transaction preconditions. They do not read the app `.env` or delete `backend/.test-data`.

Broad backend command, from backend:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_review.py tests/test_external_summary_import.py tests/test_external_summary_tracking.py tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py -q -W error::RuntimeWarning
```

**Final broad backend run: 168 passed, 4 skipped, 3 warnings in 106.20 seconds.** The four skips explicitly reserve PostgreSQL verification for Steps 1, 2, 4 and 5. The three warnings are existing Alembic path_separator deprecations; RuntimeWarnings were treated as errors. Final review-only verification passed **25 tests, with 1 PostgreSQL skip**. Focused rollback/association checks also passed two tests. These exercise production services/routes rather than duplicate their implementation.

Broad browser command, from WBS_UI:

```text
node node_modules/@playwright/test/cli.js test --config ../backend/.data/external-summary-step05/playwright.config.mts external-summary-review.spec.ts external-summary-progress.spec.ts workflow-resume.spec.ts workflow-polish.spec.ts project-document-navigation.spec.ts document-deduplication.spec.ts workflow-integration.spec.ts
```

**61 passed, 0 failed, 0 skipped.** Final review-only run after adding keyboard and legacy editing/generation coverage: **18 passed, 0 failed, 0 skipped**. The isolated ignored config starts its own local Vite server and intercepts APIs; it does not use a real backend/provider. A separate mobile screenshot recheck passed one test. The final legacy-input/structured-overflow recheck passed two tests. The two previously documented ingestion-navigation failures were not changed or claimed fixed; that failing pair was not rerun. Relevant ingestion milestone/auth and existing navigation/dialog tests in the broad suite passed.

Initial development runs exposed expected old handoff assertions, async ORM timestamp refresh/union serialization issues, fixture encoding/timing/locator errors, and an unnecessary legacy workflow refresh. These were corrected in the scoped implementation/tests. They are not counted as final passing runs. Final legacy navigation tests remained unchanged. Ordinary generated-history retry behavior is preserved; only external summary controls are restricted. A final three-test import/history/review compatibility check passed after that scope refinement.

Other checks:

```text
npm.cmd run lint
node node_modules/typescript/bin/tsc -p tsconfig.app.json --incremental --tsBuildInfoFile ../backend/.data/external-summary-step05/app.tsbuildinfo
node node_modules/vite/bin/vite.js build --configLoader runner --outDir ../backend/.data/external-summary-step05/dist
python -m ruff check <affected backend files>
python -m ruff format --check <new/fully formatted backend files>
python -m pip check
git diff --check
git diff --cached --check
```

Lint, TypeScript and production build passed. The intentional ignored build directory outside the UI root produces Vite's non-emptying notice. Ruff and whitespace checks passed after correcting one changed test assertion's line length. No dependency additions/upgrades; pip check found no broken requirements. Bundle marker scan found no ngrok/upstream API-key configuration/header strings. UTF-8 and baseline fingerprint checks confine changes to Step 5 review/handoff/contracts/tests/artifacts; historical migrations, configuration and unrelated source remain unchanged.

## Exit status and remaining gates

Locally satisfied: lossless seven-section presentation; stable partial edits and original evidence preservation; optimistic conflict/no-op behavior; explicit current-revision human approval; scoped imported readiness/recovery; honest confidence/citation/WBS capabilities; legacy compatibility; isolated API/browser verification.

Pending: actual PostgreSQL RLS/grants, pooled transaction-local scope, competing save/approval/import/deletion locking; live upstream envelope/citation/status conventions and TLS; deployed worker/Beat routing/import recovery; full assistive-technology/runtime qualification. No verified disposable PostgreSQL target was supplied and postgres/initdb/docker commands were unavailable. SQLite sequential conflict/rollback tests do not establish PostgreSQL concurrency. Synthetic browser success does not establish actual end-to-end hosted summary generation.

No Step 6 project, new generator/verifier/retrieval/WBS algorithm, new routes, live requests, private documents, environment/secret edits, feature enablement, Docker/Nginx/CI/VM changes, deployment, commit or push occurred. No migration was added or applied to the application database. Temporary synthetic test resources are isolated; screenshots and verification artifacts contain synthetic content only.
