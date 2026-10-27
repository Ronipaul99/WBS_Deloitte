# Authentication and Authorization Completion Specification

Document status: Draft for implementation  
Version: 1.0  
Date: 2026-10-17  
System: WBS Genie  
Scope: React UI, FastAPI API, Neon PostgreSQL, local authentication, RBAC, tenant administration,
account recovery, production hardening, and future SSO

Phase execution documents: [authentication and authorization execution pack](authentication-authorization-phases/README.md)

## 1. Purpose

This document defines the functional and technical work required to complete authentication and
authorization end to end for WBS Genie. It converts the existing security foundation into an
operational, testable, and production-ready user journey.

The specification is organized into implementation phases. Each phase includes:

- functional requirements and user behavior;
- technical design and affected components;
- security requirements;
- test requirements;
- dependencies and migration considerations;
- measurable acceptance criteria.

## 2. Current State

### 2.1 Already implemented

- Local email and password login API.
- Argon2id password hashing.
- Short-lived internal JWT access tokens.
- Opaque rotating refresh tokens stored as hashes.
- HttpOnly refresh cookie support.
- Refresh-token replay detection and family revocation.
- Logout, logout-all, password change, session listing, and session revocation APIs.
- Authentication-version invalidation through `users.auth_version`.
- Login rate limiting by keyed email and IP fingerprints.
- Authentication audit events.
- Development, local, OIDC, and hybrid authentication modes.
- Tenant membership validation for tenant-scoped routes.
- React login, authentication provider, token refresh, sign-out, and tenant selection views.
- Neon migrations for identities, sessions, audit events, and user authentication versions.
- Backend contract tests and mocked Playwright authentication tests.

### 2.2 Incomplete items

- The configured environment still uses the development authentication bypass.
- There is no verified first administrator in local-auth mode.
- Membership roles exist but are not consistently enforced per operation.
- Password recovery and transactional email delivery are not implemented.
- Account and session management APIs do not yet have complete UI screens.
- Tenant administrators cannot manage members through the product.
- The WBS workflow UI still uses mock workflow services.
- Browser tests mock authentication APIs instead of running against live FastAPI.
- Production deployment and monitoring controls are not configured.
- SSO provider integration is not configured.

## 3. Scope

### 3.1 In scope

- Production-quality local authentication.
- Tenant-aware role-based access control.
- Password recovery.
- Account and session management.
- Tenant member and role administration.
- React-to-FastAPI integration for authenticated workflows.
- Live full-stack authentication and authorization tests.
- Production security configuration and operational controls.
- A future SSO implementation that reuses internal sessions and tenant authorization.

### 3.2 Out of scope

- Social login providers.
- User-defined roles in the first release.
- Attribute-based access control beyond tenant membership and fixed roles.
- Machine-to-machine authentication.
- SCIM provisioning in the first SSO release.
- Replacing Neon, FastAPI, React, or the current internal JWT design.

## 4. Actors and Personas

| Actor | Description | Primary capabilities |
|---|---|---|
| Anonymous user | User without a valid access or refresh session | Login and request password recovery |
| Viewer | Tenant member who consumes approved WBS information | Read projects, results, validations, and exports |
| Editor | Tenant member who creates and updates WBS content | Viewer capabilities plus create, upload, generate, edit, and validate |
| Administrator | Tenant member responsible for access and governance | Editor capabilities plus member, role, and tenant administration |
| Platform operator | Deployment and security operator outside the application | Provision first administrator, rotate secrets, migrate DB, monitor events |
| Identity provider | Future OIDC provider | Authenticate enterprise users and return verified identity claims |

## 5. Security Principles

The implementation must follow these rules in every phase:

1. Deny by default. A route is unavailable unless its required permission is explicitly granted.
2. Authentication and tenant authorization are separate decisions.
3. Membership and role data come from the database, not client-controlled claims.
4. Tenant-owned records are always queried with their `tenant_id` boundary.
5. Passwords, reset tokens, refresh tokens, and invitations are never stored in plaintext.
6. Access and recovery errors do not disclose whether an account exists.
7. Access tokens remain short-lived and are never persisted in browser storage.
8. State-changing cookie endpoints validate the browser origin.
9. Administrative and security-sensitive actions create structured audit events.
10. Production configuration fails closed when required security values are absent.
11. Logs, traces, and error messages must not contain passwords, bearer tokens, cookies, or secrets.
12. Tests include both valid behavior and deliberate abuse cases.

## 6. Authorization Model

### 6.1 Fixed roles

The first release uses three tenant-scoped roles:

- `VIEWER`
- `EDITOR`
- `ADMIN`

A user can have a different role in each tenant.

### 6.2 Permission catalog

