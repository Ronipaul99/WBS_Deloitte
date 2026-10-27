import { expect, test } from '@playwright/test';
import type { Page, Route } from '@playwright/test';
import {
  EDITOR_PERMISSIONS,
  VIEWER_PERMISSIONS,
  mockAuthenticatedUser,
} from './auth-mocks';

const currentAdmin = {
  user_id: '00000000-0000-0000-0000-000000000001',
  email: 'planner@example.com',
  display_name: 'Test Planner',
  role: 'ADMIN',
  status: 'ACTIVE',
  joined_at: '2026-09-01T08:00:00Z',
};

const editor = {
  user_id: '22222222-2222-4222-8222-222222222222',
  email: 'editor@example.com',
  display_name: 'Project Editor',
  role: 'EDITOR',
  status: 'ACTIVE',
  joined_at: '2026-10-01T08:00:00Z',
};

const pendingInvitation = {
  id: '33333333-3333-4333-8333-333333333333',
  email: 'pending@example.com',
  role: 'VIEWER',
  status: 'PENDING',
  expires_at: '2026-10-25T08:00:00Z',
  created_at: '2026-10-22T08:00:00Z',
  invited_by_user_id: currentAdmin.user_id,
};

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function openMembers(page: Page) {
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page).toHaveURL(/\/settings\/members$/);
  await expect(page.getByRole('heading', { name: 'Workspace members' })).toBeVisible();
}

test('administrator manages roles, invitations, and removals from Settings', async ({ page }) => {
  await mockAuthenticatedUser(page);
  let members = [currentAdmin, editor];
  let invitations = [pendingInvitation];
  let changedRole = '';
  let invitationSent = '';
  let resendCount = 0;

  await page.route('**/api/v1/tenants/*/members?*', (route) => json(route, 200, {
    members,
    invitations,
    total_members: members.length,
    total_invitations: invitations.length,
    offset: 0,
    limit: 10,
  }));
  await page.route('**/api/v1/tenants/*/members/*', async (route) => {
    const userId = route.request().url().split('/').at(-1) ?? '';
    if (route.request().method() === 'PATCH') {
      const payload = route.request().postDataJSON() as { role: 'ADMIN' | 'EDITOR' | 'VIEWER' };
      changedRole = payload.role;
      members = members.map((member) => (
        member.user_id === userId ? { ...member, role: payload.role } : member
      ));
      return json(route, 200, members.find((member) => member.user_id === userId));
    }
    members = members.filter((member) => member.user_id !== userId);
    return route.fulfill({ status: 204 });
  });
  await page.route('**/api/v1/tenants/*/invitations**', async (route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === 'POST' && url.endsWith('/resend')) {
      resendCount += 1;
      return json(route, 200, pendingInvitation);
    }
    if (request.method() === 'DELETE') {
      const invitationId = url.split('/').at(-1) ?? '';
      invitations = invitations.filter((item) => item.id !== invitationId);
      return route.fulfill({ status: 204 });
    }
    const payload = request.postDataJSON() as { email: string; role: 'ADMIN' | 'EDITOR' | 'VIEWER' };
    invitationSent = payload.email;
    const created = {
      ...pendingInvitation,
      id: '44444444-4444-4444-8444-444444444444',
      email: payload.email,
      role: payload.role,
    };
    invitations = [...invitations, created];
    return json(route, 201, created);
  });

  await page.goto('/');
  await openMembers(page);

  await expect(page.getByText('Project Editor')).toBeVisible();
  await page.getByLabel('Role for Project Editor').selectOption('VIEWER');
  await expect.poll(() => changedRole).toBe('VIEWER');

  await page.getByRole('button', { name: 'Invite member' }).click();
  const inviteDialog = page.getByRole('dialog', { name: 'Invite member' });
  await expect(inviteDialog.getByLabel('Email address')).toBeFocused();
  await inviteDialog.getByLabel('Email address').fill('new.member@example.com');
  await inviteDialog.getByLabel('Workspace role').selectOption('EDITOR');
  await inviteDialog.getByRole('button', { name: 'Send invitation' }).click();
  await expect.poll(() => invitationSent).toBe('new.member@example.com');

  await page.getByRole('button', { name: 'Resend invitation to pending@example.com' }).click();
  await expect.poll(() => resendCount).toBe(1);
  await page.getByRole('button', { name: 'Revoke invitation for pending@example.com' }).click();
  const revokeDialog = page.getByRole('dialog', { name: 'Revoke this invitation?' });
  await expect(revokeDialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await revokeDialog.getByRole('button', { name: 'Revoke invitation' }).click();
  await expect(page.getByText('pending@example.com')).toHaveCount(0);

  await page.getByRole('button', { name: 'Remove Project Editor' }).click();
  await page.getByRole('dialog', { name: 'Remove this member?' }).getByRole('button', { name: 'Remove member' }).click();
  await expect(page.getByText('Project Editor')).toHaveCount(0);
});

