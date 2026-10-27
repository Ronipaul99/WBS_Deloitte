# Step 2 verification results

Date: 2026-10-27. Local Python 3.12.10 / Windows AMD64, pytest 8.4.2,
Pydantic 2.14.1 and Ruff 0.17.0. No database service or dependency was installed.

## Final combined verification

Result: **278 passed, 14 skipped, 13 warnings in 41.10 seconds**, exit code 0.
The 14 skips are the explicit disposable PostgreSQL integration cases. They are
not passes. The warnings are the existing Alembic `path_separator` deprecation
emitted by historical migration tests; no CI/config change was made to silence them.

Run from `backend` using the following process-local settings. They neither edit
`.env` nor point to application data. Existing migration regressions independently
set their own temporary SQLite paths. New storage tests never import app settings.

```powershell
@'
import os, pytest
os.environ.update(
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT='false',
    DOCUMENT_INGESTION_ENABLED='false',
    DATABASE_URL='sqlite+aiosqlite:///:memory:',
    DIRECT_DATABASE_URL='',
    AUTO_CREATE_TABLES='false',
)
raise SystemExit(pytest.main([
    '--noconftest',
    'tests/test_agent_schema.py',
    'tests/test_llm_permissions.py',
    'tests/test_agent_schema_postgres.py',
    'tests/test_agent_contracts.py',
    'tests/test_agent_checkpointer_spike.py',
    'tests/test_pgvector_schema.py',
    'tests/test_ingestion_orchestration_contract.py',
    'tests/test_document_lifecycle_contract.py',
    'tests/test_vector_persistence_contract.py',
    '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

The final set comprises 56 Step 2 local tests, 188 unchanged Step 1 tests and 34
historical migration/vector/deletion regression tests. The existing shared
`tests/conftest.py` was not loaded: it imports the application and deletes
`backend/.test-data` at session end. Existing user uploads were not used or removed.
No broad application/UI end-to-end suite was run.

## Actual local evidence

- Admin/editor/viewer/unknown-role matrix and matching frontend permission names.
  Model use also requires summary-update permission. Repositories recheck active
  membership and use explicit tenant/source/run predicates in an explicit transaction.
- Foreign-key rejection of cross-tenant credential references; bound checkpoint
  denial, viewer-use/editor-audit denial and tenant-scoped legacy reads.
- Typed/size/nesting/finite JSON checks and forbidden secret/transcript/reasoning fields.
  Fixture profiles cannot be enabled as live-qualified models.
- Immutable revisions/profile versions/checkpoints/evidence/approval history and
  completed steps; canonical quote/hash/claim/revision binding on evidence writes.
- Duplicate checkpoint, step and outbox identities; optimistic active-pointer and
  approval versioning; stale source rejection and unchanged generated revision text.
- Full historical SQLite upgrade followed by new migration up/down/up; Alembic
  version stamping; exact legacy text/approval/origin preservation and unchanged
  documents, processing-run records, chunk contents and stored 384-value embeddings.
- Empty-schema downgrade recovery and refusal to downgrade populated agent storage.
  Existing Alembic `command.check` confirms migrated SQLite schema matches metadata.
- Emitted SQL assertions cover FORCE/ENABLE RLS, WITH CHECK policies, scoped GUCs
  and all new protected tables. These assertions do not execute PostgreSQL SQL.

During development, isolated historical tests initially inherited incompatible
ingestion flags from local configuration. The process-local overrides above fixed
test isolation. A missing test import was fixed and its case rerun before the final
combined passing run. Failed development runs are not counted as passing evidence.

## Static/frontend/dependency checks

Ruff `check` on all changed/new Python implementation and test files: **passed**.
Ruff `format --check` on the 16 implementation/new-test Python files: **passed**.
The six historical test files retain their existing formatting and change only
the expected application migration head.

From `WBS_UI`:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit --project tsconfig.app.json
.\node_modules\.bin\eslint.cmd src/auth/permissions.ts
```

Both returned exit code 0. No UI components or flows were changed.
`backend/.venv/Scripts/python.exe -m pip check` returned
**No broken requirements found**. No dependency manifests/locks changed in Step 2.

Final diff/whitespace/link and starting-snapshot hash checks confirm only Step 2
files and necessary migration-head test expectations changed. Step 1 code/artifacts,
unrelated deployment edits and the master/later-step plans were preserved. No file
from the starting snapshot was deleted.

## Unverified release gates

No disposable PostgreSQL target was available. The opt-in suite requires explicit
separate URLs, disposable acknowledgement, a `wbs_step02_` database name, and an
empty public schema. It includes runtime-role RLS/grants, raw SQL negative tests,
pointer/audit triggers, source/vector preservation, wrong-scope linking, duplicate
identities, context reset and guarded downgrade. These 14 cases remain **skipped**.

No live API/provider calls, worker/ARM64 build, VM access, application DB migration,
deployment, credentials/encryption qualification or production checkpointer test
was performed. See [remaining inputs](remaining-inputs.md).
