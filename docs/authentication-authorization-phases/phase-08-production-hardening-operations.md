# Phase 8: Production Hardening and Operations

## Phase Status

Repository implementation completed on 2026-10-22. Production hosting, managed secret injection,
external monitoring/alert routing, active edge controls, restore evidence, and incident exercises
remain pending platform decisions. See `phase-08-artifacts/implementation-evidence.md`.

## Outcome

The completed local authentication and authorization system runs in production with HTTPS, secure
configuration, release gates, monitoring, cleanup, tested recovery, and documented incident response.

## Execution Context

Existing application controls include:

- production configuration validation in `backend/app/core/config.py`;
- Secure-cookie requirement for production;
- development-mode rejection in production;
- exact CORS origin parsing and wildcard rejection;
- API security headers in `backend/app/main.py`;
- application login rate limiting and audit events;
- direct and pooled Neon URL support;
- Alembic deployment process;
- `backend/SECURITY.md` deployment guidance.

This phase requires platform decisions outside the repository. Do not mark it complete based only on
application tests.

## Required Platform Decisions

- API and UI hosting platforms;
- TLS termination and DNS ownership;
- secret manager;
- edge/WAF/rate-limiting service;
- centralized logs, metrics, traces, and alerting;
- transactional email provider from Phase 3;
- backup and restore ownership;
- authentication-event retention and privacy policy;
- on-call and incident escalation path;
- staging and production Neon branches/projects.

## Production Configuration Baseline

Required values include:

```dotenv
APP_ENV=production
AUTH_MODE=local
AUTO_CREATE_TABLES=false
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
AUTH_ACCESS_TOKEN_MINUTES=15
AUTH_REFRESH_TOKEN_DAYS=7
CORS_ORIGINS=https://<ui-host>
PUBLIC_UI_URL=https://<ui-host>
```

JWT, audit, database, email, and future OIDC secrets must be injected from the secret manager. Secret
values must not appear in deployment manifests, shell arguments, build logs, or source control.

## Work Breakdown

### 1. Separate build-time and runtime configuration

- Build immutable API and UI artifacts.
- Inject runtime secrets only into API processes.
- Treat `VITE_*` values as public build configuration, never secrets.
- Validate the final public API/UI origins.
- Prevent development `.env` files from entering images or deployment bundles.
- Generate a software bill of materials when supported.

### 2. Enforce transport and browser security

- TLS for every public endpoint;
- HTTP-to-HTTPS redirect;
- HSTS after domain validation;
- Secure and HttpOnly cookies;
- restrictive UI Content Security Policy;
- `frame-ancestors 'none'` or equivalent clickjacking protection;
- MIME sniffing and referrer restrictions;
- no caching of auth responses or protected HTML;
- exact CORS origins and required methods/headers only.

Review the current external font import. Self-host or explicitly allow only required font origins in
the CSP. Avoid broad `script-src` exceptions.

### 3. Add edge abuse controls

Rate-limit at minimum:

- login;
- refresh;
- forgot/reset password;
- invitation acceptance/resend;
- file upload;
- generation/job creation.

Use separate thresholds by endpoint risk. Preserve application database rate limits as defense in
depth. Configure request body limits and connection timeouts at both edge and API.

Do not trust `X-Forwarded-For` until proxy trust boundaries are explicitly configured. Ensure the
application receives the intended client address only from approved proxies.

### 4. Configure secret lifecycle

Document creation, storage, access review, rotation, and revocation for:

- database runtime and migration credentials;
- JWT signing secret;
- audit fingerprint secret;
- email-provider key;
- object-storage credentials;
- future OIDC client secret.

JWT rotation must consider active access tokens. Audit-secret rotation affects fingerprint
correlation. Forced reauthentication requires refresh-session revocation in addition to signing-key
rotation.

### 5. Implement maintenance jobs

Schedule deletion or archival for:

- expired/revoked refresh-session records;
- expired/used password-reset tokens;
- expired/revoked invitations;
- temporary uploads and failed exports;
- audit events after approved retention.

Maintenance must be observable, tenant-safe, idempotent, and tested against large data volumes.

