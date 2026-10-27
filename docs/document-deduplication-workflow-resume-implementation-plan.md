# Content-Based Document Detection and Workflow Resume

Status: proposed implementation plan; application changes are not implemented by this document.

Prepared: 2026-10-28.

## 1. Intended outcome

When a user selects a document whose exact content already exists in the current workspace, the
application finds the original document, offers to continue its previous work, and opens the last
valid saved stage. It preserves the original `document_id`, project, saved summary, WBS edits,
generation history, and validation results. A duplicate does not create another stored document or
automatically restart processing.

The normal browser path identifies a duplicate before transferring the file. The backend remains
responsible for correctness if a client bypasses that check or two users submit simultaneously.

This plan changes upload coordination and workflow recovery. It does not implement the separate
agentic summary/WBS engines or certify their production readiness.

## 2. Proposed product rules

These rules are the working defaults from the discussion, rather than implemented behavior.

| Situation | Behavior |
| --- | --- |
| Identical bytes and identical filename | Offer the existing document/workflow. |
| Identical bytes and a different filename | Same behavior; filename is display metadata. |
| Different bytes and identical filename | Create a new document; preserve the original. |
| Same visible text but changed PDF/Office metadata | Treat as a different file if its bytes differ. |
| Match in another project in the same workspace | Show the original project and offer to continue there. Do not silently move the document. |
| Match in another workspace | Do not disclose or reuse it. |
| Processing or generation still running | Attach to the existing job and show its current progress. |
| Existing generated WBS | Open that workflow's saved WBS version, including persisted edits. |
| Failed/cancelled work | Show the failed stage and an explicit retry action; preserve successful earlier work. |
| A different template is selected | Ask whether to continue the saved workflow or create a new generation workflow using the existing document. |
| Several historical documents/workflows match | Show a selection; never silently choose an unrelated result. |
| Document is being deleted | Show a temporary unavailable state; do not race deletion with reuse. |
| Document is deleted | Allow a genuinely new upload after deletion finishes and its claim is released. |
| Project is archived | Do not auto-resume or unarchive it. Offer only actions allowed by current permissions. |

Workspace means tenant. Matching crosses projects only within the active tenant and the user's
current authorization. The v1 duplicate message is **“This document already exists. Continue
previous work?”**, with the original project, document name, saved stage, and last update shown.
Cancel leaves the current screen unchanged and performs no upload.

The v1 flow does not offer another stored copy of identical project-document bytes. A new template
or an explicit regenerate action creates another workflow/version against the existing document.
Independent projects sharing a physical source file would require a later document-reference
model; moving the original `document_id` between projects is not part of this change.

“Where the user left off” means committed progress and saved edits. Unsaved browser edits are not
recoverable unless autosave is added separately. Returning to a screen must not start a new job.

## 3. Verified repository baseline

| Existing area | Current behavior | Required change |
| --- | --- | --- |
| `backend/app/api/routes/documents.py` | Validates a project upload, saves an object, and inserts a fresh `Document`. | Coordinate fingerprinting, duplicate resolution, and creation before saving another object. |
| `backend/app/services/storage.py` | Generates a UUID storage key; local/S3 `save()` validates and closes the upload. | Separate upload preparation from permanent storage so duplicate checks occur first. |
| `backend/app/models/domain.py` | `Document.content_sha256` exists, but is populated by ingestion; filename is not unique. | Add a verified upload-time fingerprint without changing ingestion identity semantics. |
| `backend/app/api/routes/ingestions.py` | Reuses an active job or a compatible completed ingestion for an existing document. | Keep this behavior and resolve the original document before invoking it. |
| `backend/app/api/routes/summaries.py` | Summary creation inserts a job; editing updates the same summary and clears approval. | Make starts/retries idempotent and record the summary revision used by generation. |
| `backend/app/api/routes/generations.py` | Generation job JSON records document, summary, and template IDs. | Add durable workflow linkage and an immutable generation-input identity. |
| `backend/app/api/routes/wbs.py` | Latest WBS is selected by project, not document. | Resume through verified workflow/generation provenance, never project-latest alone. |
| `backend/app/api/routes/validations.py` | Starting validation inserts a new validation run. | Resume reads an existing validation; create only on an explicit action. |
| `WBS_UI/src/services/workflowApi.ts` | Starts upload/template/ingestion; restore resets downstream IDs to null. | Introduce resolve/resume contracts and preserve downstream references. |
| `WBS_UI/src/services/workflowSessionStorage.ts` | Saves ingestion IDs in browser session storage. | Keep only a navigation hint; recover authoritative state from the server. |
| `WBS_UI/src/App.tsx` | Restoration routes to `doc_processing`. | Route from a validated server resume response. |
| `WBS_UI/src/views/CreateWbsScreen.tsx` | Receives an already-created project. | Resolve a selected file before upload and avoid creating an additional project on a match. |