| Permission | Viewer | Editor | Admin |
|---|---:|---:|---:|
| `project:read` | Yes | Yes | Yes |
| `project:create` | No | Yes | Yes |
| `project:update` | No | Yes | Yes |
| `project:archive` | No | No | Yes |
| `document:read` | Yes | Yes | Yes |
| `document:upload` | No | Yes | Yes |
| `summary:read` | Yes | Yes | Yes |
| `summary:update` | No | Yes | Yes |
| `summary:approve` | No | Yes | Yes |
| `template:read` | Yes | Yes | Yes |
| `template:manage` | No | Yes | Yes |
| `wbs:read` | Yes | Yes | Yes |
| `wbs:generate` | No | Yes | Yes |
| `wbs:update` | No | Yes | Yes |
| `validation:read` | Yes | Yes | Yes |
| `validation:run` | No | Yes | Yes |
| `export:read` | Yes | Yes | Yes |
| `export:create` | No | Yes | Yes |
| `member:read` | No | No | Yes |
| `member:invite` | No | No | Yes |
| `member:update` | No | No | Yes |
| `member:remove` | No | No | Yes |
| `audit:read` | No | No | Yes |

### 6.3 Response behavior

- Missing or invalid access token: `401 Unauthorized` with `WWW-Authenticate: Bearer`.
- Valid user without tenant membership: `403 Forbidden`.
- Valid member without the required permission: `403 Forbidden`.
- Tenant-owned record not found inside the authorized tenant: `404 Not Found`.
- Records in another tenant must not be distinguishable from nonexistent records.

## 7. Functional Requirements

| ID | Requirement |
|---|---|
| AUTH-F-001 | A provisioned local user can sign in with email and password. |
| AUTH-F-002 | A user with a valid refresh session remains signed in after a page reload. |
| AUTH-F-003 | A rotated refresh token cannot be reused without revoking its token family. |
| AUTH-F-004 | A user can sign out from the current session or every session. |
| AUTH-F-005 | A user can change the local password after confirming the current password. |
| AUTH-F-006 | A user can request and complete password recovery without account disclosure. |
| AUTH-F-007 | A user can view and revoke active sessions. |
| AUTH-F-008 | A user with multiple memberships must select an active tenant. |
| AUTH-F-009 | Every tenant operation enforces the permission matrix. |
| AUTH-F-010 | An administrator can list members and manage roles. |
| AUTH-F-011 | An administrator can invite a new tenant member. |
| AUTH-F-012 | The system prevents removal or demotion of the final active administrator. |
| AUTH-F-013 | Authentication and administrative security events are auditable. |
| AUTH-F-014 | The React client recovers once from access-token expiration without losing work. |
| AUTH-F-015 | Production cannot start with the development bypass or insecure cookie settings. |
| AUTH-F-016 | A future enterprise user can authenticate by SSO and receive the same internal session. |

## 8. Non-Functional Requirements

### 8.1 Security

- Password hashes use Argon2id with the library's reviewed recommended parameters.
- New passwords contain at least 12 characters and no more than 128 UTF-8 bytes.
- Access-token lifetime defaults to 15 minutes and is configurable between 5 and 60 minutes.
- Refresh-session lifetime defaults to 7 days and cannot exceed 30 days.
- Password reset and invitation tokens contain at least 256 bits of entropy.
- Password reset tokens expire within 30 minutes and are single-use.
- Authentication responses use `Cache-Control: no-store`.
- Production refresh cookies use `Secure`, `HttpOnly`, and an explicitly configured SameSite mode.
- Rate limiting is enforced in the application and at the deployment edge.

### 8.2 Reliability

- Refresh rotation is transactional.
- Security-sensitive database updates are idempotent where possible.
- Email delivery failure does not expose account existence.
- Expired and revoked sessions are periodically removed according to retention policy.

### 8.3 Performance

- Authorization adds no more than one membership lookup to a tenant request.
- Membership lookups use the composite primary key or an equivalent indexed query.
- Access-token validation does not require a refresh-session lookup on every request.
- Login password verification remains deliberately expensive but bounded by rate limiting.

### 8.4 Accessibility

- All authentication controls have accessible names and keyboard focus states.
- Errors use both visible text and `role="alert"` where appropriate.
- Authentication flows work at 320 px width without horizontal overflow.
- Loading states do not move focus unexpectedly.

### 8.5 Observability

- Audit events have a stable event type, result, subject/user reference, time, and safe metadata.
- Authentication metrics include success, failure, rate limit, refresh reuse, reset, and revocation.
- Alerts must not include token values or password data.

## 9. Phase 1: Activate Local Authentication

### 9.1 Objective

Replace the development bypass with a real Neon-backed administrator session while keeping a safe
recovery path for operators.

