# Alert Catalog

The API exposes authenticated Prometheus data at `/api/v1/health/metrics`. The scrape token is
independent from user authentication. The edge must restrict this route to the monitoring network.
Request labels use route templates, not raw URLs, and auth labels use controlled event names.

## Available signals

- `wbs_auth_events_total{event_type,outcome}`: login, refresh, refresh reuse, recovery, invitation,
  authorization denial, final-admin denial, admin mutations, and operator revocations.
- `wbs_http_requests_total{method,route,status_class}` and
  `wbs_http_request_duration_seconds{method,route}`: error rate and latency without tenant/user IDs.
- `wbs_refresh_sessions{state}`: active and revoked database records at scrape time.
- `wbs_migration_at_head`: `1` only when the database revision matches the application head.
- `wbs_maintenance_runs_total{outcome}`: cleanup success/failure in the process that runs it.
- `/api/v1/health/live` and `/api/v1/health/ready`: process, database, migration, and administrator
  readiness signals.

## Required alerts

| Alert | Suggested staging trigger | Severity | Owner response |
| --- | --- | --- | --- |
| Refresh-token reuse | Any `refresh_reuse` failure | Critical | Security on-call; revoke user sessions and investigate |
| Privileged login attack | Failed login spike for protected admin test account fingerprint | High | Security on-call; edge block and account review |
| Authorization denial spike | `authorization_denied` or `tenant_access_denied` rate above baseline | High | App on-call; inspect route/permission and actor fingerprint |
| Final-admin protection attempt | Any `tenant_final_admin_denied` | Medium | Tenant support + security review |
| Unusual admin role changes | `tenant_member_role_changed` outside change window | High | Tenant owner confirmation |
| Email outage | Failed `password_reset_delivery` or `tenant_invitation_delivery` sustained 5 minutes | High | Disable UI feature flag, then API feature flag |
| Cleanup failure | Any maintenance failure or missing daily success | High | Operations; rerun and inspect database/storage connectivity |
| Database/readiness failure | Ready endpoint fails 2 checks | Critical | Operations/database owner |
| Migration drift | `wbs_migration_at_head == 0` | Critical | Stop rollout; migration owner |
| Production config failure | Config gate non-zero | Critical | Block deployment |
| API error/latency | 5xx or p95 above approved SLO | High | App on-call |

Thresholds require staging load data and formal SLOs before launch. Every critical/high alert must be
triggered in a controlled staging exercise, page an owned destination, and link to the relevant
runbook. Dashboards and alerts must not export Authorization, Cookie, password, token, connection
string, email address, provider code, request body, or raw query values.
