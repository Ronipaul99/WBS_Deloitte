# Phase 2: Enforce Role-Based Authorization

## Phase Status

Implemented and verified on October 22, 2026. Every tenant route now enforces one named permission,
tenant-owned request queries are scoped in SQL, and the UI derives command visibility from `/me`.

## Outcome

Every tenant-scoped API operation enforces a named server-side permission. Role changes take effect
on the next request, and a resource belonging to another tenant is never exposed.

## Execution Context

Relevant existing code:

- `MembershipRole` and `TenantMembership` in `backend/app/models/domain.py`;
- `TenantContext` and `require_tenant_member` in `backend/app/api/dependencies.py`;
- tenant routes under `backend/app/api/routes/`;
- membership role returned through `backend/app/api/routes/identity.py`;
- domain response schemas in `backend/app/schemas/domain.py`;
- workflow coverage in `backend/tests/test_workflow.py`.

Current access tokens contain user and session identity but no authoritative tenant role. Preserve
that design. Authorization must use current database membership data.

## Permission Source of Truth

Implement the permission catalog from the master specification as a typed server-owned mapping.
Suggested location:

- `backend/app/core/permissions.py` for permission definitions and role mappings;
- `backend/app/api/authorization.py` for FastAPI permission dependencies.

Do not scatter string role comparisons through route functions.

## Files Expected to Change

- `backend/app/core/permissions.py` (new)
- `backend/app/api/authorization.py` (new)
- `backend/app/api/dependencies.py`
- every tenant route in `backend/app/api/routes/`
- `backend/app/api/routes/identity.py`
- `backend/app/schemas/domain.py`
- `backend/tests/test_authorization.py` (new)
- existing workflow tests
- React auth types when `/me` adds derived permissions

No database migration is expected unless membership activation/history fields are introduced.

## Work Breakdown

### 1. Define typed permissions

Create a `Permission` string enum or equivalent literal type. Define one immutable permission set for
each known role. Unknown database roles must resolve to an empty permission set and generate a safe
security diagnostic.

Keep permission names stable because they become API/UI contract values. Do not use route names as
permissions.

### 2. Build authorization dependencies

Add dependency factories similar to:

```python
def require_permission(permission: Permission): ...
def require_role(*roles: MembershipRole): ...
```

The dependency must:

1. validate the authenticated user;
2. load the tenant by the path `tenant_id`;
3. reject inactive tenants;
4. load the user's membership using tenant and user IDs;
5. resolve the database role through the permission map;
6. reject missing permissions with `403`;
7. return a typed context containing tenant, user, role, and permissions.

Preserve a single membership query per request. Avoid separately calling `require_tenant_member` and
then querying the same membership again.

### 3. Map every endpoint

Create a temporary route inventory and assign exactly one primary permission to every tenant-scoped
operation.

Minimum mapping:

- project list/get: `project:read`;
- project create: `project:create`;
- project update: `project:update`;
- archive/delete: `project:archive`;
- document get: `document:read`;
- document upload: `document:upload`;
- summary read/update/approve: matching summary permissions;
- template list/get: `template:read`;
- template create/update/delete: `template:manage`;
- generation start: `wbs:generate`;
- WBS read/update: matching WBS permissions;
- validation read/run: matching validation permissions;
- export read/create: matching export permissions;
- job polling: permission inherited from the job's operation or a documented `job:read` permission.

Apply authorization before parsing or persisting large uploads and before queuing background work.

### 4. Enforce tenant-scoped queries

Review every database lookup for tenant-owned entities. Queries must include the authorized tenant ID
in SQL:

```python
select(Project).where(Project.id == project_id, Project.tenant_id == context.tenant.id)
```

Do not load by ID first and compare `tenant_id` in Python. Apply the same rule to jobs, documents,
summaries, templates, WBS versions, validations, and exports.

Use `404` for a tenant-owned record absent from the authorized tenant so cross-tenant IDs are not
distinguishable.

### 5. Extend `/me`

For each active membership return:

- tenant ID, name, and slug;
- current role;
- derived permission strings.

The UI may use permissions to render controls, but the API must recalculate authorization from the
database on every protected request.

### 6. Add frontend permission helpers

Extend the auth context with a type-safe `can(permission)` helper based on the selected membership.
Use it only to hide or disable unavailable commands. Do not treat hidden controls as an access
control.

At minimum, update create, upload, generation, edit, validation, export, and Settings navigation
commands.

## Test Matrix

Create table-driven backend tests for every permission:

| Test dimension | Required coverage |
|---|---|
| Role | Viewer, Editor, Admin, unknown role |
| Tenant | Own tenant, other tenant, inactive tenant |
| Membership | Active/present, absent, changed, removed |
| Resource | Existing in tenant, existing elsewhere, nonexistent |
| Operation | Read, create, update, archive/delete, administrative |

Specific tests:

- Viewer can read but cannot start generation or upload.
- Editor can execute the WBS workflow but cannot manage members or archive restricted resources.
- Admin can perform all mapped operations.
- Role change takes effect while the old access token is still valid.
- Membership removal takes effect immediately.
- A guessed cross-tenant resource ID returns the approved non-disclosing result.
- Unknown roles fail closed.
- A job cannot be polled from another tenant.