### 9.2 Functional specification

- The platform operator provisions the first administrator through the CLI.
- The command prompts for a password interactively.
- The administrator belongs to an active tenant with role `ADMIN`.
- After configuration changes, an unauthenticated browser sees the login screen.
- Correct credentials open the user's tenant or tenant-selection screen.
- Incorrect credentials return a generic error.

### 9.3 Technical specification

1. Run migration verification before provisioning.
2. Use `python -m app.cli create-admin` to create or link:
   - `users`;
   - `auth_identities` with provider `local`;
   - `tenants` when the requested tenant does not exist;
   - `tenant_memberships` with role `ADMIN`.
3. Store `AUTH_JWT_SECRET` and `AUTH_AUDIT_SECRET` as separate deployment secrets.
4. Set `AUTH_MODE=local` and restart the API.
5. Add a startup readiness check that reports unhealthy when local auth is enabled and no active
   administrator exists. It must not reveal administrator details.
6. Keep `AUTH_MODE=development` permitted only when `APP_ENV` is `development` or `test`.

### 9.4 Security controls

- The CLI must never accept a password argument.
- The CLI must reject weak passwords and duplicate local identities.
- Generated secrets must contain at least 32 bytes of entropy.
- Configuration validation must reject empty or short JWT secrets.
- The first-admin procedure must be documented as an audited operator action.

### 9.5 Tests

- CLI creates user, identity, tenant, and membership atomically.
- CLI rejects password mismatch, weak password, and duplicate identity.
- Local mode rejects requests without a bearer token.
- Production mode rejects development authentication.
- Readiness behavior is tested with and without an administrator.
- A live browser can log in to FastAPI using the provisioned test administrator.

### 9.6 Acceptance criteria

- `AUTH_MODE=local` is active in the target environment.
- No protected route succeeds through the development identity.
- At least one active administrator can sign in through React.
- Refresh, reload, and sign-out work against Neon.
- No credential or secret is committed to Git.

## 10. Phase 2: Enforce Role-Based Authorization

### 10.1 Objective

Apply the fixed permission matrix consistently to every tenant-scoped API operation.

### 10.2 Functional specification

- Viewers can inspect WBS information but cannot mutate it.
- Editors can perform normal WBS creation and modification workflows.
- Administrators can perform all editor operations and manage tenant access.
- A user cannot use a role from one tenant in another tenant.
- Unauthorized controls are hidden or disabled in React, but the API remains the authority.

### 10.3 Technical specification

Add an authorization module containing:

```python
ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]]
require_permission(permission: Permission)
require_role(*roles: MembershipRole)
```

`require_permission` must:

1. depend on the authenticated user;
2. load the active tenant and membership from the database;
3. reject inactive tenants or users;
4. resolve the permission from a server-owned mapping;
5. return a typed tenant authorization context used by route queries.

Route queries must filter by both the resource identifier and the authorized `tenant_id`. Loading a
record by ID and checking its tenant afterward is not acceptable.

`GET /me` should return role and derived permissions for each active membership so the UI can render
appropriate controls. The server must never trust those returned permissions when processing a
later request.

### 10.4 API mapping

- Apply read permissions to all `GET` endpoints.
- Apply create/update permissions to document, project, summary, generation, validation, and export
  mutation endpoints.
- Reserve archive/delete and membership changes for administrators.
- Apply permission checks before expensive uploads or background jobs are created.

### 10.5 Security controls

- Default to no permissions for unknown roles.
- Do not encode tenant roles as authoritative access-token claims.
- Use constant error wording for forbidden tenant resources.
- Audit denied administrative operations with safe request metadata.
- Add a code-review checklist requiring authorization dependencies on every new tenant route.

### 10.6 Tests

- Table-driven tests cover every role and permission.
- Each mutation endpoint has at least one insufficient-role test.
- Cross-tenant tests cover guessed project, document, template, WBS, validation, job, and export IDs.
- A changed membership takes effect without requiring a new access token.
- An inactive tenant or membership is rejected.

### 10.7 Acceptance criteria

- Every tenant endpoint maps to a named permission.
- No client-supplied tenant ID or role grants access by itself.
- Viewer, Editor, and Admin behavior matches the matrix.
- Cross-tenant resource tests return the approved non-disclosing response.

## 11. Phase 3: Password Recovery

### 11.1 Objective

Allow local users to regain account access through a secure, single-use recovery flow.

### 11.2 Functional specification

1. A user selects "Forgot password" on the login screen.
2. The user enters an email address.
3. The UI always displays the same confirmation regardless of account existence.
4. An eligible local user receives a time-limited reset link.
5. The link opens the React reset-password screen.
6. The user submits and confirms a new password.
7. All existing sessions are revoked and the user returns to login.
8. Expired, invalid, or already-used links display the same safe recovery error.

