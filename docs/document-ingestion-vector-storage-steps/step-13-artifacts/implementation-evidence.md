# Step 13 Implementation Evidence

## Status

- Repository implementation: complete for repository-controlled scope.
- External release verification: pending.
- Destructive retention/orphan cleanup: intentionally disabled pending approved policy values.

## Changed Files

Backend lifecycle and schema:

- `backend/app/models/domain.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/domain.py`
- `backend/migrations/versions/d4e7b2c91a63_add_document_deletion_lifecycle.py`
- `backend/app/api/routes/documents.py`
- `backend/app/services/document_lifecycle.py`
- `backend/app/services/dispatcher.py`
- `backend/app/worker.py`

Isolation and lifecycle enforcement:

- `backend/app/api/routes/ingestions.py`
- `backend/app/api/routes/helpers.py`
- `backend/app/api/routes/jobs.py`
- `backend/app/services/ingestion/repository.py`
- `backend/app/services/ingestion/orchestrator.py`

Maintenance and operations:

- `backend/app/services/document_maintenance.py`
- `backend/app/services/ingestion/workspace.py`
- `backend/app/services/storage.py`
- `backend/app/core/config.py`
- `backend/app/core/observability.py`
- `backend/app/cli.py`
- `backend/.env.example`
- `backend/README.md`
- `docs/document-ingestion-vector-storage-steps/step-13-artifacts/operations-runbook.md`

Frontend:

- `WBS_UI/src/App.tsx`
- `WBS_UI/src/services/documentsApi.ts`
- `WBS_UI/src/services/workflowTypes.ts`
- `WBS_UI/src/views/ProjectScreens.tsx`
- `WBS_UI/src/views/ProjectScreens.css`
- `WBS_UI/tests/workflow-mocks.ts`
- `WBS_UI/tests/document-deletion.spec.ts`

Focused tests and migration-head updates:

- `backend/tests/test_document_lifecycle.py`
- `backend/tests/test_document_lifecycle_contract.py`
- `backend/tests/test_ingestion_api.py`
- `backend/tests/test_database_config.py`
- Step 3, 10, and 11 migration-head assertions now expect `d4e7b2c91a63`.

## Migration

- Revision: `d4e7b2c91a63`
- Previous revision: `c8d4a1e72f09`
- Adds document lifecycle, deletion job/timestamps/error state, and a scoped durable deletion outbox.
- Enables and forces PostgreSQL RLS on the outbox with transaction-local `app.tenant_id` policy.
- Requires the deployment-provided restricted runtime role and grants only scoped CRUD.
- Downgrade is blocked when deletion dispatch or non-active lifecycle data exists. The release
  rollback path is a reviewed forward fix.

## Deletion Contract

1. Authorization and tenant scope are rechecked and the document row is locked.
2. Active ingestion is cancelled and its dispatch is dead-lettered.
3. The active pointer is cleared and every document chunk is removed in the initiation transaction.
4. The document becomes `DELETING`, vectors are marked hidden, and job/outbox records commit.
5. After commit, Celery receives only deletion job and document UUIDs.
6. The worker reloads trusted scope, validates the persisted generated object key, and deletes it
   idempotently.
7. Success scrubs object metadata and leaves a minimal `DELETED` tombstone. Failure never restores
   chunks or the active pointer.

Duplicate API requests return the existing deletion job. Duplicate worker delivery does not repeat
completed object cleanup. Storage outages use bounded jittered retry through the durable outbox.
Invalid persisted keys fail permanently with a stable state code.

## Retention and Reconciliation

- Retention is fail-closed and requires explicit bounded values for every policy category.
- Current/active runs are excluded at the query level.
- Bounded cleanup covers failed, cancelled, superseded, and malware processing runs; unreferenced
  terminal jobs; scrubbed tombstones; and stale workspaces.
- Tombstone cleanup removes residual summary/outbox state in scoped order and does not touch object
  storage, which must already be clean.
