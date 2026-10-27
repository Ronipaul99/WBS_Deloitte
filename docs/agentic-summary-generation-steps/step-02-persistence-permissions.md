# Step 2: Add scoped persistence, migrations, and permissions

Status: independent local implementation verified; PostgreSQL verification pending.
Evidence: [Step 2 artifacts](step-02-artifacts/implementation-evidence.md).
Depends on [Step 1](step-01-contracts-capability-qualification.md), whose live-provider
qualification remains pending. No provider was enabled by this step.
Next: [Step 3](step-03-credentials-endpoint-security.md).

## Objective

Store connection/profile versions, durable runs, evidence, and immutable summary
content without weakening existing vector-storage constraints or tenant isolation.

## Implementation tasks

1. Add these records with explicit tenant scope and bounded JSON columns:

   | Record | Required information |
   | --- | --- |
   | `llm_connections` | Tenant, provider/format, approved endpoint policy, enabled state, active credential reference |
   | `llm_credential_versions` | Connection/tenant, encrypted bytes, nonce/key version, lifecycle metadata; no plaintext column |
   | `llm_model_profiles` / versions | Connection/tenant, model ID, immutable settings/capability version, enabled/default state |
   | `agent_workflow_runs` | Job, document/run/source/profile snapshots, state, budget, lease/fencing token, latest-request sequence |
   | `agent_step_runs` / checkpoints | Run/node/batch/attempt identity, input hash, validated artifact, completion and usage |
   | `workflow_dispatch_outbox` | Scoped run/job, task/continuation identity, delivery state, lease and retry timestamps |
   | `summary_revisions` | Summary/document/tenant/run, immutable structured content, provenance and quality result |
   | `summary_evidence` | Revision/claim/source-run/chunk references, canonical hash and validated locators |
   | Approval events | Exact revision, reviewer, decision/time, expected version; append-only audit history |

2. Extend `DocumentSummary` with an active revision pointer. Preserve the current
   unique-per-document summary row and legacy fields as a compatibility projection.
   Revision content stays immutable; approval events do not rewrite generated text.
3. Define composite uniqueness/foreign keys so a document, revision, evidence row,
   profile, connection, job, and workflow cannot be linked across tenants. Specify
   deletion order and indexes for pending outbox work, run steps, and revision history.
4. Map detailed workflow states to existing job statuses. Keep generation completion
   distinct from human approval. Include partial, quality-blocked, stale, failed,
   and cancelled outcomes without mapping them to an approved/complete summary.
5. Add `llm:manage`, `llm:use`, and a usage-audit permission. Admins manage/use;
   editors use only with summary permissions; viewers cannot trigger model calls.
   Implement both backend permission checks and matching frontend permission names.
6. Enforce RLS and scoped application predicates on new protected records. Bind
   checkpoint access to server-created tenant/run identity. Do not store pickles
   or credentials inside graph state. Do not repurpose ingestion outbox foreign keys.
7. Add an Alembic migration from the actual repository head, using the existing
   migration/runtime-role separation. Runtime processes must not create tables.
   Preserve old summary text/history as legacy/unverified content, not verified AI output.

## Proposed implementation targets

- `backend/app/models/agent_workflows.py`, `models/llm.py`, and existing domain models.
- A new migration under `backend/migrations/versions/`.
- `backend/app/core/permissions.py` and `WBS_UI/src/auth/permissions.ts`.
- Scoped repositories under `backend/app/services/agents/` and `services/llm/`.

## Verification

Use disposable PostgreSQL databases for migrate-up and recovery checks. Attempt
cross-tenant inserts, joins, checkpoint reads, credential lookup, evidence linking,
and active-revision updates under the runtime role. Test duplicate step/outbox
identities, stale revision updates, unknown role denial, and legacy summary reads.
Test a downgrade only against disposable data; do not downgrade a live schema
containing new revisions as a routine application rollback.

Suggested tests: `test_agent_schema.py`, `test_agent_schema_postgres.py`, and
`test_llm_permissions.py`. Unit tests alone do not establish PostgreSQL RLS behavior.

## Exit criteria

- [ ] Runtime-role constraints and RLS reject cross-tenant relationships/access.
- [ ] Migration preserves existing ingestion/vector records and legacy summaries.
- [x] Immutable revision content, approval history, and active-pointer rules are explicit.
- [x] Admin/editor/viewer permissions are enforced server-side and tested.
- [x] New persistence paths exclude secret/transcript/reasoning fields; synthetic records contain none.

The first two criteria remain open for actual disposable PostgreSQL verification.
SQLite migration/data preservation tests and emitted-policy assertions passed;
neither proves PostgreSQL RLS or trigger execution. Do not mark this step fully
complete until [remaining checks](step-02-artifacts/remaining-inputs.md) pass.