### 11.3 Data model

Add `password_reset_tokens`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK to users, cascade delete |
| `token_hash` | String(64) | Unique SHA-256 digest |
| `expires_at` | Timestamp TZ | Maximum 30 minutes |
| `used_at` | Timestamp TZ nullable | Set atomically on success |
| `requested_ip_hash` | String(64) nullable | Keyed audit fingerprint |
| `created_at` | Timestamp TZ | Audit and cleanup |

Only the raw token sent in the email can complete the reset. It must never be persisted or logged.

### 11.4 APIs

#### `POST /api/v1/auth/forgot-password`

Request:

```json
{ "email": "user@example.com" }
```

Response for every syntactically valid email:

```json
{ "message": "If the account is eligible, password reset instructions will be sent." }
```

The endpoint returns `202 Accepted` and applies account and IP rate limits.

#### `POST /api/v1/auth/reset-password`

Request:

```json
{
  "token": "opaque-reset-token",
  "new_password": "a-new-strong-password"
}
```

On success, the endpoint:

- marks the token used in the same transaction;
- hashes the new password;
- increments `auth_version`;
- revokes every refresh session;
- records `password_reset_completed`;
- returns `200 OK` without an access token.

### 11.5 Email integration

Create a provider interface instead of calling a vendor SDK from the route:

```python
class TransactionalEmailProvider(Protocol):
    async def send_password_reset(self, recipient: str, reset_url: str) -> None: ...
```

Required configuration:

- provider credentials from a secret manager;
- verified sender identity;
- `PUBLIC_UI_URL` allowlisted by configuration;
- delivery timeout and retry policy.

Development may use a controlled test inbox. Raw reset URLs must not be written to production logs.

### 11.6 Security controls

- Replace any older unused reset token when a new one is requested.
- Do not send reset mail for inactive users or identities without a local password.
- Prevent open redirects by constructing the URL only from configured `PUBLIC_UI_URL`.
- Use a database row lock when consuming the token.
- Apply password strength and breached-password policy selected for the organization.
- Retain only safe delivery metadata in audit events.

### 11.7 Tests

- Known and unknown accounts return indistinguishable responses and timing ranges.
- Token hash is stored while the raw token is absent from the database and logs.
- Valid reset works once.
- Used and expired tokens fail.
- Concurrent reset attempts allow only one success.
- Successful reset invalidates old access and refresh sessions.
- Email provider failure does not disclose account status.

### 11.8 Acceptance criteria

- The browser flow succeeds from request through password replacement.
- Recovery cannot be used to enumerate users.
- Reset links are single-use, time-limited, and non-replayable.
- Existing sessions become invalid after reset.

## 12. Phase 4: Account and Session Management UI

### 12.1 Objective

Expose the existing account security capabilities through accessible authenticated screens.

### 12.2 Functional specification

Add a Security section under Settings containing:

- profile email and display name as read-only identity information;
- change-password form for local identities;
- active session list;
- current-session indicator;
- revoke action for another session;
- sign out everywhere action with confirmation;
- success and failure notifications.

OIDC-only users must not see the local password form. They should see the configured identity
provider name and a message that password changes are managed by that provider.

### 12.3 Technical specification

- Use the shared authenticated API client for every request.
- Do not display stored IP fingerprints.
- Extend session responses with a server-derived device label or safe user-agent summary if desired.
- After password change or logout-all, clear in-memory access state and navigate to login.
- Do not put sensitive account data in URLs or browser storage.
- Use confirmation dialogs only for session revocation and logout-all.

### 12.4 UI states

- Loading skeleton with stable dimensions.
- Empty state when no other sessions exist.
- Inline current-password validation error.
- Generic request failure with retry.
- Disabled submit while a mutation is in progress.
- Reauthentication screen after global revocation.

### 12.5 Tests

- Local user changes password and must sign in again.
- Incorrect current password is handled without clearing the session.
- Current and other sessions are labeled correctly.
- Revoking another session removes it from the list.
- Logout-all clears the React user and token state.
- OIDC user does not receive a local password form.
- Keyboard, focus, and mobile layout tests pass.

### 12.6 Acceptance criteria

- All existing account security APIs are reachable from the UI.
- No session or password action requires browser storage tokens.
- Error and loading states are accessible and do not leak sensitive details.

## 13. Phase 5: Tenant Member Administration

### 13.1 Objective

Allow administrators to manage tenant access without database or CLI intervention.

### 13.2 Functional specification

Administrators can:

- list active and pending tenant members;
- invite a new member by email and role;
- resend or revoke a pending invitation;
- change an active member's role;
- deactivate or remove a member;
- inspect when membership access was last changed.

