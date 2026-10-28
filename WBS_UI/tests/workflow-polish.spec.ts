import { expect, test, type Page } from '@playwright/test';
import { setupDocumentWorkflow, ids } from './document-workflow-mocks';
import { createProjectAndOpenWbs } from './workflow-mocks';

async function openDuplicate(page: Page) {
  await page.goto('/');
  await createProjectAndOpenWbs(page);
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'scope.csv', mimeType: 'text/csv', buffer: Buffer.from('Task,Description\n1,Synthetic scope\n'),
  });
  await page.getByRole('button', { name: 'Process Document', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  return dialog;
}

test('duplicate dialog contains keyboard focus, dismisses safely and restores focus', async ({ page }, testInfo) => {
  const { calls } = await setupDocumentWorkflow(page);
  const dialog = await openDuplicate(page);
  await expect(dialog).toHaveAccessibleName('This document already exists. Continue previous work?');
  await expect(dialog.getByRole('button', { name: 'Continue previous work', exact: true })).toBeFocused();
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press('Tab');
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }
  await page.screenshot({ path: testInfo.outputPath('duplicate-desktop.png') });
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Process Document', exact: true })).toBeFocused();
  expect(calls.uploadRequests).toBe(0);
});

test('multiple matches and long names fit a mobile dialog', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupDocumentWorkflow(page);
  await page.route('**/document-workflows/resolve', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      disposition: 'MULTIPLE_MATCHES', upload_handle: null,
      candidates: [0, 1].map((index) => ({
        workflow_id: `21000000-0000-4000-8000-00000000000${index + 1}`,
        document_id: ids.document, project_id: ids.project,
        project_name: index ? 'Original delivery project' : 'Project Scope',
        file_name: index ? 'Saved-scope.csv' : `${'Detailed-project-requirements-'.repeat(5)}.pdf`,
        stage: index ? 'FAILED' : 'SUMMARY_REVIEW',
        updated_at: '2026-10-28T10:00:00Z', requires_project_switch: Boolean(index),
      })),
    }),
  }));
  const dialog = await openDuplicate(page);
  await expect(dialog.getByRole('radio')).toHaveCount(2);
  await dialog.getByRole('radio').nth(1).check();
  await expect(dialog.getByRole('radio').nth(1)).toBeChecked();
  await expect(dialog.getByText('Continuing opens the original project.')).toBeVisible();
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const bounds = await dialog.boundingBox();
  expect(bounds!.y).toBeGreaterThanOrEqual(10);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(834);
  await page.screenshot({ path: testInfo.outputPath('duplicate-mobile.png') });
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).not.toBeVisible();
});

test('an in-flight continuation cannot be dismissed', async ({ page }) => {
  const { calls } = await setupDocumentWorkflow(page);
  const dialog = await openDuplicate(page);
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**/document-workflows/${ids.workflow}`, async (route) => {
    await held;
    await route.fallback();
  });
  await dialog.getByRole('button', { name: 'Continue previous work', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await expect(dialog.getByRole('button', { name: 'Close dialog' })).toBeDisabled();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  release();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
  expect(calls.uploadRequests).toBe(0);
});

test('processing success has a focused next action and returns to saved work', async ({ page }, testInfo) => {
  const { state, legacy } = await setupDocumentWorkflow(page, { listSaved: true, stage: 'INGESTED' });
  state.allowed_actions = ['start_summary'];
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Continue previous work', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('saved-work-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Document processed successfully' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Generate summary', exact: true })).toBeFocused();
  await expect(dialog.getByRole('list', { name: 'Workflow progress' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('success-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath('success-mobile.png') });
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Continue previous work', exact: true })).toBeVisible();
  expect(legacy.summaryStarts).toBe(0);
});

test('saved checkpoint presents progress and mobile actions without starting jobs', async ({ page }, testInfo) => {
  const { state, legacy } = await setupDocumentWorkflow(page, { listSaved: true, stage: 'DOCUMENT_READY' });
  state.allowed_actions = ['start_ingestion'];
  state.source_requires_processing = true;
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Continue saved work', exact: true })).toBeVisible();
  await expect(page.getByText(/processing needs to be refreshed/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('checkpoint-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Start document processing', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('checkpoint-mobile.png'), fullPage: true });
  expect(legacy.ingestionStarts).toBe(0);
});
