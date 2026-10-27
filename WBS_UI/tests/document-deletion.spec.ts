import { expect, test } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';
import { mockWorkflowApi } from './workflow-mocks';

const document = {
  id: '20000000-0000-0000-0000-000000000001',
  tenant_id: '00000000-0000-0000-0000-000000000001',
  project_id: '10000000-0000-0000-0000-000000000001',
  kind: 'PROJECT',
  file_name: 'project-scope.pdf',
  content_type: 'application/pdf',
  size_bytes: 2048,
  lifecycle_status: 'ACTIVE',
  deletion_requested_at: null,
  deletion_completed_at: null,
  created_at: '2026-10-22T10:00:00Z',
};

test('starts durable deletion once and removes the document only after completion', async ({ page }, testInfo) => {
  await mockAuthenticatedUser(page);
  const state = await mockWorkflowApi(page, {
    projectDocuments: [document],
    deletionStages: ['DELETING_OBJECTS', 'COMPLETED'],
  });
  await page.goto('/');

  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Project name').fill('Project Scope');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();

  await expect(page.getByRole('heading', { name: 'Project documents' })).toBeVisible();
  await expect(page.getByText('project-scope.pdf')).toBeVisible();
  await page.getByRole('button', { name: 'Delete project-scope.pdf' }).click();
  await page.getByRole('button', { name: 'Confirm' }).click();

  await expect(page.getByText('Deleting', { exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('document-deleting-desktop.png'),
    fullPage: true,
  });
  expect(state.deletionStarts).toBe(1);
  await expect(page.getByText('project-scope.pdf')).toHaveCount(0, { timeout: 7_000 });
  expect(state.deletionStarts).toBe(1);
  expect(state.deletionPolls).toBeGreaterThanOrEqual(2);
  expect(state.requestPaths.some((path) => path.includes('storage'))).toBe(false);
});

test('keeps a failed cleanup hidden behind a safe status without starting again', async ({ page }) => {
  await mockAuthenticatedUser(page);
  const state = await mockWorkflowApi(page, {
    projectDocuments: [{ ...document, lifecycle_status: 'DELETING' }],
    deletionStages: ['FAILED'],
  });
  await page.goto('/');

  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Project name').fill('Project Scope');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();

  await expect(page.getByText('Cleanup needs attention')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete project-scope.pdf' })).toHaveCount(0);
  expect(state.deletionStarts).toBe(0);
  await expect(page.getByText(/private endpoint|object key|raw exception/i)).toHaveCount(0);
});

test('keeps document lifecycle controls inside the mobile viewport', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAuthenticatedUser(page);
  await mockWorkflowApi(page, { projectDocuments: [document] });
  await page.goto('/');

  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Project name').fill('Project Scope');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();

  const documentList = page.getByRole('region', { name: 'Project documents' });
  await expect(documentList).toBeVisible();
  const bounds = await documentList.boundingBox();
  expect(bounds).not.toBeNull();
  expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(390);
  await expect(page.getByRole('button', { name: 'Delete project-scope.pdf' })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('document-lifecycle-mobile.png'),
    fullPage: true,
  });
});