for (const account of [
  { role: 'VIEWER' as const, permissions: VIEWER_PERMISSIONS },
  { role: 'EDITOR' as const, permissions: EDITOR_PERMISSIONS },
]) {
  test(`${account.role.toLowerCase()} direct member URL renders access denied`, async ({ page }) => {
    await mockAuthenticatedUser(page, account);
    await page.route('**/api/v1/tenants/*/members?*', (route) => json(route, 403, {
      detail: 'You do not have permission to perform this operation.',
    }));
    await page.goto('/settings/members');
    await expect(page.getByRole('heading', { name: 'Access denied' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'Members' })).toHaveCount(0);
  });
}

test('member list exposes stable error, retry, empty, search, and pagination states', async ({ page }) => {
  await mockAuthenticatedUser(page);
  let requests = 0;
  const offsets: string[] = [];
  const searches: string[] = [];
  await page.route('**/api/v1/tenants/*/members?*', async (route) => {
    requests += 1;
    const url = new URL(route.request().url());
    offsets.push(url.searchParams.get('offset') ?? '');
    searches.push(url.searchParams.get('search') ?? '');
    if (requests <= 2) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      return json(route, 503, { detail: 'Unavailable.' });
    }
    const offset = Number(url.searchParams.get('offset') ?? 0);
    return json(route, 200, {
      members: offset === 0 ? [currentAdmin] : [editor],
      invitations: [],
      total_members: 12,
      total_invitations: 0,
      offset,
      limit: 10,
    });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Settings' }).click();
  await expect(page.getByRole('status')).toContainText('Loading workspace members');
  await expect(page.getByRole('alert')).toContainText('Workspace members could not be loaded.');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.locator('tbody').first().getByText('Test Planner', { exact: true })).toBeVisible();

  await page.getByLabel('Search members and invitations').fill('editor');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect.poll(() => searches.at(-1)).toBe('editor');
  await page.getByRole('button', { name: 'Next page' }).click();
  await expect.poll(() => offsets.at(-1)).toBe('10');
  await expect(page.getByText('Project Editor')).toBeVisible();
  await expect(page.getByText('No pending invitations.')).toBeVisible();
});

