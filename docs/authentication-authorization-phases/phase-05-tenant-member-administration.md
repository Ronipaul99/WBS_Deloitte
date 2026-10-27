# Phase 5: Tenant Member Administration

## Phase Status

Implemented and locally verified. The Neon migration, SMTP delivery, and feature flag still require
staging activation before production rollout.

## Outcome

Tenant administrators can invite users, list membership, change roles, revoke invitations, and remove
members without direct database access. The final active administrator remains protected.

## Execution Context

Relevant existing code:

- `Tenant`, `User`, `TenantMembership`, and `MembershipRole` in
  `backend/app/models/domain.py`;
- local identities in `backend/app/models/auth.py`;
- tenant authorization dependencies completed in Phase 2;
- email provider interface completed in Phase 3;
- tenant and role data returned by `/me`;
- Settings navigation and account UI from Phase 4.

Do not start this phase before Phase 2 permission enforcement. Member administration must never rely
only on hiding frontend controls.

## Product Decisions

- Invitations expire after 72 hours by default and rotate their secret when resent.
- The invitation role is fixed. Administrators revoke and create a replacement to change it.
- Membership removal hard-deletes the access row; immutable authentication events retain the
  administrative history.
- Existing users receive the same invitation email and must authenticate as the invited address
  before acceptance.
- New-user setup creates a local identity while local or hybrid authentication is enabled. An
  already authenticated matching OIDC identity can accept, but the enterprise SSO sign-in journey
  remains Phase 9 work.
- Security operators and tenant administrators holding `audit:read` are the intended audit readers.
  A product audit viewer is deferred because it is not part of the Phase 5 API contract.
- Multiple historical invitations are retained, while tenant-row locking permits at most one
  unexpired active invitation for a normalized tenant/email pair.

## Files Expected to Change

- `backend/app/models/auth.py` or a dedicated membership model module
- `backend/app/models/__init__.py`
- new Alembic migration
- `backend/app/schemas/members.py` (new)
- `backend/app/services/members.py` (new)
- `backend/app/api/routes/members.py` (new)
- `backend/app/api/router.py`
- email provider/templates
- `backend/tests/test_members.py` (new)
- new frontend member service
- new tenant-member Settings views and CSS
- frontend browser tests

## Work Breakdown

### 1. Add invitation persistence

Create `TenantInvitation` with:

- tenant ID;
- normalized target email;
- fixed role;
- unique token hash;
- inviting administrator user ID;
- expiry;
- accepted and revoked timestamps;
- created and updated timestamps.

Add indexes for tenant/status listing, token lookup, email/tenant duplication checks, and cleanup.
Store only the invitation-token digest.

Decide and document whether multiple historical invitations may exist. At most one unexpired active
invitation should exist for the same tenant and normalized email.

### 2. Create the membership service boundary

Place transactional rules in a service rather than route handlers:

- list members and pending invitations;
- create/resend/revoke invitation;
- accept invitation;
- update membership role;
- remove/deactivate membership;
- count active administrators with a lock;
- write audit events.

Use database transactions and row-level locks for final-administrator operations. Checking the admin
count and mutating the membership must occur atomically.

### 3. Implement admin APIs

Add:

- `GET /api/v1/tenants/{tenant_id}/members`;
- `POST /api/v1/tenants/{tenant_id}/invitations`;
- `POST /api/v1/tenants/{tenant_id}/invitations/{invitation_id}/resend`;
- `DELETE /api/v1/tenants/{tenant_id}/invitations/{invitation_id}`;
- `PATCH /api/v1/tenants/{tenant_id}/members/{user_id}`;
- `DELETE /api/v1/tenants/{tenant_id}/members/{user_id}`;
- `POST /api/v1/auth/accept-invitation`.

All tenant routes require their Phase 2 `member:*` permission. Invitation acceptance uses only the
single-use token and does not accept a tenant ID selected by the browser.

### 4. Implement invitation acceptance

Existing authenticated user:

1. validate and consume the token atomically;
2. verify normalized account email matches the invitation policy;
3. create the membership with invitation role;
4. mark invitation accepted;
5. audit and return tenant membership.

New user:

- present an account setup flow appropriate for local or SSO policy;
- require email ownership through possession of the invitation;
- create identity and membership transactionally;
- do not treat an unverified typed email as identity proof.

Tokens are single-use and tenant-bound. Expired, revoked, accepted, and invalid tokens receive the
same safe external error.

### 5. Implement member-management UI

Admin Settings view includes:

- searchable member table;
- role and status columns;
- pending invitations;
- invite command;
- role menu with fixed choices;
- remove and revoke commands with confirmation;
- empty, loading, error, and pagination states.

Viewer and Editor users must not see member administration navigation. A direct URL still depends on
API authorization and renders Access Denied on `403`.

### 6. Add audit behavior

Record invitation creation, resend, revoke, accept, role change, removal, final-admin denial, and
cross-tenant denial using allowlisted metadata.

Do not include raw invitation tokens. Store email as a keyed fingerprint in security events unless
the business audit policy explicitly authorizes the normalized email.

### 7. Add maintenance

- delete expired invitation tokens after retention;
- optionally retain immutable administrative audit events;
- monitor resend abuse and delivery failures;
- invalidate or expire pending invitations when a tenant is deactivated.

## Concurrency and Integrity Requirements