The product must prevent:

- a non-admin from accessing member administration;
- an administrator from removing or demoting the final active administrator;
- an administrator from assigning an unknown role;
- an invitation for an email that is already an active member;
- invitation acceptance into a different tenant.

### 13.3 Data model

Add `tenant_invitations`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `tenant_id` | UUID | Indexed tenant FK |
| `email_normalized` | String(320) | Target account |
| `role` | String(20) | Fixed allowed role |
| `token_hash` | String(64) | Unique invitation digest |
| `invited_by` | UUID | Administrator user FK |
| `expires_at` | Timestamp TZ | Configurable, default 72 hours |
| `accepted_at` | Timestamp TZ nullable | Single-use marker |
| `revoked_at` | Timestamp TZ nullable | Administrative revocation |
| `created_at` | Timestamp TZ | Audit ordering |

Add explicit membership activation state only if membership removal must preserve history. Otherwise,
remove the membership and retain the security event as the immutable audit record.

### 13.4 APIs

- `GET /api/v1/tenants/{tenant_id}/members`
- `POST /api/v1/tenants/{tenant_id}/invitations`
- `POST /api/v1/tenants/{tenant_id}/invitations/{invitation_id}/resend`
- `DELETE /api/v1/tenants/{tenant_id}/invitations/{invitation_id}`
- `POST /api/v1/auth/accept-invitation`
- `PATCH /api/v1/tenants/{tenant_id}/members/{user_id}`
- `DELETE /api/v1/tenants/{tenant_id}/members/{user_id}`

Every tenant administration endpoint requires `member:*` permission and a fresh database membership
check.

### 13.5 Audit events

Record at minimum:

- `member_invited`;
- `invitation_resent`;
- `invitation_revoked`;
- `invitation_accepted`;
- `member_role_changed`;
- `member_removed`;
- `member_action_denied`.

Metadata may include tenant ID, actor user ID, target user ID, old role, and new role. Do not place raw
invitation tokens in metadata.

### 13.6 Tests

- Admin can complete each member workflow.
- Viewer and Editor receive `403` for every administration endpoint.
- Final administrator protection is concurrency-safe.
- Invitation is tenant-bound, single-use, and expires correctly.
- Existing user gains membership; new user completes identity setup securely.
- Role changes affect the next request without access-token renewal.
- Cross-tenant member and invitation IDs cannot be accessed.

### 13.7 Acceptance criteria

- Normal tenant access management requires no direct database changes.
- The final active administrator cannot be lost.
- Every administrative change is attributable through audit events.

## 14. Phase 6: Complete Frontend and Workflow Integration

### 14.1 Objective

Remove mock authentication and workflow boundaries so the browser uses the real API for the complete
authenticated WBS journey.

### 14.2 Functional specification

- The app starts in loading, login, tenant selection, or authenticated workspace state.
- The selected tenant determines every project and WBS request.
- Available commands reflect the user's current permissions.
- Access expiration is recovered without discarding an in-progress form or upload selection when
  technically possible.
- Refresh failure returns to login and clears protected React state.
- A role change becomes visible after refetching `/me` or receiving a forbidden response.

### 14.3 Technical specification

1. Replace mock workflow calls in `wbsService.ts` with typed API modules.
2. Route all calls through `apiClient.ts`.
3. Include the selected `tenant_id` in tenant-scoped route paths, never in an authorization header.
4. Keep access tokens only in module memory.
5. Maintain one shared refresh promise to prevent parallel refresh storms.
6. Retry an API request no more than once after refresh.
7. Cancel active requests when the user signs out or changes tenant.
8. Clear tenant-owned caches and job polling when the active tenant changes.
9. Add a permission helper used only for UI presentation:

```typescript
can(permission: Permission): boolean
```

10. Treat server `403` responses as authoritative even when the UI previously showed the control.

### 14.4 Frontend routes or states

- `/login`
- `/forgot-password`
- `/reset-password`
- `/select-workspace`
- `/settings/profile`
- `/settings/security`
- `/settings/members` for administrators
- protected WBS workflow routes or equivalent state-machine boundaries

React Router may be introduced at this phase if direct links, recovery links, and browser navigation
cannot be handled safely by the current state-based application.

### 14.5 Security controls

- Add a production Content Security Policy at the hosting layer.
- Remove unnecessary third-party font or script origins from the login page.
- Avoid rendering server error bodies as HTML.
- Sanitize uploaded filenames before display and storage.
- Never use localStorage or sessionStorage for access, refresh, reset, or invitation tokens.
- Reset and invitation tokens may appear in the initial URL, but must be removed from browser history
  using `history.replaceState` immediately after parsing.

### 14.6 Tests

