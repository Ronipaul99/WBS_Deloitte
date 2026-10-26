# Step 3 Implementation Evidence

## Status

Repository implementation completed on 2026-10-24. The isolated PostgreSQL/Neon migration,
restricted runtime-role RLS tests, real `VECTOR(384)` dimension checks, and exact filtered vector
query remain pending. Step 3 is not externally release-verified and ingestion writes must remain
disabled.

## Scope Delivered

- Added the `pgvector` Python dependency and SQLAlchemy `Vector(384)` mapping.
- Added document processing state without assigning processed state to existing documents.
- Added versioned processing runs with idempotency, scope, lifecycle, and active-run constraints.
- Added canonical chunks with source traceability, JSONB metadata, and non-null embeddings.
- Added composite tenant/project/document ownership constraints and run-to-chunk cascade deletion.
- Added a deferred composite active-run relationship for atomic activation.
- Added one Alembic revision with extension setup, role validation, grants, and forced RLS.
- Added a PostgreSQL transaction-local tenant-context helper.
- Added repository tests and opt-in isolated PostgreSQL integration tests.
- Added guarded downgrade and forward-fix documentation.

No extraction, document parsing, OCR, malware scanning, tokenization, chunk generation, embedding
runtime, model download, ingestion worker, queue behavior, vector-search API, summary, LLM, RAG,
agentic workflow, or React change was implemented.

## Changed Files

- `backend/pyproject.toml`
- `backend/app/core/config.py`
- `backend/app/db/session.py`
- `backend/app/models/domain.py`
- `backend/app/models/__init__.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/a4f9c2d18e76_add_pgvector_ingestion_schema.py`
- `backend/tests/test_database_config.py`
- `backend/tests/test_pgvector_schema.py`
- `backend/tests/test_pgvector_postgres.py`
- `backend/README.md`
- `docs/document-ingestion-vector-storage-steps/step-03-pgvector-ingestion-schema.md`
- `docs/document-ingestion-vector-storage-steps/step-03-artifacts/implementation-evidence.md`

`backend/.env` was not modified, printed, or included in evidence. Existing unrelated working-tree
changes, including Step 1, Step 2, authentication, workflow, and React changes, were preserved.

## Migration Identity

| Item | Revision |
| --- | --- |
| Previous head | `f2a84d719c35` |
| Step 3 head | `a4f9c2d18e76` |

The migration creates the `vector` extension only on PostgreSQL and requires an online connection.
Extension setup errors are replaced with a controlled privilege message. It never drops the shared
extension.

## Schema Contract

### Documents

- Nullable `content_sha256`, `current_processing_run_id`, `processing_status`, `processed_at`, and
  `processing_error_code` columns.
- Unique scope key `(id, tenant_id, project_id)`.
- Deferred composite active-run foreign key requiring the selected run to belong to the same
  document, project, and tenant.
- Existing rows retain null processing state and are not represented as processed.

### Processing Runs

- UUID identity plus tenant, project, document, and job scope.
- Status, source content hash, extractor identity, embedding configuration, counts, timestamps, and
  sanitized error fields.
- Composite document and job ownership foreign keys.
- Unique scope key and deterministic processing-configuration idempotency constraint.
- Partial unique index preventing more than one `QUEUED` or `IN_PROGRESS` run per document.
- Checks requiring 384 embedding dimensions, valid statuses, 64-character content hashes, and
  non-negative counts.

### Chunks

- UUID identity plus processing-run, tenant, project, and document scope.
- Ordinal, token count, canonical content, content hash, block and source-location fields.
- PostgreSQL JSONB heading and source metadata.
- Non-null PostgreSQL `VECTOR(384)` embedding.
- Unique `(processing_run_id, ordinal)` and B-tree scope index.
- Composite run ownership foreign key with `ON DELETE CASCADE`.
- No HNSW or IVFFlat index.

## Database Role and RLS Contract

- Runtime and migration role names are derived from the pooled and direct database URLs; no role is
  hardcoded in the migration.
- Enabled ingestion configuration rejects identical runtime and migration roles.
- The PostgreSQL migration verifies that it is connected as the configured migration role.
- It rejects a missing runtime role, the migration role as runtime, a superuser runtime role, or a
  runtime role with `BYPASSRLS`.
- Public privileges are revoked and CRUD is granted only to the configured runtime role for the new
  tables.
