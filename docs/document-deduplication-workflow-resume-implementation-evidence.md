# Document deduplication and workflow resume: implementation evidence

Prepared 2026-10-28 against
[the implementation plan](document-deduplication-workflow-resume-implementation-plan.md).

Repository implementation is available behind default-off flags. This is **not a production
release approval**: disposable PostgreSQL and real object-storage release checks remain blocked
by unavailable external resources. No shared database was migrated or backfilled.

## Migration-history recovery follow-up

A subsequent `alembic upgrade head` reported missing revision `a13d9e7b602c`.
A read-only transaction against Neon confirmed `alembic_version = a13d9e7b602c`,
the 18 question-bank column names defined by the original migration, and no
`document_workflows` or `document_content_claims` tables. No question text, account
records, credentials or other application data was retrieved. No shared schema/data
changes, migration, backfill or revision stamp were executed.

Recovered `a13d9e7b602c_add_summary_question_bank.py` byte-for-byte from commit
`c4ecaf1` on `feat/summary-generation-agent`. Neon stores the schema and Alembic
revision; the recovered Python source came from Git, not from Neon. This verifies
revision and column-name correspondence, not every PostgreSQL constraint/grant.

Added no-op merge revision `c92e6b4a710d` with parents `a13d9e7b602c` and
`f31a0d8c72e9`; both original parent revisions still descend from `e71c4a9b203d`.
The local application now has one head, **`c92e6b4a710d`**. From the observed Neon
revision, upgrading to this head applies the deduplication branch and merge without
rerunning the already-applied question-bank creation migration.

Alembic autogeneration excludes only the reflected, otherwise-unmapped
`rfp_question_bank` table while this checkout lacks the optional question-bank model.
This prevents proposing a destructive drop of an existing independent migration's
table. If its model is integrated later, ordinary comparison resumes. Other unmapped
tables remain detectable. No question-bank engine/model was implemented or changed.

Follow-up verification: 39 migration/schema regression tests passed in 63.01 seconds.
They cover clean upgrade/downgrade/re-upgrade, upgrades from either original branch,
populated question-bank row preservation, reverting only deduplication without dropping
the bank, the original populated-bank downgrade guard, one valid head, and continued
detection of other unexpected tables. `alembic heads` reports only `c92e6b4a710d`.
The recovered migration was checked byte-for-byte against Git. Backend/migration lint
and `git diff --check` passed. The isolated API/browser smoke was rerun against the
merged migration head: 1 passed, with `alembic check` reporting no model/schema drift.
Real PostgreSQL upgrade/role/RLS/provider verification remains a separate release gate;
the metadata inspection above does not satisfy it.

## Phase mapping and decisions

| Phase | Implementation and current evidence | Exit status |
| --- | --- | --- |
| 1. Contracts | `schemas/document_workflows.py`, `document_workflows` API, frontend types. Exact bytes, tenant-wide lookup, explicit original-project confirmation, selection for multiple histories. Committed stage is authoritative; optional per-user tab cursor/autosave is deferred as allowed by the plan. | Repository contract implemented. |
| 2. Schema | Additive revision `f31a0d8c72e9` follows actual head `e71c4a9b203d`. Fingerprints, claims, owned upload ledger, workflows, request keys, dispatch outbox, durable malware disposition; scoped FKs, revisions, immutable validation snapshot, forced tenant RLS and grants on new PostgreSQL tables. | SQLite upgrade/downgrade/re-upgrade and model drift check passed. Real PostgreSQL upgrade/RLS/FK gate remains open. |
| 3. Uploads | `document_content.py`, storage preparation, new and legacy upload routes. Backend validates and independently hashes bounded bytes before permanent writes. Unique claims use database time, renewable leases, owner fencing, and exact-key compensation. | Local repeat/rename, forged hash, key replay/conflict, pending owner, takeover, late owner, and injected storage failure checks passed. True PostgreSQL contention remains open. |
| 4. Recovery | `document_workflow_resume.py`, durable task publication, minimal summary/generation/validation/job/lifecycle hooks. Exact saved version/revision, explicit new generation/retry, late-worker guards, read-only resume, source release compatibility and newer processing attempts. | Targeted domain/API tests passed. External concurrent transition/deletion verification remains open. |
| 5. UI | Browser SHA-256 preflight, original-project notice, template choice, server-race fallback, saved-work listing, v1 hint migration and v2 workflow hints, server-driven stage routing, historical-output notice, exact validation WBS loading. | Browser coverage and isolated API/browser smoke passed. |
| 6. Backfill | Tenant-required bounded dry-run/apply CLI verifies trusted stored objects, reports integrity/missing/ambiguous/archive/deletion state, preserves duplicate rows, and recovers only explicit generation lineage. Cleanup and publication reconciliation are separate bounded commands. | Synthetic isolated legacy-copy tests passed. Target-environment copy rehearsal/backfill is not executed. |
| 7. Verification | Backend, migration, lint/build, contract browser, and isolated fullstack checks below. Opt-in real PostgreSQL tests are included. | Local verification recorded; external release gates remain open. |
| 8. Rollout | Flag order, maintenance and rollback instructions below. | Documented only. Deployment/enabling/live operations were prohibited by the request. |