- Login and reload use the live backend.
- Tenant selection changes API request paths and clears previous tenant data.
- Access-token expiry causes exactly one refresh for concurrent requests.
- Refresh failure clears protected content.
- Viewer does not see editor/admin commands.
- Forced server `403` still blocks an action even if a control is visible.
- No credential appears in web storage, URL history after consumption, console, or error telemetry.

### 14.7 Acceptance criteria

- Authentication mocks are absent from the end-to-end suite.
- The WBS workflow completes through real FastAPI endpoints.
- Permission-aware UI behavior matches API enforcement.
- Tenant switches cannot expose stale data from another tenant.

## 15. Phase 7: Live Full-Stack Verification

### 15.1 Objective

Prove the complete browser, API, and database behavior using repeatable automated tests.

### 15.2 Test environment

- Start FastAPI on an isolated port.
- Start React/Vite configured for that API.
- Use an isolated PostgreSQL/Neon test branch or disposable database.
- Run Alembic migrations before the suite.
- Seed one tenant and users for Viewer, Editor, and Admin roles through supported factories or CLI
  services.
- Capture browser traces and screenshots only on failure.
- Delete test sessions and data after the suite.

### 15.3 Required scenarios

#### Authentication

- Successful and failed login.
- Login rate limit.
- Page reload through refresh cookie.
- Access-token expiry and transparent refresh.
- Parallel request refresh coordination.
- Current logout and logout-all.
- Password change and old-password rejection.
- Password reset success, expiry, reuse, and concurrent consumption.
- Refresh-token replay and family revocation.

#### Authorization

- Viewer, Editor, and Admin positive paths.
- Every role's denied operations.
- Cross-tenant resource IDs.
- Membership removal during an active session.
- Role change during an active session.
- Inactive user and inactive tenant.
- Final administrator protection.

#### Browser security

- Refresh cookie flags.
- No tokens in localStorage or sessionStorage.
- Untrusted Origin rejection.
- CORS rejection for unapproved origins.
- Protected data is removed after authentication loss.
- Mobile and desktop layouts have no overflow or overlapping controls.

### 15.4 Additional verification

- Ruff and backend tests.
- TypeScript production build and ESLint.
- Alembic upgrade, downgrade on disposable data, re-upgrade, and schema drift check.
- Dependency vulnerability scanning.
- Secret scanning.
- Container image scanning when container builds are introduced into CI.

### 15.5 Acceptance criteria

- All required tests run in CI without external manual setup.
- Tests contain no production credentials.
- Failed tests provide enough safe diagnostics to reproduce the problem.
- Release is blocked on authentication, authorization, migration, or security-scan failures.

## 16. Phase 8: Production Hardening and Operations

### 16.1 Objective

Deploy the completed local authentication system with secure defaults, monitoring, and recovery
procedures.

### 16.2 Configuration

Required production values:

```dotenv
APP_ENV=production
AUTH_MODE=local
AUTO_CREATE_TABLES=false
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_JWT_SECRET=<secret-manager-reference>
AUTH_AUDIT_SECRET=<different-secret-manager-reference>
CORS_ORIGINS=https://<approved-ui-host>
PUBLIC_UI_URL=https://<approved-ui-host>
```

Database credentials, OIDC credentials, email-provider credentials, JWT secrets, and audit secrets
must come from a secret manager rather than source-controlled environment files.

### 16.3 Edge and hosting controls

- Terminate TLS with supported protocols and certificates.
- Redirect HTTP to HTTPS.
- Apply HSTS after HTTPS validation.
- Rate-limit authentication paths by IP and broader abuse signals.
- Limit request body size at the proxy and application.
- Configure a restrictive Content Security Policy for React.
- Restrict allowed methods and origins.
- Prevent caching of authenticated HTML and authentication responses.

### 16.4 Monitoring and alerting

Alert on:

- repeated login failures across accounts;
- repeated failures against a single privileged account;
- refresh-token reuse;
- password reset abuse;
- administrator role changes;
- final-administrator protection attempts;
- unexpected production configuration failure;
- authorization-denial spikes;
- database migration failure.

Metrics and events must use IDs or keyed fingerprints rather than passwords, tokens, or raw cookie
contents.

### 16.5 Retention and cleanup

- Define authentication event retention with legal and privacy stakeholders.
- Periodically delete expired refresh, reset, and invitation records.
- Preserve required administrative audit history.
- Test backup restoration and tenant data consistency.

### 16.6 Incident procedures

Document procedures for:

- JWT signing-secret exposure;
- database credential exposure;
- refresh-token theft or replay alert;
- administrator account compromise;
- email-provider compromise;
- accidental removal of access;
- rollback after a failed authentication deployment.

