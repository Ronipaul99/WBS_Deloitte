# Phase 9: Enterprise SSO

## Phase Status

Repository implementation completed on 2026-10-23. Real-provider registration, claim confirmation,
staging protocol evidence, security approval, and a current break-glass exercise remain deployment
gates. See `phase-09-artifacts/implementation-evidence.md`.

## Outcome

Enterprise users authenticate through the approved OIDC provider and receive the same internal WBS
access and refresh sessions as local users. SSO never bypasses tenant membership or RBAC.

## Execution Context

Existing support:

- `AuthIdentity` separates provider identity from the domain user;
- preliminary external bearer-token validation existed and is replaced in this phase by the
  backend-managed code flow and internal WBS sessions;
- settings support `oidc` and `hybrid` modes;
- internal access tokens, refresh sessions, RBAC, and tenant selection already exist;
- invitation-based provisioning is available after Phase 5.

Recommended target design: backend-managed OIDC Authorization Code flow with PKCE, followed by an
internal WBS refresh session. Do not persist provider tokens in browser storage.

## Required Provider Decisions

- provider and tenant/directory;
- OIDC discovery URL, issuer, audience/client ID, and approved algorithms;
- confidential client or public-client policy;
- registered redirect and logout URIs;
- claims used for immutable subject, email, display name, and provider tenant;
- group/claim size behavior;
- invitation-only versus approved JIT provisioning;
- local fallback and break-glass policy;
- single logout requirement;
- provider key rotation and outage behavior.

## Files Expected to Change

- `backend/app/core/config.py`
- `backend/app/core/security.py`
- `backend/app/api/routes/auth.py` or new `sso.py`
- `backend/app/services/sso.py` (new)
- state/nonce persistence model or Redis service
- `backend/app/models/auth.py` if additional provider metadata is required
- new Alembic migration when persistence changes
- `backend/app/schemas/auth.py`
- `backend/tests/test_sso.py` (new)
- login and callback handling in React
- Settings identity display
- deployment secret/configuration
- SSO runbooks and documentation

## Target Flow

### 1. Start authorization

`GET /api/v1/auth/sso/start` must:

1. verify SSO mode and provider readiness;
2. generate random state, nonce, and PKCE verifier/challenge;
3. persist state server-side or in a protected, integrity-checked, short-lived cookie;
4. bind state to the browser and an allowlisted internal return path;
5. redirect to the provider authorization endpoint.

Do not accept an arbitrary return URL. Store only a normalized relative path from an allowlist.

### 2. Handle callback

`GET /api/v1/auth/sso/callback` must:

1. reject provider errors safely;
2. validate and consume state once;
3. exchange the authorization code using PKCE;
4. validate issuer, audience, signature, algorithm, nonce, and time claims;
5. extract the provider's immutable subject and provider tenant/directory ID;
6. resolve or link the application identity;
7. check active user and tenant provisioning;
8. create the normal internal refresh-session family;
9. set the HttpOnly refresh cookie;
10. redirect to the allowlisted UI completion path without tokens in the URL.

The React app then calls the existing refresh endpoint to receive an internal access token.

### 3. Implement identity resolution

Primary lookup uses `(provider, subject)`. Include provider tenant/directory in the subject namespace
or explicit columns where required.

Linking rules:

- never link solely from an unverified email;
- invitation acceptance may authorize linking to an existing user after verified provider login;
- conflicting local/external identities require an explicit authenticated linking process;
- an identity can map to only one user;
- account-linking changes are audited;
- removal of one identity must not delete the user while other identities or tenant ownership remain.

### 4. Apply provisioning policy

Recommended default: invitation/pre-provisioning required.

For an unlinked verified identity:

- check a matching active tenant invitation using normalized verified email;
- consume the invitation and link identity transactionally; or
- show access pending/denied without disclosing other tenant data.

If approved JIT provisioning is introduced, restrict it by provider tenant and verified domain, assign
the minimum role, and never infer application tenant membership solely from provider group claims
without an explicit mapping policy.

### 5. Unify internal sessions

After identity resolution, issue the same internal access and refresh design used by local auth.

Benefits:

- one React API client;
- one session-management UI;
- one logout-all mechanism;
- immediate database role/membership changes;
- no provider token in application JavaScript;
- consistent audit events.

Document whether local logout also redirects to provider logout. Do not depend on provider logout for
application session revocation.

### 6. Build React SSO journey

Login screen:

- show enterprise sign-in only when enabled by public configuration;
- keep local form in `hybrid` mode;
- use a clear provider-neutral or approved provider label;
- prevent multiple authorization starts while redirecting.

Callback/completion:

