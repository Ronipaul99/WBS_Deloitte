# Phase 1: Activate Local Authentication

## Phase Status

Implementation completed on 2026-10-22; target environment activation and live Neon verification
remain pending operator-supplied administrator details and deployment secrets.

Implemented in this phase:

- atomic, testable first-administrator provisioning service;
- explicit `--link-existing-user` safety gate;
- local administrator readiness enforcement with generic public failures;
- independent JWT and audit secret validation;
- production rejection of the development seed password;
- indexed administrator membership lookup and Alembic migration `c1a75d9e4b20`;
- provisioning, rollback, readiness, configuration, anonymous-access, and logout tests.
- disposable live React and FastAPI smoke verification for login, reload, and logout.

Operational work still pending:

- apply the migration to the selected Neon branch;
- provision the operator-approved administrator;
- store real secret values outside Git and switch the target environment to `AUTH_MODE=local`;
- repeat the verified React and FastAPI browser journey against the selected Neon environment.

## Outcome

A real administrator can sign in through React using a Neon-backed local identity. The development
authentication bypass is disabled in the target environment, and the application fails closed when
local authentication is misconfigured.

## Execution Context

The repository already contains:

- local auth endpoints in `backend/app/api/routes/auth.py`;
- JWT and refresh-token primitives in `backend/app/core/security.py`;
- Argon2id helpers in `backend/app/core/passwords.py`;
- auth configuration validation in `backend/app/core/config.py`;
- identity, refresh-session, and audit models in `backend/app/models/auth.py`;
- first-admin CLI support in `backend/app/cli.py`;
- the applied auth migration `8c2f6e441b7a`;
- React auth state in `WBS_UI/src/auth/AuthProvider.tsx`;
- login and tenant-selection views;
- backend local-auth tests using a seeded test identity.

The active `backend/.env` currently uses `AUTH_MODE=development`. Do not replace or print its Neon
connection strings. Do not invent an administrator password or place one in an environment file.

## Required Inputs

Confirm before execution:

- administrator email and display name;
- initial tenant name and stable slug;
- target Neon branch/database;
- staging and local UI origins;
- secret-management location for JWT and audit secrets;
- operator responsible for the break-glass administrator.

## Files Expected to Change

Likely code and test changes:

- `backend/app/cli.py`
- `backend/app/services/provisioning.py`
- `backend/app/db/init_db.py`
- `backend/app/api/routes/health.py`
- `backend/app/core/config.py`
- `backend/app/models/domain.py`
- `backend/migrations/versions/c1a75d9e4b20_index_admin_memberships.py`
- `backend/tests/test_provisioning.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_health.py`
- `backend/tests/test_database_config.py`
- `backend/README.md`
- deployment environment configuration outside Git

Do not commit `backend/.env`.

## Work Breakdown

### 1. Preflight the database

1. Confirm the intended Neon project and branch.
2. Run `alembic current` and confirm revision `8c2f6e441b7a` or later.
3. Run `alembic check` and resolve drift before provisioning.
4. Confirm `AUTO_CREATE_TABLES=false` for Neon.
5. Confirm the pooled URL is used at runtime and the direct URL only for migrations.

Evidence:

- current revision output without connection-string values;
- schema drift result;
- backup or Neon branch restore point.

### 2. Complete first-admin safety behavior

Review and test `python -m app.cli create-admin` for these behaviors:

- password is obtained only through `getpass`;
- password and confirmation must match;
- password policy is enforced before database changes;
- email is normalized consistently with login;
- duplicate local identity is rejected;
- existing users may be linked only after explicit safe validation;
- tenant, user, identity, and membership changes commit atomically;
- no password, hash, or token is printed;
- failure rolls back every pending record.

Add service-level functions if CLI logic becomes difficult to test without invoking a terminal.

### 3. Add an administrator readiness check

Extend readiness behavior so local or hybrid mode verifies that at least one active user has an
active `ADMIN` membership in an active tenant.

Requirements:

- readiness returns an unhealthy status without revealing email, tenant, or user IDs;
- liveness remains healthy when the process is running;
- database outages remain distinguishable from missing setup in internal logs only;
- OIDC-only behavior follows its provisioning policy;
- the query is indexed and lightweight.

Do not make public health output disclose counts or privileged identities.

### 4. Provision the administrator

Run from an approved operator terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.cli create-admin --email <admin-email> --display-name "<display-name>" --tenant-slug <slug> --tenant-name "<tenant-name>"
```

Enter the password only at the hidden prompt. Verify the resulting user, local identity, tenant, and
admin membership through a safe database query or admin diagnostic that never returns the password
hash.

### 5. Configure secrets and mode

Generate independent high-entropy values for:

- `AUTH_JWT_SECRET`;
- `AUTH_AUDIT_SECRET`.

Store them in the approved secret manager or ignored local `.env`. Configure:

```dotenv
AUTH_MODE=local
AUTH_ACCESS_TOKEN_MINUTES=15
AUTH_REFRESH_TOKEN_DAYS=7
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_SECURE=false
```

`AUTH_COOKIE_SECURE=false` is permitted only for local HTTP development. Staging and production must
use HTTPS and `true`.

Do not set `DEV_USER_PASSWORD` in a shared or production environment.

### 6. Run the live login journey

1. Start FastAPI with the target configuration.
2. Start React with `VITE_API_URL` pointing to FastAPI.
3. Open a clean browser context.
4. Confirm the login screen appears instead of the workspace.
5. Confirm an invalid password returns the generic error.
6. Sign in with the provisioned administrator.
7. Confirm `/me` returns the intended tenant and `ADMIN` role.
8. Reload the browser and verify refresh-cookie restoration.
9. Sign out and confirm the refresh session cannot be reused.
10. Confirm no token appears in localStorage or sessionStorage.

## Test Plan

Automated tests must cover:

- CLI success and transactional rollback;
- weak, mismatched, and duplicate password cases;
- local mode without credentials;
- startup configuration failures;
- readiness with zero and one active administrator;
- real login, refresh, reload, and logout;
- cookie path, HttpOnly, SameSite, and development Secure behavior;
- secret and credential absence from captured logs.

## Security Review Checklist

- [ ] Development bypass is impossible when `APP_ENV=production`.
- [ ] JWT and audit secrets are independent and have sufficient entropy.
- [ ] Administrator password was never present in shell history or Git.
- [ ] No default production credentials exist.
- [ ] Failed login does not distinguish missing, inactive, or incorrect accounts.
- [ ] Cookies use the intended path and attributes.
- [ ] CORS origins exactly match the UI origins.
- [ ] Neon URLs remain ignored and unprinted.

## Rollback

If activation fails before user traffic:

1. stop the affected API instance;
2. restore the previous deployment configuration;
3. keep the authentication schema because it is backward-compatible with development mode;
4. revoke any refresh sessions created during verification;
5. investigate configuration and data without weakening validation.

Do not downgrade the migration solely to disable local auth. Do not re-enable the development bypass
in staging or production as a workaround.

## Exit Criteria

- [ ] Target environment runs with `AUTH_MODE=local`.
- [ ] At least one active administrator exists.
- [ ] Anonymous access to protected routes receives `401`.
- [ ] Administrator login succeeds through the real React and FastAPI services.
- [ ] Refresh, reload, and logout behavior pass.
- [ ] Readiness and production configuration tests pass.
- [ ] Secrets and credentials are absent from source control and evidence.

## Handoff to Phase 2

Provide the administrator test identity through the approved test fixture mechanism, the active
tenant ID, live login evidence, final environment-key names, and any authorization inconsistencies
discovered while exercising the WBS routes.
