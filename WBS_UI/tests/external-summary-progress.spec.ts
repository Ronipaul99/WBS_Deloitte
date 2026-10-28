import { expect, test, type Page } from '@playwright/test';
import { ids, setupDocumentWorkflow } from './document-workflow-mocks';
import { ADMIN_PERMISSIONS, mockAuthenticatedUser, VIEWER_PERMISSIONS } from './auth-mocks';
import type { ExternalSummaryStatus } from '../src/services/workflowTypes';

const requestId = '92000000-0000-4000-8000-000000000001';
const jobId = '93000000-0000-4000-8000-000000000001';
function metadata(overrides: Partial<ExternalSummaryStatus> = {}): ExternalSummaryStatus {
  return { execution_backend: 'external_summary', request_id: requestId, job_id: jobId,
    document_id: ids.document, workflow_id: ids.workflow, job_type: 'DOCUMENT_SUMMERIZATION',
    submission_state: 'ACKNOWLEDGED', binding_state: 'VERIFIED', status: 'IN_PROGRESS',
    provider_status: 'RUNNING', progress: 20, current_step: 'SUMMARY:QUEUED', attempt_count: 1,
    updated_at: '2026-10-28T10:34:34Z', result_state: 'NOT_READY', summary_id: null,
    summary_revision: null, error_code: null, error_message: null, can_retry: false, can_cancel: false, ...overrides };
}

async function setup(page: Page, submit = false) {
  const context = await setupDocumentWorkflow(page, { listSaved: true, stage: submit ? 'INGESTED' : 'SUMMARIZING' });
  const state = context.state;
  state.summary_id = null;
  state.summary_revision = null;
  state.allowed_actions = submit ? ['start_summary'] : [];
  const runtime = { value: metadata(), reads: 0, posts: 0, statusCode: 200 };
  if (!submit) state.external_summary = runtime.value;
  await page.route(`**/documents/${ids.document}/summary**`, async (route) => {
    if (route.request().method() === 'POST') {
      runtime.posts += 1;
      state.stage = 'SUMMARIZING'; state.allowed_actions = [];
      state.external_summary = metadata({ job_id: null, binding_state: 'PENDING', status: 'QUEUED',
        submission_state: 'SUBMIT_PENDING', progress: 0, provider_status: null, current_step: null });
      return route.fulfill({ status: 202, json: { execution_backend: 'external_summary', request_id: requestId,
        job_id: null, document_id: ids.document, job_type: 'DOCUMENT_SUMMERIZATION',
        submission_state: 'SUBMIT_PENDING', status: 'QUEUED', provider_status: null,
        progress: 0, current_step: 'Summary submission awaiting verified job tracking', result_state: 'NOT_READY', summary_id: null } });
    }
    expect(route.request().url()).toContain(`/summary/requests/${requestId}?workflow_id=${ids.workflow}`);
    runtime.reads += 1;
    return route.fulfill({ status: runtime.statusCode, json: runtime.statusCode === 200 ? runtime.value : { detail: 'Synthetic read unavailable' } });
  });
  await page.clock.install();
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  return { ...context, runtime };
}

test('one explicit submission shows each pending/running update and waits for imported readiness', async ({ page }, testInfo) => {
  const { runtime } = await setup(page, true);
  runtime.value = metadata({ job_id: null, binding_state: 'PENDING', status: 'QUEUED',
    submission_state: 'SUBMIT_PENDING', progress: 0, provider_status: null });
  await page.getByRole('button', { name: 'Generate summary', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Submission pending', exact: true })).toBeVisible();
  expect(runtime.posts).toBe(1);
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  runtime.value = metadata({ binding_state: 'WAITING_FOR_JOB', status: 'QUEUED', provider_status: null, progress: 0 });
  await page.clock.fastForward(2_000);
  await expect(page.getByRole('heading', { name: 'Waiting for job visibility' })).toBeVisible();
  for (const progress of [0, 20, 75, 100]) {
    runtime.value = metadata({ progress, current_step: `SUMMARY:OBSERVED_${progress}` });
    await page.clock.fastForward(5_000);
    await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(progress));
    await expect(page.getByText(`SUMMARY:OBSERVED_${progress}`, { exact: true })).toBeVisible();
  }
  await expect(page.getByText(/100% progress alone/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('summary-desktop.png'), fullPage: true });
  runtime.value = metadata({ status: 'COMPLETED', provider_status: 'completed', progress: 100, result_state: 'IMPORT_PENDING' });
  await page.clock.fastForward(5_000);
  await expect(page.getByRole('heading', { name: 'Finalizing summary' })).toBeVisible();
  await expect(page.getByText(/Result import is pending/)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Review project summary/i })).toHaveCount(0);
  const reads = runtime.reads;
  await page.clock.fastForward(30_000);
  await expect.poll(() => runtime.reads).toBeGreaterThan(reads);
  expect(runtime.posts).toBe(1);
  await expect(page.getByText(requestId, { exact: true })).toBeVisible();
  await expect(page.getByText(jobId, { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('summary-mobile.png'), fullPage: true });
});

