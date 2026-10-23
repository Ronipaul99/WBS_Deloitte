# Phase 8 Implementation Evidence

## Implemented in the repository

- Production validation now requires PostgreSQL TLS for runtime and migration URLs, exact HTTPS UI
  and CORS origins, Secure cookies, explicit trusted proxy CIDRs, migration-head readiness,
  authenticated metrics, production auth mode, and disabled automatic schema creation.
- CORS methods/headers are explicit. Authenticated/auth responses are `no-store`; production API
  responses add HSTS and a deny-all API CSP. Request bodies are rejected from declared size before
  route parsing and uploaded files retain streamed size/type enforcement.
- UI Google font imports were removed. The production UI container sends a CSP with exact API
  origin, no script exceptions, clickjacking/MIME/referrer policies, immutable asset caching, and
  no-store HTML. `style-src 'unsafe-inline'` remains necessary for existing React dynamic styles and
  is recorded for later nonce/class refactoring.
- API and UI images use multi-stage builds and non-root runtime users. Docker build contexts exclude
  `.env`, tests, local data, caches, and development outputs.
- Auth, authorization, HTTP latency/status, session state, migration state, and maintenance metrics
  are available through a secret-protected endpoint. Permission denials record controlled route
  templates and permission/role labels.
- `python -m app.cli run-maintenance` performs batched, idempotent cleanup of retained refresh
  sessions, reset tokens, invitations, auth events, stale failed exports, and temporary files. File
  cleanup rejects cross-tenant storage keys.
- Operator commands provide confirmation-gated targeted and global session invalidation, including
  access-token invalidation through `auth_version` and auditable operator events.
- Readiness verifies database access, Alembic head in production, and an active local administrator.
- CI scans secrets/dependencies/API and UI images, validates the production configuration contract,
  verifies migrations/schema drift, runs the Phase 7 live suite, creates CycloneDX SBOMs, and records
  source/image identities as release evidence.
- Reference edge controls, environment inventory, architecture, secret lifecycle, alert catalog,
  deployment/restore procedure, incident runbooks, and readiness review are checked in.

## Verification performed

Verified locally on 2026-10-22:

- `python -m ruff check app tests migrations`: passed.
- `python -m pytest`: 81 passed; one upstream Starlette/httpx deprecation warning.
- `npm.cmd run lint` and `npm.cmd run build`: passed.
- mocked Playwright suite: 32 passed.
- live SQLite Phase 7 smoke: 15 passed after applying every Alembic revision and reporting no schema
  drift; the harness removed its processes and disposable data.
- CI and Compose YAML parse checks: passed.

The automated suite covers configuration rejection, metrics authentication, body limits, cleanup
idempotency/multiple batches/tenant storage protection, and operator session invalidation in
addition to Phases 1-7. Docker is not installed on the verification host, so local API/UI image
builds, container health/CSP inspection, Trivy scans, and SBOM generation remain assigned to the CI
workflow and staging evidence.

## Required external evidence before completion

- Hosting/DNS/TLS, secret manager, edge/WAF, telemetry, email provider, Neon environment, storage,
  backup owner, retention/privacy approval, and on-call decisions.
- Staging Phase 7 run through deployed HTTPS domains, real CSP/CORS/cookie checks, controlled edge
  `429` tests, and every critical alert delivered to the owned response path.
- Successful timed Neon restore with tenant/identity/membership/session validation.
- JWT/audit/database/email rotation exercises and mass-revocation evidence.
- Failed deploy/forward-fix exercise, incident tabletop, signed readiness review, and no unresolved
  critical/high findings.

Phase 8 must remain operationally incomplete until those links and approvals are attached to
`production-readiness-review.md`.
