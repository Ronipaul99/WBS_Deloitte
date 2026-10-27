import { expect, test } from '@playwright/test';

async function mockUnauthenticatedSession(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/auth/refresh', (route) => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'No active session.' }),
  }));
  await page.route('**/api/v1/me', (route) => route.fulfill({
    status: 401,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Bearer access token is required.' }),
  }));
}

test('forgot-password request ends in the neutral confirmation state', async ({ page }) => {
  await mockUnauthenticatedSession(page);
  await page.route('**/api/v1/auth/forgot-password', (route) => route.fulfill({
    status: 202,
    contentType: 'application/json',
    body: JSON.stringify({
      message: 'If the account is eligible, password reset instructions will be sent.',
    }),
  }));

  await page.goto('/');
  await page.getByRole('button', { name: 'Forgot password?' }).click();
  await expect(page).toHaveURL(/\/forgot-password$/);
  await page.getByLabel('Email address').fill('person@example.com');
  await page.getByRole('button', { name: 'Send reset link' }).click();

  await expect(page.getByRole('status')).toContainText(
    'If the account is eligible, password reset instructions will be sent.',
  );
  await expect(page.getByText('person@example.com')).toHaveCount(0);
});

test('reset token is held only in memory and removed from the URL', async ({ page }) => {
  await mockUnauthenticatedSession(page);
  const rawToken = 'browser-secret-reset-token';
  let submittedToken = '';
  await page.route('**/api/v1/auth/reset-password', async (route) => {
    const body = route.request().postDataJSON() as { token: string };
    submittedToken = body.token;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: 'Password reset complete.' }),
    });
  });

  await page.goto(`/reset-password#token=${rawToken}`);
  await expect(page).toHaveURL(/\/reset-password$/);
  await expect(page.locator('body')).not.toContainText(rawToken);
  expect(await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }))).toEqual({ local: [], session: [] });

  await page.getByLabel('New password', { exact: true }).fill('New-Secure-Password-42');
  await page.getByLabel('Confirm new password').fill('New-Secure-Password-42');
  await page.getByRole('button', { name: 'Update password' }).click();

  await expect(page.getByRole('heading', { name: 'Password updated' })).toBeVisible();
  expect(submittedToken).toBe(rawToken);
  expect(await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }))).toEqual({ local: [], session: [] });
});

test('missing reset token presents the generic unavailable state', async ({ page }) => {
  await mockUnauthenticatedSession(page);
  await page.goto('/reset-password');

  await expect(page.getByRole('heading', { name: 'Reset link unavailable' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText(
    'The password reset link is invalid or has expired.',
  );
});

test('forgot-password flow works with keyboard controls on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockUnauthenticatedSession(page);
  await page.route('**/api/v1/auth/forgot-password', (route) => route.fulfill({
    status: 202,
    contentType: 'application/json',
    body: JSON.stringify({
      message: 'If the account is eligible, password reset instructions will be sent.',
    }),
  }));

  await page.goto('/forgot-password');
  await page.keyboard.type('mobile@example.com');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');

  await expect(page.getByRole('status')).toBeVisible();
  const panelBox = await page.locator('.login-panel').boundingBox();
  expect(panelBox).not.toBeNull();
  expect(panelBox!.x).toBeGreaterThanOrEqual(0);
  expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(390);
});
