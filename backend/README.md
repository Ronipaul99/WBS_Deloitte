# WBS Generator Backend

FastAPI boilerplate for the tenant-aware WBS generation workflow. It includes:

- async FastAPI and SQLAlchemy
- SQLite for zero-configuration local development
- Neon-ready pooled runtime and direct migration connections
- PostgreSQL and Redis through Docker Compose
- Celery worker wiring for long-running document and AI tasks
- development identity seeding and an OIDC-ready authentication boundary
- tenant membership checks on every tenant-owned resource
- local object storage with tenant-prefixed keys
- document summary, WBS generation, validation, and export placeholders
- OpenAPI documentation and end-to-end contract tests

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open:

- API documentation: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Readiness check: `http://127.0.0.1:8000/api/v1/health/ready`

Development mode automatically provisions this tenant ID:

```text
00000000-0000-0000-0000-000000000001
```

No bearer token is required while `AUTH_MODE=development`.

## Run with PostgreSQL, Redis, and Celery

```powershell
cd backend
docker compose up --build
```

The API runs on port `8000`. The worker consumes Redis-backed Celery jobs. Uploaded files and
generated exports are stored in the shared `uploads` volume.

## Test and lint

```powershell
python -m pytest
ruff check .
```

## Database migrations

### Connect Neon

In the Neon dashboard, copy both connection strings. Use the pooled URL for API traffic and the
direct URL for schema migrations. Do not commit either credential.

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@ep-EXAMPLE-pooler.REGION.aws.neon.tech/neondb?sslmode=require
DIRECT_DATABASE_URL=postgresql://USER:PASSWORD@ep-EXAMPLE.REGION.aws.neon.tech/neondb?sslmode=require
DATABASE_USE_NULL_POOL=true
AUTO_CREATE_TABLES=false
```

The application converts standard Neon `postgresql://` URLs to SQLAlchemy's asyncpg dialect. The
pooled URL is used only by the running API; Alembic deliberately uses the direct URL.

Apply the checked-in migrations to a new Neon branch or database before starting the API:

```powershell
alembic upgrade head
```

### Make a schema change

Use this process for every database change:

1. Create a Neon development branch from the current production branch.
2. Point `DIRECT_DATABASE_URL` at that development branch.
3. Update the SQLAlchemy models in `app/models/domain.py`.
4. Generate a migration:

```powershell
alembic revision --autogenerate -m "describe the model change"
```

5. Review the generated file in `migrations/versions/`. Autogeneration must not be accepted
   without checking column types, nullability, defaults, indexes, constraints, and data backfills.
6. Apply and verify it on the Neon development branch:

```powershell
alembic upgrade head
alembic check
python -m pytest
```

7. Commit the model and migration together. In deployment, run `alembic upgrade head` before
   starting the new API version.

Use `alembic downgrade -1` only while testing a reversible migration. For production failures,
prefer a reviewed forward-fix migration when rolling back would risk losing data.

`AUTO_CREATE_TABLES=true` remains available only for throwaway local SQLite tests. Keep it `false`
for Neon so every schema change has a migration history.

## Authentication and tenancy

Set `AUTH_MODE=oidc` and configure `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL` to validate
SSO access tokens. Users must also be provisioned in `users` and `tenant_memberships`.

The tenant ID in a route never grants access by itself. `require_tenant_member` verifies that the
authenticated user belongs to the tenant before a tenant-owned query runs.

## Processor integration points

Replace the placeholder implementations in `app/services/workflows.py` with:

1. PDF, DOCX, XLSX, and XML extraction.
2. LLM-based summary and requirement extraction.
3. WBS generation from the approved summary and selected template.
4. Primavera P6-specific validation and export logic.

Keep the job lifecycle and persisted result contracts stable so the React UI can poll jobs without
depending on the underlying AI provider.