The IDE-mentioned `agent_workflows.py`, `agent_validation.py`, and agentic summary step documents
were not present in this checkout during preparation. Reconcile this plan with those files if they
are introduced before implementation. Existing summary/WBS worker code includes placeholder
behavior; this plan must not assume the missing agentic implementation already exists.

## 4. Architecture and responsibilities

```text
Select project document
    -> browser computes SHA-256 + byte count
    -> tenant-authorized resolve request
        -> existing match: show Continue previous work
            -> GET authoritative workflow state
            -> open saved stage; poll existing jobs if necessary
        -> no match: submit multipart upload
            -> server validates and independently computes SHA-256
            -> atomically acquire content claim
                -> another owner already exists: return duplicate/pending state
                -> this request owns claim: save one object and document
            -> create/attach workflow
            -> explicitly start required processing once
```

Browser hashing avoids unnecessary network transfer. It is an optimization, not proof that new
upload bytes match a client-supplied digest. Direct API clients must receive the same duplicate
protection through server-computed fingerprints and the database claim.

The existing project chosen in the UI is a destination only for a new upload. A match in a different
project requires an explicit switch to the original project. Existing project/document ownership
constraints remain intact.

## 5. Database design

Use additive Alembic migrations. Do not delete, merge, or overwrite historical data as a shortcut.
Choose revision identifiers from the actual migration head at implementation time.

### 5.1 Verified upload fingerprint

Add nullable `documents.upload_sha256` with lowercase 64-character hexadecimal validation and an
index on `(tenant_id, upload_sha256, size_bytes)`. A non-null value means the backend has verified
the bytes, either at upload or through a trusted storage backfill.

Keep `content_sha256` for its existing ingestion contract. Ingestion must verify that downloaded
bytes agree with `upload_sha256` when available, in addition to existing checks. A disagreement is
an integrity failure, not permission to reuse a different document.

Do not add a unique constraint directly to historical `documents`: duplicate files may already
exist. Enforce new upload ownership through the content-claim table below.

### 5.2 Content claims and simultaneous requests

Introduce `document_content_claims` with:

| Field | Purpose |
| --- | --- |
| `tenant_id`, `sha256` | Unique content key within a tenant. |
| `size_bytes` | Verify exact byte count alongside the digest. |
| `state` | `RESERVED`, `READY`, or `DELETING`. |
| `project_id`, `document_id` | Original document scope after publication. |
| `owner_token` | Random reservation/fencing token for the current uploader. |
| `lease_expires_at` | Recovery of interrupted uploads. |
| `pending_storage_key` | Exact generated object key owned by this reservation, for cleanup. |
| `created_at`, `updated_at` | Operational timestamps. |

Require a unique key on `(tenant_id, sha256)`, non-negative size, and state-dependent checks:
`READY` requires a document scope; an upload reservation has an owner and a live lease. Add a
composite FK from `(document_id, tenant_id, project_id)` to the existing document scope constraint.
Do not allow a claim to reference another tenant's document.

