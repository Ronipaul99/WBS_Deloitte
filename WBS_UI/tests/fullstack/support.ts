import { readFileSync } from 'node:fs';
import { request as playwrightRequest, test as base, expect } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';

export interface FullstackState {
  run_id: string;
  tenant_a_id: string;
  tenant_b_id: string;
  inactive_tenant_id: string;
  final_admin_tenant_id: string;
  emails: Record<string, string>;
  user_ids: Record<string, string>;
}

export interface ApiSession {
  context: APIRequestContext;
  token: string;
  setCookie: string;
}

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required by the full-stack test suite.`);
  return value;
};

export const apiUrl = required('FULLSTACK_API_URL');
export const uiUrl = required('FULLSTACK_UI_URL');
export const endpoint = (path: string): string => (
  `${apiUrl}${path.startsWith('/') ? path : `/${path}`}`
);
export const password = required('FULLSTACK_TEST_PASSWORD');
export const resetToken = required('FULLSTACK_RESET_TOKEN');
export const expiredResetToken = required('FULLSTACK_EXPIRED_RESET_TOKEN');
export const invitationToken = required('FULLSTACK_INVITATION_TOKEN');
export const changedPassword = `${password}!Changed`;
export const resetPassword = `${password}!Reset`;
export const invitationPassword = `${password}!Invite`;
export const state = JSON.parse(
  readFileSync(required('FULLSTACK_STATE_PATH'), 'utf8'),
) as FullstackState;

export const originHeaders = { Origin: uiUrl, Accept: 'application/json' };

export async function loginApi(email: string, candidatePassword = password): Promise<ApiSession> {
  const context = await playwrightRequest.newContext({
    baseURL: apiUrl,
    extraHTTPHeaders: originHeaders,
  });
  const response = await context.post(endpoint('/auth/login'), {
    data: { email, password: candidatePassword },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json() as { access_token: string };
  return {
    context,
    token: body.access_token,
    setCookie: response.headers()['set-cookie'] ?? '',
  };
}

export function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

type FetchOptions = NonNullable<Parameters<APIRequestContext['fetch']>[1]>;

export async function apiFetch(
  session: ApiSession,
  path: string,
  options: FetchOptions = {},
) {
  const run = () => session.context.fetch(endpoint(path), {
    ...options,
    headers: {
      ...bearer(session.token),
      ...(options.headers as Record<string, string> | undefined),
    },
  });
  let response = await run();
  if (response.status() !== 401) return response;

  const refreshed = await session.context.post(endpoint('/auth/refresh'));
  if (refreshed.status() !== 200) return response;
  session.token = (await refreshed.json() as { access_token: string }).access_token;
  response = await run();
  return response;
}

export async function loginPage(page: Page, email: string): Promise<void> {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.locator('#login-password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

export async function assertNoCredentialStorage(page: Page): Promise<void> {
  const values = await page.evaluate(() => ({
    local: Object.entries(localStorage),
    session: Object.entries(sessionStorage),
  }));
  const serialized = JSON.stringify(values);
  for (const secret of [
    password,
    changedPassword,
    resetPassword,
    invitationPassword,
    resetToken,
    expiredResetToken,
    invitationToken,
  ]) {
    expect(serialized).not.toContain(secret);
  }
  expect(serialized.toLowerCase()).not.toContain('access_token');
  expect(serialized.toLowerCase()).not.toContain('refresh_token');
}

type Fixtures = { securityTelemetry: void };

export const test = base.extend<Fixtures>({
  securityTelemetry: [async ({ page }, use, testInfo) => {
    const consoleMessages: string[] = [];
    const networkSummary: Array<{ method: string; path: string; status: number; correlationId: string | null }> = [];

    page.on('console', (message) => consoleMessages.push(message.text()));
    page.on('response', (response) => {
      let path = '<invalid-url>';
      try {
        path = new URL(response.url()).pathname;
      } catch {
        // The diagnostic remains useful without preserving a malformed URL.
      }
      networkSummary.push({
        method: response.request().method(),
        path,
        status: response.status(),
        correlationId: response.headers()['x-correlation-id'] ?? null,
      });
    });

    await use();

    const consoleText = consoleMessages.join('\n');
    for (const secret of [
      password,
      changedPassword,
      resetPassword,
      invitationPassword,
      resetToken,
      expiredResetToken,
      invitationToken,
    ]) {
      expect(consoleText, 'Browser console output must not contain test credentials.').not.toContain(secret);
    }
    if (testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach('sanitized-network-summary', {
        body: JSON.stringify(networkSummary, null, 2),
        contentType: 'application/json',
      });
    }
  }, { auto: true }],
});

export { expect };