test('read failure retains last known progress and Check status never submits again', async ({ page }) => {
  const { runtime } = await setup(page);
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
  runtime.statusCode = 503;
  await page.clock.fastForward(2_000);
  await expect(page.getByRole('status')).toContainText('Status read unavailable');
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '20%, last known');
  runtime.statusCode = 200; runtime.value = metadata({ progress: 75 });
  await page.getByRole('button', { name: 'Check status', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '75');
  expect(runtime.posts).toBe(0);
});

test('bounded waiting pauses and checks the same identity', async ({ page }) => {
  const { runtime } = await setup(page);
  await expect(page.getByRole('progressbar')).toBeVisible();
  await page.clock.fastForward(120_001);
  await expect(page.getByRole('status')).toContainText('Waiting paused');
  runtime.value = metadata({ progress: 76 });
  await page.getByRole('button', { name: 'Check status', exact: true }).click();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '76');
  expect(runtime.posts).toBe(0);
});

for (const [name, changes, heading] of [
  ['failed', { status: 'FAILED', progress: 100 }, 'Summary failed'],
  ['cancelled', { status: 'CANCELLED', progress: 100 }, 'Summary cancelled'],
  ['stale', { status: 'UNAVAILABLE', binding_state: 'STALE', result_state: 'STALE' }, 'Source or configuration changed'],
  ['unavailable', { status: 'UNAVAILABLE', binding_state: 'UNAVAILABLE', result_state: 'INVALID' }, 'Status unavailable'],
  ['ambiguous', { status: 'UNAVAILABLE', submission_state: 'SUBMISSION_UNKNOWN' }, 'Submission outcome unknown'],
  ['inconsistent completion', { provider_status: 'COMPLETED', progress: 65 }, 'Waiting for consistent completion'],
] as const) {
  test(`${name} stays truthful and never offers remote retry, cancellation or review`, async ({ page }) => {
    const { runtime } = await setup(page);
    runtime.value = metadata(changes);
    await page.clock.fastForward(2_000);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /Retry failed|Generate summary|Cancel summary/ })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: /Review project summary/i })).toHaveCount(0);
    expect(runtime.posts).toBe(0);
  });
}

test('foreign request, unsupported status and changed job identity cannot replace last known data', async ({ page }) => {
  const { runtime } = await setup(page);
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
  for (const changes of [ { request_id: jobId }, { status: 'SUCCESS' }, { job_id: requestId }, { progress: 101 } ]) {
    runtime.value = { ...metadata(), ...changes } as ExternalSummaryStatus;
    await page.clock.fastForward(5_000);
    await expect(page.getByRole('status')).toContainText('Status read unavailable');
    await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
    runtime.value = metadata();
    await page.getByRole('button', { name: 'Check status', exact: true }).click();
    await expect(page.getByRole('status')).toContainText('Generating summary');
  }
  expect(runtime.posts).toBe(0);
});

test('refresh and lost browser storage recover from the saved document workflow without another POST', async ({ page }) => {
  const { state, runtime } = await setup(page);
  await expect(page.getByRole('progressbar')).toBeVisible();
  await page.reload();
  await expect(page.getByRole('progressbar')).toBeVisible();
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.route(`**/projects/${ids.project}/documents`, (route) => route.fulfill({ json: [state.document] }));
  await page.route(`**/document-workflows/documents/${ids.document}`, (route) => route.fulfill({ json: [state] }));
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Project documents', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open document original-scope.csv', exact: true }).click();
  await page.getByRole('button', { name: 'Go to workflow', exact: true }).click();
  await expect(page.getByRole('progressbar')).toBeVisible();
  expect(runtime.posts).toBe(0);
});

test('navigation aborts an outstanding read and late progress cannot reopen the workflow', async ({ page }) => {
  const { runtime } = await setup(page);
  await expect(page.getByRole('progressbar')).toBeVisible();
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  let entered = 0;
  await page.route('**/summary/requests/**', async (route) => {
    entered++; await held;
    await route.fulfill({ json: metadata({ progress: 99 }) }).catch(() => {});
  });
  await page.clock.fastForward(2_000);
  await expect.poll(() => entered).toBe(1);
  await page.clock.fastForward(20_000);
  expect(entered).toBe(1);
  await page.getByRole('button', { name: 'Back to project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Project documents', exact: true })).toBeVisible();
  release();
  await page.clock.fastForward(20_000);
  await expect(page.getByRole('heading', { name: 'Summary progress' })).toHaveCount(0);
  expect(runtime.posts).toBe(0);
});

