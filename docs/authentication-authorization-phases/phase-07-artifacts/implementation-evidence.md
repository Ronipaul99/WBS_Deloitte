# Phase 7 Implementation Evidence

## Delivery Status

The live full-stack verification harness is implemented. A disposable SQLite smoke run completed
all 15 scenarios locally on 2026-10-22. PostgreSQL 16 is the release-blocking target in GitHub
Actions and Docker Compose; it was not run locally because Docker is not installed on this
workstation.

## Environment Flow

```text
run-fullstack.mjs
  -> disposable PostgreSQL 16 (Compose) or explicitly acknowledged CI database
  -> alembic upgrade head + alembic check
  -> guarded deterministic seed with per-run users, passwords, JWT secrets, and reset tokens
  -> FastAPI :8011 + isolated uploads + eager jobs
  -> Vite :5187 configured for the test API
  -> Playwright full-stack tests (no auth, tenant, or workflow route mocks)
  -> process, volume, upload, database, and secret-file teardown
```

The default database container binds PostgreSQL only to `127.0.0.1:55432`. The orchestrator refuses
occupied UI/API ports, refuses external databases whose name does not contain `wbs_fullstack`, and
requires an explicit disposable-database acknowledgement for external URLs.

## Test Matrix

| Area | Live coverage |
|---|---|
| Authentication | anonymous/invalid/valid login, cookie restoration, access expiry, concurrent refresh, refresh replay, logout, logout-all, password change |
| Recovery and invitation | enumeration-safe forgot response, valid reset, expired/reused reset, invitation account creation, URL token removal |
| Browser security | memory-only access token, empty credential storage, HttpOnly/SameSite cookie, console secret check, untrusted Origin, CORS, protected back navigation |
| Authorization | Viewer/Editor/Admin families, runtime role change, runtime membership removal, inactive user/tenant, final-admin race |
| Tenant isolation | project, document, job, WBS, validation, and export IDs replayed across tenants with non-disclosure assertions |
| Workflow | required document upload, summary, approval, WBS generation, validation, protected JSON export |
| UI | multi-tenant switching, auth-loss cleanup, desktop and mobile horizontal-overflow assertions |

## Diagnostics

API responses include a generated `X-Correlation-ID`; server logs record only correlation ID,
method, path, status, and duration. Playwright keeps tracing and video disabled because they can
capture credentials. On CI failure, only screenshots and a sanitized network summary containing
method, URL path, response status, and correlation ID are uploaded. Headers, cookies, bodies,
queries, and fragments are excluded.

## CI Gates

`.github/workflows/fullstack-security.yml` runs:

1. Gitleaks repository secret scan;
2. Ruff backend lint;
3. backend Pytest contracts;
4. frontend ESLint and production build;
5. Alembic upgrade and drift check against PostgreSQL 16;
6. live Playwright through `npm run test:e2e:fullstack`;
7. `pip-audit`, production `npm audit`, and Trivy container scan.

## Verification Results

| Command | Result |
|---|---|
| `ruff check app tests migrations` | Passed |
| `python -m pytest` | 66 passed |
| `npm run lint` | Passed |
| `npm run build` | Passed |
| `npx playwright test` | 32 passed |
| `npm run test:e2e:fullstack:smoke` | 15 passed in 24.9 seconds |
| `npm run test:e2e:fullstack` | Not run locally; Docker unavailable. PostgreSQL execution is configured in CI. |

The successful smoke run left no listeners on `8011` or `5187` and no per-run database, upload,
state, artifact, or secret files under `.fullstack-runtime`.

## Exercised Configuration

The runner fixes `APP_ENV=test`, `AUTH_MODE=local`, five-second access tokens, rotating refresh
cookies, password recovery and tenant invitations, test-only mail delivery, eager jobs, migration-
only schema creation, disabled development principal bootstrapping, null database pooling, isolated
uploads, exact CORS/UI origins, and unique JWT/audit secrets. Test-only lifetime and bootstrap
controls are rejected outside `APP_ENV=test`.

## Timing Assumptions

Readiness is polled for up to 45 seconds. Jobs are polled to terminal server state and run eagerly;
the only deliberate fixed wait is 5.25 seconds for the test-only five-second access-token expiry.
Functional assertions are not retried.

## Handoff

Phase 8 should confirm the first PostgreSQL CI result, configure branch protection to require this
workflow, decide retention for security artifacts, and integrate deployment-platform logging and
alerting using `X-Correlation-ID`.
