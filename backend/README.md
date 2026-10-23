# WBS Generator Backend

FastAPI boilerplate for the tenant-aware WBS generation workflow. It includes:

- async FastAPI and SQLAlchemy
- SQLite for zero-configuration local development
- Neon-ready pooled runtime and direct migration connections
- PostgreSQL and Redis through Docker Compose
- Celery worker wiring for long-running document and AI tasks
- Argon2id local passwords, short-lived JWT access tokens, and rotating refresh sessions
- backend-managed OIDC Authorization Code with PKCE and internal application sessions
- database-backed role permissions on every tenant-owned operation
- local development storage and private S3-compatible Neon Object Storage
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

## Use Neon Object Storage

The document and WBS template upload endpoints use local disk by default. To use a private Neon
bucket, create a fresh storage credential and place these values only in the untracked `.env` file
or your deployment secret manager:

```dotenv
STORAGE_BACKEND=s3
OBJECT_STORAGE_BUCKET=assets
AWS_ENDPOINT_URL_S3=https://YOUR-ENDPOINT.storage.REGION.aws.neon.tech
AWS_ACCESS_KEY_ID=YOUR-NEW-KEY-ID
AWS_SECRET_ACCESS_KEY=YOUR-NEW-SECRET
AWS_REGION=us-east-2
```

Restart the API after changing storage settings. `GET /api/v1/health/ready` verifies access to the
configured bucket. Uploads continue through the authenticated API; the backend validates the
declared type, file signature, actual byte size, tenant/project ownership, and writes a generated
key such as `tenants/{tenant}/projects/{project}/documents/{uuid}.pdf`. Original filenames remain
database metadata and are never used as object keys. Do not make the bucket public and do not place
S3 credentials in `WBS_UI` environment variables.

## Enable local authentication

Apply migrations, provision the first administrator, and then enable local authentication:

```powershell
cd backend
alembic current
alembic upgrade head
alembic check
python -m app.cli create-admin --email admin@example.com --display-name "WBS Admin" --tenant-slug default --tenant-name "Default Workspace"
```

The command prompts for the password without placing it in shell history. Use at least 12
characters. Then generate separate high-entropy values for `AUTH_JWT_SECRET` and
`AUTH_AUDIT_SECRET`, set `AUTH_MODE=local`, and restart the API. Never commit these values.
The API readiness endpoint returns `503` in local or hybrid mode until an active administrator has
an active tenant, an `ADMIN` membership, and a usable local identity.

If the email already belongs to a verified user, review that record first and explicitly add
`--link-existing-user`. The command otherwise refuses to attach a new password to an existing
account. All tenant, user, identity, and membership changes are committed as one transaction.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run the UI with `VITE_API_URL=http://127.0.0.1:8000/api/v1`. Access tokens remain in browser
memory; the rotating refresh credential is sent only as an HttpOnly cookie.

The `/me` response includes the current role and derived permission strings for every active tenant
membership. Tenant routes recalculate permissions from the database on every request, so a role
change or membership removal takes effect without waiting for the access token to expire. The
OpenAPI document lists the expected `401`, `403`, and non-disclosing `404` outcomes.

## Enable password recovery

Password recovery is off by default. Apply migration `d7f3c2a91e60`, configure a verified SMTP
sender, and set the public UI origin before enabling it:

```dotenv
PASSWORD_RECOVERY_ENABLED=true
PUBLIC_UI_URL=https://wbs.example.com
EMAIL_PROVIDER=smtp
EMAIL_FROM=no-reply@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=secret-managed-value
SMTP_PASSWORD=secret-managed-value
SMTP_SECURITY=starttls
```

Production startup rejects HTTP reset origins, missing SMTP credentials, unencrypted SMTP, and the
test email provider. The reset secret has 256 bits of entropy, expires within 30 minutes, is stored
only as a SHA-256 digest, and is carried in the email URL fragment so it is not sent to the UI web
server. A successful reset increments the user's auth version and revokes every refresh session.

Enable `VITE_PASSWORD_RECOVERY_ENABLED=true` only after the schema and backend configuration are
live. Also apply an edge rate limit to both recovery endpoints. Schedule this command daily to
remove only used or expired records older than `PASSWORD_RESET_RETENTION_DAYS`:

```powershell
python -m app.cli cleanup-password-reset-tokens
```

If email delivery fails, turn off the UI flag first and then `PASSWORD_RECOVERY_ENABLED`; never log
or display reset links as a fallback. Validate the sender domain, delivery, expiry, reuse rejection,
and spam handling in staging before production activation.

## Enable tenant invitations

Apply migration `e6b91f2c4a73`, configure the same verified email provider and public UI origin used
for recovery, and then enable invitations:

