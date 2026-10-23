import { request as playwrightRequest } from '@playwright/test';
import {
  apiUrl,
  assertNoCredentialStorage,
  bearer,
  changedPassword,
  endpoint,
  expect,
  expiredResetToken,
  invitationPassword,
  invitationToken,
  loginApi,
  loginPage,
  originHeaders,
  password,
  resetPassword,
  resetToken,
  state,
  test,
} from './support';

test.describe('live authentication and browser security', () => {
  test('rejects invalid credentials and restores a valid browser session without storage leaks', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();

    await page.getByLabel('Email address').fill(`unknown.${state.run_id}@example.com`);
    await page.locator('#login-password').fill('incorrect-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('alert')).toHaveText('The email or password is incorrect.');

    await page.getByLabel('Email address').fill(state.emails.editor_a);
    await page.locator('#login-password').fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();

    const refreshCookie = (await page.context().cookies()).find(
      (cookie) => cookie.name === 'wbs_refresh',
    );
    expect(refreshCookie).toMatchObject({
      httpOnly: true,
      sameSite: 'Lax',
      secure: false,
      path: '/api/v1/auth',
    });
    await assertNoCredentialStorage(page);

    await page.reload();
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();
    await assertNoCredentialStorage(page);
  });

  test('coalesces concurrent refreshes after the test-only access token expires', async ({ page }) => {
    await loginPage(page, state.emails.editor_a);
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();

    let successfulRefreshes = 0;
    page.on('response', (response) => {
      if (
        response.request().method() === 'POST'
        && new URL(response.url()).pathname.endsWith('/auth/refresh')
        && response.status() === 200
      ) successfulRefreshes += 1;
    });

    // The access lifetime is deliberately five seconds only in APP_ENV=test.
    await page.waitForTimeout(5_250);
    await page.evaluate(async () => {
      const modulePath = '/src/services/apiClient.ts';
      const api = await import(modulePath);
      await Promise.all([
        api.apiRequest('/me'),
        api.apiRequest('/me/tenants'),
        api.apiRequest('/me'),
      ]);
    });

    expect(successfulRefreshes).toBe(1);
    await assertNoCredentialStorage(page);
  });

  test('rotates refresh tokens and revokes the family when an old token is replayed', async () => {
    const session = await loginApi(state.emails.session);
    const oldRefreshToken = /(?:^|;\s*)wbs_refresh=([^;]+)/.exec(session.setCookie)?.[1];
    expect(oldRefreshToken).toBeTruthy();

    const rotated = await session.context.post(endpoint('/auth/refresh'));
    expect(rotated.status()).toBe(200);

    const replay = await playwrightRequest.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: {
        ...originHeaders,
        Cookie: `wbs_refresh=${oldRefreshToken}`,
      },
    });
    expect((await replay.post(endpoint('/auth/refresh'))).status()).toBe(401);
    expect((await session.context.post(endpoint('/auth/refresh'))).status()).toBe(401);

    await replay.dispose();
    await session.context.dispose();
  });

  test('logout, logout-all, and password change invalidate the expected credentials', async () => {
    const logoutSession = await loginApi(state.emails.session);
    expect((await logoutSession.context.post(endpoint('/auth/logout'))).status()).toBe(200);
    expect((await logoutSession.context.post(endpoint('/auth/refresh'))).status()).toBe(401);
    await logoutSession.context.dispose();

    const first = await loginApi(state.emails.session);
    const second = await loginApi(state.emails.session);
    const logoutAll = await first.context.post(endpoint('/auth/logout-all'), {
      headers: bearer(first.token),
    });
    expect(logoutAll.status()).toBe(200);
    expect((await second.context.get(endpoint('/me'), { headers: bearer(second.token) })).status()).toBe(401);
    await first.context.dispose();
    await second.context.dispose();

    const change = await loginApi(state.emails.password_change);
    const changed = await change.context.post(endpoint('/auth/change-password'), {
      headers: bearer(change.token),
      data: { current_password: password, new_password: changedPassword },
    });
    expect(changed.status(), await changed.text()).toBe(200);
    expect((await change.context.get(endpoint('/me'), { headers: bearer(change.token) })).status()).toBe(401);
    await change.context.dispose();

    const oldPassword = await playwrightRequest.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: originHeaders,
    });
    expect((await oldPassword.post(endpoint('/auth/login'), {
      data: { email: state.emails.password_change, password },
    })).status()).toBe(401);
    expect((await oldPassword.post(endpoint('/auth/login'), {
      data: { email: state.emails.password_change, password: changedPassword },
    })).status()).toBe(200);
    await oldPassword.dispose();
  });

  test('handles forgot/reset expiry and reuse while removing the reset token from browser history', async ({ page }) => {
    const anonymous = await playwrightRequest.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: originHeaders,
    });
    const known = await anonymous.post(endpoint('/auth/forgot-password'), {
      data: { email: state.emails.editor_a },
    });
    const unknown = await anonymous.post(endpoint('/auth/forgot-password'), {
      data: { email: `missing.${state.run_id}@example.com` },
    });
    expect(known.status()).toBe(202);
    expect(unknown.status()).toBe(202);
    expect(await known.json()).toEqual(await unknown.json());
    expect((await anonymous.post(endpoint('/auth/reset-password'), {
      data: { token: expiredResetToken, new_password: resetPassword },
    })).status()).toBe(400);

    await page.goto(`/reset-password#token=${encodeURIComponent(resetToken)}`);
    await expect(page).toHaveURL(/\/reset-password$/);
    await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible();
    await page.getByLabel('New password', { exact: true }).fill(resetPassword);
    await page.getByLabel('Confirm new password', { exact: true }).fill(resetPassword);
    await page.getByRole('button', { name: 'Update password' }).click();
    await expect(page.getByRole('heading', { name: 'Password updated' })).toBeVisible();
    await assertNoCredentialStorage(page);

    expect((await anonymous.post(endpoint('/auth/reset-password'), {
      data: { token: resetToken, new_password: `${resetPassword}!Again` },
    })).status()).toBe(400);
    expect((await anonymous.post(endpoint('/auth/login'), {
      data: { email: state.emails.reset, password },
    })).status()).toBe(401);
    expect((await anonymous.post(endpoint('/auth/login'), {
      data: { email: state.emails.reset, password: resetPassword },
    })).status()).toBe(200);
    await anonymous.dispose();
  });

  test('removes invitation tokens before creating a tenant-scoped account', async ({ page }) => {
    await page.goto(`/accept-invitation#token=${encodeURIComponent(invitationToken)}`);
    await expect(page).toHaveURL(/\/accept-invitation$/);
    await expect(page.getByRole('heading', { name: 'Join your workspace' })).toBeVisible();
    await page.getByLabel('Display name').fill('Invited Fullstack User');
    await page.getByLabel('Password', { exact: true }).fill(invitationPassword);
    await page.getByLabel('Confirm password').fill(invitationPassword);
    await page.getByRole('button', { name: 'Create account and join' }).click();
    await expect(page.getByRole('heading', { name: new RegExp(`Welcome to Tenant A`) })).toBeVisible();
    await assertNoCredentialStorage(page);
  });

  test('enforces rate limits, trusted origins, CORS, inactive identities, and correlation IDs', async () => {
    const client = await playwrightRequest.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: originHeaders,
    });
    const limitedEmail = `limited.${state.run_id}@example.com`;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      expect((await client.post(endpoint('/auth/login'), {
        data: { email: limitedEmail, password: 'incorrect-password' },
      })).status()).toBe(401);
    }
    const limited = await client.post(endpoint('/auth/login'), {
      data: { email: limitedEmail, password: 'incorrect-password' },
    });
    expect(limited.status()).toBe(429);
    expect(limited.headers()['retry-after']).toBe('60');
    expect(limited.headers()['x-correlation-id']).toBeTruthy();

    for (const email of [state.emails.inactive, state.emails.sso]) {
      const denied = await client.post(endpoint('/auth/login'), { data: { email, password } });
      expect(denied.status()).toBe(401);
      expect(await denied.json()).toEqual({ detail: 'Invalid email or password.' });
    }

    const editor = await loginApi(state.emails.editor_a);
    const hostile = await playwrightRequest.newContext({
      baseURL: apiUrl,
      extraHTTPHeaders: { Origin: 'https://untrusted.example.com' },
    });
    expect((await hostile.post(endpoint('/auth/login'), {
      data: { email: state.emails.editor_a, password },
    })).status()).toBe(403);
    const protectedResponse = await hostile.get(endpoint('/me'), { headers: bearer(editor.token) });
    expect(protectedResponse.headers()['access-control-allow-origin']).toBeUndefined();

    const inactiveTenant = await loginApi(state.emails.inactive_tenant);
    const me = await inactiveTenant.context.get(endpoint('/me'), { headers: bearer(inactiveTenant.token) });
    expect((await me.json()).tenants).toEqual([]);
    expect((await inactiveTenant.context.get(
      endpoint(`/tenants/${state.inactive_tenant_id}/projects`),
      { headers: bearer(inactiveTenant.token) },
    )).status()).toBe(404);

    await inactiveTenant.context.dispose();
    await hostile.dispose();
    await editor.context.dispose();
    await client.dispose();
  });
});
