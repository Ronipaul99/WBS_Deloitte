# WBS Generator Backend

FastAPI boilerplate for the tenant-aware WBS generation workflow. It includes:

- async FastAPI and SQLAlchemy
- SQLite for zero-configuration local development
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

The application auto-creates tables for the first development run. The initial Alembic migration
is included for managed environments; disable `AUTO_CREATE_TABLES` and apply it with:

```powershell
alembic upgrade head
```

Create and commit another revision under `migrations/versions/` whenever the models change:

```powershell
alembic revision --autogenerate -m "describe the model change"
```

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
