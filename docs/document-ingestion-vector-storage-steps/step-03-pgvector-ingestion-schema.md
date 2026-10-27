# Step 3: Add pgvector and the Ingestion Schema

## Step Status

Repository implementation completed on 2026-10-24. PostgreSQL/pgvector verification under the
restricted runtime role and isolated Neon migration verification remain pending, so this step is
not externally release-verified.

## Objective

Create the PostgreSQL structures required for versioned document processing and tenant/project-
isolated vector storage. The schema must support idempotent retries, atomic activation, safe
reprocessing, source traceability, deletion, and Row-Level Security before any vectors are written.

## Prerequisites

- Step 1 complete.
- Approved direct Neon migration credential and pooled runtime credential.
- Runtime database role that does not own application tables and lacks `BYPASSRLS`.
- Confirmed embedding dimension of 384.
- Backup/restore point for the target Neon branch before migration testing.

## Data Model

### Changes to `documents`

Add:

- `content_sha256` string, nullable for pre-existing rows;
- `current_processing_run_id` UUID, nullable until a run is active;
- `processing_status` string or enum;
- `processed_at` timestamp;
- `processing_error_code` string;
- uniqueness on `(id, tenant_id, project_id)` for composite ownership references.

### `document_processing_runs`

Add:

- UUID primary key;
- tenant, project, document, and job identifiers;
- processing status;
- document content hash;
- extractor name/version;
- embedding provider/model/dimensions;
- page, worksheet, block, and chunk counts;
- start, completion, failure, and audit timestamps;
- stable error code and sanitized error message.

Add composite ownership foreign keys, a tenant/project/document history index, an idempotency
constraint, and partial protection against concurrent active runs.

### `document_chunks`

Add:

- UUID primary key;
- processing-run, tenant, project, and document identifiers;
- ordinal and token count;
- canonical chunk content and SHA-256 hash;
- block type, page, worksheet, row range, and heading path;
- JSONB source metadata;
- non-null `VECTOR(384)` embedding;
- timestamps.

Add uniqueness by processing run and ordinal plus a B-tree scope index. Do not create HNSW in this
step; exact filtered search is the correctness baseline.

## Relationship Design

1. Add the processing-run table without the document active-run foreign key.
2. Add the chunk table and ownership constraints.
3. Add `documents.current_processing_run_id` after both tables exist.
4. Require the active run to belong to the same document, tenant, and project through a composite
   relationship or an equivalent deferred constraint/transactional validation.
5. Use `ON DELETE CASCADE` from processing run to chunks.
6. Do not automatically hard-delete the original object from a database cascade.

## Row-Level Security Design

Enable and force RLS on `document_processing_runs` and `document_chunks`.

Policies must:

- compare `tenant_id` with a transaction-local `app.tenant_id` setting;
- apply to reads through `USING`;
- apply to inserts and updates through `WITH CHECK`;
- fail closed when the setting is absent or invalid;
- allow only the restricted application role;
- preserve a separate controlled migration/operations role.

Application sessions must set tenant context with `SET LOCAL` inside a transaction. Never use a
connection-global setting that can leak across pooled requests.

## Implementation Tasks

1. Add the `pgvector` Python package to `backend/pyproject.toml`.
2. Register SQLAlchemy vector types in the domain model.
3. Add processing status enums/constants shared by API and worker code.
4. Implement models and relationships in `backend/app/models/domain.py`.
5. Generate an Alembic revision, then manually review every operation.
6. Add `CREATE EXTENSION IF NOT EXISTS vector` through the migration credential.
7. Create tables, constraints, indexes, grants, and RLS policies.
8. Backfill safe defaults for existing documents without claiming they are processed.
9. Add repository/session support for transaction-local tenant context.
10. Add a migration-head readiness test for the new revision.
11. Document forward-fix and downgrade behavior.
12. Ensure downgrade does not drop a shared vector extension automatically.

## Files Expected to Change

- `backend/pyproject.toml`
- `backend/app/models/domain.py`
- `backend/app/models/__init__.py`
- `backend/app/db/session.py`
- new Alembic migration
- schema/config/readiness tests
- new PostgreSQL/pgvector integration tests

## Test Matrix

Migration:

- clean Neon branch upgrade;
- upgrade from current migration head with existing documents;
- application startup at new migration head;
- documented downgrade or forward-fix rehearsal;
- extension already present;
- migration role lacks permission to create extension, producing a clear deployment failure.

Schema:

- valid 384-dimensional insert;
- wrong vector dimension rejected;
- missing scope rejected;
- duplicate run ordinal rejected;
- chunk cascade when a processing run is deleted;
- document cannot activate another document's run;
- failed run can coexist with a previous active completed run.

RLS:

- tenant A cannot select, insert, update, or delete tenant B rows;
- same-tenant project A queries do not return project B when repository scope is applied;
- missing tenant setting returns no data or raises the approved fail-closed error;
- pooled connection reuse does not retain the previous transaction's tenant;
- runtime role cannot disable policies or bypass RLS.

## Security Checklist

- [ ] Runtime and migration database roles are separated.
- [ ] Runtime role lacks table ownership and `BYPASSRLS`.
- [ ] RLS applies to reads and writes.
- [x] Composite ownership constraints prevent mismatched tenant/project/document rows.
- [x] Vector and chunk content are not accessible through unscoped repository methods.
- [x] Migrations contain no credentials or tenant data.
- [x] Downgrade does not destroy a shared extension unexpectedly.

## Verification

Validate and apply the migration on an isolated Neon branch. Run PostgreSQL-specific tests using the
runtime role, inspect policies and grants, insert a known vector, and execute an exact cosine-distance
query with tenant/project predicates.

SQLite tests may remain for unrelated modules but are not evidence for this step.

## Rollback

Do not enable ingestion writes until the schema and RLS verification pass. Prefer a forward migration
for defects discovered after data is written. Never automatically drop the vector extension, active
chunk data, or document originals as part of an application rollback.

## Exit Criteria

- [ ] Neon migration succeeds from the current head.
- [ ] `VECTOR(384)` accepts valid and rejects invalid dimensions.
- [ ] Processing runs and chunks enforce ownership and lifecycle constraints.
- [ ] RLS negative tests pass under the actual runtime role.
- [ ] Exact tenant/project-filtered vector query passes.
- [ ] Migration, policy, grant, and rollback evidence is recorded.

## Handoff to Step 5 and Step 10

Provide generated model types, status values, tenant-context session helper, constraints, active-run
contract, and repository expectations. Extraction creates values for this schema; persistence makes
the activation transaction concrete.

