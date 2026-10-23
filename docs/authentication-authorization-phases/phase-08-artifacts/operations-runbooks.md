# Authentication Incident Runbooks

## Common protocol

**Incident owner:** security on-call. **Supporting owners:** application on-call, operations,
database owner, and privacy/legal when data exposure is possible.

Open the restricted incident channel and record UTC timestamps, alert payloads, correlation IDs,
artifact versions, affected safe IDs, auth-event fingerprints, approvals, and actions. Never record
passwords, bearer/cookie values, reset/invitation links, database URLs, provider codes, or secret
values. Preserve logs read-only before retention or rotation changes. After containment, complete a
root-cause review with corrective owners and dates.

## Administrator account compromise

**Prerequisites:** confirmed admin email, incident approval, backend job with production secret access.

1. Contain the identity:
   `python -m app.cli revoke-user-sessions --email <admin-email> --confirm REVOKE_USER_SESSIONS`.
2. Disable the user through the approved admin/data procedure without removing the final active
   administrator. If it is the final admin, provision the approved recovery administrator first.
3. Review login, refresh, authorization denial, role/member, invitation, export, and object access
   events for the user ID and fingerprints. Rotate the password through recovery only after email
   control is verified.
4. Tenant owner confirms all role and membership changes. Escalate suspected data access to privacy.

## JWT signing secret exposure

1. Create a new independent JWT secret in the manager and deploy the API with it.
2. Immediately run
   `python -m app.cli revoke-all-sessions --confirm REVOKE_ALL_SESSIONS` to increment every auth
   version and revoke refresh records.
3. Revoke the old secret, verify all prior access/refresh credentials fail, monitor new logins, and
   preserve the suspected exposure path. Do not rotate the audit secret unless it was also exposed.

## Database credential exposure

1. Restrict network access and pause migrations/deployments using the affected principal.
2. Create a least-privilege replacement in Neon, update the secret manager, deploy consumers, and
   verify readiness. Revoke the old principal only after consumers move.
3. Review Neon connection/query audit evidence and application correlation IDs. If integrity is in
   doubt, restore to an isolated branch and follow `deployment-and-restore-runbook.md`.

## Refresh-token replay alert

1. Identify the user ID/family from internal auth evidence; never copy the raw token.
2. Confirm the token family was revoked automatically, then run targeted session revocation if the
   user's auth version was not already changed.
3. Review IP/user-agent fingerprints, login, password change/reset, tenant access, and data actions.
   Require password reset when account compromise is plausible.

## Mass logout or session revocation

With security and incident-owner approval, run
`python -m app.cli revoke-all-sessions --confirm REVOKE_ALL_SESSIONS`. Confirm existing access tokens
return `401`, all users can reauthenticate, and the `operator_mass_session_revocation` event exists.
Communicate expected reauthentication before execution unless immediate containment forbids delay.

## Email provider compromise or outage

1. Disable `VITE_PASSWORD_RECOVERY_ENABLED`, deploy UI, then disable
   `PASSWORD_RECOVERY_ENABLED` and `TENANT_INVITATIONS_ENABLED` in the API.
2. Revoke the provider key, retain delivery/audit logs, and investigate messages sent in the window.
3. Configure and test a replacement key/sender in staging. Re-enable API capabilities before UI
   entry points, and monitor delivery events. Never disclose raw links through support channels.

## Loss of final administrator access

1. Obtain two-person approval and verify tenant ownership out of band.
2. Use a restricted production job and run `python -m app.cli create-admin` with reviewed email,
   display name, tenant slug/name; enter the password only at the hidden prompt. Use
   `--link-existing-user` only after verifying the existing identity.
3. Confirm readiness, ADMIN membership, and successful login. Preserve approvals and provisioning
   output. Review why final-admin access was lost.

## Failed migration and rollback decision

Stop API traffic, capture `alembic current`, migration logs, database errors, image digest, and restore
point. The database owner decides between a backward-compatible image rollback and a forward-fix
migration. Test the chosen path on a restored branch first. Never force a downgrade that can discard
auth, membership, session, invitation, or audit data.

## Privacy request affecting authentication events

Privacy/legal defines scope and legal hold. Search only by approved user ID or keyed fingerprints;
do not attempt to reverse fingerprints. Export the minimum fields to the approved case system, apply
the authorized deletion/anonymization procedure, and record counts and reviewer approval. Do not
change global retention to satisfy one request. Validate referential and tenant integrity afterward.
