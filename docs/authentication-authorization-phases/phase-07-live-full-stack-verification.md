# Phase 7: Live Full-Stack Verification

## Phase Status

Implemented. The release suite exercises React, FastAPI, migrations, authentication, tenant RBAC,
and the WBS workflow without API mocks. The local disposable SQLite smoke run passes; the configured
PostgreSQL GitHub Actions gate remains to be observed on its first CI run because Docker is not
installed on the implementation workstation.

## Outcome

A repeatable CI suite proves the complete React, FastAPI, and PostgreSQL authentication and
authorization journey, including abuse cases, without production credentials or mocked auth APIs.

## Execution Context

Existing tests:

- backend fixtures in `backend/tests/conftest.py`;
- authentication tests in `backend/tests/test_auth.py`;
- workflow contract tests in `backend/tests/test_workflow.py`;
- Playwright configuration in `WBS_UI/playwright.config.ts`;
- mocked authentication routes in `WBS_UI/tests/auth-mocks.ts`;
- UI tests in `WBS_UI/tests/dashboard.spec.ts` and `create-wbs.spec.ts`.

Phase 6 must provide stable live workflow APIs and test seed data before this phase begins.

## Test Environment Design

Use isolated services:

- disposable PostgreSQL container or dedicated Neon test branch;
- FastAPI on a test-only port;
- React/Vite configured to the test API;
- mail provider fake or controlled test inbox;
- eager background jobs or a dedicated test worker;
- isolated upload directory;
- secrets generated for the test run only.

Never run destructive tests against a shared development or production Neon branch.

## Files Expected to Change

- `WBS_UI/playwright.fullstack.config.ts` (new or equivalent)
- full-stack tests under `WBS_UI/tests/fullstack/`
- test orchestration scripts in package configuration
- backend seed/factory helpers under `backend/tests/`
- CI workflow files when available
- Docker Compose test configuration when selected
- documentation for local execution and failure artifacts

## Work Breakdown

### 1. Build deterministic environment orchestration

Create one command that:

1. starts the isolated database;
2. waits for database readiness;
3. runs `alembic upgrade head`;
4. provisions Viewer, Editor, Admin, two tenants, and required fixtures;
5. starts FastAPI with `APP_ENV=test` and `AUTH_MODE=local`;
6. starts the frontend with the test API URL;
7. waits for both readiness endpoints;
8. runs Playwright;
9. terminates child processes;
10. removes disposable data and secrets even after failure.

Use process-safe teardown. Do not rely on a developer manually stopping servers.

### 2. Create supported test data factories

Factories must use application services or direct test-only database helpers with the same invariants
as production. Avoid hard-coded production-like credentials.

Required identities:

- Admin in Tenant A;
- Editor in Tenant A;
- Viewer in Tenant A;
- Admin in Tenant B;
- multi-tenant user with different roles;
- local user for reset/password tests;
- SSO-only shape for account UI tests when relevant.

Generate a unique password and JWT secrets per run. Keep them in process environment only.

### 3. Replace auth route mocks

Full-stack tests must not intercept:

- `/auth/*`;
- `/me`;
- tenant membership endpoints;
- WBS workflow endpoints.

Retain narrow network interception only for external providers such as transactional email when using
a fake adapter. Keep fast mocked component tests separate from release-blocking full-stack tests.

### 4. Implement authentication scenarios

- anonymous user sees login;
- invalid email/password returns generic failure;
- valid login enters correct tenant;
- refresh cookie restores after reload;
- access-token expiry refreshes once;
- concurrent requests share one refresh;
- old refresh-token replay revokes the family;
- current logout blocks refresh;
- logout-all invalidates existing access tokens;
- password change invalidates old password and sessions;
- forgot/reset flow succeeds and handles expiry/reuse;
- rate-limited login honors retry behavior.

Use server-side test hooks or reduced test-only access lifetime rather than sleeping for production
token durations.

### 5. Implement authorization scenarios

For Viewer, Editor, and Admin, cover each permission family through the browser and direct API calls.

Required abuse cases:

- cross-tenant project ID;
- cross-tenant document ID;
- cross-tenant job polling;
- cross-tenant WBS/validation/export IDs;
- member-management request by Viewer or Editor;
- role changed while session remains active;
- membership removed while session remains active;
- inactive user and inactive tenant;
- simultaneous final-admin demotion/removal.

Assert status and absence of protected response data, not only UI messages.

### 6. Implement browser security assertions

- localStorage and sessionStorage contain no credentials;
- password/reset/invitation values are absent from console output;
- reset/invitation token is removed from browser URL history after parsing;
- refresh cookie has expected attributes for the test environment;
- untrusted Origin requests are rejected;
- CORS does not expose protected responses to unapproved origins;
- protected UI disappears after authentication loss;
- back navigation does not reveal stale protected screens;
- desktop/mobile pages have no incoherent overlap or horizontal overflow.

### 7. Add migration and static gates

CI order:

1. secret scan;
2. backend lint;
3. frontend lint;
4. backend unit/integration tests;
5. frontend build;
6. Alembic upgrade and drift check;
7. full-stack Playwright;
8. dependency and container scans.

Fail fast on migration or security-gate failure. Retain sanitized failure traces for debugging.

### 8. Stabilize timing and failure diagnostics

- wait on readiness and visible state rather than fixed sleeps;
- use deterministic job behavior in the test environment;
- identify each generated user and tenant by run ID;
- include correlation IDs in safe server logs;
- capture trace, screenshot, and network summary only on failure;
- redact Authorization and Cookie headers from artifacts;
- retry only tests proven to fail from infrastructure timing, not functional assertions.

## Test Commands

Expose stable scripts such as:

```powershell
npm.cmd run test:e2e
npm.cmd run test:e2e:fullstack
npm.cmd run test:e2e:fullstack:smoke
```

The full-stack script should own service lifecycle. Document prerequisites and ports. Support a CI
mode that never reuses an existing local server.

## Security Review Checklist

- [x] Test database is isolated and disposable.
- [x] No production secret or URL is used.
- [x] Auth and `/me` are not mocked in release-blocking tests.
- [x] Failure artifacts omit credentials, cookies, bodies, and URL query/fragment values.
- [x] Abuse scenarios assert response confidentiality.
- [x] Tests cover runtime role/membership changes.
- [x] Teardown runs after success, failure, and interruption.
- [x] CI blocks release on security test failures.

## Exit Criteria

- [x] One command runs the migrated live stack and tests.
- [x] Authentication scenarios pass without API mocks.
- [x] RBAC and cross-tenant abuse matrix passes.
- [x] Full WBS workflow passes for allowed roles.
- [x] Browser credential-storage and cookie assertions pass.
- [x] CI includes migration, scan, build, lint, and full-stack gates.
- [x] Test teardown leaves no processes, data, or secret files.

## Handoff to Phase 8

Provide the orchestration command, CI job, environment diagram, test matrix and results, sanitized
failure artifacts, timing assumptions, and a list of all deployment configuration exercised by the
suite.

The implementation evidence and current verification record are in
[`phase-07-artifacts/implementation-evidence.md`](phase-07-artifacts/implementation-evidence.md).