Claims are acquired with an atomic insert/conflict transaction, not “SELECT then INSERT.” Use
short transactions; do not hold a database transaction open during the object-store upload.
Lease takeover and final publication use compare-and-set checks on the owner token. A stale owner
must never publish, release another owner's claim, or delete another owner's object.

After a successful object save, insert the document and change its claim to `READY` in one database
transaction. Commit before dispatching downstream work through the existing job/outbox path.
Track object-save/database-commit failures for compensation and reconciliation.

A live `RESERVED` claim returns a pending response with `Retry-After` and an opaque status handle;
it does not send the second request to object storage. A same-digest/different-size inconsistency
fails safely and is investigated rather than reusing the record.

### 5.3 Durable document workflow

Add `document_workflows` to connect a document to its particular generation history:

- UUID `id`; `tenant_id`, `project_id`, and `document_id`.
- `processing_run_id`, `summary_id`, `summary_revision`, and optional `summary_job_id`.
- Optional `template_id` and a snapshot of the selected template's identity/revision.
- Optional `generation_job_id`, `wbs_version_id`, and `validation_id`.
- `generation_input_fingerprint`, `checkpoint_revision`, `created_at`, and `updated_at`.
- A stored checkpoint hint, verified against referenced domain records before it is returned.

Use tenant/project/document scoped foreign keys where applicable. Add supporting unique scope
constraints to referenced tables when required; an application-only tenant check is insufficient
for cross-tenant reference integrity. Avoid destructive cascading deletes of WBS history.

Multiple workflow rows may share one original document, for example when the user deliberately
changes templates or regenerates. They must not create another source document/object.

Add a workflow reference to generation jobs and WBS versions so workers publish results to the
correct workflow. Resolve migration ordering for circular optional references with two-step
creation or deferrable constraints; document the chosen FK names in the migration.

### 5.4 Revisions and result lineage

Add a monotonically increasing summary revision. Increment it whenever persisted summary content
changes. Record the approved revision and immutable generation inputs on the generation attempt.
The generation-input fingerprint includes document fingerprint, active ingestion identity,
approved summary revision/content digest, template identity, relevant generation settings, and
pipeline version. A mutable summary ID alone cannot identify the inputs of a historical WBS.

Record the WBS revision used by validation, or a stable digest of its saved tree and coverage.
Editing a WBS invalidates the “current validation” association without deleting old validation
history. Stale validation must not be presented as validation of the latest edits.

### 5.5 Optional per-user navigation cursor

If exact saved screen/tab restoration is included, add `user_workflow_cursors` keyed by
`(tenant_id, user_id, workflow_id)`. Store a validated screen/tab hint and update time. Keep this
separate from shared processing progress so one user's navigation does not change another's.
The server falls back to the correct durable stage when a cursor is no longer valid.

This cursor is not an autosave mechanism. Saved summary/WBS changes remain in their domain tables.

## 6. Proposed API contracts

All paths below are relative to `/api/v1`. Add response models in `backend/app/schemas/domain.py`
or a dedicated `document_workflows.py` schema module, and register the router in `api/router.py`.

### 6.1 Resolve before uploading

`POST /tenants/{tenant_id}/document-workflows/resolve`

Request:

```json
{
  "sha256": "<64 lowercase hexadecimal characters>",
  "size_bytes": 345678,
  "selected_project_id": "<project UUID>"
}
```

Use a JSON body so fingerprints do not appear in URL query logs. Validate digest and size limits;
authorize the tenant and applicable read/upload actions before looking up content. No-match and
unauthorized matches must not reveal another tenant's existence or identifiers.

Return one of `NEW`, `MATCH`, `MULTIPLE_MATCHES`, `UPLOAD_PENDING`, or `TEMPORARILY_UNAVAILABLE`.
Matching responses contain authorized candidate document/project/workflow IDs, original filename,
saved stage, and last update. Include `requires_project_switch` when relevant. Do not return object
keys, raw file contents, internal error traces, or fingerprints in generic logs.

This endpoint is read-only despite using POST. It neither creates a project nor starts a job.
Re-authorize and re-check current state when Continue is selected; resolution can race deletion.