test('final-administrator denial is shown without optimistic role drift', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/tenants/*/members?*', (route) => json(route, 200, {
    members: [currentAdmin],
    invitations: [],
    total_members: 1,
    total_invitations: 0,
    offset: 0,
    limit: 10,
  }));
  await page.route('**/api/v1/tenants/*/members/*', (route) => json(route, 409, {
    detail: 'The final active administrator cannot be demoted.',
  }));
  await page.goto('/');
  await openMembers(page);
  await page.getByLabel('Role for Test Planner').selectOption('EDITOR');
  await expect(page.getByRole('alert')).toHaveText('The final active administrator cannot be demoted.');
  await expect(page.getByLabel('Role for Test Planner')).toHaveValue('ADMIN');
});

test('new local account accepts an invitation on mobile without persisting the token', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/v1/auth/refresh', (route) => json(route, 401, { detail: 'No session.' }));
  await page.route('**/api/v1/me', (route) => json(route, 401, { detail: 'Unauthorized.' }));
  let acceptedToken = '';
  await page.route('**/api/v1/auth/accept-invitation', async (route) => {
    const payload = route.request().postDataJSON() as { token: string; display_name: string };
    acceptedToken = payload.token;
    expect(payload.display_name).toBe('New Planner');
    return json(route, 200, {
      message: 'Invitation accepted.',
      account_created: true,
      tenant_id: '00000000-0000-0000-0000-000000000001',
      tenant_name: 'Test Workspace',
      role: 'VIEWER',
    });
  });

  await page.goto('/accept-invitation#token=single-use-secret');
  await expect(page).toHaveURL(/\/accept-invitation$/);
  await page.getByLabel('Display name').fill('New Planner');
  await page.getByLabel('Password', { exact: true }).fill('A-Secure-Invitation-Password-84');
  await page.getByLabel('Confirm password').fill('A-Secure-Invitation-Password-84');
  await page.getByRole('button', { name: 'Create account and join' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Test Workspace' })).toBeVisible();
  expect(acceptedToken).toBe('single-use-secret');
  const storage = await page.evaluate(() => ({
    local: JSON.stringify(localStorage),
    session: JSON.stringify(sessionStorage),
    url: window.location.href,
  }));
  expect(storage.local).not.toContain('single-use-secret');
  expect(storage.session).not.toContain('single-use-secret');
  expect(storage.url).not.toContain('single-use-secret');
  await expect(page.locator('body')).not.toHaveCSS('overflow-x', 'scroll');
});

test('existing account signs in and accepts its invitation', async ({ page }) => {
  let accepted = false;
  let authorization = '';
  await page.route('**/api/v1/auth/refresh', (route) => json(route, 401, { detail: 'No session.' }));
  await page.route('**/api/v1/auth/login', (route) => json(route, 200, {
    access_token: 'existing-user-access', token_type: 'bearer', expires_in: 900,
  }));
  await page.route('**/api/v1/me', (route) => {
    if (!route.request().headers().authorization) {
      return json(route, 401, { detail: 'Unauthorized.' });
    }
    return json(route, 200, {
      id: '55555555-5555-4555-8555-555555555555',
      email: 'existing@example.com',
      display_name: 'Existing User',
      identity_providers: ['local'],
      can_change_password: true,
      can_manage_sessions: true,
      tenants: accepted ? [{
        id: '00000000-0000-0000-0000-000000000001',
        name: 'Test Workspace',
        slug: 'test',
        role: 'EDITOR',
        permissions: EDITOR_PERMISSIONS,
      }] : [],
    });
  });
  await page.route('**/api/v1/auth/accept-invitation', (route) => {
    authorization = route.request().headers().authorization ?? '';
    accepted = true;
    return json(route, 200, {
      message: 'Invitation accepted.',
      account_created: false,
      tenant_id: '00000000-0000-0000-0000-000000000001',
      tenant_name: 'Test Workspace',
      role: 'EDITOR',
    });
  });

  await page.goto('/accept-invitation#token=existing-secret');
  await page.getByRole('tab', { name: 'Existing account' }).click();
  await page.getByLabel('Email address').fill('existing@example.com');
  await page.getByLabel('Password', { exact: true }).fill('Correct-Horse-Battery-Staple-84');
  await page.getByRole('button', { name: 'Sign in and join' }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('button', { name: 'Create project', exact: true })).toBeVisible();
  expect(authorization).toBe('Bearer existing-user-access');
});

test('authenticated invitation recipient can switch accounts without losing the token', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/auth/logout', (route) => json(route, 200, { message: 'Signed out.' }));
  await page.goto('/accept-invitation#token=account-switch-secret');
  await expect(page).toHaveURL(/\/accept-invitation$/);
  await page.getByRole('button', { name: 'Use another account' }).click();
  await expect(page.getByRole('tab', { name: 'Existing account' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  const storage = await page.evaluate(() => `${localStorage}|${sessionStorage}|${location.href}`);
  expect(storage).not.toContain('account-switch-secret');
});
