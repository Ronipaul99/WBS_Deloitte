# Authentication and Authorization Execution Pack

This directory breaks the master [functional and technical specification](../authentication-authorization-functional-technical-spec.md)
into independently executable development phases.

Each phase document contains the context an engineer needs to begin work without reconstructing the
design from earlier conversations. The master specification remains the source of truth for product
behavior and security policy. These files define execution order, repository impact, verification,
and handoff evidence.

## Phase Map

| Phase | Document | Current status | Depends on |
|---:|---|---|---|
| 1 | [Activate local authentication](phase-01-activate-local-authentication.md) | Code complete; target activation pending | Existing auth migration |
| 2 | [Enforce role-based authorization](phase-02-enforce-role-based-authorization.md) | Implemented and locally verified | Phase 1 |
| 3 | [Password recovery](phase-03-password-recovery.md) | Code complete; staging email activation pending | Phase 1 and email decision |
| 4 | [Account and session UI](phase-04-account-session-ui.md) | Implemented and locally verified | Phase 1 |
| 5 | [Tenant member administration](phase-05-tenant-member-administration.md) | Implemented and locally verified; staging activation pending | Phases 2 and 3 email interface |
| 6 | [Frontend and workflow integration](phase-06-frontend-workflow-integration.md) | Implemented and locally verified | Phases 1-5 |
| 7 | [Live full-stack verification](phase-07-live-full-stack-verification.md) | Implemented; local live smoke verified, PostgreSQL CI run pending | Phase 6 |
| 8 | [Production hardening and operations](phase-08-production-hardening-operations.md) | Repository implementation verified; platform activation and exercises pending | Phase 7 |
| 9 | [Enterprise SSO](phase-09-enterprise-sso.md) | Repository flow verified; provider approval and staging evidence pending | Phase 8 and provider decision |

## Execution Rules

1. Complete phases in dependency order. Phases 3 and 4 may run in parallel after Phase 1.
2. Use one implementation branch and pull request per phase unless the phase document explicitly
   separates database and UI delivery.
3. Do not mix unrelated WBS workflow refactors into authentication phases.
4. Apply schema changes through reviewed Alembic migrations on a Neon development branch.
5. Do not place credentials, passwords, raw tokens, database URLs, or provider secrets in commits,
   test output, screenshots, issue comments, or pull requests.
6. Preserve the access-token-in-memory and HttpOnly-refresh-cookie design.
7. Treat server-side authorization as authoritative; UI permission checks are presentation only.
8. Update the phase status and evidence section before review.
9. A phase is not complete when code exists; it is complete when its exit criteria and tests pass.
10. Stop deployment if a migration, authorization test, security test, or configuration gate fails.

## Standard Verification Commands

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest
ruff check app tests migrations
alembic check
```

Frontend:

```powershell
cd WBS_UI
npm.cmd run lint
npm.cmd run build
npx.cmd playwright test
```

Run Neon migration commands only against the intended development branch first. Confirm the active
database host without printing credentials.

## Required Phase Handoff

Every completed phase must provide:

- implementation summary;
- database revision, when applicable;
- affected API contracts;
- configuration changes without secret values;
- test command results;
- manual verification evidence;
- security review findings and disposition;
- deployment and rollback notes;
- known limitations passed to the next phase.

## Overall Completion Gate

The local authentication and authorization implementation is end to end through Phase 8. Phase 9's
repository-owned enterprise SSO journey is implemented, but production enterprise SSO cannot be
claimed until provider registration, target-environment protocol evidence, security approval, and
the break-glass exercise are complete.
