import { expect, test, type Page } from '@playwright/test';
import { ids, setupDocumentWorkflow } from './document-workflow-mocks';

async function setup(page: Page) {
  const context = await setupDocumentWorkflow(page, { listSaved: true, stage: 'SUMMARY_REVIEW' });
  await page.route(`**/projects/${ids.project}/documents`, (route) => route.fulfill({
    json: [context.state.document],
  }));
  await page.route(`**/document-workflows/documents/${ids.document}`, (route) => route.fulfill({
    json: [context.state],
  }));
  await page.route(`**/documents/${ids.document}/file`, (route) => route.fulfill({
    contentType: 'text/plain', body: 'Synthetic original document',
  }));
  return context;
}

test('a project with saved progress opens its workspace and Create new WBS opens upload', async ({ page }) => {
  const { calls } = await setup(page);
  await page.addInitScript(({ tenant, project, workflow }) => {
    sessionStorage.setItem(`wbs.ingestion.v1:${tenant}:active`, project);
    sessionStorage.setItem(`wbs.ingestion.v1:${tenant}:${project}`, JSON.stringify({
      version: 2, tenantId: tenant, projectId: project, workflowId: workflow,
    }));
  }, ids);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /review project summary/i })).toBeVisible();
  await page.getByRole('button', { name: 'My Projects', exact: true }).click();
  const reads = calls.reads;
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Project documents', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Work breakdown structures' })).toBeVisible();
  expect(calls.reads).toBe(reads);
  await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Process Document', exact: true })).toBeVisible();
  expect(calls.reads).toBe(reads);
  // Choosing an existing file still uses the duplicate dialog, not an implicit redirect.
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'renamed.csv', mimeType: 'text/csv', buffer: Buffer.from('Task,Description\n1,Synthetic scope\n'),
  });
  await page.getByRole('button', { name: 'Process Document', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'This document already exists. Continue previous work?' })).toBeVisible();
  expect(calls.uploadRequests).toBe(0);
});

test('document dialog views the original and explicitly opens its current workflow stage', async ({ page }, testInfo) => {
  const { legacy, calls } = await setup(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  const documentButton = page.getByRole('button', { name: 'Open document original-scope.csv', exact: true });
  await documentButton.click();
  const dialog = page.getByRole('dialog', { name: 'Your document', exact: true });
  await expect(dialog.getByText('Summary ready for review', { exact: true })).toBeVisible();
  expect(calls.reads).toBe(0);
  await dialog.getByRole('button', { name: 'View document', exact: true }).click();
  await expect(page.frameLocator('iframe[title="Preview of original-scope.csv"]').locator('body')).toContainText('Synthetic original document');
  await page.screenshot({ path: testInfo.outputPath('document-dialog-desktop.png') });
  await page.keyboard.press('Escape');
  await expect(documentButton).toBeFocused();
  await documentButton.click();
  await dialog.getByRole('button', { name: 'Go to workflow', exact: true }).click();
  await expect(page.getByRole('heading', { name: /review project summary/i })).toBeVisible();
  expect(calls.reads).toBe(1);
  expect(legacy.summaryStarts).toBe(0);
  expect(legacy.ingestionStarts).toBe(0);
});

test('multiple document workflows require selection and fit mobile', async ({ page }, testInfo) => {
  const { state } = await setup(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route(`**/document-workflows/documents/${ids.document}`, (route) => route.fulfill({
    json: [state, { ...state, workflow_id: '21000000-0000-4000-8000-000000000002', stage: 'FAILED' }],
  }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Open document original-scope.csv', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('combobox')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Go to workflow' })).toBeDisabled();
  await dialog.getByRole('combobox').selectOption(ids.workflow);
  await expect(dialog.getByRole('button', { name: 'Go to workflow' })).toBeEnabled();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('document-dialog-mobile.png') });
});

test('foreign workflows are rejected while viewing remains available', async ({ page }) => {
  const { state, calls } = await setup(page);
  await page.route(`**/document-workflows/documents/${ids.document}`, (route) => route.fulfill({
    json: [{ ...state, document_id: 'foreign-document' }],
  }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Open document original-scope.csv', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('alert')).toContainText('Saved workflows are unavailable');
  await expect(dialog.getByRole('button', { name: 'Go to workflow' })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'View document' })).toBeEnabled();
  expect(calls.reads).toBe(0);
});
