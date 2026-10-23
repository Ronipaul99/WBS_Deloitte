# Phase 4: Account and Session Management UI

## Phase Status

Implemented and locally verified. Live deployed-environment verification remains part of Phase 7.

## Outcome

Authenticated users can review identity details, change a local password, inspect active sessions,
revoke another session, and sign out everywhere without operator assistance.

## Execution Context

Existing backend endpoints:

- `POST /api/v1/auth/change-password`;
- `GET /api/v1/auth/sessions`;
- `DELETE /api/v1/auth/sessions/{session_id}`;
- `POST /api/v1/auth/logout-all`;
- `GET /api/v1/me`.

Existing frontend components:

- auth state in `WBS_UI/src/auth/AuthProvider.tsx`;
- API client in `WBS_UI/src/services/apiClient.ts`;
- profile dropdown and Settings navigation in `WBS_UI/src/components/AppLayout.tsx`;
- Settings currently renders a placeholder through `WBS_UI/src/App.tsx`.

The access token remains memory-only. Continue using the refresh cookie and shared API client.

## Product Decisions

First-release decisions:

- timestamps are sufficient; device labels are deferred;
- email and display name are read-only;
- current session can be ended using normal Sign Out;
- session list revokes other sessions;
- local credentials are described as a WBS Genie password, and federated credentials as enterprise
  SSO;
- changing email is deferred because it requires identity reverification.

## Files Expected to Change

- `WBS_UI/src/App.tsx`
- `WBS_UI/src/components/AppLayout.tsx`
- `WBS_UI/src/auth/authContext.ts`
- `WBS_UI/src/auth/AuthProvider.tsx`
- `WBS_UI/src/services/apiClient.ts`
- new account/security service module
- new Settings profile/security views and CSS
- frontend Playwright tests
- optionally `backend/app/schemas/auth.py` and auth routes for richer session metadata
- backend session tests

## Work Breakdown

### 1. Finalize account contracts

Confirm `/me` exposes:

- user ID;
- display name;
- email;
- identity providers or an `can_change_password` flag;
- active memberships and permissions.

Avoid making React infer local-password availability from email or role.

Confirm session response exposes only safe information:

- opaque session record ID;
- created time;
- last-used time;
- expiry time;
- current-session boolean;
- optional server-derived device/browser label.

Do not return stored IP or user-agent fingerprints.

### 2. Add typed account API functions

Create a focused frontend service with:

```typescript
getSessions()
revokeSession(sessionId)
changePassword(currentPassword, newPassword)
logoutAll()
```

All functions must use `apiRequest`. Do not duplicate token-refresh logic in a view.

### 3. Replace the Settings placeholder

Build a quiet operational Settings layout with Profile and Security tabs or sections.

Profile section:

- display name;
- email;
- selected tenant and role;
- identity provider information.

Security section:

- local change-password form when allowed;
- active sessions list;
- revoke command for other sessions;
- sign-out-everywhere command.

Use icon buttons only where the symbol is familiar and include tooltips for unfamiliar icons. Do not
place cards inside cards.

### 4. Implement change-password behavior

- Require current password, new password, and confirmation.
- Apply basic client validation for feedback while keeping the server authoritative.
- Disable submission while pending.
- Do not retain field values after completion or navigation.
- On success, clear auth state and navigate to login because the backend revokes sessions.
- On incorrect current password, preserve the session and show the safe inline error.
- Never write password values to logs, telemetry, URL state, or global state.

### 5. Implement session management

- Load sessions when the Security view opens.
- Mark the current session clearly.
- Sort current first, then most recently used.
- Confirm before revoking another session.
- Optimistically remove only after successful API response, or refetch on success.
- Treat a `404` during revocation as already absent and refetch.
- After logout-all, clear all cached user and tenant data before showing login.

### 6. Wire the profile menu

- Profile Details navigates to Settings/Profile.
- Sign Out continues to revoke the refresh family and clear local state.
- Close menus on navigation, sign-out, Escape, and outside interaction.
- Ensure keyboard and focus management work.

## Error and State Requirements

- Stable loading state that does not resize surrounding layout.
- Empty session state when no other devices exist.
- Generic recoverable API error with retry.
- Inline field errors for password validation.
- Confirmation dialog for logout-all and session revocation.
- Access loss immediately removes protected content.
- SSO-only user sees provider-managed password text, not a disabled password form.

## Test Plan

Backend:

- session list belongs only to the current user;
- session IDs cannot revoke another user's session;
- current session is identified from access-token family ID;
- password change requires the correct current password;
- password change increments `auth_version` and revokes all refresh sessions;
- OIDC-only identity cannot use local password change.

Frontend and browser:

- Profile Details opens the correct view.
- Local user changes password and returns to login.
- Password values disappear after navigation and success.
- Other session can be revoked.
- Sign out everywhere clears the workspace and tenant state.
- Current session is not accidentally shown as another device.
- SSO-only view hides local password inputs.
- Loading, empty, error, desktop, mobile, and keyboard states pass.
- Browser storage contains no credentials.

## Security Review Checklist

- [x] Password fields never enter shared React state, logs, or telemetry.
- [x] Session response excludes raw IP/user-agent fingerprints.
- [x] Revocation verifies session ownership in SQL.
- [x] Global logout clears tenant-owned client caches.
- [x] OIDC users cannot set a local password unless explicitly enrolled.
- [x] UI errors do not expose hashes, tokens, or backend trace details.
- [x] Destructive commands require deliberate confirmation.

## Rollout and Rollback

The Settings UI can be deployed after its APIs are stable. If a UI issue occurs, hide the Settings
navigation while retaining backend endpoints. Do not disable server revocation or password security
to preserve a broken UI flow.

## Exit Criteria

- [x] Profile and Security views replace the placeholder.
- [x] Local password change works through the browser.
- [x] Session list and other-session revocation work.
- [x] Logout-all clears server and browser state.
- [x] SSO-only identity behavior is correct.
- [x] Accessibility and responsive tests pass.
- [x] No credential persists in web storage or application logs.

## Implementation Evidence

- `GET /api/v1/me` returns `identity_providers`, `can_change_password`, and
  `can_manage_sessions` without returning identity subjects or credential material.
- SSO-only identities delegate password changes to the provider but retain WBS Genie session review,
  revocation, and logout-all controls.
- The account security service centralizes session, password-change, and logout-all requests through
  the shared refresh-aware API client.
- Profile Details is available to every authenticated role through the header menu. The existing
  sidebar Settings permission remains unchanged because it represents administrative settings.
- Password values stay inside the mounted form. Navigation unmounts the form, and successful
  password change or logout-all clears access, user, and selected-tenant state.
- Current sessions are sorted first and cannot be revoked from the list. Other-session revocation
  and logout-all require confirmation; a stale session `404` triggers a refetch.
- Backend verification: `python -m pytest -q` (`53 passed`) and
  `ruff check app tests migrations` passed.
- Frontend verification: `npx.cmd playwright test` (`19 passed`), plus `npm.cmd run lint` and
  `npm.cmd run build` passed.
- Sanitized visual evidence: [desktop Security](phase-04-artifacts/desktop-security.png) and
  [mobile Profile](phase-04-artifacts/mobile-profile.png).
- No schema revision was required for this phase.

Known limitation: device and browser labels are intentionally deferred because the server does not
retain or expose raw user-agent data. Live deployment verification remains in Phase 7.

## Handoff

Provide final account/session TypeScript types, navigation behavior, screenshots for desktop/mobile,
API contract changes, test results, and any remaining identity-edit requirements.
