import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  VIEWER_PERMISSIONS,
  mockAuthenticatedUser,
} from './auth-mocks';

const currentSession = {
  id: '11111111-1111-4111-8111-111111111111',
  created_at: '2026-10-20T08:00:00Z',
  last_used_at: '2026-10-22T09:00:00Z',
  expires_at: '2026-10-29T09:00:00Z',
  current: true,
};

const otherSession = {
  id: '22222222-2222-4222-8222-222222222222',
  created_at: '2026-10-18T08:00:00Z',
  last_used_at: '2026-10-21T10:30:00Z',
  expires_at: '2026-10-28T10:30:00Z',
  current: false,
};

async function openProfileSettings(page: Page) {
  await page.getByRole('button', { name: 'Open profile menu' }).click();
  await page.getByRole('menuitem', { name: 'Profile Details' }).click();
  await expect(page.getByRole('heading', { name: 'Account settings' })).toBeVisible();
}

async function openSecuritySettings(page: Page) {
  await openProfileSettings(page);
  await page.getByRole('tab', { name: 'Security' }).click();
}

test('profile menu opens personal settings for a viewer', async ({ page }) => {
  await mockAuthenticatedUser(page, {
    role: 'VIEWER',
    permissions: VIEWER_PERMISSIONS,
  });
  await page.goto('/');

  const profileButton = page.getByRole('button', { name: 'Open profile menu' });
  await profileButton.click();
  await page.getByText('WBS Genie').first().click();
  await expect(page.getByRole('menu', { name: 'Profile menu' })).toHaveCount(0);

  await openProfileSettings(page);
  const settingsPanel = page.getByRole('tabpanel');
  await expect(settingsPanel.getByText('Test Planner', { exact: true })).toBeVisible();
  await expect(page.getByText('planner@example.com')).toBeVisible();
  await expect(page.getByText('Test Workspace', { exact: true })).toBeVisible();
  await expect(page.getByText('WBS Genie password')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
});

test('security view identifies current session and revokes only another session', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/auth/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([otherSession, currentSession]),
  }));
  let revokedSessionId = '';
  await page.route('**/api/v1/auth/sessions/*', (route) => {
    revokedSessionId = route.request().url().split('/').at(-1) ?? '';
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Session revoked.' }),
    });
  });

  await page.goto('/');
  await openSecuritySettings(page);
  await expect(page.getByText('Current session')).toBeVisible();
  await expect(page.getByText('This device')).toBeVisible();
  await expect(page.getByText('Other active session', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Revoke other active session' })).toHaveCount(1);

  await page.getByRole('button', { name: 'Revoke other active session' }).click();
  const dialog = page.getByRole('dialog', { name: 'Revoke this session?' });
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  await page.getByRole('button', { name: 'Revoke other active session' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Revoke session' }).click();
  await expect(page.getByText('Other active session', { exact: true })).toHaveCount(0);
  await expect(page.getByText('No other active sessions.')).toBeVisible();
  expect(revokedSessionId).toBe(otherSession.id);
});

test('password fields clear after navigation and incorrect password preserves the session', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/auth/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([currentSession]),
  }));
  await page.route('**/api/v1/auth/change-password', (route) => route.fulfill({
    status: 400,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Current password is incorrect.' }),
  }));

  await page.goto('/');
  await openSecuritySettings(page);
  await page.getByLabel('Current password').fill('Incorrect-Current-Password-42');
  await page.getByLabel('New password', { exact: true }).fill('New-Password-Value-84');
  await page.getByLabel('Confirm new password').fill('New-Password-Value-84');
  await page.getByRole('tab', { name: 'Profile' }).click();
  await page.getByRole('tab', { name: 'Security' }).click();

  await expect(page.getByLabel('Current password')).toHaveValue('');
  await expect(page.getByLabel('New password', { exact: true })).toHaveValue('');
  await page.getByLabel('Current password').fill('Incorrect-Current-Password-42');
  await page.getByLabel('New password', { exact: true }).fill('New-Password-Value-84');
  await page.getByLabel('Confirm new password').fill('New-Password-Value-84');
  await page.getByRole('button', { name: 'Update password' }).click();

  await expect(page.getByRole('alert')).toHaveText('Current password is incorrect.');
  await expect(page.getByRole('heading', { name: 'Account settings' })).toBeVisible();
});

test('successful password change clears credentials and returns to login', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/auth/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([currentSession]),
  }));
  let validRequestShape = false;
  await page.route('**/api/v1/auth/change-password', (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    validRequestShape = typeof body.current_password === 'string'
      && typeof body.new_password === 'string'
      && !('confirmation' in body);
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Password changed.' }),
    });
  });

  await page.goto('/');
  await openSecuritySettings(page);
  await page.getByLabel('Current password').fill('Current-Password-Value-42');
  await page.getByLabel('New password', { exact: true }).fill('New-Password-Value-84');
  await page.getByLabel('Confirm new password').fill('New-Password-Value-84');
  await page.getByRole('button', { name: 'Update password' }).click();

  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  expect(validRequestShape).toBe(true);
  expect(await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }))).toEqual({ local: [], session: [] });
});

test('sign out everywhere requires confirmation and clears protected state', async ({ page }) => {
  await mockAuthenticatedUser(page);
  await page.route('**/api/v1/auth/sessions', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([currentSession]),
  }));
  await page.route('**/api/v1/auth/logout-all', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ message: 'Signed out on all devices.' }),
  }));

  await page.goto('/');
  await openSecuritySettings(page);
  await page.getByRole('button', { name: 'Sign out everywhere' }).click();
  const dialog = page.getByRole('dialog', { name: 'Sign out everywhere?' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Sign out everywhere' }).click();

  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Account settings' })).toHaveCount(0);
});

test('SSO-only account delegates passwords but retains application session controls', async ({ page }) => {
  let sessionRequests = 0;
  await mockAuthenticatedUser(page, {
    identityProviders: ['oidc'],
    canChangePassword: false,
  });
  await page.route('**/api/v1/auth/sessions', (route) => {
    sessionRequests += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([currentSession]),
    });
  });

  await page.goto('/');
  await openSecuritySettings(page);

  await expect(page.getByText('Password managed by enterprise SSO')).toBeVisible();
  await expect(page.getByLabel('Current password')).toHaveCount(0);
  await expect(page.getByText('Current session')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign out everywhere' })).toBeVisible();
  expect(sessionRequests).toBeGreaterThan(0);
});

test('session loading failure has a stable retry and empty state', async ({ page }) => {
  await mockAuthenticatedUser(page);
  let requests = 0;
  await page.route('**/api/v1/auth/sessions', async (route) => {
    requests += 1;
    if (requests <= 2) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Unavailable.' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });

  await page.goto('/');
  await openSecuritySettings(page);
  await expect(page.getByRole('status')).toHaveText(/Loading active sessions/);
  await expect(page.getByRole('alert')).toContainText('Active sessions could not be loaded.');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText('No active sessions were returned.')).toBeVisible();
});

test('profile menu and settings remain keyboard accessible on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAuthenticatedUser(page, {
    role: 'VIEWER',
    permissions: VIEWER_PERMISSIONS,
  });
  await page.goto('/');

  const profileButton = page.getByRole('button', { name: 'Open profile menu' });
  await profileButton.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menuitem', { name: 'Profile Details' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(profileButton).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menuitem', { name: 'Profile Details' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Account settings' })).toBeVisible();

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);
});
