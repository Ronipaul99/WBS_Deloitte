import { expect, test, type Page } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';
import {
  createProjectAndOpenWbs,
  mockWorkflowApi,
  type WorkflowMockState,
} from './workflow-mocks';

async function uploadProject(page: Page) {
  await createProjectAndOpenWbs(page);
  const inputs = page.locator('input[type="file"]');
  await inputs.first().setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('project scope'),
  });
  await page.getByRole('button', { name: 'Process Document' }).click();
}

async function setup(page: Page, options: Parameters<typeof mockWorkflowApi>[1] = {}) {
  await mockAuthenticatedUser(page);
  const state = await mockWorkflowApi(page, options);
  await page.goto('/');
  return state;
}

test('stops the required-document workflow at the processed milestone', async ({ page }) => {
  const state: WorkflowMockState = await setup(page);
  await uploadProject(page);
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();

  expect(state.templateUploads).toBe(0);
  expect(state.projectCreates).toBe(1);
  expect(state.ingestionStarts).toBe(1);
  expect(state.summaryStarts).toBe(0);
  expect(state.generationPayload).toBeNull();

  const storageKeys = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  expect(storageKeys.local).toEqual([]);
  expect(storageKeys.session).toHaveLength(2);
});

test('offers only the project scope upload when creating a WBS', async ({ page }) => {
  const state = await setup(page);
  await createProjectAndOpenWbs(page);
  await expect(page.getByRole('heading', { name: 'Reference WBS Template' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Upload reference WBS template' })).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(1);
  await page.locator('input[type="file"]').setInputFiles({
    name: 'project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('project scope'),
  });
  await page.getByRole('button', { name: 'Process Document' }).click();
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();

  expect(state.templateUploads).toBe(0);
  expect(state.ingestionStarts).toBe(1);
  expect(state.summaryStarts).toBe(0);
});

test('shows a safe ingestion failure without substituting later workflow results', async ({ page }) => {
  await setup(page, { ingestionStages: ['FAILED'], ingestionErrorCode: 'DOCUMENT_MALFORMED' });
  await uploadProject(page);

  await expect(page.getByRole('heading', { name: 'Document processing stopped' })).toBeVisible();
  await expect(page.getByText('The document structure could not be read safely.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
});

test('refreshes an expired access token once while polling ingestion', async ({ page }) => {
  const state = await setup(page, {
    ingestionStages: ['QUEUED', 'COMPLETED'],
    unauthorizedIngestionPollOnce: true,
  });
  await uploadProject(page);

  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();
  expect(state.refreshDuringGenerationPoll).toBe(true);
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
          'project:read', 'project:create', 'document:read', 'document:upload', 'document:process',
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
  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();

  expect(state.requestPaths.length).toBeGreaterThan(0);
  expect(state.requestPaths.every((path) => (
    path.includes('/tenants/00000000-0000-0000-0000-000000000001/')
  ))).toBe(true);
});
