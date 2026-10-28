# Step 2 implementation and verification

Date: 2026-10-28 (Asia/Calcutta).

Status: locally implemented; PostgreSQL, live-service and deployed-worker qualification remain pending. This step does not enable the integration or import summaries.

## Baseline and migration lineage

- Step 1 source and tests were already present as working-tree/untracked changes; planning documents were already staged. Those changes were preserved except the explicitly required compatibility extensions described below.
- Initial tracked diff was four files, 40 additions and three removals. Initial Step 1 file fingerprints were captured in ignored `backend/.data/external-summary-step02/baseline.json` to distinguish existing work from this step.
- No applicable repository `AGENTS.md` was found by the scan.
- Read the complete selected step, index/master plan, Step 1 artifacts/code/tests, existing summary/job/workflow models/routes, permissions, transactions and test setup.
- Initial source migration head: `d82f6a913b70`. Added head: `e94b7d20a631` with that exact parent. Historical migrations are unchanged. No application database was inspected or migrated.
- Shared destructive tests/conftest.py was inspected and not loaded. Tests use isolated temporary resources via `--noconftest -p tests.upload_transaction_support`; `.test-data` was not deleted.

## Files changed and why

| Area | Step 2 change |
| --- | --- |
| `backend/app/services/external_summary_tracking.py` | Exact metadata projection, authorization/source/checkpoint checks, status mapping, guarded binding, generic-job guards and DB-only worker reconciliation. |
| `backend/app/schemas/external_summary_tracking.py` | Metadata-only typed status with request/job identities, submission/binding/result states, progress/step/timestamp and unsupported-control flags. |
| `backend/app/models/external_summary.py` | Verification marker, scoped request identity constraint and per-workflow binding model. |
| `backend/app/models/document_workflows.py` | Composite identity uniqueness required for cross-document association foreign keys. |
| `backend/app/models/__init__.py` | Register the added binding model. |
| `backend/migrations/versions/e94b7d20a631_external_summary_job_bindings.py` | Narrow additive marker/constraint/association schema, FORCE RLS and separate restricted runtime grants; downgrade removes only Step 2 additions. |
| `backend/app/services/external_summary_submission.py` | Attach every explicitly submitted/reused workflow within the existing Step 1 transaction, without job verification there. |
| `backend/app/core/config.py` | Default 60-second visibility/inconsistency grace, bounded 1-600 seconds. No actual environment file changes. |
| `backend/app/api/routes/summaries.py` | Tenant/document/request-scoped status GET, sanitized DB failure, atomic metadata binding commit. |
| `backend/app/api/routes/jobs.py` | Reject external generic GET/events/cancel/retry before full ORM job loading or execution-row mutation. |
| `backend/app/services/document_workflow_resume.py`, workflow schema | External metadata and truthful pending/stopped/import-pending recovery; legacy summary history remains separate. |
| `backend/app/worker.py` | Conditional entry in existing Beat schedule plus DB-only binding reconciliation task. No new service/scheduler. |
| `backend/tests/test_external_summary_tracking.py` | Synthetic production-boundary tests, SQL projection checks, isolated FK/migration verification and explicit PostgreSQL skip. |
| `backend/tests/test_external_summary_submission.py` | Adjust only migration-test head/current-model expectations for Step 2 additions, while still testing the unchanged Step 1 migration. |

The schema gap and rationale were recorded before the additive migration in [design-boundaries.md](design-boundaries.md). No dependencies were added or upgraded.

## Exact lookup and access boundaries

The shared-job query uses all predicates:

```text
id = acknowledged external_job_id
job_type = DOCUMENT_SUMMERIZATION
tenant_id = trusted tenant
project_id = trusted project
request_payload is a JSON object
request_payload.document_id = canonical trusted document UUID string
```

PostgreSQL JSON/JSONB object admission uses a JSON cast and `json_typeof`; SQLite uses its JSON object function. Real PostgreSQL execution remains unverified.

The SELECT projects only job ID, status, progress, step, attempts and timestamps. It does not select `result_payload`, full request JSON, error_message or error_code. SQL-capture tests assert the actual status request and generic external-job guards never load results or UPDATE jobs.

Current caller requires both SUMMARY_READ and JOB_READ. Request/document/workflow scope resolves server-side; original submitter authorization/auth-version, source/run identity and current configuration are rechecked before binding. Known identifiers alone confer no authority. Fresh transactions reapply trusted tenant context; the strict active-transaction guard is unchanged.

A same-tenant ID-only lookup distinguishes a wrong type/project/document/request shape from a missing row. Foreign-tenant rows hidden by RLS cannot safely be distinguished from absent rows: they remain visibility-pending only within grace and fail closed afterward. No cross-tenant existence lookup is performed.

## Binding and ownership

- Each submitted/reused workflow gets its own request association with expected checkpoint and previous summary-job pointer, in the existing document-locked submission transaction.
- Composite request/workflow scope foreign keys prevent association to another document. Synthetic SQLite enforcement was explicitly enabled for the cross-document FK test; that does not establish PostgreSQL RLS.
- Binding occurs only after exact row and metadata validation. The document lock and refreshed expected checkpoint/pointer protect the workflow update.
- First binding sets workflow.summary_job_id and advances checkpoint once, while storing request/association verification timestamps atomically. Repeated reads do not increment checkpoint again.
- Job.workflow_id and every externally owned execution field remain unchanged. Compatible forks can attach to the same request/job without stealing the originating workflow.
- Original Step 1 intents lacking an association return an explicit missing-association state. An authorized compatible POST may attach them; no historical checkpoint is silently fabricated by a GET.
- Status GET may persist guarded verification metadata, but never generation, result import or externally owned job writes. Existing-worker reconciliation performs the same DB-only binding independently of browser activity, without child-task waits.
- Reconciliation is bounded to 100 unverified associations per active tenant per tick, with the existing conservative 1,000-tenant scan boundary. It does not poll the upstream HTTP service.

