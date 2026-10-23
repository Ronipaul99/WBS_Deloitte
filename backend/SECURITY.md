# Security Model

## Authentication design

- Passwords are hashed with Argon2id through `pwdlib`; plaintext passwords are never stored.
- Access tokens are signed JWTs with issuer, audience, type, expiry, not-before, session, token ID,
  and authentication-version claims. Their default lifetime is 15 minutes.
- Refresh tokens are 384-bit opaque values. Only SHA-256 digests are stored in the database.
- Every refresh rotates the token in a locked transaction. Reuse of an old token revokes the
  entire token family.
- Refresh cookies are HttpOnly, scoped to `/api/v1/auth`, and SameSite. Production refuses to
  start unless Secure cookies are enabled.
- Logout-all and password changes increment `users.auth_version`, immediately invalidating all
  previously issued access tokens, and revoke every refresh session.
- Login errors do not reveal whether an account exists. Argon2 work is also performed for unknown
  accounts to reduce timing differences.
- Login failures are rate-limited by keyed email and client-IP fingerprints stored in the shared
  database. Raw email addresses and IP addresses are not written to authentication events.
- Password-reset requests return the same accepted response for eligible and ineligible accounts.
  Reset secrets contain 256 bits of entropy, are persisted only as SHA-256 digests, expire within
  30 minutes, and are atomic single-use credentials.
- Generated reset links use a configured UI origin and put the secret in the URL fragment, which
  is removed immediately by React and is not sent to the UI host in the HTTP request.
- Successful resets revoke every refresh session and increment the user's authentication version.
  Delivery failures invalidate the associated reset record without exposing account eligibility.
- The current-user response exposes only identity provider names and explicit password/session
  capability flags. It never returns identity subjects, password hashes, or raw session fingerprints.
- Session revocation checks ownership in the database and writes a keyed, token-free audit event.
- Tenant invitation secrets contain 256 bits of entropy, are stored only as SHA-256 digests, expire
  after 72 hours by default, rotate on resend, and are consumed once with a conditional database
  update. Delivery failure revokes the invitation.
- Enterprise SSO uses Authorization Code with S256 PKCE. State, nonce, and verifier are random;
  their browser copy is encrypted and HttpOnly, while a database digest enforces expiry and
  single-use consumption. Provider tokens are processed only by the backend callback.
- Discovery issuer and production authorization, token, and JWKS endpoints are pinned. ID tokens
  require an approved asymmetric algorithm, current signature key, issuer, audience, time claims,
  nonce, immutable subject, verified email, and approved provider directory.
- Application APIs accept only WBS-issued access tokens. SSO and local users share the same refresh
  rotation, session revocation, database memberships, and RBAC path.

## Authorization and tenancy

- Authentication does not grant tenant access. Every tenant-owned route resolves the user from
  the validated token and checks `tenant_memberships` in the database.
- Tenant IDs supplied by the client are treated only as resource identifiers, never as proof of
  access.
- Local credentials are stored in `auth_identities`, separate from `users`, so an OIDC identity can
  be linked without changing domain ownership records.
- Member role changes and removals lock the tenant row through commit. The active-administrator
  count and mutation share that transaction, preventing concurrent changes from removing the final
  active administrator.
- Existing users must authenticate with the invited email. Possession of an invitation can create a
  new local identity, but cannot attach a membership to a different existing identity.
- Administrative and cross-tenant denial events contain keyed email fingerprints and allowlisted
  UUID/role metadata only; invitation tokens and raw email addresses are excluded.

## Browser protections

- The React client never writes access or refresh tokens to localStorage or sessionStorage.
- Cookie-authenticated state-changing endpoints validate browser origins against the exact CORS
  allowlist. Wildcard CORS is rejected at startup.
- API responses include MIME-sniffing, frame, referrer, and permissions-policy headers. Production
  responses also include HSTS.
- Authentication responses use `Cache-Control: no-store`.
- Production validates exact HTTPS origins, TLS database connections, explicit proxy trust,
  migration-aware readiness, and authenticated monitoring before startup.
- The production UI artifact self-hosts fonts and applies a restrictive CSP without script
  exceptions; protected SPA HTML is not cached.
- A final API `401` after the single refresh attempt clears user and tenant state immediately, so
  protected workspace content is removed when access is lost.

## Deployment checklist

1. Use a managed HTTPS endpoint and set `APP_ENV=production`.
2. Set `AUTO_CREATE_TABLES=false`, run `alembic upgrade head` as a deployment step, and use a
   restricted migration credential separately from the pooled runtime credential.
3. Set `AUTH_MODE=local`, `oidc`, or `hybrid`; production rejects the development bypass.
4. Generate independent high-entropy `AUTH_JWT_SECRET` and `AUTH_AUDIT_SECRET` values in the
   deployment secret manager. Rotate them through a planned forced reauthentication.
5. Set `AUTH_COOKIE_SECURE=true` and keep `AUTH_COOKIE_SAMESITE=lax` unless a reviewed cross-site
   deployment requires `none`.
6. Restrict `CORS_ORIGINS` to the deployed UI origins. Do not use wildcards.
7. Provision administrators with `python -m app.cli create-admin`; do not pass passwords as command
   arguments or seed production passwords through environment variables.
8. Apply infrastructure rate limits to `/api/v1/auth/*` in addition to the database-backed login
   control, and alert on `refresh_reuse`, repeated login failures, and administrator changes.
9. Back up the database, test restoration, scan dependencies and container images, and run the
   backend, lint, build, and browser test suites before promotion.
10. For recovery, verify the SMTP sender/domain, use an HTTPS `PUBLIC_UI_URL`, enable the backend
    before the UI entry point, apply edge rate limits, and schedule retained-token cleanup.
11. For invitations, deploy `e6b91f2c4a73` first, verify the acceptance route and sender, enable
    `TENANT_INVITATIONS_ENABLED`, monitor delivery/resend events, and schedule invitation cleanup.
12. Schedule `python -m app.cli run-maintenance`, connect authenticated metrics to owned alerts, and
    complete the Phase 8 restore and incident exercises before enabling production traffic.
13. For SSO, apply `f2a84d719c35`, register the exact callback, pin reviewed provider metadata,
    inject independent client/state secrets, test key rotation, and begin in `AUTH_MODE=hybrid`.
14. Keep a monitored local administrator until the approved recovery policy replaces it. Do not
    promote `AUTH_MODE=oidc` solely because the happy-path provider login succeeds.

## Operational notes

Regular logout revokes the refresh family. Its already-issued access token can remain usable until
the short expiry; use logout-all for immediate invalidation. If a signing secret or database
credential is exposed, rotate it, revoke active sessions, review `auth_events`, and investigate
tenant data access logs.

For email delivery incidents, disable `VITE_PASSWORD_RECOVERY_ENABLED` and then
`PASSWORD_RECOVERY_ENABLED`. Do not expose raw links through logs or operator messages. The test
email provider is accepted only under `APP_ENV=test` and must never be used as a production fallback.

For invitation delivery incidents, set `TENANT_INVITATIONS_ENABLED=false` to stop new sends while
leaving existing membership administration available. Revoke affected active invitations, review
`tenant_invitation_delivery` events, and never send raw invitation URLs through logs or tickets.
