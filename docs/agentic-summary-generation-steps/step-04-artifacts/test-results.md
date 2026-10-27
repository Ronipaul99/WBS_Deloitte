# Step 4 executed verification

Date: 2026-10-27. Python 3.12.10, Windows AMD64. Existing packages include
cryptography 46.0.7, httpcore 1.0.9, httpx 0.28.1, AnyIO 4.15.1 and Pydantic
2.14.1. No dependency file or installed package was changed for Step 4.

## Final combined run

Executed from `backend` with process-only synthetic settings and the destructive
shared conftest disabled. `.env` loading is disabled for the regression process;
there is no application/Neon database fallback. PostgreSQL tests keep their own
explicit disposable URL/acknowledgment guard and skip before connecting when absent.

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
    'tests/test_database_config.py',
    '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

Actual result: **708 passed, 14 skipped, 13 warnings in 82.61s**; exit 0.
Independent collection confirmed **197 Step 4 tests** in the two new test modules.
The remaining passed tests cover the Step 1-3 implementation and relevant existing
configuration/ingestion/vector regressions. The 14 skipped tests are the opt-in
Step 2 PostgreSQL integration tests, not successful RLS/grant verification.

Warnings are the existing Alembic `prepend_sys_path`/missing `path_separator`
deprecations from ingestion/lifecycle/vector migration tests. They were preserved.

An earlier targeted run exposed the expected Step 1 fixture-serialization mismatch
after adding the empty `tool_results` default. Only the three request fixture
defaults and the two affected schema snapshot entries were refreshed. The final
combined run includes and passes the unchanged fixture-generation assertion.

## Established local coverage

- All three protocol payloads and all three existing output contracts; explicit
  token-limit dialects, temperature/schema support gates and native replay formats.
- Every registered tool, native and JSON actions, unknown/invalid tools and IDs,
  tool result/error replay, exclusive envelopes, local Pydantic validation and
  bounded schema projection including external-reference denial.
- Refusal, truncation, partial native output, malformed/duplicate/nonfinite JSON,
  absent/partial usage, cache tokens, returned model mismatch and oversized bodies.
- HTTP 400/401/403/404/422, 429/Retry-After integer/date handling, explicit transient
  retry policies, connect failures and ambiguous timeout-after-submit behavior.
- Shared attempt/token/deadline bounds, exactly one permitted format-repair request
  across the ledger, no retry of that repair, cancellation, stalled sleeps, late
  results and a server reporting token-ceiling violations. Unknown usage remains
  unknown while known per-attempt metadata remains available.
- Fresh credential resolution between attempts, rotation and revocation during
  retry/repair, tenant/connection receipt binding before any dial, current-key
  prompt/response exclusion and DEBUG diagnostic redaction.
- Probes for authentication, exact model access, schema, tools, small output limits,
  usage, temperature and timeouts. Candidate pending profiles remain pending;
  synthetic observations cannot become live qualification or enable profiles.
- Qualification fingerprints and probe-setting invalidation; explicit live-probe
  permit/expiry/configuration/cost admission denial without making a network call.
- Missing model lists, manual IDs, bounded single pages, malformed/oversized lists
  and refusal to follow returned URLs.
- Existing Step 3 URL/DNS/peer/TLS/header/redirect/rebinding/encryption/permission
  regressions and Step 1/2 contract/storage compatibility.

All protocol traffic, DNS, public numeric addresses and TLS stream behavior were
simulated. Tests use synthetic credentials and fixtures, not private documents or
real vendor accounts. No real certificate, Mac gateway, provider schema behavior,
PostgreSQL role, Linux ARM64 worker or production recovery result is claimed.

## Lint, formatting, dependencies and scope

Executed with the following file list:

```powershell
$step4Files = @(
  'app/services/llm/adapter_types.py',
  'app/services/llm/protocol_support.py',
  'app/services/llm/base.py',
  'app/services/llm/openai_provider.py',
  'app/services/llm/anthropic_provider.py',
  'app/services/llm/compatible_provider.py',
  'app/services/llm/registry.py',
  'app/services/llm/capabilities.py',
  'app/services/llm/contracts.py',
  'app/services/llm/secure_transport.py',
  'tests/llm_adapter_fixtures.py',
  'tests/test_llm_adapters.py',
  'tests/test_llm_capabilities.py'
)
.\.venv\Scripts\python.exe -m ruff check @step4Files
.\.venv\Scripts\python.exe -m ruff format --check @step4Files
.\.venv\Scripts\python.exe -m pip check
```

Results: Ruff lint passed, all thirteen Python files are formatted, and pip reported
**No broken requirements found**. `git diff --check` passed; Git emitted only LF/CRLF
normalization notices for affected existing files.

The pre-implementation SHA-256 inventory includes tracked and nonignored untracked
files, so pre-existing uncommitted work is protected independently of Git HEAD or
staging state. Compared with that inventory, only the four justified prerequisite
compatibility files, Step 4 document and index changed. Additions are the eight
Step 4 modules, three test files and five artifact documents. No inventoried file
was deleted. Models, migrations, permissions, config/dependencies, earlier artifact
documents, UI, ingestion/retrieval, Docker/Nginx and CI contents were preserved.

No `.env`, actual credentials, VM, hosted service or application database was
changed. No deployment, commit or push was performed. See
[remaining inputs](remaining-inputs.md) for unverified external gates.