### 6.2 Create or reuse at upload

`POST /tenants/{tenant_id}/document-workflows/uploads`

Multipart fields: `file`, `project_id`, optional client digest, and optional template-selection
metadata. Support an `Idempotency-Key` scoped to the tenant/user/action and validated request
identity, so a lost response can be retried without repeating side effects.

The server validates the actual bytes, computes the authoritative fingerprint, and executes the
claim protocol. Never accept the client digest as the stored verified hash.

| Result | HTTP behavior |
| --- | --- |
| New object/document/workflow committed | `201`, disposition `CREATED`, original IDs and resume state. |
| Existing document in selected project | `200`, disposition `REUSED`; no new object or processing job. |
| Existing document in a different project | `409 EXISTING_DOCUMENT_IN_OTHER_PROJECT`, authorized candidate metadata; require an explicit project switch. |
| Another upload owns a live reservation | `202`, disposition `UPLOAD_PENDING`, status handle and `Retry-After`. |
| Resolve result became unavailable | Typed `409`/`410` as appropriate; refresh state instead of silently creating a copy. |
| File invalid or supplied digest disagrees | Existing validation error or `422 CONTENT_FINGERPRINT_MISMATCH`; no permanent object. |

Keep the existing project-scoped document upload route compatible by using the same service. It
must never return a document from another project as if it belonged to the requested project.
The hash gate must apply to direct uploads too; frontend-only detection is not sufficient.

For a new document, return a `DOCUMENT_READY` state even if ingestion has not started. The UI then
uses an explicit idempotent start action. A failure between upload and ingestion must be resumable.

### 6.3 Read the workflow to resume

`GET /tenants/{tenant_id}/document-workflows/{workflow_id}`

Example response:

```json
{
  "workflow_id": "<workflow UUID>",
  "project_id": "<original project UUID>",
  "document_id": "<original document UUID>",
  "checkpoint_revision": 8,
  "stage": "WBS_READY",
  "resume_screen": "results",
  "processing_run_id": "<run UUID>",
  "ingestion_job_id": "<job UUID>",
  "summary_id": "<summary UUID>",
  "summary_revision": 3,
  "template_id": null,
  "generation_job_id": "<generation job UUID>",
  "wbs_version_id": "<saved version UUID>",
  "validation_id": null,
  "allowed_actions": ["view_wbs", "edit_wbs", "start_validation"]
}
```

Fields that do not exist at an earlier stage are null. Include typed job progress/error data when
needed, and distinguish an existing historical output from the active regeneration attempt.
Return an ETag/checkpoint revision for safe concurrent updates. Permission-filter allowed actions
and data, and recheck normal route permissions on every subsequent request.

Reading this endpoint must never generate a summary, retry a job, generate a WBS, or run validation.
Return typed `WORKFLOW_STATE_INCONSISTENT` errors for broken references and record a reconciliation
event instead of guessing from unrelated project history.

## 7. Resume state resolution

Implement one backend resolver shared by duplicate detection, project Resume actions, and browser
restoration. Read a consistent snapshot, validate document/project/lifecycle scope, then validate
the provenance of every linked result. Stored checkpoint hints must agree with domain records.

| Durable condition | Stage | UI destination/action |
| --- | --- | --- |
| Object/document saved; no ingestion started | `DOCUMENT_READY` | Offer Start processing against the original document. |
| Ingestion queued/in progress | `INGESTING` | `doc_processing`; poll the existing job. |
| Ingestion complete; no summary yet | `INGESTED` | Offer Generate summary once; do not start on a GET or component mount. |
| Summary queued/in progress | `SUMMARIZING` | Show summary progress for that job. |
| Saved summary awaiting approval | `SUMMARY_REVIEW` | `doc_summary`; load saved content. |
| Approved summary, generation not started | `SUMMARY_APPROVED` | Review/continue; generate only after an explicit action. |
| Current generation attempt running | `GENERATING` | `analyzing`; poll it; optionally link to an earlier completed WBS. |
| Current generation committed a WBS | `WBS_READY` | `results`; load its exact saved version. |
| Validation running for the current saved WBS revision | `VALIDATING` | `validation`; poll the existing validation. |
| Validation finished for that same revision | `VALIDATED` | Restore its result or a valid saved user cursor. |
| An active attempt failed/cancelled | `FAILED` / `CANCELLED` | Show its error and last successful stage; explicit Retry. |

