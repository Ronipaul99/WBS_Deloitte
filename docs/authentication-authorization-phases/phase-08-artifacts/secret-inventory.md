# Secret Inventory and Lifecycle

This inventory records names and ownership only. Never add values, connection strings, reset links,
invitation links, provider codes, or screenshots containing them.

| Secret | Consumer | Minimum access | Rotation and revocation |
| --- | --- | --- | --- |
| `DATABASE_URL` | API and worker | Runtime DML only | Rotate credential, redeploy, revoke old credential, verify readiness |
| `DIRECT_DATABASE_URL` | Migration job | Schema migration only | Rotate independently; never inject into API/UI |
| `AUTH_JWT_SECRET` | API | Read at runtime | Add new secret, deploy, run mass session revocation, revoke old secret |
| `AUTH_AUDIT_SECRET` | API | Read at runtime | Rotate with recorded correlation boundary; old/new fingerprints cannot be joined |
| `METRICS_BEARER_TOKEN` | API and scraper | Scrape only | Rotate scraper and API together; verify unauthorized scrape fails |
| `SMTP_USERNAME/PASSWORD` | API | Send from approved identity | Rotate provider key, test delivery, revoke old key |
| Object-storage key | API and worker | Tenant-prefixed object operations | Rotate workload identity/key and inspect access logs |
| Future OIDC client secret | API | OIDC token exchange only | Follow IdP overlap window and revoke sessions if assurance is affected |

## Lifecycle procedure

1. **Create:** generate in the approved manager or provider; require high entropy and separate values
   for JWT, audit, and metrics. Never generate through a shell command that logs output in CI.
2. **Store:** keep production and staging scopes separate. Disable secret display after creation where
   supported. No secret is a Docker build argument or `VITE_*` value.
3. **Grant:** use workload identity and least privilege. Human read access is break-glass, approved,
   time-limited, and audited.
4. **Inject:** mount or inject only into the process that consumes the value. Mask all CI values and
   prevent command tracing around secret-loading steps.
5. **Review:** quarterly and after staffing/platform changes, export principals and remove stale
   grants. The reviewer must not be the sole secret owner.
6. **Rotate:** test in staging, create an overlap window where the protocol permits, deploy consumers,
   verify health/telemetry, revoke the old value, and attach evidence to the change record.
7. **Respond:** suspected exposure is treated as compromise. Follow `operations-runbooks.md`, retain
   access/audit evidence, and do not paste values into tickets or chat.

JWT rotation alone does not invalidate an already accepted refresh credential. Run the explicit
session revocation command in the JWT runbook. Audit-secret rotation changes fingerprints and must
record the exact rotation timestamp for investigations.
