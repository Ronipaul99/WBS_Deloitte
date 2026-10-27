# Step 5 verification results

Date: 2026-10-27. Tests used only synthetic data and disposable pytest SQLite
files. No real provider, broker, application/Neon DB or live worker was contacted.

## Actual results

| Check | Result |
| --- | --- |
| Final Step 5 focused suite | **43 passed, 3 skipped**, 62.05 seconds |
| Combined Step 5 and Steps 1-4/ingestion/vector/config regressions | **748 passed, 17 skipped**, 13 existing Alembic configuration warnings, 135.40 seconds |
| Supplemental durable receipt/real-adapter integration check after receipt-scope hardening | **3 passed**, 33 deselected |
| Ruff lint, all changed Python code/tests | Passed |
| Ruff formatting check, 27 implementation/test files | Passed |
| `python -m pip check` | No broken requirements found |

The combined run preceded the final SQL routing adapter, ID-only Celery adapter
and receipt-isolation test additions. The final focused suite includes those
changes. Counts overlap and must not be added together. All three skipped Step 5
tests and the 14 prerequisite skips require disposable PostgreSQL provisioning;
none are counted as successful RLS/concurrency evidence.

Installed versions inspected: LangGraph 1.2.18, langgraph-checkpoint 4.3.1,
Pydantic 2.14.1, SQLAlchemy 2.1.4, Celery 5.6.3, Ruff 0.17.0. Existing pins were
reused; no package installation or upgrade occurred.

## Focused command

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest --noconftest tests/test_agent_recovery.py tests/test_agent_outbox.py tests/test_agent_checkpoint_postgres.py -q --tb=short
```

No shared `tests/conftest.py` was loaded. Its destructive `.test-data` cleanup
was not used. Temporary databases are pytest-owned; no application settings or
configured database URL are used by these new fixtures.

## Combined regression invocation

The combined run explicitly disabled `.env` loading and used an in-memory
database configuration before importing tests that inspect application settings:

```python
import os
import pytest

os.environ.update(
    DOCUMENT_INGESTION_LOCAL_DEVELOPMENT="false",
    DOCUMENT_INGESTION_ENABLED="false",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    DIRECT_DATABASE_URL="",
    AUTO_CREATE_TABLES="false",
    LLM_SECURITY_ENABLED="false",
    AGENTIC_SUMMARY_ENABLED="false",
)
from app.core.config import Settings
Settings.model_config["env_file"] = None

raise SystemExit(pytest.main([
    "--noconftest",
    "tests/test_agent_recovery.py",
    "tests/test_agent_outbox.py",
    "tests/test_agent_checkpoint_postgres.py",
    "tests/test_llm_adapters.py",
    "tests/test_llm_capabilities.py",
    "tests/test_llm_credentials.py",
    "tests/test_llm_endpoint_policy.py",
    "tests/test_agent_schema.py",
    "tests/test_llm_permissions.py",
    "tests/test_agent_schema_postgres.py",
    "tests/test_agent_contracts.py",
    "tests/test_agent_checkpointer_spike.py",
    "tests/test_pgvector_schema.py",
    "tests/test_ingestion_orchestration_contract.py",
    "tests/test_document_lifecycle_contract.py",
    "tests/test_vector_persistence_contract.py",
    "tests/test_database_config.py",
    "-q", "--tb=short",
]))
```

## Evidence established locally

- Real LangGraph execution with typed, bounded one-node continuations; terminal
  and repair-transition validation; unknown state versions denied.
- Atomic job/run/outbox creation rollback and checkpoint/continuation rollback.
- Duplicate delivery, sequential competing/expired claims, stale fence rejection,
  broker-acceptance/acknowledgment ambiguity, backoff and dead delivery limits.
- Current membership/source/connection/endpoint checks; cancellation of an
  in-flight synthetic handler; no late completion after cancellation/deletion.
- Scoped checkpoint history/read denial for another tenant/run; unsupported saver
  operations rejected; committed nodes reused on continuation and safe resume.
- Durable admissions across new budget instances, one format repair, binding and
  deadline protection, overrun handling, cross-connection receipt rejection and
  conservative refusal to replay an ambiguous unfinished node.
- Existing Step 4 protocol adapter actually exercises durable retry/repair hooks
  through controlled fake DNS/HTTP/credential authorization, without a real socket.
- Synthetic publication uses existing immutable revisions/active-pointer CAS:
  one active draft, duplicate task rejection and no fabricated human approval.
- ID-only Celery adapter disables implicit producer retries; worker runtime rejects
  an unknown delivery or tampered job/requester routing metadata.
- Document-free synthetic probes require administrator permission and retain fake
  provenance. Live worker probes fail closed on the explicit persistence gap.

## Exit criteria status

| Step 5 criterion | Local evidence | Still required |
| --- | --- | --- |
| Commit/publish crashes recover through outbox | Synthetic transaction/broker fault tests | PostgreSQL and actual worker/broker crash tests |
| Duplicate/fenced attempts cannot duplicate active outputs | Sequential fencing, rollback and synthetic draft CAS tests | Concurrent PostgreSQL publication races |
| Recovery preserves pins/work/scope | Typed checkpoints, scoped predicates, routing and safe-resume tests | Runtime-role RLS, pooling and real process recovery |
| Budgets/cancellation/disable checks apply | Durable hooks and lifecycle negative tests; unsupported live probe path blocked | Real transport/worker race qualification and document-free test ledger |
| Single processing slot, one Beat | Conditional application configuration only | Actual deployed CLI/process topology verification |

These results do not mark Step 5 fully complete. See [remaining inputs](remaining-inputs.md).
