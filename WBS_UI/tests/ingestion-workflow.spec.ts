import { expect, test, type Page } from '@playwright/test';
import { ADMIN_PERMISSIONS, mockAuthenticatedUser } from './auth-mocks';
import { createProjectAndOpenWbs, mockWorkflowApi } from './workflow-mocks';

async function startDocumentProcessing(page: Page, withTemplate = false) {
  await createProjectAndOpenWbs(page);
  const inputs = page.locator('input[type="file"]');
  await inputs.first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('synthetic project scope'),
  });
  if (withTemplate) {
    await inputs.nth(1).setInputFiles({
      name: 'reference-template.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('synthetic template'),
    });
  }
  await page.getByRole('button', { name: 'Process Document' }).click();
}

async function setup(page: Page, options: Parameters<typeof mockWorkflowApi>[1] = {}) {
  await mockAuthenticatedUser(page);
  const state = await mockWorkflowApi(page, options);
  await page.goto('/');
  return state;
}

test('uploads in order, starts ingestion once, and never starts summary or cancellation', async ({ page }) => {
  const state = await setup(page);
  await startDocumentProcessing(page, true);

  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();
  expect(state.documentUploads).toBe(1);
  expect(state.templateUploads).toBe(1);
  expect(state.ingestionStarts).toBe(1);
  expect(state.summaryStarts).toBe(0);
  expect(state.cancellationRequests).toBe(0);
  const documentIndex = state.requestPaths.findIndex((path) => path.endsWith('/documents'));
  const templateIndex = state.requestPaths.findIndex((path) => path.endsWith('/templates'));
  const ingestionIndex = state.requestPaths.findIndex((path) => path.endsWith('/ingestions'));
  expect(documentIndex).toBeGreaterThanOrEqual(0);
  expect(templateIndex).toBeGreaterThan(documentIndex);
  expect(ingestionIndex).toBeGreaterThan(templateIndex);
});

test('never moves displayed progress backward when the next stage reports a lower value', async ({ page }) => {
  await setup(page, {
    ingestionStages: ['SCANNING', 'SCANNING', 'SCANNING', 'EXTRACTING', 'EXTRACTING'],
    ingestionProgress: [20, 20, 20, 15, 15],
  });
  await startDocumentProcessing(page);

  const stage = page.locator('.wbs-proc-stage-label');
  await expect(stage).toHaveText('scanning');
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
  await expect(stage).toHaveText('extracting');
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
});

for (const stageName of ['QUEUED', 'SCANNING', 'EXTRACTING', 'CHUNKING', 'EMBEDDING', 'PERSISTING', 'ACTIVATING']) {
  test(`renders the ${stageName} server stage`, async ({ page }) => {
    await setup(page, { ingestionStages: [stageName] });
    await startDocumentProcessing(page);
    await expect(page.locator('.wbs-proc-stage-label')).toHaveText(stageName.toLowerCase());
    await expect(page.getByRole('heading', { name: 'Processing project document' })).toBeVisible();
  });
}

test('shows retry-wait as server-managed and exposes no ingestion retry or cancel command', async ({ page }) => {
  const state = await setup(page, {
    ingestionStages: ['RETRY_WAIT', 'RETRY_WAIT', 'COMPLETED'],
  });
  await startDocumentProcessing(page);

  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('retry wait');
  await expect(page.getByText('Waiting to resume', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /retry/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /cancel/i })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();
  expect(state.ingestionStarts).toBe(1);
});

test('maps permanent failures safely without rendering backend text or infrastructure details', async ({ page }) => {
  const state = await setup(page, {
    ingestionStages: ['FAILED'],
    ingestionErrorCode: 'DOCUMENT_MALFORMED',
  });
  await startDocumentProcessing(page);

  await expect(page.getByRole('heading', { name: 'Document processing stopped' })).toBeVisible();
  await expect(page.getByText('The document structure could not be read safely.')).toBeVisible();
  await expect(page.getByText(/private endpoint|object key|raw parser exception/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: /retry/i })).toHaveCount(0);
  expect(state.summaryStarts).toBe(0);
});

