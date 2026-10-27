import { createHash } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { createProjectAndOpenWbs } from './workflow-mocks';
import { setupDocumentWorkflow } from './document-workflow-mocks';

const bytes = Buffer.from('Task,Description\n1,Saved delivery scope\n');

for (const filename of ['original-scope.csv', 'renamed-scope.csv']) {
  test(`reuses ${filename} without uploading or restarting work`, async ({ page }) => {
    const { calls, legacy } = await setupDocumentWorkflow(page);
    await page.goto('/');
    await createProjectAndOpenWbs(page);
    await page.locator('input[type="file"]').first().setInputFiles({ name: filename, mimeType: 'text/csv', buffer: bytes });
    await page.getByRole('button', { name: 'Process Document', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'This document already exists. Continue previous work?' })).toBeVisible();
    expect(calls.uploadRequests).toBe(0);
    expect(calls.resolves[0].sha256).toBe(createHash('sha256').update(bytes).digest('hex'));
    await page.getByRole('button', { name: 'Continue previous work', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
    await expect(page.getByText('Saved delivery scope edit').first()).toBeVisible();
    expect(legacy.documentUploads).toBe(0);
    expect(legacy.ingestionStarts).toBe(0);
    expect(legacy.summaryStarts).toBe(0);
    expect(legacy.generationPayload).toBeNull();
  });
}

test('cross-project continue opens the original project after confirmation', async ({ page }) => {
  const { calls, legacy } = await setupDocumentWorkflow(page, { crossProject: true });
  await page.goto('/');
  await createProjectAndOpenWbs(page);
  await page.locator('input[type="file"]').first().setInputFiles({ name: 'renamed.csv', mimeType: 'text/csv', buffer: bytes });
  await page.getByRole('button', { name: 'Process Document', exact: true }).click();
  await expect(page.getByText('Continuing opens the original project.')).toBeVisible();
  await expect(page.getByText(/Original delivery project/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Continue previous work', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
  expect(legacy.projectCreates).toBe(1);
  expect(calls.uploadRequests).toBe(0);
});

test('cancel performs no upload, including a selected reference template', async ({ page }) => {
  const { calls, legacy } = await setupDocumentWorkflow(page);
  await page.goto('/');
  await createProjectAndOpenWbs(page);
  await page.locator('input[type="file"]').first().setInputFiles({ name: 'scope.csv', mimeType: 'text/csv', buffer: bytes });
  await page.locator('input[type="file"]').nth(1).setInputFiles({ name: 'new-template.csv', mimeType: 'text/csv', buffer: bytes });
  await page.getByRole('button', { name: 'Process Document', exact: true }).click();
  await expect(page.getByText(/Continuing keeps the saved template/)).toBeVisible();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create Work Breakdown Structure' })).toBeVisible();
  expect(calls.uploadRequests).toBe(0);
  expect(legacy.templateUploads).toBe(0);
});

test('unavailable browser hashing falls back to server detection without restarting processing', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(crypto, 'subtle', { value: undefined });
    Object.defineProperty(crypto, 'randomUUID', { value: undefined });
  });
  const { calls, legacy } = await setupDocumentWorkflow(page);
  await page.goto('/');
  await createProjectAndOpenWbs(page);
  await page.locator('input[type="file"]').first().setInputFiles({ name: 'scope.csv', mimeType: 'text/csv', buffer: bytes });
  await page.getByRole('button', { name: 'Process Document', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
  expect(calls.uploadRequests).toBe(1);
  expect(calls.resolves).toHaveLength(0);
  expect(legacy.ingestionStarts).toBe(0);
});