The referenced agentic model files are absent in this checkout. Existing summary and WBS workers
remain placeholders. Their algorithms were not implemented or redesigned. Existing ingestion
release checks were extracted into a shared helper so recovery and explicit processing use the
same compatibility rules. Four existing migration-contract test constants were advanced to the
new head; earlier migration assertions remain intact.

## Implemented behavior

- Filename changes have no effect on identity; different bytes with the same name remain distinct.
  Browser preflight sends only digest/size/project. The server never trusts that digest as evidence
  of multipart content and never interprets a lookup failure as a new file.
- Direct/legacy uploads use the same claims. A live owner returns 202 with an opaque polling handle.
  Publication and the base workflow commit together. A losing/expired owner cannot publish a
  document or delete another owner's key. Owned attempts survive crashes for reconciliation.
- An accessible match preserves its document ID and original project. Multiple legacy documents
  or generation histories require a choice. Unindexed legacy rows fail closed until verified.
  Archived, deleting, known missing/integrity-failed and malware-rejected sources are unavailable.
  A known malware disposition survives document deletion.
- A workflow references its source run, summary revision, template identity, generation job,
  exact WBS version and validation revision. Generation snapshots include actual summary inputs.
  Later summary/template/processing changes mark compatibility changed; prior WBS edits remain
  viewable. Validation snapshots freeze the WBS tree/coverage and become stale after WBS edits.
- Summary and generation starts attach to existing attempts. Explicit regeneration uses a scoped
  request key and creates another recorded workflow; retry preserves the failed job. Publication
  failures remain pending in a durable outbox for bounded reconciliation. Resume GETs, component
  mounts and status refreshes create no jobs.
- Browser storage contains navigation hints rather than saved domain records. Project listing
  and content lookup recover without session storage. Optional exact-tab cursor and unsaved
  browser edits are outside the selected default. Existing empty projects are not deleted on a
  cross-project match.

## Checks actually executed

All database writes here used test-created SQLite databases or the isolated fullstack harness.
Tests set local object storage explicitly. No check used the application's shared Neon URL.

| Check | Result |
| --- | --- |
| Baseline workflow/PDF backend regression | 20 passed before implementation. |
| Initial new backend API/claim/backfill/migration suite | 14 passed; 3 opt-in PostgreSQL tests skipped. |
| Expanded recovery/backfill/lifecycle run | 17 passed, including owned deletion and retained threat disposition. |
| Backend authorization/migration integration | Permission dependency contract corrected; all migration expectations updated to the additive head. Full-suite result: **574 passed, 3 baseline failures, 9 skipped** in 147.86 seconds. All 19 new local feature tests passed. |
| `ruff check app tests` | Passed. |
| `git diff --check` | Passed. |
| Frontend lint | Passed. |
| Frontend production build | Passed. Restricted cache writes required a sandbox-permission rerun; no dependency or configuration changes were made to work around it. |
| Duplicate/resume/upload/deletion/workflow browser suite | 30 passed. Includes saved edits and historical-input notice. |
| Ingestion browser regression | 19 passed, 1 transient `RETRY_WAIT` display assertion failed in a 29-test run (the other 9 were new feature tests and passed). The failing assertion then passed alone on both the untouched baseline and the current code. It was not weakened or rewritten. |
| `npm.cmd run test:e2e:document-workflows:smoke` | 1 passed against real isolated API/browser, local object storage and freshly migrated SQLite. `alembic check` reported no new upgrade operations. First upload 201, legacy renamed upload 200 with same ID, preflight match, recovery after storage clearing, one document and no resume-created jobs. |
| Untouched-baseline comparison | Refresh-token replay, SSO state-cookie and embedding manifest checksum tests each reproduce their failures on archived HEAD source with the unchanged packaging inputs. Authentication and packaging code/config were left untouched. |

Final verification: `pytest -q --tb=short` finished with 574 passed, 3 failed, 9 skipped.
The failures are `test_auth.py::test_refresh_rotation_detects_replay_and_revokes_family`,
`test_sso.py::test_state_is_browser_bound_single_use_and_return_path_is_allowlisted`, and
`test_embedding_packaging.py::test_model_inventory_checksum_matches_release_configuration`;
all three reproduce on untouched baseline source. The nine skips include the three new opt-in
PostgreSQL tests and six existing environment-dependent tests. This is not an all-green
repository test claim.

After final browser request-key fallback changes (including missing `crypto.randomUUID`), all
10 feature browser tests passed again. Final frontend lint/build passed. Intermediate failures
above are retained to avoid presenting failed checks as passing.

## Configuration and maintenance runbook