test('treats unknown server state conservatively and never fabricates success', async ({ page }) => {
  await setup(page, { ingestionStages: ['PRIVATE_INTERNAL_STATE'] });
  await startDocumentProcessing(page);

  await expect(page.getByRole('heading', { name: 'Processing status unavailable' })).toBeVisible();
  await expect(page.getByText('The latest processing status is temporarily unavailable. Your ingestion has not been restarted.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toHaveCount(0);
});

test('status recovery re-fetches without starting another ingestion', async ({ page }) => {
  const state = await setup(page, { ingestionStages: ['SCANNING'] });
  await startDocumentProcessing(page);
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Processing project document' })).toBeVisible();
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');
  expect(state.ingestionStarts).toBe(1);

  await page.getByRole('button', { name: 'Back to project' }).click();
  await expect(page.getByRole('button', { name: 'Resume document processing' })).toBeVisible();
  await page.getByRole('button', { name: 'Resume document processing' }).click();
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');
  expect(state.ingestionStarts).toBe(1);
});

for (const terminal of [
  { stage: 'COMPLETED', heading: 'Document processed successfully' },
  { stage: 'FAILED', heading: 'Document processing stopped' },
]) {
  test(`restores a ${terminal.stage.toLowerCase()} ingestion after refresh without restarting it`, async ({ page }) => {
    const state = await setup(page, {
      ingestionStages: [terminal.stage],
      ingestionErrorCode: terminal.stage === 'FAILED' ? 'DOCUMENT_MALFORMED' : undefined,
    });
    await startDocumentProcessing(page);
    await expect(page.getByRole('heading', { name: terminal.heading })).toBeVisible();

    await page.reload();
    await expect(page.getByRole('heading', { name: terminal.heading })).toBeVisible();
    expect(state.ingestionStarts).toBe(1);
  });
}

test('aborts status work on navigation and suppresses its stale response', async ({ page }) => {
  const state = await setup(page, {
    ingestionStages: ['SCANNING', 'COMPLETED'],
    ingestionStatusDelayMs: 1_000,
  });
  await startDocumentProcessing(page);
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');

  await page.getByRole('button', { name: 'Back to project' }).click();
  await expect(page.getByRole('button', { name: 'Resume document processing' })).toBeVisible();
  await page.waitForTimeout(1_200);
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toHaveCount(0);
  expect(state.ingestionStarts).toBe(1);
});

test('tenant switch aborts polling and clears the scoped recovery context', async ({ page }) => {
  await mockAuthenticatedUser(page, {
    tenants: [
      {
        id: '00000000-0000-0000-0000-000000000002',
        name: 'Finance Workspace',
        slug: 'finance',
        role: 'ADMIN',
        permissions: ADMIN_PERMISSIONS,
      },
      {
        id: '00000000-0000-0000-0000-000000000001',
        name: 'Engineering Workspace',
        slug: 'engineering',
        role: 'ADMIN',
        permissions: ADMIN_PERMISSIONS,
      },
    ],
  });
  await mockWorkflowApi(page, { ingestionStages: ['SCANNING'] });
  await page.goto('/');
  await page.getByRole('button', { name: /Engineering Workspace/ }).click();
  await startDocumentProcessing(page);
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');

  await page.getByRole('button', { name: 'Open profile menu' }).click();
  await page.getByRole('menuitem', { name: 'Switch workspace' }).click();
  await expect(page.getByRole('heading', { name: 'Choose a workspace' })).toBeVisible();
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
});

test('transport recovery only checks status and preserves the original ingestion', async ({ page }) => {
  const state = await setup(page, {
    ingestionStages: ['SCANNING'],
    ingestionStatusHttpError: 503,
    ingestionStatusHttpErrorAfter: 2,
  });
  await startDocumentProcessing(page);

  await expect(page.getByRole('heading', { name: 'Processing status unavailable' })).toBeVisible();
  await page.getByRole('button', { name: 'Check status again' }).click();
  await expect(page.getByRole('heading', { name: 'Processing status unavailable' })).toBeVisible();
  expect(state.ingestionStarts).toBe(1);
  expect(state.summaryStarts).toBe(0);
});

test('bounded polling timeout offers status refresh without restarting ingestion', async ({ page }) => {
  const state = await setup(page, { ingestionStages: ['SCANNING'] });
  await createProjectAndOpenWbs(page);
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('synthetic project scope'),
  });
  await page.clock.install();
  await page.getByRole('button', { name: 'Process Document' }).click();
  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('scanning');

  for (let elapsed = 0; elapsed < 125_000; elapsed += 5_000) {
    await page.clock.fastForward(5_000);
    await new Promise((resolve) => setTimeout(resolve, 1));
  }

  await expect(page.getByRole('heading', { name: 'Processing status unavailable' })).toBeVisible();
  await expect(page.getByText('Processing is taking longer than expected. Check the status again in a moment.')).toBeVisible();
  expect(state.ingestionStarts).toBe(1);
});

test('stores identifiers only and clears recovery context after completion navigation', async ({ page }) => {
  await setup(page, { documentFileName: `${'long-project-scope-'.repeat(12)}.pdf` });
  await startDocumentProcessing(page);
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();

  const storedBeforeNavigation = await page.evaluate(() => Object.values(sessionStorage));
  expect(storedBeforeNavigation.join(' ')).not.toContain('long-project-scope');
  expect(storedBeforeNavigation.join(' ')).not.toContain('access_token');
  expect(storedBeforeNavigation.join(' ')).not.toContain('object_key');

  await page.getByRole('button', { name: 'Back to project' }).click();
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
});