### 6. Configure monitoring

Metrics:

- login success/failure/rate limit;
- refresh success/reuse/failure;
- active and revoked session counts;
- password reset request/completion;
- invitation lifecycle;
- authorization denials by permission and route;
- administrator mutations;
- API latency/error rate;
- database pool and migration state.

Alerts:

- refresh reuse;
- privileged-account login attack;
- denial spike;
- final-admin protection attempt;
- unusual admin role changes;
- email delivery outage;
- cleanup failure;
- database connectivity or migration failure;
- production configuration validation failure.

Use safe IDs and keyed fingerprints. Redact Authorization, Cookie, password, reset token, invitation
token, connection string, and provider code values before log export.

### 7. Build deployment gates

Recommended deployment order:

1. verify backup/restore point;
2. run secret and dependency scans;
3. build immutable artifacts;
4. apply reviewed Alembic migration with restricted migration credential;
5. run schema drift check;
6. deploy API with readiness disabled from traffic until healthy;
7. deploy UI;
8. run Phase 7 smoke subset;
9. enable traffic gradually;
10. monitor security and error signals;
11. record release evidence.

No application instance should start serving traffic before its required schema is present.

### 8. Create operational runbooks

Required runbooks:

- administrator account compromise;
- JWT secret exposure;
- database credential exposure;
- refresh-token replay alert;
- mass logout/session revocation;
- email-provider compromise or outage;
- loss of final administrator access;
- failed database migration;
- rollback and forward-fix decision;
- Neon restore and tenant-consistency validation;
- privacy request affecting authentication events.

Each runbook identifies owner, prerequisites, exact safe commands, communication path, evidence to
preserve, and post-incident review.

### 9. Perform production-readiness review

Review architecture, threat model, authorization inventory, data retention, dependencies, platform
configuration, test evidence, runbooks, and ownership with engineering, security, and operations.

Resolve high-severity findings before launch. Record accepted residual risks with owner and review
date.

## Verification Plan

- Run the Phase 7 suite against staging with production-like security settings.
- Validate real HTTPS cookie behavior through the deployed domains.
- Test CORS and CSP using browser developer/security reports.
- Confirm logs and traces redact sensitive fields.
- Trigger each critical alert in a controlled environment.
- Restore a backup and validate memberships, identities, and sessions.
- Exercise secret rotation and forced session revocation.
- Simulate failed deployment and rollback/forward-fix procedures.
- Validate edge rate limits without locking out normal workflows.

## Security Review Checklist

- [ ] TLS and Secure cookies are enforced.
- [ ] Secrets exist only in the approved manager and runtime injection path.
- [ ] CORS and CSP contain no unnecessary wildcards.
- [ ] Proxy trust and client-IP behavior are reviewed.
- [ ] Edge and application rate limits are active.
- [ ] Sensitive fields are redacted from every telemetry path.
- [ ] Maintenance and retention are scheduled and monitored.
- [ ] Backup restoration and incident runbooks are tested.
- [ ] Release gates block security and migration failures.

## Rollout Strategy

Use staging first, followed by a controlled production rollout with a small traffic percentage or
limited tenant cohort when infrastructure permits. Keep the previous application artifact available,
but prefer forward database fixes when rollback could discard auth or audit data.

Do not roll back to development authentication. A failed auth release must fail closed or restore the
last secure production version.

## Exit Criteria

- [ ] Production environment passes configuration validation.
- [ ] HTTPS, cookies, CORS, CSP, and edge limits are verified externally.
- [ ] Secrets and credentials follow documented lifecycle management.
- [ ] Monitoring and alerts are connected to an owned response process.
- [ ] Maintenance and retention jobs run successfully.
- [ ] Backup restoration and incident runbooks have test evidence.
- [ ] Phase 7 suite and production smoke tests pass.
- [ ] Production-readiness review has no unresolved critical/high findings.

## Handoff

Provide final architecture/environment diagrams, deployment manifest references, secret inventory
without values, alert catalog, runbook links, restore evidence, release evidence, residual risks, and
owners. Completion of this phase establishes end-to-end local authentication and authorization.