Resolve the selected workflow/attempt rather than simply choosing the furthest stage among all
project rows. A newly failed regeneration must not erase the earlier WBS or falsely appear as a
successful generation. Completed output remains available as historical output.

Template/summary/pipeline changes invalidate compatibility for *new generation*. They do not erase
an existing WBS. Clearly identify historical output and create a new attempt only on user request.
Reuse the existing ingestion release-identity checks; identical source bytes do not automatically
mean old vectors meet a newly deployed extractor/embedding contract.

## 8. Idempotency, failures, and deletion

1. Enforce active-attempt uniqueness for each workflow and job type. Concurrent start requests
   return the same job. Explicit regeneration/retry creates a distinct recorded attempt.
2. Summary/generation/validation creation and workflow pointer updates commit together. Worker
   completion updates result records and workflow references transactionally; publish external
   tasks after commit using the established durable dispatch mechanisms where available.
3. Use attempt/revision checks so a late worker cannot overwrite a newer workflow result. GET and
   refresh are read-only; retries of navigation must not duplicate work.
4. If object save fails, release only the caller's reservation. If database publication fails after
   save, compensate or queue cleanup for that exact generated key. Record enough ownership
   information to reconcile a crash between steps.
5. Leases use database time, bounded durations, and renewal for slow uploads. After expiry, fence
   the old owner before takeover. Reconciliation checks ownership before deleting a pending key.
6. Mark content claims `DELETING` in the same transaction that starts document deletion. Release
   after object/vector deletion is complete. A completed deletion of a legacy canonical document
   first checks for another active matching legacy document before removing the claim.
7. Archived projects and malware/quarantined files are not resumable content. Preserve a known
   threat disposition so uploading identical malicious bytes does not bypass rejection.
8. If old objects are missing or their hashes disagree, report an integrity/unavailable state.
   Do not return a broken result as resumable or erase saved WBS data to repair the source.

## 9. Frontend changes

### 9.1 File selection and lookup

Add `WBS_UI/src/services/documentFingerprint.ts` with SHA-256 and byte-count calculation. Respect
the configured upload size cap. Web Crypto with `file.arrayBuffer()` is acceptable only within
that measured bound; use a worker if profiling shows UI blocking. Larger future limits require a
streaming approach. Require a secure browser context for Web Crypto.

Show `Checking existing documents…`, cancel/discard obsolete results if the selected file, tenant,
or project changes, and avoid logging fingerprints. If browser hashing is unavailable, explain
that the server will check during upload; correctness must not depend on the browser capability.

Add a duplicate notice showing original project/name and saved progress. Continue re-fetches the
workflow and routes to it. Multiple matches use a selector. A selected different template requires
an explicit continue-saved-template versus new-generation choice before template upload occurs.

### 9.2 Routing and browser recovery

- Extend `workflowTypes.ts` with typed resolve/resume responses and a discriminated workflow state.
  Do not invent required ingestion IDs before ingestion starts.
- Update `documentsApi.ts`/`workflowApi.ts` to distinguish created, reused, and pending outcomes.
- Replace downstream-null-reset restoration with the authoritative resume endpoint.
- Update `App.tsx` to route from validated stage/cursor, including results and validation.
- Keep browser storage as `{version, tenantId, workflowId}` navigation hints. On missing/expired
  storage, project/workflow listing and content lookup must still recover the saved work.
- Migrate v1 ingestion context through a server lookup; do not trust cached job IDs or stages.
  Clear only unusable hints on 403/404; preserve hints for transient connectivity errors.