- do not parse provider tokens;
- call internal refresh after backend redirect;
- load `/me` and tenant memberships;
- show safe access-pending/denied states;
- remove transient query parameters from history.

Settings:

- display linked provider name;
- hide local password change for SSO-only users;
- support reviewed link/unlink operations only if included in product scope.

### 7. Configure logout and lifecycle

- Local application logout always revokes internal refresh sessions.
- Optional provider logout uses an exact registered post-logout URI.
- Disabled provider users must be blocked according to token/session policy and sync strategy.
- Define how quickly provider deactivation affects an existing internal session.
- For high-risk environments, add periodic provider revalidation or shorter internal session lifetime.

### 8. Preserve break-glass access

Maintain at least one tightly controlled local administrator or documented operator recovery mechanism
unless organizational policy forbids it. Protect it with a strong unique credential, monitoring, and
scheduled access review.

Do not make production recovery depend entirely on the same provider being recovered.

## Configuration Requirements

Expected secret-managed values include:

```dotenv
AUTH_MODE=hybrid
OIDC_ISSUER=https://<provider-issuer>
OIDC_AUDIENCE=<client-id-or-api-audience>
OIDC_JWKS_URL=https://<provider-jwks>
OIDC_CLIENT_ID=<client-id>
OIDC_CLIENT_SECRET=<secret-manager-reference>
OIDC_REDIRECT_URI=https://<api-host>/api/v1/auth/sso/callback
```

Prefer OIDC discovery with issuer pinning when supported. Do not allow runtime request parameters to
override issuer, redirect URI, or client ID.

## Test Plan

Protocol validation:

- valid authorization code flow;
- missing/mismatched/replayed state;
- invalid nonce;
- PKCE mismatch;
- wrong issuer/audience;
- disallowed algorithm;
- invalid signature;
- expired/not-yet-valid token;
- provider error callback;
- signing-key rotation.

Identity and authorization:

- linked identity login;
- invited identity first login;
- unprovisioned identity denial;
- unverified email cannot link;
- ambiguous/conflicting identity denial;
- SSO and local identities for one user receive identical memberships;
- provider tenant claim alone grants no WBS tenant access;
- role changes take effect without provider token renewal.

Browser and operations:

- provider tokens never appear in storage, URL, logs, or traces;
- callback redirects only to approved UI path;
- refresh/reload uses internal session;
- local and optional provider logout behavior;
- provider outage and break-glass procedure;
- hybrid-mode rollback to local login.

Use a standards-compliant local OIDC test provider or verified provider test tenant. Do not weaken
validation through test-only production code paths.

## Security Review Checklist

- [x] Authorization Code with PKCE is used.
- [x] State and nonce are random, expiring, browser-bound, and single-use.
- [x] Issuer, audience, algorithms, signature, and times are pinned and validated.
- [x] Redirect paths are exact and allowlisted; application logout is local-only in this scope.
- [x] Identity linking uses immutable subject, not email alone.
- [x] Provider tokens never reach browser storage.
- [x] Database membership remains the authorization source.
- [x] Invitation-only provisioning is implemented; production approval is pending.
- [ ] Break-glass access and provider outage procedures are tested in the target environment.

## Rollout

1. Configure provider test tenant and exact callback URIs.
2. Validate protocol and identity tests in isolation.
3. Deploy `hybrid` mode to staging.
4. Link a controlled pilot group through invitations.
5. Monitor login, linking, denial, and provider errors.
6. Roll out by tenant or cohort.
7. Keep local fallback during the approved migration window.
8. Change to `oidc` only after recovery and break-glass policy is accepted.

## Rollback

In `hybrid` mode, disable the enterprise sign-in entry point and preserve local sessions while fixing
the provider flow. Revoke suspicious SSO-created internal sessions when protocol or identity-linking
issues occur. Do not delete linked identities during an outage.

## Exit Criteria

- [x] Enterprise sign-in completes through the backend code flow and PKCE in automated tests.
- [x] Provider tokens are absent from application JavaScript and storage.
- [x] Identity linking and invitation provisioning are safe and audited.
- [x] SSO users receive normal internal sessions and database permissions.
- [x] Provider claims do not bypass tenant membership.
- [ ] Protocol, abuse, browser, outage, and rollback tests pass against the approved provider tenant.
- [ ] Provider configuration and security review are approved.
- [ ] Break-glass procedure has current test evidence.

## Final Handoff

Provide provider metadata references, claim mapping, linking/provisioning policy, migration cohort
plan, protocol test evidence, logout behavior, break-glass runbook, alerts, residual risks, and the
date for local-auth migration review.
