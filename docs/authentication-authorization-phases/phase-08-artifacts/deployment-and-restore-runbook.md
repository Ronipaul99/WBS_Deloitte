# Deployment and Restore Runbook

**Owner:** Release manager. **Approvers:** engineering, operations, database owner, security.

## Preconditions

- Approved artifact digests/SBOM and no unresolved critical/high findings.
- A verified Neon restore point and named restore operator.
- Runtime, migration, email, metrics, and storage secrets injected by workload identity/manager.
- Edge, alert routing, maintenance schedule, and on-call ownership active in staging.
- Phase 7 suite passed against the release candidate.

## Production deployment

1. Record the source revision, API/UI image digests, change ticket, approvers, and restore point.
2. Run repository secret, dependency, and image scans. Stop on high/critical failures.
3. In the migration job, load its secret without echoing it, then run:

   ```powershell
   cd backend
   python -m app.cli check-production-config
   alembic current
   alembic upgrade head
   alembic check
   ```

4. Deploy the API image with traffic disabled. Poll `/api/v1/health/live`, then
   `/api/v1/health/ready`. Readiness remains `503` if the database is unavailable, migrations are
   behind, or no active local administrator exists.
5. Deploy the UI image built with the final `VITE_API_URL`; set `API_ORIGIN` to the exact API origin.
6. Run the Phase 7 smoke subset through public HTTPS domains. Verify Secure/HttpOnly/SameSite cookie,
   CORS, CSP, HSTS, no-store, correlation ID, and edge `429` behavior.
7. Enable a limited tenant cohort or small traffic percentage. Watch alerts, 5xx, latency, login,
   refresh, authorization denials, email delivery, and database saturation.
8. Increase traffic only after the observation window. Attach test/alert evidence and close the
   change record.

The migration job must finish before API traffic. Never set `AUTO_CREATE_TABLES=true` to recover a
deployment.

## Rollback or forward fix

1. Disable new traffic and preserve logs, traces, database revision, and artifact digests.
2. If code failed and the schema is backward-compatible, restore the previous secure image.
3. If a migration changed or removed data, prefer a reviewed forward migration. Do not run an
   Alembic downgrade until the database owner proves it is lossless on a restored copy.
4. Never restore `AUTH_MODE=development`, insecure cookies, an old exposed secret, or an artifact
   with a failed security gate.

## Neon restore exercise

1. Database owner creates a new isolated restore branch from the recorded point. Production remains
   untouched and credentials are not copied into the ticket.
2. Point a temporary API deployment at the restored branch using restricted temporary credentials.
3. Run `alembic current`, `alembic check`, and readiness.
4. Validate counts and sampled relationships for users, auth identities, tenant memberships,
   refresh sessions, invitations, and auth events. Confirm every membership references the intended
   tenant and user; do not export raw secrets or password hashes.
5. Sign in with dedicated restore-test identities for ADMIN, EDITOR, VIEWER, inactive, and
   cross-tenant denial scenarios. Run the Phase 7 staging smoke subset.
6. Record recovery point/time achieved, validation queries, test result, owners, timestamps, and
   discrepancies. Delete the temporary branch and revoke temporary credentials after approval.

Restore evidence must be renewed on the cadence approved by the database owner and after material
schema/authentication changes.
