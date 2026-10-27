import { expect, test } from '@playwright/test';
import { mockAuthenticatedUser, VIEWER_PERMISSIONS, EDITOR_PERMISSIONS } from './auth-mocks';
import { defaultModelSettings } from '../src/services/llmModelDefaults';
import type { Page } from '@playwright/test';
import { ADMIN_PERMISSIONS } from './auth-mocks';

const pageErrors = new WeakMap<Page, string[]>();
test.beforeEach(({ page }) => { const errors: string[] = []; pageErrors.set(page, errors); page.on('pageerror', e => errors.push(e.message)); });
test.afterEach(({ page }) => { expect(pageErrors.get(page)).toEqual([]); });

const connectionId = '00000000-0000-0000-0000-000000000005';
const approvalId = '00000000-0000-0000-0000-000000000070';
const secret = 'synthetic-key-for-ui-tests-never-a-real-credential';
const connection = { id: connectionId, name: 'Mac gateway', provider: 'openai_compatible',
  protocol: 'chat_completions', revision: 1, enabled: true, configured: true,
  endpoint: { approval_id: approvalId, host: 'gateway.example.invalid', port: 443, path_prefix: '/v1' } };
const profile = { id: '00000000-0000-0000-0000-000000000006', name: 'Demo model',
  connection_id: connectionId, revision: 1, version: 1, model_id: 'manual-llama-model',
  provider: 'openai_compatible', enabled: false, is_default: false, usable: false,
  qualification: 'pending', tested_at: null, settings: defaultModelSettings,
  capabilities: { temperature: 'unknown', native_tools: 'unknown', json_schema: 'unknown' } };

async function setup(page: Page) {
  const submitted: Record<string, unknown>[] = [];
  // Block every unmatched API call; these tests cannot reach a real backend.
  await page.route('**/api/v1/**', route => route.fulfill({ status: 200, json: [] }));
  await mockAuthenticatedUser(page);
  await page.route('**/llm/**', async route => {
    const url = new URL(route.request().url()); const path = url.pathname;
    const method = route.request().method();
    if (method !== 'GET') submitted.push(route.request().postDataJSON() as Record<string, unknown>);
    if (path.endsWith('/endpoints')) return route.fulfill({ json: [{ id: approvalId,
      host: 'gateway.example.invalid', port: 443, path_prefix: '/v1', auth_scheme: 'bearer',
      providers: ['openai', 'openai_compatible'] }] });
    if (path.endsWith('/connections') && method === 'GET') return route.fulfill({ json: [connection] });
    if (path.endsWith('/profiles') && method === 'GET') return route.fulfill({ json: [profile] });
    if (path.endsWith('/test')) return route.fulfill({ status: 202, json: {
      id: 'test-only-id', connection_id: connectionId, profile_id: profile.id, state: 'queued',
      error_code: null, result: {}, calls_reserved: 0, tokens_reserved: 0 } });
    if (path.includes('/tests/')) return route.fulfill({ json: {
      id: 'test-only-id', connection_id: connectionId, profile_id: profile.id, state: 'succeeded',
      error_code: null, result: { origin: 'synthetic_fixture' }, calls_reserved: 4, tokens_reserved: 16000 } });
    if (path.endsWith('/state')) return route.fulfill({ status: 409, json: { detail: {
      code: 'llm_qualification_required', message: 'Qualification required.' } } });
    if (path.includes('/connections')) return route.fulfill({ json: { ...connection,
      revision: 2, name: (route.request().postDataJSON() as { name?: string }).name ?? connection.name } });
    return route.fulfill({ status: 201, json: { ...profile, model_id: (route.request().postDataJSON() as { model_id?: string }).model_id ?? profile.model_id } });
  });
  return submitted;
}

