# Step 13 Document Lifecycle Operations Runbook

## Safety Posture

- Document deletion is asynchronous and irreversible at the application layer.
- The first committed transaction hides vectors before object cleanup is dispatched.
- Never restore `current_processing_run_id`, chunks, or vector visibility automatically.
- Retention and orphan cleanup are disabled until privacy/legal durations and operator ownership are
  approved outside the repository.
- Use the direct migration role only for Alembic. Use the restricted pooled runtime role for API,
  worker, and reconciliation checks.

## Deployment Sequence

1. Create an isolated Neon branch from the intended release baseline.
2. Set the direct migration credential through secret management and run `alembic upgrade head`.
3. Verify revision `d4e7b2c91a63`, the lifecycle constraints, the deletion outbox grants, and
   `ENABLE/FORCE ROW LEVEL SECURITY`.
4. Verify the runtime role does not own the outbox, has no `BYPASSRLS`, and cannot cross tenants.
5. Start the non-root Celery worker and scheduler with non-eager execution.
6. Exercise a synthetic deletion through the API, interrupt the worker after object deletion, and
   prove a repeated delivery completes the tombstone without restoring vector visibility.
7. Verify project lists retain `DELETING` documents and omit `DELETED` tombstones.

## Normal Commands

```powershell
# Safe report only
python -m app.cli reconcile-document-lifecycle --tenant-id TENANT_UUID

# Explicitly approved bounded repair
python -m app.cli reconcile-document-lifecycle --tenant-id TENANT_UUID `
  --repair --confirm APPLY_DOCUMENT_REPAIRS

# Recover pending/stale deletion dispatches
python -m app.cli recover-document-deletions --tenant-id TENANT_UUID

# Retention report only
python -m app.cli run-document-retention --tenant-id TENANT_UUID

# Approved retention execution
python -m app.cli run-document-retention --tenant-id TENANT_UUID `
  --execute --confirm APPLY_DOCUMENT_RETENTION
```

Omitting `--tenant-id` performs a bounded global pass and requires the same operational approval as
the tenant-specific command. Reports contain counts and stable categories only.

## Retention Enablement

Keep `DOCUMENT_RETENTION_ENABLED=false` until all seven policy periods are approved and recorded:

- failed processing runs;
- cancelled processing runs;
- superseded completed runs;
- terminal jobs;
- malware events;
- document tombstones;
- stale temporary workspaces.

Keep `DOCUMENT_ORPHAN_CLEANUP_ENABLED=false` until the managed prefix, minimum object age, backup
coverage, and operator approval process are verified. A repair command and the enabled flag are both
required before an orphan object can be deleted.

## Alerts

Alert on these low-cardinality conditions:

- `deleting_vectors` is nonzero;
- `deleting_object` remains nonzero beyond the deletion target age;
- deletion dispatch or cleanup reaches its maximum attempt count;
- `invalid_active_run`, `invalid_counts`, `ownership`, or `missing_object` is observed;
- orphan or stale-workspace backlog grows between bounded passes;
- scheduled recovery/reconciliation has no recent successful run.

Do not attach filenames, object keys, document hashes, tenant content, vectors, endpoints,
credentials, or raw exceptions to alerts.

## Incident Handling

1. Disable new delete requests at the edge if deletion initiation is defective.
2. Continue safe recovery for documents already committed as `DELETING`; do not expose them.
3. Run reconciliation in dry-run mode and preserve its sanitized count report.
4. Resolve object-store, Redis, worker, or database availability before an approved repair pass.
5. Leave dead dispatches dead until the underlying incident is understood; do not create an
   unbounded retry loop.
6. For accidental deletion, follow the approved Neon and object-storage restore process, validate
   tenant/project/document ownership, and use a reviewed forward-fix. Never manually reactivate a
   stale run or vector set.

## Rollback

The migration downgrade refuses to proceed while any deletion dispatch or non-active lifecycle
state exists. Do not force a rollback that drops active cleanup state. Disable initiation, finish or
repair hidden deletions, and deploy a reviewed forward migration when data exists.