Frontend tests must confirm controls match the returned permission set and that a forced server `403`
is still handled safely.

## Security Review Checklist

- [ ] Permission mapping is centralized and immutable at runtime.
- [ ] No route trusts role or tenant claims supplied by the browser.
- [ ] Every tenant entity query includes `tenant_id`.
- [ ] Unknown roles receive no permissions.
- [ ] Expensive work occurs after authorization.
- [ ] Forbidden responses do not disclose cross-tenant existence.
- [ ] Administrative denials create safe audit events where required.
- [ ] OpenAPI documents expected `401`, `403`, and `404` outcomes.

## Rollout

1. Deploy permission code with all existing roles mapped.
2. Run audit-only comparison in staging if existing workflows may depend on overly broad access.
3. Test each role using separate accounts.
4. Deploy API enforcement before relying on hidden frontend controls.
5. Monitor denial rates and route names after release.

## Rollback

Rollback should restore the previous application version, not weaken individual checks ad hoc. If a
permission mapping is incorrect, ship a reviewed mapping fix with tests. Preserve audit events and
membership data.

## Exit Criteria

- [x] Every tenant endpoint has a named permission.
- [x] All request-side resource queries enforce the tenant boundary in SQL.
- [x] Viewer, Editor, and Admin behavior matches the approved matrix.
- [x] Role and membership changes take effect without token renewal.
- [x] Cross-tenant negative tests cover every resource family.
- [x] Frontend controls reflect permissions without replacing server enforcement.
- [x] Authorization tests pass locally and are ready for CI.

## Handoff to Later Phases

Provide the final permission enum, role mapping, route inventory, `/me` contract, test factories for
all three roles, and documented behavior for membership removal and inactive tenants.

## Implementation Handoff

### Permission model

`backend/app/core/permissions.py` is the server source of truth. The role maps are immutable at
runtime and unknown database roles resolve to no permissions with a generic warning. The access
token still contains only user/session identity; tenant role and permissions are loaded from the
database on every protected request.

Two stable job permissions were added because polling and lifecycle operations are shared by
multiple workflows:

- `job:read`: poll a job or subscribe to its events;
- `job:manage`: cancel or retry a job.

Viewer receives read permissions. Editor receives the Viewer set plus workflow creation and update
permissions. Admin receives the Editor set plus project archive and member/audit permissions.

### Route inventory

| API operation | Primary permission |
|---|---|
| Project create | `project:create` |
| Project list/get | `project:read` |
| Project update | `project:update` |
| Project archive | `project:archive` |
| Document upload/delete | `document:upload` |
| Document list/get | `document:read` |
| Summary generate/update | `summary:update` |
| Summary get | `summary:read` |
| Summary approve | `summary:approve` |
| Template upload/archive | `template:manage` |
| Template list/get | `template:read` |
| WBS generation start | `wbs:generate` |
| WBS latest/version list | `wbs:read` |
| WBS update | `wbs:update` |
| Validation start | `validation:run` |
| Validation get | `validation:read` |
| Export start | `export:create` |
| Export get/list/download | `export:read` |
| Job get/events | `job:read` |
| Job cancel/retry | `job:manage` |

All tenant routers publish `401`, `403`, and `404` response descriptions in OpenAPI. A missing or
inactive tenant and a tenant-owned resource outside the authorized tenant return `404`. A missing
membership, unknown role, or missing permission returns `403` without disclosing another tenant's
data.

### `/me` contract

Each active tenant membership now includes a sorted `permissions: string[]` field alongside `id`,
`name`, `slug`, and `role`. The React auth context exposes `can(permission)` against the selected
membership. Navigation and create, upload, generation, summary editing, WBS editing, validation,
export, and Settings commands use this helper for presentation only.

### Database and configuration

No database schema or configuration change was required for Phase 2. Existing membership roles are
used as the authorization source. No migration was created.

### Verification evidence

Completed locally on October 22, 2026:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
# 34 passed

.\.venv\Scripts\python.exe -m ruff check app tests
# All checks passed

cd ..\WBS_UI
npm.cmd run build
# TypeScript and Vite build passed

npm.cmd run lint
# ESLint passed

npx.cmd playwright test
# 7 passed
```

The backend authorization suite covers the complete immutable role map, Viewer and Editor behavior,
Admin workflow access, unknown roles, inactive and absent memberships, same-token role changes and
membership removal, OpenAPI outcomes, and cross-tenant project, document/summary, template, job,
WBS, validation, and export IDs. Browser tests cover Viewer and Editor controls plus a forced `403`
identity response.

### Deployment and rollback

Deploy the API permission enforcement before the UI that hides unavailable commands. Monitor `403`
and `404` rates by route without recording raw tokens or cross-tenant identifiers. Roll back the
application release as a unit if the approved role mapping is incorrect; do not bypass individual
checks. No database rollback is needed for this phase.