Signing-secret rotation must be paired with refresh-session revocation when forced reauthentication
is required.

### 16.7 Acceptance criteria

- Production refuses all insecure configuration combinations.
- Security monitoring receives and correlates authentication events.
- Operators can rotate secrets and revoke sessions using documented procedures.
- Backup and restore tests include authentication and membership tables.
- Deployment passes the complete Phase 7 verification suite.

## 17. Phase 9: Enterprise SSO

### 17.1 Objective

Add enterprise OIDC sign-in without weakening or duplicating the internal tenant authorization and
session model.

### 17.2 Functional specification

- The login screen offers the configured enterprise sign-in command.
- The provider authenticates the user.
- The backend maps the verified provider subject to `auth_identities`.
- A provisioned user receives the same internal access token and refresh session used by local auth.
- Unprovisioned users receive a non-disclosing access-pending or denied result according to policy.
- Local authentication can remain enabled during migration through `AUTH_MODE=hybrid`.

### 17.3 Recommended technical flow

Use an OIDC Authorization Code flow with PKCE and a backend callback:

1. `GET /api/v1/auth/sso/start` creates cryptographically random state, nonce, and PKCE values.
2. The backend stores short-lived state in a protected cookie or server-side record.
3. The browser is redirected to the provider.
4. `GET /api/v1/auth/sso/callback` validates state and exchanges the authorization code.
5. The backend validates issuer, audience, signature, nonce, time claims, and approved algorithm.
6. Identity lookup uses `(provider, subject)` and, where required, the provider tenant identifier.
7. The backend creates the normal internal refresh session and redirects to an allowlisted UI path.
8. The React client calls the normal refresh endpoint to obtain an internal access token.

This approach keeps provider access and refresh tokens out of browser storage and lets local and SSO
users share the same authorization model.

### 17.4 Provisioning policy

Default policy: no unrestricted just-in-time tenant access.

An SSO identity may be linked when:

- an administrator has invited the normalized verified email; or
- a pre-provisioned user record contains the approved identity; or
- an explicitly configured organization policy permits JIT creation into a limited default role.

Provider tenant/domain claims are identity evidence, not application tenant authorization.

### 17.5 Security controls

- Pin approved issuer, audience, redirect URI, and signing algorithms.
- Validate state, nonce, PKCE, token times, and signature.
- Prevent identity linking solely from an unverified email claim.
- Reject ambiguous accounts with multiple possible links.
- Store provider client secrets only in the secret manager.
- Audit identity linking, first login, denied provisioning, and unlinking.
- Provide a tested break-glass administrator procedure independent of provider availability.

### 17.6 Tests

- Valid provider callback creates an internal session.
- Invalid state, nonce, issuer, audience, algorithm, signature, and expired code are rejected.
- Unprovisioned identities cannot choose a tenant.
- Invitation-based linking is single-use and tenant-bound.
- Local and SSO identities linked to the same user receive identical tenant permissions.
- Provider outage does not remove the documented break-glass path.

### 17.7 Acceptance criteria

- No provider token is persisted in browser storage.
- SSO identity does not bypass database membership checks.
- Hybrid migration and rollback are documented and tested.
- Provider configuration and security review are complete.

## 18. API Contract Summary

### 18.1 Existing authentication APIs

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Anonymous | Local sign-in |
| POST | `/api/v1/auth/refresh` | Refresh cookie | Rotate session and issue access token |
| POST | `/api/v1/auth/logout` | Refresh cookie | Revoke current refresh family |
| POST | `/api/v1/auth/logout-all` | Bearer | Revoke all sessions and access versions |
| POST | `/api/v1/auth/change-password` | Bearer | Replace local password and revoke sessions |
| GET | `/api/v1/auth/sessions` | Bearer | List active sessions |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Bearer | Revoke a session |
| GET | `/api/v1/me` | Bearer | Return current user and memberships |

### 18.2 Planned APIs

| Method | Path | Authentication | Permission |
|---|---|---|---|
| POST | `/api/v1/auth/forgot-password` | Anonymous | Rate limited |
| POST | `/api/v1/auth/reset-password` | Reset token | Single-use token |
| POST | `/api/v1/auth/accept-invitation` | Invitation token | Single-use token |
| GET | `/api/v1/tenants/{tenant_id}/members` | Bearer | `member:read` |
| POST | `/api/v1/tenants/{tenant_id}/invitations` | Bearer | `member:invite` |
| POST | `/api/v1/tenants/{tenant_id}/invitations/{id}/resend` | Bearer | `member:invite` |
| DELETE | `/api/v1/tenants/{tenant_id}/invitations/{id}` | Bearer | `member:invite` |
| PATCH | `/api/v1/tenants/{tenant_id}/members/{user_id}` | Bearer | `member:update` |
| DELETE | `/api/v1/tenants/{tenant_id}/members/{user_id}` | Bearer | `member:remove` |
| GET | `/api/v1/auth/sso/start` | Anonymous | SSO enabled |
| GET | `/api/v1/auth/sso/callback` | OIDC state | SSO enabled |

