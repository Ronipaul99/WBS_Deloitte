# Step 7 verification results

Date: 2026-10-27. Final combined run: **829 passed, 24 skipped, 13 warnings in
218.23 seconds**. No final failures. All network generation/provider and application
database access were excluded. No dependency was installed or upgraded.

## Isolated backend regression command

From `backend`, using the existing virtual environment:

```powershell
@'
import os, pytest
os.environ.update(
    DATABASE_URL='sqlite+aiosqlite:///:memory:', DIRECT_DATABASE_URL='',
    AUTO_CREATE_TABLES='false', DOCUMENT_INGESTION_ENABLED='false',
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT='false', AGENTIC_SUMMARY_ENABLED='false',
    LLM_MANAGEMENT_ENABLED='false', LLM_CONNECTION_TESTS_ENABLED='false',
    LLM_SECURITY_ENABLED='false',
)
from app.core.config import Settings
Settings.model_config['env_file'] = None
raise SystemExit(pytest.main([
    '--noconftest',
    'tests/test_agent_evidence.py',
    'tests/test_agent_evidence_recovery.py',
    'tests/test_agent_evidence_postgres.py',
    'tests/test_agent_recovery.py',
    'tests/test_agent_outbox.py',
    'tests/test_agent_checkpoint_postgres.py',
    'tests/test_llm_management.py',
    'tests/test_llm_management_api.py',
    'tests/test_llm_management_postgres.py',
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
    'tests/test_hybrid_retrieval.py',
    'tests/test_document_chunking.py',
    'tests/test_summary_question_bank.py', '-q', '--tb=short',
]))
'@ | .\.venv\Scripts\python.exe -
```

The shared destructive `tests/conftest.py` was not loaded. Synthetic SQLite
databases use pytest temporary paths; backend/.test-data was not deleted or used.
The 24 skips are three Step 7, four Step 6, three Step 5 and fourteen Step 2
opt-in disposable PostgreSQL checks. No disposable credentials were supplied.
Warnings are existing Alembic path_separator deprecations, not suppressed failures.

## New Step 7 checks

- Completed source identity, current active run, source hashes/counts, canonical
  metadata and permission checks; tenant/project/document/run override attacks.
- Deterministic inventory root/chain, multi-page restore, missing/tampered pages,
  section pagination, invalid/foreign cursors and changed canonical text.
- Processing/lifecycle/hash/activation changes and authorization removal between
  reads; publication guard detects changed uncited chunks.
- Exact Unicode code-point ranges, emoji/combining text, altered quote/hash/page/
  scope, physical versus printed pages and conservative table/header row locators.
- Complete ordered primary partition, explicit context IDs without extra primary
  coverage, profile-dependent plans, shared overhead/headroom, blocked oversized
  or exhausted plans, empty-source refusal and source-loss warning propagation.
- Assigned/retrieved/delivered/processed distinction, wrong-input completion
  rejection and reading coverage remaining independent of retrieval operations.
- Existing ToolAction validation, unknown tools/scope fields, source prompt
  injection remaining plain data, bounded outputs and errors, repeated call-ID
  bypass rejection, safe diagnostics and definition absence uncertainty.
- Query embedding identity mismatch and SQLite search refusal; no fake test is
  described as a PostgreSQL vector-search success.
- Immutable step-page writes, seal-last crash recovery, replay equality, foreign
  descriptor rejection, cross-tenant/requester denial, stale fences, cancelled
  reads, durable allowance reconstruction/cancellation and guarded downgrade.

Tests use synthetic qualification-shaped model snapshots only as deterministic
inputs. They never persist/promote live capabilities or enable a connection.
Later analyst completion receipts are controller primitives; no real analyst,
provider, graph handler or summary generation was invoked.

An initial run found an inherited schema_version field being incorrectly projected
onto a SQL processing row. It was excluded explicitly. A small-context test's
expectation was corrected to allow valid additional smaller batches, and citation
row precision was made conservative for repeated context headers. The final run
includes those fixes; initial failures were not reported as successful evidence.

## Local private-RFP check

Read-only historical local artifacts were available. The 110-page PDF's actual
file hash matches the historical canonical export. All 161 exported descriptors
passed Step 7 source/reference validation and formed a valid six-page inventory
chain. Exported source/run ownership and primary counts were checked.

The newer quality audit reports 391 chunks, without a matching full canonical
chunk export used in this check. This is **not** current database activation,
latest-run coverage, vector-component verification or RLS qualification. Original
tokenizer-dependent chunker digests were retained, not independently recomputed.
Separate text/metadata hashes were computed from the canonical export.

Raw hashes, identifiers, vectors and extracted text remain ignored. The sanitized
local result is `backend/.data/step07-local-rfp-audit.json`; no private fixture was
added to Git. No configured database or cloud object was accessed.

## Static and compatibility checks

- Ruff check and format-check cover the 17 new/affected implementation, migration
  and evidence-test files. Existing head-assertion files are checked separately.
- `python -m pip check`: no broken requirements.
- Isolated evidence import: app.db.session is absent from sys.modules; no
  configured session/engine is initialized by the reused retrieval helpers.
- Final diff review compares against the initial checkout snapshot; existing
  question-bank implementation/data and unrelated changes are preserved.
- No frontend code changed, so frontend build/browser tests were not repeated.
- No old migration, embedding, ingestion behavior, credentials, environment,
  deployment or live VM changed.

Local logs: `backend/.data/step07-regressions-final.log`. SQLite/fake success does
not establish PostgreSQL grants/RLS/vector behavior, concurrent recovery, actual
tokenizer/provider capacity or ARM64 worker performance. See
[remaining inputs](remaining-inputs.md).
