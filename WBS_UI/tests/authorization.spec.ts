import { expect, test } from '@playwright/test';
import {
  EDITOR_PERMISSIONS,
  VIEWER_PERMISSIONS,
  mockAuthenticatedUser,
} from './auth-mocks';

test('viewer sees read-only navigation without create or settings commands', async ({ page }) => {
  await mockAuthenticatedUser(page, { role: 'VIEWER', permissions: VIEWER_PERMISSIONS });
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'My Projects' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Templates' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Exports' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create WBS' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Generate Draft WBS' })).toHaveCount(0);
});

test('editor can create a WBS but does not see administrative settings', async ({ page }) => {
  await mockAuthenticatedUser(page, { role: 'EDITOR', permissions: EDITOR_PERMISSIONS });
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Create WBS' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate Draft WBS' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0);
});

test('a forced identity 403 fails safely back to the login screen', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ access_token: 'expired-membership-token', token_type: 'bearer', expires_in: 900 }),
  }));
  await page.route('**/api/v1/me', (route) => route.fulfill({
    status: 403,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Access denied.' }),
  }));

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate Draft WBS' })).toHaveCount(0);
});