## 19. Audit Event Catalog

| Event | Result values | Required safe context |
|---|---|---|
| `login` | success/failure | user ID when known, subject/IP fingerprints |
| `login_rate_limited` | failure | subject/IP fingerprints |
| `refresh` | success/failure | user ID, session family ID |
| `refresh_reuse` | failure | user ID, session family ID |
| `logout` | success | user/session when known |
| `logout_all` | success | user ID |
| `password_changed` | success/failure | user ID |
| `password_reset_requested` | accepted | fingerprints, no raw email |
| `password_reset_completed` | success/failure | user ID when known |
| `session_revoked` | success/failure | actor user ID, target session ID |
| `member_invited` | success/failure | actor, tenant, role, target fingerprint |
| `member_role_changed` | success/failure | actor, target, tenant, old/new roles |
| `member_removed` | success/failure | actor, target, tenant |
| `sso_login` | success/failure | provider, user ID when known |
| `identity_linked` | success/failure | provider, user ID |

Audit details must be structured JSON with an allowlist of fields. Arbitrary request bodies and
headers must not be copied into events.

## 20. Migration Strategy

For each phase containing schema changes:

1. Create a Neon development branch.
2. Update SQLAlchemy models.
3. Generate an Alembic migration.
4. Review constraints, indexes, defaults, foreign-key deletion behavior, and existing-data impact.
5. Test upgrade from the current production revision.
6. Run `alembic check`.
7. Test downgrade only on disposable data.
8. Run backend and full-stack tests.
9. Apply the migration before the application deployment.
10. Use a forward-fix migration when production rollback could lose security or audit data.

Security tokens and sessions must never be copied from production into lower environments.

## 21. Delivery Order and Dependencies

| Order | Phase | Depends on | Primary output |
|---:|---|---|---|
| 1 | Activate local authentication | Existing migrations and CLI | Real administrator login |
| 2 | RBAC enforcement | Phase 1 | Permission-protected API |
| 3 | Password recovery | Email-provider decision | Secure account recovery |
| 4 | Account/session UI | Phase 1 | Self-service security settings |
| 5 | Tenant administration | Phase 2 and email interface | Admin member management |
| 6 | Frontend/workflow integration | Phases 1-5 | Real authenticated product journey |
| 7 | Live full-stack verification | Phase 6 | Release-blocking test suite |
| 8 | Production hardening | Phase 7 and hosting decisions | Production local auth release |
| 9 | Enterprise SSO | Identity-provider configuration | Hybrid or SSO release |

Password recovery and account/session UI may be developed in parallel after Phase 1. Tenant
administration must not ship before RBAC enforcement.

## 22. Overall Definition of Done

Authentication and authorization are complete end to end when all statements below are true:

- Production and staging have no development authentication bypass.
- A real user can log in through React and obtain a Neon-backed session.
- Reload, access expiry, refresh rotation, logout, and logout-all work through the browser.
- Password change and password recovery work without account disclosure.
- Users can inspect and revoke sessions.
- Every tenant endpoint enforces the documented permission matrix.
- Cross-tenant access is rejected and covered by tests.
- Administrators can safely manage tenant members and roles.
- The final active administrator cannot be removed or demoted.
- Authentication, recovery, and administrative changes create safe audit events.
- Access, refresh, reset, and invitation tokens are absent from browser storage and logs.
- Full-stack Playwright tests use live React, FastAPI, and an isolated migrated database.
- Production cookies, HTTPS, CORS, CSP, secrets, rate limits, monitoring, and cleanup are configured.
- All backend tests, frontend tests, linters, builds, migrations, and security scans pass in CI.
- SSO, when enabled, issues the same internal session and never bypasses tenant membership checks.

## 23. Required Decisions Before Implementation

The following decisions should be confirmed before their dependent phases begin:

1. Transactional email provider and verified sender domain.
2. Production and staging UI/API URLs.
3. Password policy beyond the current minimum and maximum length.
4. Invitation expiry and password-reset expiry.
5. Authentication audit retention period.
6. Whether membership removal is hard deletion or retained inactive history.
7. Production hosting, proxy, secret manager, monitoring, and alerting platforms.
8. SSO provider, provider tenant policy, and JIT provisioning policy.
9. Break-glass administrator ownership and review schedule.

These decisions must be recorded in the implementation pull requests and deployment runbook rather
than left as implicit environment behavior.