No environment files were edited. Configure these through the deployment's normal configuration
mechanism only after the external release checks pass:

| Setting | Default | Purpose |
| --- | --- | --- |
| `DOCUMENT_WORKFLOW_RESUME_ENABLED` | `false` | Expose lookup/recovery and write durable workflow lineage. |
| `DOCUMENT_UPLOAD_REUSE_ENABLED` | `false` | Enforce verified content claims on both upload APIs; requires resume enabled. |
| `DOCUMENT_UPLOAD_LEASE_SECONDS` | `120` | Database-time lease, renewed during save; allowed range 15–3600. Measure target-provider upload duration before choosing a value. |

Deploy compatible schema/backend before frontend. Pause new uploads during the initial
backfill/enabling window: resume enabled with reuse disabled deliberately rejects new uploads,
while saved-work readers remain available. Complete tenant backfill and ambiguity review before
enabling reuse. A null verified fingerprint is not treated as a safe new-content result.

Commands below are examples for a separately configured **isolated copy**. They were not run
against any shared/live database. Run from `backend`, supply that copy's runtime/migration URLs
and object storage, and validate role separation using the repository's existing deployment checks.

```powershell
# Read-only by default. Continue with the returned next_cursor for further bounded batches.
.\.venv\Scripts\python.exe -m app.cli backfill-document-workflows --tenant-id <tenant-uuid> --batch-size 100
# Only after reviewing the dry run on the isolated copy:
.\.venv\Scripts\python.exe -m app.cli backfill-document-workflows --tenant-id <tenant-uuid> --batch-size 100 --apply --confirm APPLY_DOCUMENT_WORKFLOW_MAINTENANCE
# Use --after <next-cursor-uuid> for subsequent backfill pages; reruns are idempotent.
.\.venv\Scripts\python.exe -m app.cli reconcile-document-uploads --tenant-id <tenant-uuid> --batch-size 100
.\.venv\Scripts\python.exe -m app.cli reconcile-document-workflow-dispatches --tenant-id <tenant-uuid> --batch-size 100
# Both reconciliation commands also require --apply and the same explicit confirmation to write.
```

Cleanup defaults to a one-hour grace period and touches only keys in the owned-upload ledger,
after checking the claim owner and document references. It does not scan arbitrary objects for
deletion. Schedule tenant-bounded upload cleanup and pending-dispatch reconciliation with the
normal maintenance mechanism after release verification.

Backfill does not change document IDs, object keys, owners, summaries or WBS content. Missing,
corrupted or ambiguous inputs need operator review. Generation history without a recorded input
snapshot has unknown compatibility. A project-only WBS is never assigned to every document.

Metrics use bounded labels: `wbs_document_content_total`, `wbs_document_content_lookup_seconds`
and `wbs_workflow_resumes_total`. They contain no raw hashes, filenames, content or credentials.
Inspect HTTP/request correlation IDs and pending-dispatch/cleanup counts; do not add sensitive
values as metric labels. Provider latency, lease duration and browser hashing performance still
need measurement in the target environment.

Rollback keeps additive schema, claims and saved workflows. Pause new uploads by retaining
resume enabled and setting reuse disabled; lookup/readers remain available. Disable the new UI
separately if reverting frontend code, then reconcile pending owners and publications.
Do not restore a legacy uploader that ignores claims while uploads are in flight. Reverting to an
older backend requires a maintenance window and reconciliation, not table deletion.

## External blockers and remaining release prerequisites

1. No disposable PostgreSQL URL or local PostgreSQL/Docker binaries are available. Set
   `DEDUP_TEST_POSTGRES_URL` to a disposable database and
   `DEDUP_TEST_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE` to opt into
   `tests/test_document_content_claims_postgres.py`. These tests create/drop only a generated
   private schema and test actual contention/scoped FKs; the RLS test additionally requires
   `DEDUP_TEST_POSTGRES_RUNTIME_URL` for a restricted role. Never substitute the shared app URL.
2. Rehearse the actual Alembic PostgreSQL upgrade with the migration role and inspect all new
   table policies/grants with a restricted runtime role. SQLite and metadata-based PostgreSQL
   tests do not prove the PostgreSQL migration/grant path.
3. Verify real configured S3-compatible storage, bounded multipart uploads, latency/lease renewal,
   provider failures, interrupted publication, deletion races and cleanup under concurrent load.
   Local storage and injected failures have been checked; actual provider behavior has not.
4. Run bounded backfill against an isolated deployment copy, reconcile counts and ambiguous
   lineage, then obtain separate authorization for any shared-environment operation or rollout.
5. Existing summary/WBS placeholders, production ingestion dependencies and the unrelated
   baseline failures remain separate release concerns.

No `.env`, credentials, existing accounts, authentication/user-management implementation,
question bank, agentic engine or unrelated application data was modified. No migration/backfill
was applied to a shared database. No deployment, publication, commit or push was performed.
