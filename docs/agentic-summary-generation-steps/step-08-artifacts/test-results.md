# Step 8 test results

Date: 2026-10-27. Local/synthetic evidence only. No real provider or application
database was contacted, and no feature was enabled.

## Final results

- Combined final run: **854 passed, 26 skipped, 13 warnings in 267.75 seconds**.
- Step 8 subset: **33 passed, 2 skipped**.
- Skips: disposable PostgreSQL checks for Steps 2 (14), 5 (3), 6 (4), 7 (3),
  and 8 (2). No PostgreSQL/RLS/concurrent-recovery pass is claimed.
- Warnings: 13 existing Alembic `path_separator` deprecations in ingestion,
  lifecycle and vector-persistence migration regressions.
- Ruff lint passed for all 16 changed/new Python files; Ruff formatting check
  passed for the same 16 files.
- `python -m pip check`: **No broken requirements found**. No dependency changed.
- Import isolation: importing `app.services.agents.nodes.analyst_nodes` does not
  import `app.db.session` or `app.core.config` or create configured DB/settings.
- Step 8 generated schema snapshot matches the current contract definitions.
- Initial-baseline hash comparison: exactly nine intended existing files changed;
  all other 519 baseline files retained their initial hashes. New files are
  confined to Step 8 implementation, tests and artifacts.
- `git diff --check`: passed; existing Git LF/CRLF conversion warnings only.

Development runs caught fixture API/cleanup mismatches, a test policy-rebinding
mistake and a reflected-synthetic-secret test that correctly stopped at the
transport boundary before unknown-action validation. Fixtures were corrected;
production secret filtering, replay binding and security checks were not weakened.
The final combined run above includes the corrected tests with no failures.

## Coverage demonstrated locally

Fake checked-IP/TLS network backends exercise the actual OpenAI Responses native
and compatible JSON-action mappings. Tests cover canonical quotes, Unicode,
no-facts outcomes, refusal/truncation, malformed results, shared repair ceilings,
registered tools, injection/foreign arguments, repeated actions, credential
rotation/revocation, cancellation during calls and ambiguous timeout accounting.

Register tests cover reordered model IDs, stable identity and REQ codes, aliases,
repeated source mentions with retained citations, distinct EMD options and
conditions, total/per-unit capacity, table clauses, contradictory dates, unknown
issuer/date categories, unresolved flags, 120-requirement pagination, hash-chain
validation and explicit aggregate/individual overflow.

Disposable SQLite recovery tests use the existing store, checkpoints and tool
ledger. They inject failure before checkpoint/continuation completion, verify
rollback of the extraction/receipt, duplicate fencing, reconstruction, completed
batch reuse, incompatible policy rejection, all-batch coverage, no-facts seals,
lease expiry/cancellation and an unavailable gap search whose allowance/attempt
survives continuation. SQLite is not PostgreSQL RLS or concurrency evidence.

Steps 1–7 regressions include contracts, schemas, permissions, encryption, endpoint
security, provider mappings/capabilities, durable orchestration, management APIs,
pinned evidence, question-bank reads, ingestion/lifecycle/vector contracts,
legacy database behavior and existing hybrid retrieval.

## Reproduction

From `backend` in PowerShell, using the existing virtual environment. This runner
turns off `.env` loading and excludes the destructive shared conftest:

```powershell
@'
import os, pytest
os.environ.update(
    DATABASE_URL='sqlite+aiosqlite:///:memory:', DIRECT_DATABASE_URL='',
    AUTO_CREATE_TABLES='false', DOCUMENT_INGESTION_ENABLED='false',
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT='false', LLM_SECURITY_ENABLED='false',
    AGENTIC_SUMMARY_ENABLED='false', LLM_MANAGEMENT_ENABLED='false',
    LLM_CONNECTION_TESTS_ENABLED='false',
)
from app.core.config import Settings
Settings.model_config['env_file'] = None
raise SystemExit(pytest.main([
    '--noconftest',
    'tests/test_evidence_analyst.py',
    'tests/test_evidence_analyst_recovery.py',
    'tests/test_evidence_analyst_postgres.py',
    'tests/test_agent_evidence.py',
    'tests/test_agent_evidence_recovery.py',
    'tests/test_agent_evidence_postgres.py',
    'tests/test_agent_contracts.py',
    'tests/test_agent_checkpointer_spike.py',
    'tests/test_agent_schema.py',
    'tests/test_agent_schema_postgres.py',
    'tests/test_llm_credentials.py',
    'tests/test_llm_endpoint_policy.py',
    'tests/test_llm_permissions.py',
    'tests/test_llm_adapters.py',
    'tests/test_llm_capabilities.py',
    'tests/test_agent_recovery.py',
    'tests/test_agent_outbox.py',
    'tests/test_agent_checkpoint_postgres.py',
    'tests/test_llm_management.py',
    'tests/test_llm_management_api.py',
    'tests/test_llm_management_postgres.py',
    'tests/test_summary_question_bank.py',
    'tests/test_pgvector_schema.py',
    'tests/test_ingestion_orchestration_contract.py',
    'tests/test_document_lifecycle_contract.py',
    'tests/test_vector_persistence_contract.py',
    'tests/test_database_config.py',
    'tests/test_hybrid_retrieval.py',
    '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

The opt-in PostgreSQL module requires the separately provisioned disposable
inputs described in [remaining inputs](remaining-inputs.md). No cloud/application
URL is substituted if they are missing. The dedicated Step 8 PostgreSQL checks
were collected and skipped, not run successfully.

Raw local run XML and initial baseline hashes/status are under ignored
`backend/.data/step08-work/`; no private source text or provider transcripts are
part of public verification evidence.