test('saved keys are never echoed; omission preserves and explicit replacement is transient', async ({ page }) => {
  const bodies = await setup(page);
  await page.goto('/settings/ai-models');
  await page.getByRole('button', { name: 'Mac gateway', exact: true }).click();
  await expect(page.getByLabel('New API key', { exact: true })).toHaveCount(0);
  await page.getByLabel('Connection name', { exact: true }).fill('Renamed gateway');
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  expect(bodies[0]).not.toHaveProperty('credential');
  await page.getByLabel('Replace API key', { exact: true }).check();
  await page.getByLabel('New API key', { exact: true }).fill(secret);
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(page.getByLabel('New API key', { exact: true })).toHaveCount(0);
  expect(bodies[1].credential).toEqual({ action: 'replace', secret });
  const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
  expect(storage).not.toContain(secret);
  expect(await page.locator('body').textContent()).not.toContain(secret);
});

test('manual model entry and supported controls; worker progress never implies live qualification', async ({ page }) => {
  const bodies = await setup(page);
  await page.goto('/settings/ai-models');
  await page.getByRole('button', { name: 'New profile', exact: true }).click();
  await page.getByLabel('Profile name', { exact: true }).fill('Manual');
  await page.getByRole('combobox', { name: 'Connection', exact: true }).selectOption(connectionId);
  await page.getByLabel('Exact model ID', { exact: true }).fill('custom-exact-id');
  await expect(page.getByLabel('Temperature', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Token limit dialect', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save profile', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Test model on worker', exact: true })).toBeDisabled();
  expect(bodies[0].model_id).toBe('custom-exact-id');
  await page.getByLabel(/I understand this synthetic test/).check();
  await page.getByRole('button', { name: 'Test model on worker', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Worker test: succeeded' })).toBeVisible();
  await expect(page.getByText('Synthetic fixture result; does not enable a live profile.')).toBeVisible();
  await page.getByRole('button', { name: 'Enable profile', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('qualification is missing');
});

test('cancel and tenant remount clear replacement input', async ({ page }) => {
  await setup(page);
  await page.goto('/settings/ai-models');
  await page.getByLabel('Replace API key', { exact: true }).check();
  await page.getByLabel('New API key', { exact: true }).fill(secret);
  await page.getByRole('button', { name: 'Cancel connection edit', exact: true }).click();
  await expect(page.getByLabel('New API key', { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('New API key', { exact: true })).toHaveCount(0);
});

for (const role of ['EDITOR', 'VIEWER'] as const) {
  test(`${role} cannot open administration`, async ({ page }) => {
    await page.route('**/api/v1/**', route => route.fulfill({ json: [] }));
    await mockAuthenticatedUser(page, { role, permissions: role === 'VIEWER' ? VIEWER_PERMISSIONS : EDITOR_PERMISSIONS });
    await page.goto('/settings/ai-models');
    await expect(page.getByRole('alert')).toContainText('do not have permission');
    await expect(page.getByRole('button', { name: 'Save connection' })).toHaveCount(0);
  });
}

test('missing server configuration is accessible and never presents placeholder success', async ({ page }) => {
  await setup(page);
  await page.route('**/llm/**', route => route.fulfill({ status: 503, json: { detail: { code: 'llm_management_disabled' } } }));
  await page.goto('/settings/ai-models');
  await expect(page.getByRole('alert')).toContainText('management is unavailable');
  await expect(page.getByText('Worker test: succeeded')).toHaveCount(0);
});

test('switching tenants unmounts and clears an unsaved replacement key', async ({ page }) => {
  await setup(page);
  await mockAuthenticatedUser(page, { tenants: [
    { id: '00000000-0000-0000-0000-000000000001', name: 'Workspace A', slug: 'a', role: 'ADMIN', permissions: ADMIN_PERMISSIONS },
    { id: '00000000-0000-0000-0000-000000000002', name: 'Workspace B', slug: 'b', role: 'ADMIN', permissions: ADMIN_PERMISSIONS },
  ] });
  await page.goto('/settings/ai-models');
  await page.getByRole('button', { name: /Workspace A/ }).click();
  await page.getByLabel('Replace API key', { exact: true }).check();
  await page.getByLabel('New API key', { exact: true }).fill(secret);
  await page.getByRole('button', { name: 'Open profile menu' }).click();
  await page.getByRole('menuitem', { name: 'Switch workspace' }).click();
  await page.getByRole('button', { name: /Workspace B/ }).click();
  await expect(page.getByLabel('New API key', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain(secret);
});