- Reconciliation reports missing objects, aged orphan objects, missing dispatch, stale processing,
  invalid counts, invalid active pointers, visible deleting vectors, and stuck deletion objects.
- Automatic repairs are disabled by default. Mutating CLI modes require exact confirmations.
- Orphan deletion requires both an approved repair invocation and the separately enabled age gate.
- Dead dispatches are reported, not automatically reset into an infinite retry loop.

## Security and Observability

- Deletion storage keys come only from persisted document state and must match the exact generated
  tenant/project/document key shape.
- Status responses exclude filenames, keys, content, vectors, broker IDs, endpoints, credentials,
  and raw errors.
- Audit events record only opaque tenant/document/job identifiers and event type.
- Metrics use allowlisted lifecycle, outcome, and finding labels only.
- Workspace cleanup reuses the verified child-of-root and symlink protections from Step 4.
- Project UI uses an explicit confirmation, represents `DELETING`, polls the deletion status, and
  removes a row only after `DELETED`.

## Repository Verification

Results recorded during this implementation:

- Focused deletion/API/migration/Step 11 tests: `21 passed`.
- Extended lifecycle/retention/reconciliation tests: `9 passed`.
- Migration clean install, upgrade with existing documents, `alembic check`, guarded downgrade, and
  forward-upgrade rehearsal: passed on isolated SQLite fixtures.
- Complete backend suite: `529 passed, 6 skipped` with no failures. The skips require isolated
  PostgreSQL/pgvector or other explicitly configured external dependencies.
- Ruff check: passed across `app`, `tests`, and `migrations`.
- Ruff formatting: `145 files already formatted` for active application/tests plus the new revision.
  A whole-history format scan also identifies two untouched historical migrations; they were not
  reformatted in Step 13.
- Python compile check: passed.
- Python dependency consistency (`pip check`): passed.
- Python vulnerability audit: failed with 59 advisories across five existing installed packages:
  `certifi`, `cryptography`, `pillow`, `pip`, and `pytest`. Constraint remediation is a release
  blocker outside the Step 13 scope.
- Frontend lint: passed.
- Frontend production build: passed.
- npm production dependency audit: `0 vulnerabilities`.
- Focused deletion Playwright: `3 passed`.
- Complete frontend Playwright suite: `74 passed`.
- Desktop deleting-state and mobile lifecycle screenshots were captured and inspected; the Step 13
  filename, status, confirmation, and action controls remained visible without overlap or overflow.
- `git diff --check`: passed; Git emitted only existing LF-to-CRLF worktree warnings.

SQLite, mocks, and browser route fixtures are repository evidence only.

## Pending External Gates

- Apply `d4e7b2c91a63` on an isolated Neon branch with the direct migration role.
- Verify outbox ownership, grants, forced RLS, missing tenant context, cross-tenant isolation, and
  absence of `BYPASSRLS` using the restricted pooled runtime role.
- Prove exact vector queries return no chunks immediately after deletion initiation.
- Exercise real private Neon object deletion, missing-object idempotency, and provider outage.
- Exercise non-eager Redis/Celery publication failure, restart, duplicate delivery, dead-letter, and
  recovery using release worker containers.
- Approve privacy/legal retention durations, malware/audit treatment, scheduler ownership, alert
  destinations, and the accidental-deletion restore policy.
- Measure deletion/reconciliation backlog and target-age alert thresholds in the release environment.
- Remediate and re-audit the existing Python dependency advisories before release.

## Residual Risks

- Retention and destructive orphan cleanup cannot be released until policy values and ownership are
  approved; both remain disabled.
- Repository tests cannot prove PostgreSQL RLS, row-lock concurrency, broker delivery, or object
  provider behavior.
- Durable deletion deliberately provides no application-level undo. Recovery requires the approved
  database/object-storage restore runbook and a reviewed forward fix.