- Add Continue previous work in the project workspace so reopening does not require re-uploading.
- Update processing/review/analysis/result/validation screens to load existing resources without
  creating them on mount. Add explicit missing-stage start/retry actions where currently absent.
- Preserve unsaved-change prompts before switching projects. Persisted WBS/summary edits are loaded
  from the existing records rather than replaced with regenerated content.

The current upload view receives a project that already exists. V1 must prevent *additional*
project creation on a match, but it must not delete an already-created empty project automatically.
If the product later moves file selection before project creation, perform resolution first and
create a project only for a genuinely new workflow. That UI restructuring is a separate decision.

## 10. Existing-data migration and backfill

1. Add nullable columns, claim/workflow tables, checks, indexes, and role grants through Alembic.
   Keep behavior flags off and existing upload contracts functional.
2. Add a resumable CLI dry run reporting document counts, missing hashes, duplicate groups,
   missing objects, ambiguous lineage, and archive/deletion status. Do not print file content or
   password/connection data; treat filenames and hashes as private operational data.
3. For each active document, stream the trusted stored object through the storage abstraction,
   enforce byte limits and tenant scope, and compute/verify its fingerprint. Existing ingestion
   hashes may seed candidates but cannot blindly prove that current stored bytes still match.
4. Update fingerprints in bounded batches with optimistic checks on document lifecycle/identity.
   Do not change `document_id`, object keys, chunks, summaries, WBS versions, or owners.
5. Group verified duplicates. Create one claim per tenant/digest with a documented deterministic
   representative (oldest active document, UUID tie-breaker). Keep all historical rows/results;
   lookup can return other verified matching legacy workflows for selection.
6. Build workflow rows only when provenance is unambiguous: document -> summary and its recorded
   jobs -> generation job inputs -> WBS version -> validation. Do not assign project-latest WBS
   to every document in a project. Mark unresolved legacy cases for review instead.
7. For historical generations lacking revision snapshots, mark revision compatibility unknown;
   preserve their viewable output but do not claim they match today's mutable summary/template.
8. Re-run dry-run reports and count/referential checks. No release claim of full detection is
   valid while eligible legacy documents remain unindexed without a disclosed limitation.

Before workspace-wide enforcement, complete backfill or explicitly gate it to verified content.
Do not silently treat a failed lookup/backfill as proof that a document is new.

## 11. Implementation phases and exit criteria

### Phase 1 — Agree behavior and API/state contracts

Deliver product rules, typed stage transitions, duplicate outcomes, template-change behavior,
permission matrix, and examples for fresh/running/completed/failed/legacy workflows.

Exit: resolve the default cross-project confirmation behavior and the optional per-user cursor;
the contract identifies the original project and exact generation lineage for every resume result.

### Phase 2 — Add schema and provenance

Implement additive migrations, models, scope constraints, summary/WBS revision tracking, workflow
references, claim grants/RLS policy as appropriate, and repository methods. Register new model
metadata for both migrations and tests.

Exit: an isolated PostgreSQL database upgrades successfully; cross-tenant references and competing
content claims fail correctly; existing legacy documents remain readable.

### Phase 3 — Implement upload fingerprinting and content claims

Extract upload preparation from storage saving. Hash/validate before permanent writes, implement
resolve/upload/status responses, protect direct/legacy routes, and add lease/cleanup integration.

Exit: repeated identical uploads, including renamed/direct/concurrent requests, publish one new
document/object. Interrupted owners recover without duplicate publication or unsafe cleanup.

### Phase 4 — Implement workflow recovery and idempotent transitions

Build `document_workflow_resume` service and routes; link summary/generation/validation starts and
worker completion; implement explicit retry and compatibility rules.

Exit: every state in section 7 resumes the correct resources; repeated reads create zero jobs;
concurrent starts return one active attempt; unrelated project WBS versions are never selected.

### Phase 5 — Add UI detection and resume

Implement browser hash checks, duplicate notices/selectors, project switch, template choice,
typed routing, migrated storage hints, and project Continue actions. Preserve saved edits.