test('viewer cannot submit even if stale workflow actions offer generation', async ({ page }) => {
  const { runtime } = await setup(page, true);
  await mockAuthenticatedUser(page, { role: 'VIEWER', permissions: VIEWER_PERMISSIONS });
  await page.reload();
  await expect(page.getByRole('dialog', { name: 'Document processed successfully' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate summary', exact: true })).toHaveCount(0);
  expect(runtime.posts).toBe(0);
});

test('poller emits each value sequentially, bounds a hung request and removes abort listeners', async ({ page }) => {
  await setupDocumentWorkflow(page);
  await page.goto('/');
  const result = await page.evaluate(async () => {
    const path = '/src/services/polling.ts';
    const { pollResource, PollingTimeoutError } = await import(path);
    const controller = new AbortController();
    const signal = controller.signal;
    let listeners = 0;
    const add = signal.addEventListener.bind(signal); const remove = signal.removeEventListener.bind(signal);
    signal.addEventListener = (...args: Parameters<typeof add>) => { listeners++; add(...args); };
    signal.removeEventListener = (...args: Parameters<typeof remove>) => { listeners--; remove(...args); };
    let active = 0; let max = 0; let count = 0; const updates: number[] = [];
    const terminal = await pollResource({ signal, initialIntervalMs: 1, maxIntervalMs: 2,
      request: async () => { active++; max = Math.max(max, active); await new Promise((resolve) => setTimeout(resolve, 2)); active--; return ++count; },
      isTerminal: (value: number) => value === 3, onUpdate: (value: number) => updates.push(value) });
    let timeout = false; let aborted = false;
    try { await pollResource({ signal, timeoutMs: 5, request: (inner: AbortSignal) => {
      inner.addEventListener('abort', () => { aborted = true; }); return new Promise(() => {});
    }, isTerminal: () => false }); } catch (error) { timeout = error instanceof PollingTimeoutError; }
    return { terminal, updates, max, listeners, timeout, aborted };
  });
  expect(result).toEqual({ terminal: 3, updates: [1, 2, 3], max: 1, listeners: 0, timeout: true, aborted: true });
});

test('repeated clicks during submission produce one POST', async ({ page }) => {
  const { runtime } = await setup(page, true);
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  let attempts = 0;
  await page.route(`**/documents/${ids.document}/summary?workflow_id=*`, async (route) => {
    attempts++; await held; await route.fallback();
  });
  const button = page.getByRole('button', { name: 'Generate summary', exact: true });
  await button.evaluate((element: HTMLButtonElement) => { element.click(); element.click(); });
  await expect(button).toBeDisabled();
  await expect.poll(() => attempts).toBe(1);
  release();
  await expect(page.getByRole('heading', { name: 'Summary progress' })).toBeVisible();
  expect(runtime.posts).toBe(1);
});

test('lost acknowledgement offers read-only recovery instead of another Generate action', async ({ page }) => {
  const { state, runtime } = await setup(page, true);
  await page.route(`**/documents/${ids.document}/summary?workflow_id=*`, async (route) => {
    state.stage = 'SUMMARIZING'; state.allowed_actions = []; state.external_summary = metadata();
    await route.fulfill({ status: 503, json: { detail: 'Synthetic lost acknowledgement' } });
  });
  await page.getByRole('button', { name: 'Generate summary', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('could not be confirmed');
  await expect(page.getByRole('button', { name: 'Generate summary', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Check saved status', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Summary progress' })).toBeVisible();
  expect(runtime.posts).toBe(0); // The one POST was intercepted by the failure fixture.
});

test('legacy submission and authoritative review navigation remain compatible', async ({ page }) => {
  const { state, legacy } = await setup(page, true);
  await page.route(`**/documents/${ids.document}/summary?workflow_id=*`, async (route) => {
    await route.fulfill({ status: 202, json: { id: jobId, tenant_id: ids.tenant, project_id: ids.project,
      job_type: 'DOCUMENT_SUMMARY', status: 'IN_PROGRESS', progress: 0 } });
    state.stage = 'SUMMARY_REVIEW'; state.resume_screen = 'doc_summary';
    state.summary_id = '50000000-0000-0000-0000-000000000001';
    state.allowed_actions = ['edit_summary'];
  });
  // Override the broad Step 3 status-only fixture for a legacy summary read.
  await page.route(`**/documents/${ids.document}/summary`, (route) => route.fulfill({ json: {
    id: state.summary_id, tenant_id: ids.tenant, document_id: ids.document, summary_text: 'Saved legacy summary',
    key_points: ['Saved point'], requirements: [], is_approved: false, approved_at: null,
    created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z',
  } }));
  await page.getByRole('button', { name: 'Generate summary', exact: true }).click();
  await expect(page.getByRole('heading', { name: /Review project summary/i })).toBeVisible();
  expect(legacy.generationPayload).toBeNull();
});

for (const action of ['logout', 'tenant switch'] as const) {
  test(`${action} during a delayed read clears progress and ignores late results`, async ({ page }) => {
    const { runtime } = await setup(page);
    if (action === 'tenant switch') {
      await mockAuthenticatedUser(page, { tenants: [
        { id: ids.tenant, name: 'Test Workspace', slug: 'test', role: 'ADMIN', permissions: ADMIN_PERMISSIONS },
        { id: '00000000-0000-0000-0000-000000000002', name: 'Other Workspace', slug: 'other', role: 'VIEWER', permissions: VIEWER_PERMISSIONS },
      ] });
      await page.reload();
      await page.getByRole('button', { name: /Test Workspace/ }).click();
    }
    await expect(page.getByRole('progressbar')).toBeVisible();
    let release = () => {};
    const held = new Promise<void>((resolve) => { release = resolve; });
    let entered = false;
    await page.route('**/summary/requests/**', async (route) => {
      entered = true; await held; await route.fulfill({ json: metadata({ progress: 99 }) }).catch(() => {});
    });
    await page.route('**/auth/logout', (route) => route.fulfill({ status: 204 }));
    await page.clock.fastForward(2_000);
    await expect.poll(() => entered).toBe(true);
    await page.getByRole('button', { name: 'Open profile menu' }).click();
    await page.getByRole('menuitem', { name: action === 'logout' ? 'Sign Out' : 'Switch workspace', exact: true }).click();
    await expect(page.getByRole('heading', { name: action === 'logout' ? 'Sign in' : 'Choose a workspace', exact: true })).toBeVisible();
    release(); await page.clock.fastForward(10_000);
    await expect(page.getByRole('heading', { name: 'Summary progress' })).toHaveCount(0);
    expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
    expect(runtime.posts).toBe(0);
  });
}

test('browser traffic and stored navigation hints contain no upstream headers or summary payload', async ({ page }) => {
  const requests: { url: string; headers: Record<string, string> }[] = [];
  const messages: string[] = [];
  page.on('request', (request) => requests.push({ url: request.url(), headers: request.headers() }));
  page.on('console', (message) => messages.push(message.text()));
  await setup(page);
  await expect(page.getByRole('progressbar')).toBeVisible();
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }));
  const hint = JSON.parse(Object.values(storage.session).find((value) => value.startsWith('{'))!);
  expect(Object.keys(hint).sort()).toEqual(['projectId', 'tenantId', 'version', 'workflowId']);
  expect(requests.every((request) => !request.headers['x-api-key'] && !request.headers['ngrok-skip-browser-warning'])).toBe(true);
  expect(requests.every((request) => new URL(request.url).hostname === '127.0.0.1')).toBe(true);
  expect(JSON.stringify({ storage, messages })).not.toMatch(/ngrok|X-API-Key|result_payload|summary_text/i);
});

test('opening a different document rejects the previous delayed update', async ({ page }) => {
  const { state } = await setup(page);
  const documentId = '20000000-0000-0000-0000-000000000002';
  const workflowId = '21000000-0000-4000-8000-000000000002';
  const otherRequest = '92000000-0000-4000-8000-000000000002';
  const otherJob = '93000000-0000-4000-8000-000000000002';
  const other = { ...state, workflow_id: workflowId, document_id: documentId,
    document: { ...state.document, id: documentId, file_name: 'other-scope.pdf' },
    external_summary: metadata({ document_id: documentId, workflow_id: workflowId, request_id: otherRequest, job_id: otherJob, progress: 5 }) };
  await page.route(`**/projects/${ids.project}/documents`, (route) => route.fulfill({ json: [state.document, other.document] }));
  await page.route(`**/document-workflows/documents/${documentId}`, (route) => route.fulfill({ json: [other] }));
  await page.route(`**/document-workflows/${workflowId}`, (route) => route.fulfill({ json: other }));
  await page.route(`**/documents/${documentId}/summary/requests/**`, (route) => route.fulfill({ json: other.external_summary }));
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
  let release = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  let entered = false;
  await page.route(`**/documents/${ids.document}/summary/requests/**`, async (route) => {
    entered = true; await held; await route.fulfill({ json: metadata({ progress: 99 }) }).catch(() => {});
  });
  await page.clock.fastForward(2_000);
  await expect.poll(() => entered).toBe(true);
  await page.getByRole('button', { name: 'Back to project', exact: true }).click();
  await page.getByRole('button', { name: 'Open document other-scope.pdf', exact: true }).click();
  await page.getByRole('button', { name: 'Go to workflow', exact: true }).click();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '5');
  release(); await page.clock.fastForward(5_000);
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '5');
  await expect(page.getByText(otherRequest, { exact: true })).toBeVisible();
  await expect(page.getByText(requestId, { exact: true })).toHaveCount(0);
});
