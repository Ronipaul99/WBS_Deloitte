import { expect, test } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';

test('hybrid login offers enterprise and local sign-in', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Refresh session is required.' }),
  }));
  await page.route('**/api/v1/me', (route) => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Bearer access token is required.' }),
  }));
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Continue with Enterprise SSO' })).toBeVisible();
  await expect(page.getByLabel('Email address')).toBeVisible();
  await expect(page.locator('#login-password')).toBeVisible();
});

test('SSO callback uses the internal session and clears transient URL data', async ({ page }) => {
  await mockAuthenticatedUser(page, {
    identityProviders: ['enterprise_oidc'],
    canChangePassword: false,
  });
  await page.goto('/sso/callback');

  await expect(page.getByRole('heading', { name: 'Welcome back, Test' })).toBeVisible();
  await expect(page).toHaveURL('http://127.0.0.1:5176/');
  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(storage.local).toEqual({});
  expect(storage.session).toEqual({});
});

test('SSO callback shows only allowlisted safe provider errors', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({ status: 401 }));
  await page.route('**/api/v1/me', (route) => route.fulfill({ status: 401 }));
  await page.goto('/sso/callback?error=access_denied&provider_token=must-not-survive');

  await expect(page.getByRole('heading', { name: 'Sign-in not completed' })).toBeVisible();
  await expect(page.getByText(/does not have access yet/i)).toBeVisible();
  await expect(page).toHaveURL('http://127.0.0.1:5176/sso/callback');
  await expect(page.getByText('must-not-survive')).toHaveCount(0);
});