Exit: a renamed duplicate after logout/storage clearing reopens its existing saved stage without
an upload request. Failed/in-progress work resumes without a new processing/generation attempt.

### Phase 6 — Backfill existing content and histories

Implement the dry-run/apply CLI and ambiguity reporting; run bounded backfill in an isolated
deployment copy before scheduling it for the target environment.

Exit: counts reconcile; no historical rows are removed; eligible existing duplicates resolve;
ambiguous history is visibly handled rather than incorrectly inferred.

### Phase 7 — Integration, browser, and operational verification

Execute the matrix below, include real PostgreSQL contention and object-storage failure injection,
and record artifacts in a feature-specific implementation-evidence document.

Exit: the acceptance criteria pass, including tenant isolation, lifecycle races, and no duplicate
objects/jobs. Mocked/SQLite tests alone do not establish these guarantees.

### Phase 8 — Controlled rollout

Deploy compatible schema/backend before frontend. Enable lookup/resume for an internal tenant,
verify backfill, then enable duplicate enforcement. Keep telemetry and reconciliation enabled.

Exit: production-like resource checks pass, feature behavior is observed, and rollback has been
rehearsed without deleting saved workflows or lifting tenant boundaries.

## 12. Test and acceptance matrix

| Area | Required verification |
| --- | --- |
| Matching | Same bytes/same name and same bytes/renamed return the original ID. Same name/different bytes creates a distinct document. |
| Browser transfer | Preflight match results in no multipart upload, object save, or template upload. |
| Direct API | Bypassing preflight still reuses/rejects correctly after server hashing. Forged digest is rejected. |
| Concurrency | Parallel first uploads publish one object/document; losers get pending/reused responses. Different tenants remain independent. |
| Lost responses | Retrying upload/start after commit returns the existing resource and job. |
| Lease ownership | Slow owner, expiration, takeover, worker crash, and late completion cannot publish/delete another owner's object. |
| Saved stages | Upload-only, ingestion, summary, approved summary, generation, WBS, validation, failure, cancellation, and explicit regeneration all reopen correctly. |
| Provenance | Multiple documents/WBS versions in one project never route to the wrong document's result. |
| Inputs | A different template or edited summary creates a deliberate new generation attempt; old results remain available. |
| Edits | Saved summary/WBS edits survive reopening. Validation is marked stale after relevant WBS edits. |
| Read-only navigation | Refresh, resolve, resume, logout/login, and component remount create no new jobs. |
| Storage recovery | Missing objects, save failures, DB commit failures, orphan cleanup, and retry are correctly classified. |
| Lifecycle | Resolve/Continue races with deletion, completed deletion, archive, and membership removal are handled safely. |
| Security | No cross-tenant candidate/ID leakage; viewers read only; editor/admin actions follow existing permissions; hashes are not treated as bearer credentials. |
| Legacy content | Backfill is restartable; existing duplicate groups and ambiguous WBS lineage require correct selection/review. |
| Browser recovery | New browser context or cleared session storage still resumes through server lookup/project listing. |
| New install | Clean installation and normal first upload remain functional with optional fields null. |

Suggested backend test modules: `test_document_fingerprint.py`,
`test_document_deduplication_api.py`, `test_document_content_claims_postgres.py`,
`test_document_workflow_resume.py`, and `test_document_backfill.py`. Extend existing
`test_object_storage.py`, `test_workflow.py`, `test_ingestion_api.py`, authorization, and lifecycle
tests for integration regressions rather than duplicating their complete suites.

Suggested browser coverage: `WBS_UI/tests/document-deduplication.spec.ts` and
`WBS_UI/tests/workflow-resume.spec.ts`, using the existing Playwright/fullstack harness. Include
fresh browser contexts rather than relying exclusively on one tab's cached session state.

Implementation validation commands should use the actual available test modules and environment:

```powershell
# From backend: lint and targeted tests, then the relevant regression suite.
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m pytest <new-and-affected-test-modules>

# Run migrations only against the designated isolated test database first.
.\.venv\Scripts\python.exe -m alembic upgrade head

# From WBS_UI: static checks and browser coverage.
npm.cmd run lint
npm.cmd run build
npm.cmd run test:e2e -- tests/document-deduplication.spec.ts tests/workflow-resume.spec.ts
npm.cmd run test:e2e:fullstack
```

Real PostgreSQL claim/lease tests and real object-storage integration are required in addition to
the listed local checks. Do not run destructive tests or migrations against a shared live database.
Evidence must distinguish checks executed from planned checks and record external prerequisites.

## 13. Files expected to change

| Area | Existing or proposed files |
| --- | --- |
| Models/migrations | `backend/app/models/domain.py` or new workflow model module; `backend/app/models/__init__.py`; `backend/migrations/env.py`; new Alembic revisions. |
| Upload/lookup | `backend/app/api/routes/documents.py`; new `document_workflows.py` route; `backend/app/services/storage.py`; new fingerprint/content-claim services. |
| Resume/state | New `backend/app/services/document_workflow_resume.py` and workflow repository; domain/new schema module; `backend/app/api/router.py`. |
| Job/result linkage | Summary/generation/validation routes; `backend/app/services/workflows.py`; dispatcher and existing ingestion/lifecycle services where integration requires it. |
| Backfill/config | `backend/app/cli.py`; new backfill service; `backend/app/core/config.py`; `.env.example`; backend README. |
| UI API/types | `workflowTypes.ts`, `workflowApi.ts`, `documentsApi.ts`, `workflowSessionStorage.ts`; new `documentFingerprint.ts`. |
| UI presentation | `CreateWbsScreen.tsx`, `ProjectScreens.tsx`, `App.tsx`, existing processing/summary/analysis/WBS/validation views, and a duplicate-match component. |
| Tests/evidence | New/affected backend and Playwright tests; implementation evidence linked to this plan. |

## 14. Rollout, observability, and rollback

Introduce separate configuration controls for lookup/resume exposure and upload reuse enforcement.
They are rollout controls; enabled deployments use the existing PostgreSQL/object-storage path.
Do not introduce an alternate deployed database or embedding pipeline for this feature.

Measure new uploads, resolved/reused documents, pending claims, reservation expirations, orphan
cleanup, resume-stage counts, inconsistent references, and avoided processing attempts. Record
bounded reason codes and request IDs. Do not log raw document hashes, names, content, tokens, or
storage credentials, and avoid high-cardinality document IDs as metric labels.

Monitor lookup latency and browser hashing time within configured upload limits. Set lease/timeout
values from measured upload duration, not an assumed fast connection. Reconcile stale claims and
missing workflow links through bounded, auditable maintenance jobs.

Rollback order: disable the new UI/preflight, pause new claim acquisition/uploads if required,
and keep readers for already-created workflows. Preserve active claim ownership and uniqueness
until pending uploads settle. Do not turn off the backend gate while a legacy upload path can
race active owners. Keep additive schema/data; reverting to an older backend that ignores claims
requires an upload maintenance window and reconciliation first. Do not drop workflow tables or
delete historical results as a rollback mechanism.

## 15. Definition of done

- An identical upload, even renamed, resolves to its original accessible `document_id`.
- The normal duplicate path transfers no file and saves no second object/document.
- Bypassed preflight and concurrent uploads cannot publish duplicate new documents.
- Continue opens the original project's correct saved stage and exact WBS/validation history.
- Resume works after logout or loss of browser storage without repeating completed jobs.
- Saved edits, original ownership, tenant boundaries, users, and the question bank are preserved.
- Different templates and explicit regeneration create recorded new attempts against the existing
  source document, while retaining earlier results.
- Legacy duplicates, missing fingerprints, stale validation, failed jobs, and deletion races have
  explicit tested behavior.
- Additive migration/backfill, real PostgreSQL contention, object-store compensation, browser
  workflows, and rollback evidence are complete before release readiness is claimed.
