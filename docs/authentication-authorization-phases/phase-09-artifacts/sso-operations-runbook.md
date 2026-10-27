# Enterprise SSO Operations Runbook

## Staged Enablement

1. Apply database migration `f2a84d719c35` before deploying the API.
2. Inject reviewed provider metadata and independent secrets.
3. Keep `AUTH_MODE=hybrid`; keep `VITE_SSO_ENABLED=false` until backend readiness is confirmed.
4. Verify a monitored local administrator can sign in and has an active `ADMIN` membership.
5. Enable `VITE_AUTH_MODE=hybrid` and `VITE_SSO_ENABLED=true` for a controlled pilot.
6. Invite pilot users and verify their provider emails before login.
7. Monitor `sso_login`, `sso_identity_linked`, and invitation events for failures or conflicts.
8. Expand by approved tenant/cohort. Do not switch to `oidc` until recovery policy is approved.

## Provider Outage

1. Confirm outage using provider status and a synthetic test account. Do not repeatedly rotate secrets.
2. Disable the UI entry point with `VITE_SSO_ENABLED=false` if failures create user impact.
3. Keep `AUTH_MODE=hybrid`; existing internal sessions and local fallback continue independently.
4. Use the reviewed local administrator only from the controlled operator path.
5. Do not delete linked identities or invitations during an outage.
6. After recovery, test discovery, code exchange, nonce, key validation, and internal refresh before
   re-enabling the UI.

## Suspected Protocol or Credential Incident

1. Disable the SSO UI entry point and preserve evidence.
2. Rotate the provider client secret through the provider and secret manager.
3. For state-secret exposure, rotate `OIDC_STATE_SECRET`; pending authorization attempts will fail
   safely and must restart.
4. Revoke affected WBS sessions with `python -m app.cli revoke-user-sessions` or the approved global
   revocation command. Provider logout is not a substitute for this action.
5. Review token-free audit events and request correlation IDs. Never add query values or provider
   responses to incident logs.
6. Validate endpoint pins and provider signing keys before restoration.

## Provider Account Deactivation

Provider deactivation prevents a new provider sign-in, but it does not invalidate a WBS refresh
session already issued by this application. Until an approved provider lifecycle-event integration
exists:

1. Disable or remove the user's active WBS tenant memberships.
2. Revoke every WBS session for the user with the approved administrative process or
   `python -m app.cli revoke-user-sessions`.
3. Confirm the session inventory is empty and review the related audit events.
4. Record the elapsed time against the approved deactivation SLA.

Set `AUTH_REFRESH_TOKEN_DAYS` no longer than the accepted residual window. Provider single logout
does not replace application-session revocation.

## Logging Verification

The API and reference Nginx configuration omit query strings from access logs. Before each release,
send a synthetic callback with marker values through the deployed edge, then confirm the markers are
absent from load-balancer, CDN, proxy, APM, application, and error logs. Never use real provider
codes or state values for this verification.

## Break-Glass Exercise

At least quarterly and before removing hybrid mode:

1. Have two approved operators retrieve the local credential through the controlled process.
2. Simulate provider unavailability without changing provider production state.
3. Sign in locally, access the intended administrative tenant, and perform a harmless reviewed action.
4. Sign out everywhere, rotate or reseal the credential as policy requires, and review audit events.
5. Record date, environment, participants, result, finding owner, and next test date outside this repo.

## Rollback

Set `VITE_SSO_ENABLED=false` first. In hybrid mode, local sign-in and existing WBS sessions remain
available while the provider flow is investigated. Revoke SSO-created sessions only when the event
requires it. Roll back application code only after confirming the database migration is compatible;
the additive authorization-state table can remain during a code rollback.
