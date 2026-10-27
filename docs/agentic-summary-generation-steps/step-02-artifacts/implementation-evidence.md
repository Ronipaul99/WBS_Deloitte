# Step 2 implementation evidence

Date: 2026-10-27. Status: **partially complete**. Independent local work and tests
are implemented; actual disposable PostgreSQL migration/RLS/trigger verification
is pending. No provider capability or live database result is inferred from unit tests.

## Changed files and purpose

| Files | Purpose |
| --- | --- |
| `backend/app/models/llm.py` | Scoped connection, binary credential-version, profile and immutable profile-version records |
| `backend/app/models/agent_workflows.py` | Scoped runs, steps, JSON checkpoints, separate outbox, immutable revisions/evidence, append-only approval events |
| `backend/app/models/agent_types.py` | Shared scoped storage fields, bounds, workflow states and job-status mapping |
| `backend/app/models/agent_validation.py` | ORM validation, typed/canonical snapshots/artifacts, reference/locator checks, immutable scope/content guards |
| `backend/app/models/domain.py` | Summary revision pointer/version/origin/request sequence, and composite parent uniqueness/FKs needed for scoped linking |
| `backend/app/models/__init__.py` | Register/export new models and their validation hooks; no database connection or DDL |
| `backend/app/services/agents/persistence_types.py` | Bounded policy metadata, run budget, typed artifacts, structural secret exclusion |
| `backend/app/services/agents/scoped_storage.py` | Explicit transaction-local tenant/run/user context and current active membership/permission checks |
| `backend/app/services/agents/repository.py` | Scoped persistence operations, legacy reads, revision CAS, revision-specific approval audit persistence, usage-only projection |
| `backend/app/services/llm/repository.py` | Scoped manager-only connection/ciphertext storage and qualified-profile reads |
| `backend/app/core/permissions.py`, `WBS_UI/src/auth/permissions.ts` | Matching LLM manage/use/usage-audit permissions; no frontend flow changes |
| `backend/migrations/versions/f8c2a6d903b1_add_agent_persistence.py` | Frozen migration from actual head `e71c4a9b203d`, role checks, composite FKs, RLS, immutable/pointer/audit triggers, guarded downgrade |
| `backend/tests/agent_schema_fixtures.py` | Synthetic rows and a disposable-connection migration harness which never loads `env.py` or configured URLs |
| `backend/tests/test_agent_schema.py`, `test_llm_permissions.py` | Isolated local persistence/permission/integrity/migration tests |
| `backend/tests/test_agent_schema_postgres.py` | Opt-in fresh disposable PostgreSQL runtime-role integration checks; skipped in this run |
| Six existing migration-head assertions | Updated only the expected application head in pgvector, vector-persistence, ingestion-orchestration and deletion-lifecycle tests |
| Step 2 document, index and this artifacts folder | Actual status, schema/permission decisions, test evidence and remaining checks |

The six existing test files are `test_document_lifecycle_contract.py`,
`test_ingestion_orchestration_contract.py`, `test_pgvector_schema.py`,
`test_pgvector_postgres.py`, `test_vector_persistence_contract.py`, and
`test_vector_persistence_postgres.py`. Their historical migration IDs remain unchanged.
Step 1 contracts, fixtures, LangGraph spike, dependencies and artifacts were preserved.
No new dependencies were added.

## Exit criteria assessment

| Exit criterion | Actual evidence |
| --- | --- |
| Runtime constraints/RLS reject cross-tenant access | Implemented policies, FKs and local guard tests; **PostgreSQL execution pending** |
| Migration preserves ingestion/vector and legacy summaries | Disposable SQLite up/down/up preserves existing documents/runs/chunks/embeddings and legacy text; existing migration regressions pass; **PostgreSQL preservation pending** |
| Immutable revisions, approval history and active pointer | Explicit ORM/database rules and local repository/constraint tests; PostgreSQL trigger execution pending |
| Admin/editor/viewer enforcement | Server-side permission helper and repository membership checks tested; frontend identifiers match |
| Exclude secrets/transcripts/reasoning from new workflow storage | Typed payloads and recursive field/size guards tested; PostgreSQL check constraints emitted but not executed |

See [verification results](test-results.md), [schema decisions](schema-and-permissions.md)
and [remaining inputs](remaining-inputs.md).

## Scope confirmation

Only Step 2 storage and permission primitives were implemented. There is no
production LangGraph saver, graph execution, LLM adapter/call, credential encryption/
rotation, endpoint-security implementation, worker dispatch/retry/scheduler logic,
summary agent, new route, model management UI or review screen.

The approval operation persists a revision-specific audit decision with an atomic
storage check; it does not expose a new approval API or implement the later review
workflow. Endpoint policy records store metadata; they do not approve destinations
or perform DNS/HTTPS/SSRF checks. Credential bytes are synthetic in tests; actual
cryptographic encryption and secure credential provisioning remain Step 3 work.

No `.env`, credential, Docker, Nginx, CI or VM file/service was changed. No configured
application database was migrated or contacted for verification. No feature was
enabled, deployed, committed or pushed. Unrelated existing checkout edits remain intact.
