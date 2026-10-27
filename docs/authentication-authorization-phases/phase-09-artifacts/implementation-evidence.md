# Phase 9 Implementation Evidence

## Repository Scope Completed

- Added `GET /api/v1/auth/sso/start` and `GET /api/v1/auth/sso/callback`.
- Implemented OIDC discovery with exact issuer validation and production endpoint pins.
- Implemented Authorization Code exchange with S256 PKCE and confidential-client authentication.
- Added strict ID-token signature, asymmetric algorithm, key ID, issuer, audience, expiry, issued-at,
  not-before, nonce, verified-email, and provider-directory validation.
- Added encrypted HttpOnly browser state and database-backed expiry/single-use enforcement in
  migration `f2a84d719c35`.
- Replaced direct provider bearer-token acceptance. Every protected API now accepts only an internal
  WBS access token.
- Added immutable directory-namespaced identity resolution and invitation-authorized linking.
- Added invitation-only SSO provisioning, membership creation, and safe audit events.
- Unified SSO with the existing refresh rotation, session inventory, revocation, logout-all, and
  database RBAC controls.
- Added hybrid/OIDC login presentation, token-free completion handling, safe errors, and history
  cleanup in React.
- Added maintenance cleanup for retained OIDC authorization-state records.

## API Contracts

`GET /api/v1/auth/sso/start?return_path=/sso/callback`

- Returns `302` to the configured provider authorization endpoint.
- Sets a short-lived HttpOnly `wbs_oidc_state` cookie scoped to `/api/v1/auth/sso`.
- Rejects a return path outside `OIDC_ALLOWED_RETURN_PATHS` with `400`.
- Returns `404` when SSO is not enabled and `503` when provider discovery is unavailable.

`GET /api/v1/auth/sso/callback`

- Consumes state once before exchanging a code.
- On success, sets the normal HttpOnly WBS refresh cookie and returns `303` to `/sso/callback`.
- Never includes access, refresh, ID, or provider access tokens in the redirect URL.
- On failure, returns only an allowlisted error code: `invalid_state`, `provider_denied`,
  `invalid_response`, `provider_unavailable`, `access_denied`, `identity_conflict`, or `sso_failed`.

The React completion route calls `POST /api/v1/auth/refresh` and `GET /api/v1/me`. It does not parse
provider responses.

## Automated Evidence

Verification completed on 2026-10-23:

```text
python -m ruff check app tests
All checks passed

python -m pytest -q
105 passed

npm run lint
passed

npm run build
passed

npx playwright test
35 passed

npx playwright test tests/sso.spec.ts
3 passed

npm run test:e2e:fullstack:smoke
Alembic upgrade and drift check passed; 15 live browser tests passed
```

The SSO backend suite covers PKCE binding, valid invited and linked identities, browser-bound and
replayed state, unsafe return paths, provider denial, unprovisioned users, provider-claim tenancy
isolation, rejection of provider bearer tokens, issuer/audience/time/nonce/directory failures,
unverified email, invalid signature, disallowed algorithms, multi-audience authorized-party checks,
rotated signing keys, and callback query-string redaction.

Browser verification covers hybrid login controls, internal-session completion, absence of browser
token storage, safe errors, and immediate removal of callback query parameters.

## Deliberate Product Decisions

- Provisioning is invitation-only. JIT provisioning and provider-group-to-role mapping are absent.
- A verified provider email is necessary but not sufficient. A new link also requires an active
  invitation, while repeat login resolves by immutable provider directory plus subject.
- Application logout revokes the WBS session only. Provider single logout is not implemented because
  no provider-specific logout contract has been approved.
- Provider deactivation blocks the next provider authentication but does not automatically revoke an
  already-issued WBS refresh session. Until lifecycle events or introspection are implemented, an
  operator must revoke the user's WBS sessions or wait for the configured refresh expiry.
- Local authentication remains available in `hybrid` mode for controlled migration and break-glass.

## External Gates Still Open

- Choose and register the production provider application and exact callback URI.
- Approve issuer, client/audience, directory, claim names, algorithms, endpoint pins, and secret
  rotation ownership.
- Demonstrate the full flow against a provider test tenant, including key rotation and outage.
- Complete security review and approve invitation-only provisioning.
- Run and record the break-glass exercise in the target environment.
- Approve the provider-deactivation session window and whether provider lifecycle-event integration
  is required. Provider single logout remains a separate decision.

Phase 9 must not be represented as production-approved enterprise SSO until these gates are closed.