- RLS is enabled and forced on both new tables.
- Policies apply `USING` and `WITH CHECK` against transaction-local `app.tenant_id`.
- Missing tenant state resolves to no permitted tenant. Invalid UUID state raises a database error.

These controls are present in the reviewed migration and repository tests. Their behavior under the
actual release roles remains an external gate.

## Tenant Transaction Contract

`set_local_tenant_context(session, tenant_id)` validates and canonicalizes the UUID, requires an
active PostgreSQL transaction, and issues `SET LOCAL app.tenant_id`. The setting therefore expires
at transaction completion and cannot remain on a reused pooled connection. SQLite is a no-op only
to preserve unrelated regression tests and is not RLS evidence.

No unscoped processing-run, chunk, vector persistence, or vector search repository was added.

## Upgrade and Rollback

- Deploy the migration with the approved direct migration credential before application startup.
- The runtime role must already exist with no superuser or `BYPASSRLS` capability.
- The migration is safe when the shared vector extension already exists.
- Empty-schema downgrade removes only Step 3 tables, columns, constraints, indexes, grants, and
  policies.
- Downgrade refuses to proceed when processing runs or chunks contain data.
- Downgrade never removes the shared vector extension or source objects.
- Once ingestion data exists, defects require a reviewed forward-fix migration.

## Verification Results

Focused repository tests:

```text
python -m pytest -q tests/test_pgvector_schema.py tests/test_database_config.py
56 passed, 1 existing Starlette deprecation warning
```

Complete backend suite:

```text
python -m pytest
169 passed, 2 skipped, 1 existing Starlette deprecation warning
```

The two skipped tests are `tests/test_pgvector_postgres.py`. They require explicitly supplied
disposable PostgreSQL migration/runtime URLs and acknowledgement; they are not counted as passing
PostgreSQL or RLS evidence.

Disposable SQLite migration regression checks:

```text
alembic upgrade head
Passed: clean upgrade to a4f9c2d18e76

alembic check
No new upgrade operations detected

alembic downgrade f2a84d719c35
alembic upgrade head
Passed on an empty disposable schema

alembic current
a4f9c2d18e76 (head)
```

SQLite verifies revision ordering, structural migration compatibility, and ORM drift only. It is
not evidence for extension creation, vector dimensions, grants, PostgreSQL constraints, or RLS.

Quality checks:

```text
python -m ruff check <Step 3 Python files>
All checks passed

python -m ruff format --check <Step 3 Python files>
9 files already formatted

python -m pip check
No broken requirements found

alembic heads
a4f9c2d18e76 (head)
```

Installed dependency resolution selected `pgvector==0.5.1` within the declared `>=0.4,<1` range.

## External Release Gates Pending

- Create or select an isolated Neon branch with a backup/restore point.
- Provision separate migration and restricted runtime roles.
- Verify the runtime role is not owner, superuser, or `BYPASSRLS` and has required existing-table
  permissions.
- Upgrade from the current production-equivalent head with representative existing documents.
- Repeat a clean PostgreSQL migration with the extension absent and present.
- Verify controlled failure when the migration role cannot create the extension.
- Run `tests/test_pgvector_postgres.py` with both actual restricted roles.
- Confirm valid and invalid vector dimensions using PostgreSQL.
- Confirm ownership, idempotency, active-run, ordinal, and cascade constraints.
- Confirm tenant A cannot select, insert, update, or delete tenant B rows.
- Confirm absent and invalid tenant context fail closed and pooled reuse does not retain context.
- Execute the exact tenant/project-filtered cosine-distance query.
- Inspect sanitized policies, grants, table owners, and forced-RLS state.
- Rehearse the guarded downgrade before data and the documented forward-fix path after data.

No Neon, PostgreSQL, pgvector, runtime-role, RLS, or exact-query result is claimed without this
evidence.

## Residual Risks

- PostgreSQL-specific migration SQL has not run in this workspace because Docker/PostgreSQL and
  isolated release-role credentials were unavailable.
- Existing application tables require deployment-managed runtime grants outside the new protected
  tables; these must be verified before release.
- RLS protects the two new ingestion tables. Existing tenant tables continue using their current
  authorization and tenant-filtering controls.
- Approximate indexes are intentionally absent; filtered exact search performance must be measured
  before a later reviewed indexing step.
