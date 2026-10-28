import { randomUUID } from 'node:crypto';
import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
const api = process.env.SUMMARY_TEST_API!;
const tenant = process.env.SUMMARY_TEST_TENANT!;
const prefix = `/api/v1/tenants/${tenant}`;
const password = process.env.SUMMARY_TEST_PASSWORD!;
const token = process.env.SUMMARY_TEST_TOKEN!;
if (!api?.startsWith('http://127.0.0.1:') || !token || !password || !tenant) throw new Error('Isolated summary runner required');

async function control(request: APIRequestContext, operation: string, data: Record<string, unknown> = {}) {
  const response = await request.post(`${api}/__summary_test/${operation}`, { headers: { 'X-Test-Token': token }, data });
  expect(response.status()).toBe(200);
  return response.json();
}
async function prepare(request: APIRequestContext) {
  await control(request, 'mode', { mode: 'normal' });
  await control(request, 'pump', { active: true });
  const login = await request.post(api + '/api/v1/auth/login', { data: { email: 'developer@example.com', password } });
  expect(login.status()).toBe(200);
  const auth = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const marker = randomUUID();
  const name = `Step6 ${marker}`;
  const project = await request.post(api + prefix + '/projects', { headers: auth, data: { name } });
  expect(project.status()).toBe(201);
  const projectId = (await project.json()).id;
  const bytes = Buffer.from(`Task,Description\n1,Synthetic ${marker}\n`);
  const upload = async () => request.post(api + prefix + '/document-workflows/uploads', { headers: { ...auth, 'Idempotency-Key': randomUUID() }, multipart: {
    project_id: projectId, file: { name: 'synthetic-summary.csv', mimeType: 'text/csv', buffer: bytes },
  } });
  const uploaded = await upload(); expect(uploaded.status()).toBe(201);
  const state = (await uploaded.json()).workflow;
  const documentId = state.document_id;
  await control(request, 'ready', { document_id: documentId });
  const base = api + prefix + `/documents/${documentId}/summary`;
  const submit = () => request.post(base + `?workflow_id=${state.workflow_id}`, { headers: auth });
  const inspect = () => control(request, 'inspect', { document_id: documentId });
  const step = (status: string, progress: number, payload = 'valid') => control(request, 'step', { document_id: documentId, status, progress, payload });
  return { auth, name, state, documentId, projectId, base, submit, inspect, step, upload };
}
async function open(page: Page, name: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill('developer@example.com');
  await page.locator('#login-password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: `Open ${name}`, exact: true }).click();
  await page.getByRole('button', { name: 'Continue synthetic-summary.csv', exact: true }).click();
}

test('real backend: explicit submission, exact shared job, progress, import, editing and approval', async ({ page, request }) => {
  const c = await prepare(request);
  const browserPosts: string[] = [];
  page.on('request', (r) => { if (r.method() === 'POST' && new URL(r.url()).pathname.endsWith('/summary')) browserPosts.push(r.url()); expect(r.headers()['x-api-key']).toBeUndefined(); });
  await open(page, c.name);
  await page.getByRole('button', { name: 'Generate summary', exact: true }).click();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  const initial = await c.inspect();
  expect(initial.request_id).not.toBe(initial.job_id); expect(initial.upstream_calls).toBe(1); expect(initial.legacy_jobs).toBe(0);
  const duplicates = await Promise.all([c.submit(), c.submit()]);
  for (const repeated of duplicates) { expect(repeated.status()).toBe(202); expect((await repeated.json()).request_id).toBe(initial.request_id); }
  await control(request, 'newer', { document_id: c.documentId });
  for (const progress of [25, 65]) {
    await c.step('RUNNING', progress);
    await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(progress), { timeout: 10000 });
    await expect(page.getByText(`SUMMARY:TEST_${progress}`, { exact: true })).toBeVisible();
  }
  await c.step('RUNNING', 100);
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100', { timeout: 10000 });
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
  await c.step('COMPLETED', 100);
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible({ timeout: 12000 });
  await expect(page.locator('.wbs-rev-section-btn')).toHaveCount(7);
  await expect(page.getByText('Not recorded', { exact: true })).toBeVisible();
  const generated = await (await request.get(c.base, { headers: c.auth })).json();
  const externalDigest = (await c.inspect()).result_digest;
  expect(generated.provenance.job_id).toBe(initial.job_id); expect(generated.is_approved).toBe(false);
  await page.getByRole('textbox').fill('Human edited synthetic scope. [99]');
  await page.locator('.wbs-rev-section-btn').nth(1).click();
  await page.locator('.wbs-rev-section-btn').first().click();
  await expect(page.getByRole('textbox')).toHaveValue('Human edited synthetic scope. [99]');
  await page.getByRole('button', { name: 'Save Draft', exact: true }).click();
  await expect(page.getByText(/Revision 2/)).toBeVisible();
  await page.getByRole('button', { name: 'Approve summary', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approved', exact: true })).toBeVisible();
  const beforeReplay = await c.inspect();
  const noop = await request.patch(c.base, { headers: c.auth, data: { format: 'external_summary_v1', expected_revision: 2, sections: [] } });
  expect(noop.status()).toBe(200); expect((await noop.json()).is_approved).toBe(true);
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('Human edited synthetic scope. [99]');
  const current = await (await request.get(c.base, { headers: c.auth })).json();
  expect(current.structured_summary.generated_result).toEqual(generated.structured_summary.generated_result);
  expect(current.revision).toBe(2); expect(current.is_approved).toBe(true);
  expect((await c.inspect()).result_digest).toBe(beforeReplay.result_digest);
  expect(beforeReplay.result_digest).toBe(externalDigest);
  await expect(page.getByRole('button', { name: 'Generate WBS', exact: true })).toBeDisabled();
  expect((await c.inspect()).upstream_calls).toBe(1); expect(browserPosts).toHaveLength(1);
  expect((await c.inspect()).errors).toEqual([]);
  const mutation = await request.patch(c.base, { headers: c.auth, data: { format: 'external_summary_v1', expected_revision: 2, sections: [{ id: 'sec_1', key: 'project_overview', content: 'Revised human draft' }] } });
  expect(mutation.status()).toBe(200); expect((await mutation.json()).is_approved).toBe(false);
  expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }))).not.toContain('Human edited');
});