## Status and failure policy

| Wire value | Application projection |
| --- | --- |
| RUNNING | IN_PROGRESS; real reported progress, including 100 without claiming completion. |
| QUEUED | QUEUED. |
| COMPLETED / completed, progress 100 | COMPLETED execution, IMPORT_PENDING result; no review content or approval. |
| COMPLETED / completed, progress below 100 | Bounded inconsistent/finalizing state, then unavailable. |
| FAILED | FAILED, generic sanitized stopped message. |
| CANCELLED | CANCELLED, generic sanitized stopped message. |
| Other values, invalid bounds/step metadata | Explicit unsupported/unavailable state. |

Provenance: RUNNING was supplied in the sample; completed status was user-described. QUEUED/FAILED/CANCELLED are explicit defensive lifecycle policy exercised synthetically, not live-qualified observations. No arbitrary case normalization, success-substring matching or invented remote capabilities are used.

Missing-row grace starts from the application's acknowledgement timestamp. Once a job was verified, disappearance is unavailable immediately. Completion inconsistency is bounded by the application's first verification timestamp, or acknowledgement time if not yet verified; remote heartbeat updates cannot extend the wait. A long-running job may therefore become unavailable immediately if it later reports inconsistent completion. A corrected exact row can subsequently recover.

Raw supported provider status is retained separately. Real safe step/progress are returned; raw upstream errors are never returned. Unknown/failed submission, changed source/auth/configuration, stale checkpoint, unsupported metadata and DB read errors remain explicit. The current configured API key cannot be echoed through current_step.

## Endpoint and recovery contract

```text
GET /api/v1/tenants/{tenant_id}/documents/{document_id}/summary/requests/{request_id}
Optional workflow_id selects only an already authorized attached workflow.
```

The response contains request/job/document/workflow identities, exact job type, submission/binding states, normalized and raw status, reported step/progress, attempts/update time, result readiness and sanitized diagnostics. can_retry/can_cancel remain false. summary_id/summary_revision remain null because import belongs to Step 4.

Workflow recovery exposes the same projection through `external_summary`. Pending or remotely completed-but-unimported work stays on the checkpoint with SUMMARIZING; unavailable/stale/failed/cancelled work stays explicitly stopped. It cannot reopen an old draft, offer another summary submission or start WBS generation as this attempt's success. Historical generated WBS work retains its own lineage; legacy DOCUMENT_SUMMARY recovery remains unchanged.

Generic external-job GET/events are rejected to prevent result exposure. Generic cancel/retry are rejected before any execution-row mutation or legacy dispatch. Guards still reject the external job type when the feature is disabled; when enabled they also reject acknowledged external identities whose stored job type has become invalid. No remote cancellation or retry contract is fabricated.

## Commands and actual results

From `backend`:

```text
.venv/Scripts/python.exe -m pytest --noconftest -p tests.upload_transaction_support tests/test_external_summary_tracking.py tests/test_external_summary_submission.py tests/test_document_workflow_recovery.py tests/test_document_deduplication_api.py -q
```

Final run: **95 passed, 2 skipped**, 46.54 seconds. Both skips explicitly reserve PostgreSQL/RLS/concurrency qualification (one Step 1, one Step 2). Two existing Alembic warnings concern the absent `path_separator` setting; that unrelated configuration was not edited.

- Focused Ruff check across Step 1/Step 2 affected sources/tests/migration: passed.
- Formatting of new Step 2 modules/migration/tests and modified code ranges: checked; final scope review records any baseline formatting separately.
- `python -m pip check`: no broken requirements.
- `git diff --check`: passed.
- Script graph verifies e94b7d20a631 as head and d82f6a913b70 as parent.
- Isolated SQLite upgrade/downgrade/re-upgrade tests preserve a synthetic pre-existing tenant and compare model/column/FK shapes. The live/application database was not migrated.

Coverage includes exact versus newer job, wrong type/project/document/JSON shape, actual foreign tenant, known foreign request/workflow IDs, strict progress metadata, delayed/missing visibility and recovery, bounded inconsistent completion, current permissions/revocation/source checks, pending and acknowledged stale checkpoints, safe worker/fork binding, missing-association recovery, fresh sessions after commit/rollback, generic result/control guards, old-draft blocking, sanitized DB failure and the existing legacy submission/recovery/deduplication regressions.

## Exit criteria and remaining gates

Locally satisfied: exact scoped metadata lookup, separate request/job identities, guarded associations/verification, explicit status/grace policy, metadata endpoint, summary-specific workflow recovery, protected generic controls and legacy compatibility.

Pending:

- Disposable PostgreSQL JSON query execution, migration recovery, runtime grants/FORCE RLS, pooling and real concurrent binding/lock behavior. SQLite and SQL inspection are not proof.
- Actual upstream shared row/schema/role fields, full status vocabulary/case and completion-write timing.
- Live TLS/ngrok compatibility and deployed worker/Beat routing/uniqueness.
- Later-step progress UI, result loading/validation/import and structured review are intentionally absent.

No Steps 3-6 functionality, frontend changes, result_payload loading/import, document_summaries writes, real-service calls, actual environment/secret changes, feature enablement, deployment, commits or pushes were performed. The integration remains default-disabled and not live-qualified.
