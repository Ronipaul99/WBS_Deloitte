# Step 3 verification results

Date: 2026-10-27. Local runtime: Python 3.12.10, Windows AMD64.
Installed versions: cryptography 46.0.7, httpcore 1.0.9, httpx 0.28.1,
AnyIO 4.15.1, Pydantic 2.14.1, pydantic-settings 2.15.0.

## Final combined regression execution

From `backend`, the following command was executed. Environment changes exist only
in this test process. Disabling automatic `.env` loading avoids using application
credentials; the existing shared `tests/conftest.py` was not loaded. Synthetic
in-memory SQLite connections and pytest temporary directories are used locally.
The PostgreSQL tests require their own explicit disposable inputs and otherwise
skip before creating any database connection.

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
from app.core.config import Settings
Settings.model_config['env_file'] = None
raise SystemExit(pytest.main([
    '--noconftest',
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
    'tests/test_database_config.py',
    '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

Actual final result: **511 passed, 14 skipped, 13 warnings in 46.57s**; exit 0.
This includes 155 Step 3 tests. The 14 skips are the opt-in Step 2 PostgreSQL tests:
fresh disposable migration/runtime URLs and acknowledgment were not configured.
The warnings are existing Alembic `prepend_sys_path`/`path_separator` deprecations
in ingestion/lifecycle/vector migration tests. They were not changed in this step.

During development, synthetic fixture issues (missing fake ALPN metadata, a wrong
fixture profile UUID, and an overly long Windows parameter ID) were corrected.
Final review added purpose checks to direct service authorization and cleanup of
streams cancelled/failed during TLS before pool ownership. The combined suite was
rerun after these behavior changes; no test failure is left unresolved.

## Coverage established locally

- AES-GCM roundtrip, 100 fresh nonce samples, altered ciphertext/nonce, truncated
  envelopes, tenant/connection/credential/version AAD changes, and aliased-key-label
  tampering. Key rotation, missing/lost keys, restored keys, bounded/duplicate JSON
  key-ring parsing and secret-file input checks use ephemeral synthetic keys only.
- Explicit preserve/replace/rotate/clear/disable semantics, omitted versus null and
  empty input, atomic failed rotation, keyless emergency revocation, write-only
  schemas, controlled validation errors and metadata-only audit/response records.
- Synthetic scoped persistence with SQLite foreign keys, manager/editor/viewer and
  cross-tenant access, current membership/user checks, pinned model-profile/endpoint
  preservation, same-connection credential versioning, and per-write revalidation.
- Public/private IPv4/IPv6 and alternate representations, mapped/transition IPv6,
  metadata/loopback/link-local denial, mixed DNS answers, answer limits, rebinding,
  exact operator gateway host/port/path/purpose/auth approval and prefix bypasses.
- Real httpcore HTTP/1.1 parsing over an in-memory fake wire backend: numeric-IP
  dialing, checked actual-peer metadata, original-host TLS/SNI settings, absence of
  proxy/redirect/retry behavior, registered headers, pre-write rotation/revocation,
  bounded request/response/chunked/header sizes, invalid JSON and secret reflection.
- Connect/read/total timeout and cancellation paths, certificate-error sanitization,
  TLS-setup resource cleanup, and DEBUG log-record redaction including exceptions
  and arbitrary extra fields. TLS handshakes themselves are simulated.
- Step 1 contracts/LangGraph SQLite spike, Step 2 schema/permissions/migration
  compatibility and existing database configuration/ingestion/vector regressions.

## Lint, formatting and dependencies

Executed against the seven new security modules, three new test files and config:

```powershell
$step3Files = @(
  'app/services/llm/credentials.py',
  'app/services/llm/credential_service.py',
  'app/services/llm/endpoint_policy.py',
  'app/services/llm/errors.py',
  'app/services/llm/redaction.py',
  'app/services/llm/security_config.py',
  'app/services/llm/secure_transport.py',
  'tests/llm_security_fixtures.py',
  'tests/test_llm_credentials.py',
  'tests/test_llm_endpoint_policy.py'
)
.\.venv\Scripts\python.exe -m ruff check @step3Files app/core/config.py
.\.venv\Scripts\python.exe -m ruff format --check @step3Files
.\.venv\Scripts\python.exe -m ruff format --check --range 53-59 app/core/config.py
.\.venv\Scripts\python.exe -m pip check
```

Results: Ruff lint passed; ten new files and the added config range are formatted;
`pip check` reported **No broken requirements found**. Existing unrelated config
formatting was preserved. The direct httpcore declaration matches the version
already installed; no package install or unrelated upgrade was performed.

`git diff --check` passed (Git also reported its existing LF-to-CRLF notice for
the pre-existing `deploy/oracle/README.md` change).

## Final scope review

A SHA-256 inventory of tracked and nonignored untracked files was saved before
implementation, then compared with the final checkout. Pre-existing modified and
untracked files were included, rather than comparing only against Git HEAD.

Only these pre-existing files changed relative to that inventory:

- `backend/app/core/config.py`: six Step 3 setting/comment lines only.
- `backend/pyproject.toml`: direct httpcore dependency only; existing LangGraph
  optional dependencies retained.
- `docs/agentic-summary-generation-steps/README.md`: Step 3 status/evidence link.
- `docs/agentic-summary-generation-steps/step-03-credentials-endpoint-security.md`:
  implementation status and links; unqualified exit checkboxes remain unchecked.

Additions are exactly the seven security modules, three test files, and five
Step 3 artifact documents listed in [implementation evidence](implementation-evidence.md).
No initial inventoried file was deleted. Step 1/2 implementations, contracts,
fixtures, migration and artifacts retain their original hashes. Pre-existing
UI, ingestion, deployment, Docker/Nginx and permission changes were not altered.
`backend/.env` and actual credentials were not edited. The destructive shared
conftest and configured application database were not used.

No PostgreSQL RLS/grant/concurrency, actual HTTPS certificate, real gateway,
provider inference, ARM64 VM or deployed recovery result is claimed. See
[remaining inputs](remaining-inputs.md) for those gates.
