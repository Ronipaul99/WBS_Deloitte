# Production Readiness Review Record

## Release identity

- Review date: Pending
- Source revision and API/UI image digests: Pending
- Staging and production environment references: Pending
- Engineering, security, operations, privacy, database, and product approvers: Pending

## Review gates

| Gate | Repository evidence | External evidence | Status |
| --- | --- | --- | --- |
| Immutable builds and SBOM | Dockerfiles and CI release artifact | Registry digest/signature | Implemented / pending activation |
| Production config | `check-production-config` and tests | Secret injection/config output | Implemented / pending evidence |
| TLS, redirect, HSTS | Edge reference policy | DNS/TLS scan | Pending platform |
| Cookie, CORS, CSP, no-store | API/UI config and tests | Browser staging capture | Implemented / pending external test |
| Proxy trust and rate limits | Edge reference policy | Active provider rule export | Pending platform |
| Secrets | Inventory/lifecycle document | Manager access review and rotation drill | Pending platform |
| Monitoring and alerts | Prometheus endpoint and alert catalog | Dashboard/page test links | Implemented / pending connection |
| Maintenance and retention | `run-maintenance` and tests | Scheduler run history/privacy approval | Implemented / pending schedule |
| Migration gate | Alembic CI and migration-aware readiness | Staging/production revision evidence | Implemented / pending deployment |
| Backup restore | Restore runbook | Completed timed restore evidence | Pending exercise |
| Auth/full-stack validation | Phase 7 suite | Production-domain smoke evidence | Implemented locally / pending staging |
| Incident response | Operations runbooks and revocation CLI | Tabletop record/on-call ownership | Implemented / pending exercise |

## Threat and dependency review

Review authentication/authorization data flow, cross-tenant access, proxy spoofing, token theft,
credential stuffing, reset/invitation abuse, malicious upload size/type, administrator compromise,
secret exposure, telemetry leakage, schema drift, backup integrity, dependency/container findings,
and availability failure modes. Attach scan output and disposition every finding.

## Residual risk register

| Risk | Severity | Mitigation | Owner | Review date | Acceptance |
| --- | --- | --- | --- | --- | --- |
| Populate during platform review | Pending | Pending | Pending | Pending | Pending |

No critical/high risk may remain unresolved at launch. Acceptance of lower risks requires a named
owner, rationale, compensating control, and review date. Phase 8 is complete only after every
external evidence field above is linked and all required approvers sign this record.
