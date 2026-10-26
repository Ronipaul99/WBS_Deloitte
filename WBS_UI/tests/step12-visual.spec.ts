import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { mockAuthenticatedUser } from './auth-mocks';
import { createProjectAndOpenWbs, mockWorkflowApi } from './workflow-mocks';

async function openIngestion(page: Page, stage: string) {
  await mockAuthenticatedUser(page);
  await mockWorkflowApi(page, {
    ingestionStages: [stage],
    documentFileName: `${'enterprise-project-scope-'.repeat(8)}.pdf`,
  });
  await page.goto('/');
  await createProjectAndOpenWbs(page, 'Enterprise Transformation');
  await page.locator('input[type="file"]').first().setInputFiles({
    name: 'enterprise-project-scope.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('synthetic visual fixture'),
  });
  await page.getByRole('button', { name: 'Process Document' }).click();
}

async function assertVisualHealth(page: Page, testInfo: TestInfo, screenshotName: string) {
  const overflow = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth);
  const path = testInfo.outputPath(screenshotName);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(screenshotName, { path, contentType: 'image/png' });
}

test('desktop processing layout is stable and accessible', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    if (!request.failure()?.errorText.includes('ERR_ABORTED')) {
      failedRequests.push(new URL(request.url()).pathname);
    }
  });
  await page.setViewportSize({ width: 1440, height: 980 });
  await openIngestion(page, 'EMBEDDING');

  await expect(page.locator('.wbs-proc-stage-label')).toHaveText('embedding');
  await expect(page.getByRole('progressbar', { name: 'Document processing progress' })).toBeVisible();
  await assertVisualHealth(page, testInfo, 'step12-desktop-processing.png');
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test('mobile completed layout has no clipping or overlap', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    if (!request.failure()?.errorText.includes('ERR_ABORTED')) {
      failedRequests.push(new URL(request.url()).pathname);
    }
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await openIngestion(page, 'COMPLETED');

  await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible();
  await assertVisualHealth(page, testInfo, 'step12-mobile-completed.png');
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});

