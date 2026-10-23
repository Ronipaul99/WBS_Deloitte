# Phase 3: Password Recovery

## Phase Status

Code complete and locally verified. SMTP sender/domain validation, staging delivery evidence, edge
rate limits, and production scheduling remain deployment responsibilities.

## Outcome

An eligible local user can request a non-disclosing reset email, replace the password with a
single-use token, and have every existing session invalidated.

## Execution Context

Reuse these existing controls:

- password hashing and validation in `backend/app/core/passwords.py`;
- auth-version and session revocation logic in `backend/app/api/routes/auth.py` and
  `backend/app/services/auth.py`;
- audit fingerprinting and rate-limit patterns;
- local identities in `backend/app/models/auth.py`;
- login UI patterns in `WBS_UI/src/views/LoginScreen.tsx`;
- shared API handling in `WBS_UI/src/services/apiClient.ts`.

Do not build recovery until a transactional email provider, verified sender, and allowed public UI
URL have been selected for the target environment.

## Required Decisions

- transactional email provider;
- verified sender address/domain;
- reset expiry, with a maximum of 30 minutes;
- email retry and timeout policy;
- password policy beyond current length requirements;
- test inbox strategy;
- reset-event retention period.

Resolved for this implementation:

- vendor-neutral SMTP provider with a test-only in-memory fake;
- sender address supplied through `EMAIL_FROM` and verified operationally with the SMTP provider;
- 30-minute maximum reset lifetime;
- 10-second delivery timeout with two retries;
- shared password policy of 12 or more characters and no more than 128 UTF-8 bytes, without
  composition rules;
- in-memory test inbox restricted to `APP_ENV=test`;
- 30-day used/expired reset-record retention.

## Files Expected to Change

- `backend/app/models/auth.py`
- `backend/app/models/__init__.py`
- new Alembic migration
- `backend/app/schemas/auth.py`
- `backend/app/services/auth.py`
- `backend/app/api/routes/auth.py`
- `backend/app/core/config.py`
- `backend/app/services/email.py` (new provider interface)
- `backend/tests/test_password_recovery.py` (new)
- `WBS_UI/src/views/ForgotPasswordScreen.tsx` and CSS
- `WBS_UI/src/views/ResetPasswordScreen.tsx` and CSS
- auth navigation/routing state
- `.env.example`, README, and security documentation

## Work Breakdown

### 1. Add the reset-token model

Create `PasswordResetToken` with:

- UUID primary key;
- `user_id` FK with cascade delete;
- unique SHA-256 `token_hash`;
- timezone-aware `expires_at`;
- nullable `used_at`;
- optional keyed request IP and user-agent fingerprints;
- creation timestamp.

Add indexes for token lookup and user/creation cleanup. Do not store a raw reset token.

Generate and review an Alembic migration. Test upgrade, schema drift, downgrade on disposable data,
and re-upgrade.

### 2. Introduce an email abstraction

Define a provider protocol such as:

```python
class TransactionalEmailProvider(Protocol):
    async def send_password_reset(self, recipient: str, reset_url: str) -> None: ...
```

The route or model must not import a vendor SDK. Implement provider configuration, timeout, safe
error mapping, and a test fake. Production must fail startup if recovery is enabled without complete
email configuration.

Build reset URLs only from configured `PUBLIC_UI_URL`. Never accept a callback URL from the request.

### 3. Implement forgot-password

Add `POST /api/v1/auth/forgot-password`.

Processing order:

1. validate and normalize email;
2. compute safe fingerprints;
3. apply account and IP rate limits;
4. look up a local identity and active user;
5. return the same `202` response for every syntactically valid request;
6. for eligible users, invalidate older unused reset tokens;
7. generate at least 256 bits of random token entropy;
8. persist only its digest and expiry;
9. deliver the reset link through the provider;
10. record a non-disclosing audit event.

Unknown, inactive, and OIDC-only accounts must follow a timing-normalized safe path.

### 4. Implement reset-password

Add `POST /api/v1/auth/reset-password`.

Use a transaction and row lock to:

1. hash the submitted raw token and load the record;
2. verify unused and unexpired status;
3. load the active local identity;
4. validate and hash the new password;
5. mark the reset token used;
6. invalidate every other unused token for the user;
7. increment `users.auth_version`;
8. revoke every refresh session;
9. record `password_reset_completed`;
10. commit once.

Return a generic invalid-or-expired response for every unusable token. Do not automatically log the
user in after a reset.

### 5. Build the React flow

Forgot-password screen:

- email field with autocomplete;
- neutral submit state;
- identical confirmation for known and unknown accounts;
- link back to login;
- safe rate-limit message without account detail.

Reset-password screen:

- new password and confirmation;
- show/hide controls;
- accessible validation;
- expired/invalid state;
- success state leading to login.

Parse the reset token once, hold it in memory, and immediately remove it from the visible URL and
browser history with `history.replaceState`. Never send it to analytics or error monitoring.

### 6. Add cleanup

Create a scheduled maintenance task or documented job that deletes expired/used reset rows after the
approved retention window. Cleanup must not affect active tokens.

## API Contract

Forgot request:

```json
{ "email": "user@example.com" }
```

Always-accepted response:

```json
{ "message": "If the account is eligible, password reset instructions will be sent." }
```

Reset request:

```json
{
  "token": "opaque-token",
  "new_password": "new-password-value"
}
```

The response contains only a completion message, never a token or account profile.

## Test Plan

- Known and unknown emails return the same status and body.
- Inactive and OIDC-only identities do not receive local reset access.
- Application and edge rate limits are exercised.
- Database contains the token digest, not the raw value.
- Reset works once and fails on reuse.
- Expired token fails.
- Two concurrent reset submissions produce only one success.
- New password invalidates old access and refresh sessions.
- Email failure does not change the external response into account disclosure.
- Reset token is absent from logs, traces, screenshots, and browser storage.
- Mobile and keyboard flows pass.

## Security Review Checklist

- [ ] Reset responses cannot enumerate users.
- [ ] Raw tokens are never stored or logged.
- [ ] Reset URL origin is configuration-owned.
- [ ] Token consumption is atomic and single-use.
- [ ] Password policy is enforced server-side.
- [ ] Successful reset revokes all sessions and access versions.
- [ ] Email templates do not include unnecessary personal data.
- [ ] Provider API credentials are secret-managed.

## Rollout and Rollback

Deploy the schema and backend before exposing the UI link. Enable email delivery in staging first and
verify the actual sender, links, expiry, and spam handling.

If delivery fails in production, hide or disable the forgot-password entry point through reviewed
configuration while preserving authenticated password change and operator recovery. Do not log raw
reset links as a fallback.

## Exit Criteria

- [x] Forgot and reset APIs satisfy the non-disclosure contract.
- [ ] Transactional email delivery works in staging and production configuration is validated.
- [x] React recovery flow works from request to subsequent login.
- [x] Reset token is hashed, single-use, and short-lived.
- [x] All sessions and access versions are revoked after reset.
- [x] Cleanup and operational failure procedures are documented.
- [x] Unit, integration, abuse, and browser tests pass locally.

## Implementation Evidence

- Database revision: `d7f3c2a91e60` (`password_reset_tokens` plus lookup and retention indexes).
- Provider boundary: vendor-neutral SMTP protocol with an in-memory provider restricted to tests.
- API contracts: `POST /api/v1/auth/forgot-password` and
  `POST /api/v1/auth/reset-password`.
- Reset links are built only from `PUBLIC_UI_URL`; the secret is placed in the fragment, consumed
  once by React, and immediately removed with `history.replaceState`.
- Database-backed subject/IP throttles complement the required infrastructure edge limits.
- Cleanup owner: platform scheduler invokes `python -m app.cli cleanup-password-reset-tokens`
  daily; default retention is 30 days.
- Rollout order: migration, backend configuration, staging SMTP verification, then UI feature flag.
  Rollback hides the UI entry point first and disables backend recovery second.
- Local verification: 48 backend tests, Ruff, Alembic upgrade/check/downgrade/re-upgrade, UI lint,
  production build, and 11 Playwright tests.

## Handoff

Provide the email-provider abstraction, fake provider, reset migration revision, UI route contract,
rate-limit settings, cleanup ownership, and evidence that no raw token is present in logs or storage.
