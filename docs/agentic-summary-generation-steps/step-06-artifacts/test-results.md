# Step 6 test results

Date: 2026-10-27. Synthetic/local evidence only. No provider or application database
was contacted. No feature was enabled. No new dependency was installed.

Installed versions observed during verification: Python 3.12.10, FastAPI 0.143.0,
Pydantic 2.14.1, SQLAlchemy 2.1.4, Alembic 1.20.0, cryptography 46.0.7,
httpcore 1.0.9, Celery 5.6.3, LangGraph 1.2.18, pytest 8.4.2 and Ruff 0.17.0.

## Backend

Final combined run: **780 passed, 21 skipped, 13 warnings in 161.74 seconds**.
The skips are opt-in disposable PostgreSQL checks: four Step 6, three Step 5 and
fourteen Step 2. Warnings are existing Alembic `path_separator` deprecations.
There were no failures in the final run.

The exact PowerShell runner, from `backend`, excludes the application's `.env`
and the destructive shared `tests/conftest.py`:

```powershell
@'
import os, pytest
os.environ.update(
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT='false',
    DOCUMENT_INGESTION_ENABLED='false',
    DATABASE_URL='sqlite+aiosqlite:///:memory:',
    DIRECT_DATABASE_URL='', AUTO_CREATE_TABLES='false',
    LLM_SECURITY_ENABLED='false', AGENTIC_SUMMARY_ENABLED='false',
)
from app.core.config import Settings
Settings.model_config['env_file'] = None
raise SystemExit(pytest.main([
    '--noconftest',
    'tests/test_llm_management.py',
    'tests/test_llm_management_api.py',
    'tests/test_llm_management_postgres.py',
    'tests/test_agent_recovery.py',
    'tests/test_agent_outbox.py',
    'tests/test_agent_checkpoint_postgres.py',
    'tests/test_llm_adapters.py',
    'tests/test_llm_capabilities.py',
    'tests/test_llm_credentials.py',
    'tests/test_llm_endpoint_policy.py',
    'tests/test_agent_schema.py',
    'tests/test_llm_permissions.py',
    'tests/test_agent_schema_postgres.py',
    'tests/test_agent_contracts.py',
    'tests/test_agent_checkpointer_spike.py',
    'tests/test_pgvector_schema.py',
    'tests/test_ingestion_orchestration_contract.py',
    'tests/test_document_lifecycle_contract.py',
    'tests/test_vector_persistence_contract.py',
    'tests/test_database_config.py', '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

Step 6 coverage includes credential preservation/replace/clear/rotation/disable,
permission and cross-tenant denial, safe API validation/errors, missing keys,
optimistic updates, forged capability rejection, immutable versions, default
uniqueness, document-free request/job atomic rollback, ID-only delivery,
duplicate claims/publication, durable budget exhaustion/reconstruction,
ambiguous worker loss, permission/configuration/permit invalidation, credential
changes fencing attempts, terminal history, migration up/down/up with legacy
vectors and downgrade refusal with test history. Worker task-owned connections
and disabled behavior are covered without a real worker.

Synthetic probe integration uses controlled DNS/transport and asserts no SQL
access to documents/chunks/processing runs. A fake success cannot qualify or
enable a live model. The default unique-index test deliberately uses temporary
SQLite raw updates to exercise the constraint; it fabricates no live capability,
and the same profile still fails API qualification and usable-catalog checks.

An earlier migration-diff test exposed a missing SQLite qualification foreign
key; the additive migration was corrected and the final schema checks pass.
An added uniqueness test initially hit the stronger ORM qualification guard;
the constraint-specific test now uses raw temporary-database updates as described.
These initial failures are not counted as successful qualification evidence.

## Browser, TypeScript and build

Final Playwright run: **27 passed in 29.3 seconds**, including seven new AI Models
checks plus account, authorization and member-administration regressions:

```powershell
# Start a local test server with the existing e2e mode.
node.exe node_modules/vite/bin/vite.js --configLoader runner --mode e2e --host 127.0.0.1 --port 5176
# In a second terminal, from WBS_UI:
npx.cmd playwright test tests/ai-model-settings.spec.ts tests/account-settings.spec.ts tests/authorization.spec.ts tests/member-administration.spec.ts --output ../backend/.data/step06-playwright-final
```

New checks exercise omitted-secret preservation, explicit transient replacement,
cancel/reload and tenant switching, manual IDs, supported controls, cost consent,
accessible worker progress/unavailability, unqualified enable rejection,
editor/viewer navigation/direct-route denial, browser storage exclusion and no
unhandled page errors. All API traffic is intercepted with synthetic fixtures;
no provider or live backend is used. An initial selector incorrectly requested a
button instead of the existing `menuitem`; the test locator was fixed. An aborted
refresh's unhandled rejection was fixed in the screen and is now asserted absent.

Passed final TypeScript checks and Vite production build:

```powershell
node.exe node_modules/typescript/bin/tsc -p tsconfig.app.json --tsBuildInfoFile ../backend/.data/step06-tsc-app.tsbuildinfo
node.exe node_modules/typescript/bin/tsc -p tsconfig.node.json --tsBuildInfoFile ../backend/.data/step06-tsc-node.tsbuildinfo
node.exe node_modules/vite/bin/vite.js build --configLoader runner --outDir ../backend/.data/step06-ui-build
npm.cmd run lint
```

The normal npm build and default Playwright web-server command encountered Windows
EPERM writes under existing `node_modules/.tmp`/`.vite-temp`. The commands above
use writable ignored build-info/output paths and Vite's runner config loader.
Project configuration/permissions were not changed. Vite 8.3.3 transformed 1,954
modules; final main JS was 404.15 kB. The outside-project output warning is expected;
the output was intentionally kept under ignored `backend/.data`.

## Static and scope checks

- Ruff check and format-check passed on all 16 directly affected Python
  implementation/test/migration files.
- `python -m pip check`: no broken requirements.
- `npm.cmd run lint`: passed.
- Targeted `git diff --check`: passed (line-ending normalization notices only).
- New worker/test modules were inspected for source-document readers; none exist.
- New UI modules contain no local/session storage, console logging or provider
  VITE-secret configuration. Browser tests inspect actual storage contents.
- Built JS inspection found no synthetic replacement-key marker or LLM VITE
  API-key configuration. This is a targeted leak check, not a universal proof
  about arbitrary dependencies or pre-existing application code.
- Initial-checkout comparison and shared-file diff review are recorded in
  [scope review](scope-review.md) and [manifest](scope-manifest.json).

Ignored local logs are `backend/.data/step06-backend-final.log` and
`backend/.data/step06-playwright-final.log`. These are local convenience artifacts;
this document records the sanitized results needed for review.

PostgreSQL RLS/grants/locking, real TLS/provider compatibility, positive live
worker qualification and deployed recovery remain unverified. See
[remaining inputs](remaining-inputs.md); mocked success establishes none of them.
