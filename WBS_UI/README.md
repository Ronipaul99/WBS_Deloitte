# WBS Genie UI

A React and TypeScript interface for the tenant-aware WBS generation workflow.

## Getting started

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

The UI expects the FastAPI service at `http://127.0.0.1:8000/api/v1` by default. Override
`VITE_API_URL` only with the API origin for the target environment.

Create a production build with:

```bash
npm run build
```

Run the responsive browser smoke test with:

```bash
npx playwright install chromium
npm run test:e2e
```

## Live full-stack verification

The release-blocking browser suite owns its complete service lifecycle: isolated PostgreSQL,
migrations and drift check, deterministic identities, FastAPI on port `8011`, Vite on port `5187`,
Playwright, and teardown.

Prerequisites are the backend virtual environment, installed frontend dependencies, Playwright
Chromium, and Docker Desktop/Engine with Compose:

```powershell
cd WBS_UI
npx.cmd playwright install chromium
npm.cmd run test:e2e:fullstack
```

The local PostgreSQL container binds only to `127.0.0.1:55432`. The command refuses to reuse an
occupied API/UI port and always removes its container volume, uploads, generated secrets, and child
processes. To use another disposable PostgreSQL database, both `FULLSTACK_DATABASE_URL` containing
the database name `wbs_fullstack` and
`FULLSTACK_DATABASE_DISPOSABLE_ACK=I_ACKNOWLEDGE_THIS_DATABASE_IS_DISPOSABLE` are required.

When Docker is unavailable, this command checks orchestration and browser behavior with a disposable
SQLite file:

```powershell
npm.cmd run test:e2e:fullstack:smoke
```

The SQLite command is a workstation smoke test only. It does not replace the PostgreSQL CI gate.
On CI failure, only screenshots and method/path/status/correlation-ID summaries are retained; auth
headers, cookies, request bodies, and URL query/fragment values are never captured.

## Authentication

- Access tokens are held only in JavaScript memory and are never persisted in browser storage.
- Refresh credentials are managed by the backend as HttpOnly cookies.
- The API client performs one coordinated refresh and retries an expired request once.
- Users with one tenant enter it automatically; users with multiple tenants must choose a workspace.
- Every authenticated user can open Profile Details from the header menu. The Profile view is
  read-only, while the Security view supports local password changes, active-session review,
  revoking another session, and signing out everywhere.
- Enterprise SSO-only accounts receive provider-managed password guidance instead of local password
  controls. WBS Genie session review and revocation remain available. The UI uses explicit
  capabilities returned by `/api/v1/me` and does not infer them from an email address or role.
- Enterprise sign-in is shown only when `VITE_SSO_ENABLED=true` and `VITE_AUTH_MODE` is `oidc` or
  `hybrid`. Hybrid mode retains the local form for controlled rollout and break-glass access; OIDC
  mode hides it. `VITE_SSO_PROVIDER_LABEL` is display text only and never changes backend provider
  configuration.
- The SSO completion route reads only a safe error code, clears transient query parameters, calls
  the existing refresh endpoint, and loads `/me`. It never parses or persists provider tokens.
- Password recovery is hidden by default. Set `VITE_PASSWORD_RECOVERY_ENABLED=true` only after the
  backend migration, SMTP delivery, and `PASSWORD_RECOVERY_ENABLED` are active.
- Reset secrets are read once from the URL fragment, kept only in component memory, and immediately
  removed from the visible URL and browser history.
- Administrators can search members, invite users, change roles, resend or revoke pending
  invitations, and remove members from Settings. Viewer and Editor navigation remains hidden, while
  direct access relies on the API `403` and renders Access Denied.
- Invitation secrets are removed from the URL before rendering and never enter browser storage. New
  local users can create an account from the invitation; existing users sign in before acceptance.