- Two administrators cannot simultaneously demote/remove the final two admins and leave zero.
- Invitation acceptance cannot create duplicate memberships.
- Replayed acceptance cannot change an existing role.
- Role update validates the current membership inside the transaction.
- Removing a member revokes their tenant access immediately without necessarily invalidating sessions
  used for other tenants.
- Removing a user's last membership results in the no-workspace UI, not automatic access elsewhere.

## Test Plan

Backend:

- Admin completes every API operation.
- Viewer and Editor receive `403` for every member operation.
- Cross-tenant member and invitation IDs cannot be read or changed.
- Duplicate active invitation is rejected or safely idempotent.
- Invitation token hash, expiry, reuse, and revocation behavior.
- Existing and new-user acceptance paths.
- Concurrent final-admin demotion/removal cannot leave zero admins.
- Role changes affect the next protected request.
- Member removal blocks tenant access immediately.
- Audit events contain approved metadata only.

Frontend:

- Permission-aware navigation.
- Member list states and role changes.
- Invitation create/resend/revoke.
- Destructive confirmations.
- Server `403` handling.
- Invitation acceptance on desktop and mobile.
- No token remains in URL history or browser storage after parsing.

## Security Review Checklist

- [x] All administration APIs require named server permissions.
- [x] Final-admin invariant is transactionally enforced.
- [x] Invitation tokens are hashed, random, tenant-bound, expiring, and single-use.
- [x] Acceptance proves control of the intended identity.
- [x] Unknown roles fail validation.
- [x] Cross-tenant identifiers are non-disclosing.
- [x] Role changes take effect from the database immediately.
- [x] Audit events exclude raw tokens and secrets.

## Rollout and Rollback

Deploy schema, backend APIs, then UI. Initially enable the UI for internal administrators in staging.
If email delivery fails, keep existing-member role administration available while disabling new
invitations through reviewed configuration.

Do not roll back the invitation table after invitations have been sent. Prefer a forward fix and
revoke affected active tokens.

## Exit Criteria

- [x] Admin manages members and invitations through the product.
- [x] Viewer and Editor cannot reach administrative data or operations.
- [x] Invitation lifecycle is secure and fully tested.
- [x] Final active administrator cannot be removed or demoted.
- [x] Role changes and removal take effect immediately.
- [x] Every administrative mutation is auditable.
- [x] Maintenance and delivery-failure procedures exist.

## Implementation Evidence

### Persistence and migration

- Revision `e6b91f2c4a73` adds `tenant_invitations` after `d7f3c2a91e60` with digest lookup,
  tenant/status, and tenant/email indexes.
- The model retains accepted and revoked history. Active uniqueness is enforced while holding the
  tenant row lock, allowing a later invitation after expiration or revocation.
- An isolated SQLite migration run reached head and `alembic check` reported no model drift. Apply
  the same revision to a Neon development branch before staging.

### API contracts

- `GET /api/v1/tenants/{tenant_id}/members` supports search, offset, and limit and returns members,
  pending invitations, and independent totals.
- Create, resend, and revoke invitation endpoints require `member:invite`; role updates require
  `member:update`; removals require `member:remove`; listing requires `member:read`.
- `POST /api/v1/auth/accept-invitation` derives the tenant exclusively from the token. It accepts an
  authenticated matching user or transactionally creates a new local account when setup fields are
  supplied.
- Responses never expose token digests, raw secrets, identity subjects, or password material.

### Concurrency and auditing

- Role and removal services hold an in-process lock for local SQLite verification and a database
  tenant-row lock through commit for multi-instance PostgreSQL correctness. The administrator count
  and mutation are atomic.
- Acceptance revalidates and conditionally claims the invitation after locking; replays cannot add a
  membership or alter an existing role.
- Audit event types: `tenant_invitation_created`, `tenant_invitation_resent`,
  `tenant_invitation_revoked`, `tenant_invitation_delivery`, `tenant_invitation_accepted`,
  `tenant_invitation_rate_limited`, `tenant_member_role_changed`, `tenant_member_removed`,
  `tenant_final_admin_denied`, `tenant_resource_denied`, and `tenant_access_denied`.
- Email addresses use keyed fingerprints in events. Details are restricted to tenant, resource,
  actor/target UUID, role, operation, reason, and account-created status.

### Product and operations

- Settings opens an admin-only Members view with search, pagination, invitation management, fixed
  role choices, confirmations, and loading/empty/error/Access Denied states.
- `/accept-invitation` removes the secret from URL history before rendering. Passwords and tokens
  remain component-local and are absent from browser storage.
- Configuration is documented in `backend/.env.example`. Failed delivery revokes the invitation;
  `python -m app.cli cleanup-tenant-invitations` removes retained records after the configured period.
- Sanitized visual evidence: [desktop member administration](phase-05-artifacts/desktop-members.png)
  and [mobile invitation acceptance](phase-05-artifacts/mobile-invitation.png).

### Verification

- Backend: `python -m pytest -q` (`63 passed`), `ruff check app tests migrations`, isolated
  `alembic upgrade head`, and isolated `alembic check` all passed.
- Frontend: `npm.cmd run lint`, `npm.cmd run build`, and `npx.cmd playwright test` (`27 passed`)
  all passed.

Known limitation: SMTP and Neon staging verification remain deployment work. New-user enterprise SSO
enrollment and the tenant audit viewer remain deferred to the phases identified above.

## Handoff

Provide migration revision, member/invitation contracts, final-admin transaction evidence, email
template/configuration, audit event list, UI screenshots, and role test results to Phase 6.