```dotenv
TENANT_INVITATIONS_ENABLED=true
TENANT_INVITATION_HOURS=72
TENANT_INVITATION_RETENTION_DAYS=30
TENANT_INVITATION_RESEND_WINDOW_MINUTES=60
TENANT_INVITATION_RESEND_LIMIT=5
```

Invitation secrets contain 256 bits of entropy, are stored only as SHA-256 digests, and travel in a
URL fragment that React removes immediately. New local users provide a display name and password;
existing users must authenticate as the invited email. An email delivery failure revokes the issued
invitation instead of exposing the link through logs or an operator fallback.

Schedule retained-record cleanup daily:

```powershell
python -m app.cli cleanup-tenant-invitations
```

Deploy the migration before the API and enable `TENANT_INVITATIONS_ENABLED` only after SMTP and the
`/accept-invitation` UI route are live. Disable the flag to stop new sends while retaining existing
member role and removal administration. Do not downgrade the invitation table after links are sent;
prefer a forward fix and revoke affected invitations.

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

The release browser suite is launched from `WBS_UI`:

```powershell
cd ..\WBS_UI
npm.cmd run test:e2e:fullstack
```

## Production operations

Before promotion, validate the injected production environment without printing secrets:

```powershell
python -m app.cli check-production-config
```

Production readiness checks the database migration revision in addition to connectivity and the
administrator invariant. Metrics are disabled locally; production requires `METRICS_ENABLED=true`
and a separate secret-managed `METRICS_BEARER_TOKEN`. Scrape `/api/v1/health/metrics` only through a
private monitoring path.

Schedule the unified maintenance command daily and alert on failure or a missing success:

```powershell
python -m app.cli run-maintenance
```

The command removes only records beyond configured retention periods, stale failed-export objects,
and old `.part`/`.tmp` files. It is batched and safe to rerun. The Docker Compose maintenance profile
can exercise the same command locally with `docker compose --profile maintenance run --rm maintenance`.

Targeted and environment-wide containment commands require exact confirmation strings:

```powershell
python -m app.cli revoke-user-sessions --email admin@example.com --confirm REVOKE_USER_SESSIONS
python -m app.cli revoke-all-sessions --confirm REVOKE_ALL_SESSIONS
```

Use these only under the Phase 8 incident runbooks. The production Dockerfiles, edge reference,
secret inventory, alert catalog, deployment/restore runbook, and readiness record are linked from
`docs/authentication-authorization-phases/phase-08-artifacts/implementation-evidence.md`.

It uses `backend/docker-compose.fullstack.yml` to create an isolated PostgreSQL 16 database, applies
all Alembic revisions, verifies schema drift, seeds a unique role/tenant matrix, and removes the
database volume after the run. It never reads the backend `.env` database URL over the generated
test-process environment. Do not point the suite at a shared Neon branch.

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

Enterprise SSO uses a backend-managed Authorization Code flow with PKCE. Set `AUTH_MODE=hybrid`
during rollout, configure every `OIDC_*` value documented in `.env.example`, and register the exact
`OIDC_REDIRECT_URI`. The callback validates discovery metadata and pinned endpoints, signature,
issuer, audience, algorithm, times, nonce, verified email, and provider directory. Provider tokens
never enter application JavaScript; the callback creates the same rotating WBS refresh session used
by local authentication.

New SSO identities require an active invitation whose normalized email matches the provider's
verified email. Existing links use the immutable, directory-namespaced provider subject. Provider
claims never create tenant access on their own. Apply migration `f2a84d719c35`, keep a reviewed
local break-glass administrator in `hybrid` mode, and enable the UI with:

```dotenv
VITE_AUTH_MODE=hybrid
VITE_SSO_ENABLED=true
VITE_SSO_PROVIDER_LABEL=Enterprise SSO
```

Provider registration, claims, endpoint pins, outage handling, and rollout evidence are described
in `docs/authentication-authorization-phases/phase-09-artifacts/`.

The tenant ID in a route never grants access by itself. `require_tenant_member` verifies that the
authenticated user belongs to the tenant before a tenant-owned query runs.

See `SECURITY.md` for the threat model, security controls, and deployment checklist.
See the [authentication and authorization specification](../docs/authentication-authorization-functional-technical-spec.md)
for the phased functional and technical work required to complete the feature end to end.
The [phase execution pack](../docs/authentication-authorization-phases/README.md) contains the
implementation sequence, verification gates, and handoff evidence for each phase.

## Processor integration points

Replace the placeholder implementations in `app/services/workflows.py` with:

1. PDF, DOCX, XLSX, and XML extraction.
2. LLM-based summary and requirement extraction.
3. WBS generation from the approved summary and selected template.
4. Primavera P6-specific validation and export logic.

Keep the job lifecycle and persisted result contracts stable so the React UI can poll jobs without
depending on the underlying AI provider.