test('browser close and test delivery-pump restart recover the same committed request', async ({ browser, request }) => {
  const c = await prepare(request);
  await control(request, 'pump', { active: false });
  const first = await c.submit(); expect(first.status()).toBe(202);
  const identity = (await first.json()).request_id;
  expect((await c.inspect()).submission_state).toBe('SUBMIT_PENDING');
  await control(request, 'pump', { active: true });
  await expect.poll(async () => (await c.inspect()).submission_state).toBe('ACKNOWLEDGED');
  const context = await browser.newContext(); const page = await context.newPage();
  await open(page, c.name); await expect(page.getByRole('heading', { name: 'Summary progress' })).toBeVisible();
  await context.close();
  await control(request, 'pump', { active: false });
  await c.step('COMPLETED', 100);
  expect((await c.inspect()).summary_id).toBeNull();
  await control(request, 'pump', { active: true });
  await expect.poll(async () => (await c.inspect()).import_state).toBe('IMPORTED');
  expect((await c.inspect()).request_id).toBe(identity);
  expect((await c.inspect()).upstream_calls).toBe(1);
  const fresh = await browser.newContext(); const reopened = await fresh.newPage();
  await open(reopened, c.name);
  await expect(reopened.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible();
  await fresh.close();
});

test('completion/payload split and revision conflicts preserve the saved draft', async ({ request }) => {
  const c = await prepare(request); await c.submit();
  await expect.poll(async () => (await c.inspect()).submission_state).toBe('ACKNOWLEDGED');
  await c.step('COMPLETED', 99);
  expect((await c.inspect()).summary_id).toBeNull();
  await c.step('COMPLETED', 100, 'missing');
  await expect.poll(async () => (await c.inspect()).import_state).toBe('WAITING');
  await c.step('COMPLETED', 100); await control(request, 'due', { document_id: c.documentId });
  await expect.poll(async () => (await c.inspect()).import_state).toBe('IMPORTED');
  const summary = await (await request.get(c.base, { headers: c.auth })).json();
  const section = summary.structured_summary.generated_result.data.summary_sections[0];
  const patch = { format: 'external_summary_v1', expected_revision: 1, sections: [{ id: section.id, key: section.key, content: 'Concurrent human edit' }] };
  expect((await request.patch(c.base, { headers: c.auth, data: patch })).status()).toBe(200);
  expect((await request.post(c.base + '/approve', { headers: c.auth, data: { format: 'external_summary_v1', expected_revision: 1 } })).status()).toBe(409);
  expect((await request.patch(c.base, { headers: c.auth, data: patch })).status()).toBe(409);
  expect((await c.inspect()).revision).toBe(2); expect((await c.inspect()).approved).toBe(false);
});

test('lost acknowledgement remains unknown without another remote POST', async ({ request }) => {
  const c = await prepare(request); await control(request, 'mode', { mode: 'ambiguous' });
  await c.submit();
  await expect.poll(async () => (await c.inspect()).submission_state).toBe('SUBMISSION_UNKNOWN');
  await control(request, 'pump', { active: true });
  const repeated = await c.submit(); expect(repeated.status()).toBe(202);
  const state = await c.inspect(); expect(state.upstream_calls).toBe(1); expect(state.summary_id).toBeNull();
  expect(state.job_id).toBeNull();
});

test('failed execution and stale canonical source never import', async ({ request }) => {
  const failed = await prepare(request); await failed.submit();
  await expect.poll(async () => (await failed.inspect()).submission_state).toBe('ACKNOWLEDGED');
  await failed.step('FAILED', 100);
  expect((await failed.inspect()).summary_id).toBeNull();
  const stale = await prepare(request); await stale.submit();
  await expect.poll(async () => (await stale.inspect()).submission_state).toBe('ACKNOWLEDGED');
  await control(request, 'invalidate', { document_id: stale.documentId });
  await stale.step('COMPLETED', 100);
  await expect.poll(async () => (await stale.inspect()).import_state).toBe('STALE');
  expect((await stale.inspect()).summary_id).toBeNull();
});

test('normal deletion and re-upload cannot inherit an old summary request', async ({ request }) => {
  const c = await prepare(request); await c.submit();
  await expect.poll(async () => (await c.inspect()).submission_state).toBe('ACKNOWLEDGED');
  await control(request, 'pump', { active: false });
  const removed = await request.delete(api + prefix + `/documents/${c.documentId}`, { headers: c.auth });
  expect(removed.status()).toBe(202);
  const pending = await c.upload(); expect(pending.status()).toBe(409);
  await control(request, 'pump', { active: true });
  await expect.poll(async () => (await (await request.get(api + prefix + `/documents/${c.documentId}/deletion`, { headers: c.auth })).json()).status).toBe('COMPLETED');
  const replacement = await c.upload(); expect(replacement.status()).toBe(201);
  const next = (await replacement.json()).workflow;
  expect(next.document_id).not.toBe(c.documentId); expect(next.external_summary).toBeNull();
  expect(next.summary_id).toBeNull();
  expect((await request.get(c.base, { headers: c.auth })).status()).toBeGreaterThanOrEqual(400);
});
