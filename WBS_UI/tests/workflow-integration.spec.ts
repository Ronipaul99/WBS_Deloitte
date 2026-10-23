import { expect, test, type Page } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';
import {
  createProjectAndOpenWbs,
  mockWorkflowApi,
  type WorkflowMockState,
} from './workflow-mocks';

async function uploadProject(page: Page, withTemplate = false) {
  await createProjectAndOpenWbs(page);
  const inputs = page.locator('input[type="file"]');
  await inputs.first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('project scope'),
  });
  if (withTemplate) {
    await inputs.nth(1).setInputFiles({
      name: 'reference-template.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('template'),
    });
  }
  await page.getByRole('button', { name: 'Generate Draft WBS' }).click();
}

async function reachResults(page: Page) {
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible();
  await page.getByRole('button', { name: 'Generate WBS' }).click();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
}

async function setup(page: Page, options: Parameters<typeof mockWorkflowApi>[1] = {}) {
  await mockAuthenticatedUser(page);
  const state = await mockWorkflowApi(page, options);
  await page.goto('/');
  return state;
}

test('runs the required-document workflow through summary, WBS, validation, and protected export', async ({ page }) => {
  const state: WorkflowMockState = await setup(page);
  await uploadProject(page);
  await expect(page.getByRole('heading', { name: 'Processing Project Document' })).toBeVisible();
  await reachResults(page);

  expect(state.templateUploads).toBe(0);
  expect(state.projectCreates).toBe(1);
  expect(state.generationPayload).toEqual({
    document_id: '20000000-0000-0000-0000-000000000001',
    summary_id: '50000000-0000-0000-0000-000000000001',
  });
  await expect(page.getByText('Commission the system').first()).toBeVisible();

  await page.getByRole('button', { name: 'Validate & Proceed' }).click();
  await expect(page.getByRole('heading', { name: 'WBS Validation' })).toBeVisible();
  await expect(page.getByText('Unique WBS codes')).toBeVisible();
  await page.getByRole('button', { name: 'Back to WBS Structure' }).click();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  await page.getByRole('button', { name: 'Export as JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('wbs-v1.json');

  const storageKeys = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  expect(storageKeys).toEqual({ local: [], session: [] });
});

test('uploads and submits the optional template only when selected', async ({ page }) => {
  const state = await setup(page);
  await uploadProject(page, true);
  await reachResults(page);

  expect(state.templateUploads).toBe(1);
  expect(state.generationPayload).toMatchObject({
    template_id: '30000000-0000-0000-0000-000000000001',
  });
});

test('shows the backend job failure without substituting mock results', async ({ page }) => {
  await setup(page, { failSummaryJob: true });
  await uploadProject(page);

  await expect(page.getByRole('heading', { name: 'Document Extraction Interrupted' })).toBeVisible();
  await expect(page.getByText('Document parser rejected the uploaded content.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
});

test('refreshes an expired access token once while polling generation', async ({ page }) => {
  const state = await setup(page, { refreshDuringGenerationPoll: true });
  await uploadProject(page);
  await reachResults(page);

  expect(state.refreshDuringGenerationPoll).toBe(true);
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
});

test('scopes every workflow request to the workspace selected from multiple tenants', async ({ page }) => {
  await mockAuthenticatedUser(page, {
    tenants: [
      {
        id: '00000000-0000-0000-0000-000000000002',
        name: 'Finance Workspace',
        slug: 'finance',
        role: 'ADMIN',
        permissions: [],
      },
      {
        id: '00000000-0000-0000-0000-000000000001',
        name: 'Engineering Workspace',
        slug: 'engineering',
        role: 'ADMIN',
        permissions: [
          'project:read', 'project:create', 'document:read', 'document:upload',
          'summary:read', 'summary:update', 'summary:approve', 'template:read',
          'template:manage', 'wbs:read', 'wbs:generate', 'wbs:update',
          'validation:read', 'validation:run', 'export:read', 'export:create',
          'job:read', 'job:manage',
        ],
      },
    ],
  });
  const state = await mockWorkflowApi(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Choose a workspace' })).toBeVisible();
  await page.getByRole('button', { name: /Engineering Workspace/ }).click();
  await uploadProject(page);
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible();

  expect(state.requestPaths.length).toBeGreaterThan(0);
  expect(state.requestPaths.every((path) => (
    path.includes('/tenants/00000000-0000-0000-0000-000000000001/')
  ))).toBe(true);
});
