import { expect, test } from '@playwright/test';
import { setupDocumentWorkflow, ids } from './document-workflow-mocks';

test('a fresh browser session resumes from the project without uploading or cached context', async ({ page }) => {
  const { calls, legacy } = await setupDocumentWorkflow(page, { listSaved: true });
  await page.goto('/');
  expect(await page.evaluate(() => sessionStorage.length)).toBe(0);
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'AI WBS Builder' })).toBeVisible();
  expect(calls.reads).toBeGreaterThanOrEqual(2);
  expect(calls.uploadRequests).toBe(0);
  expect(legacy.ingestionStarts).toBe(0);
  expect(legacy.summaryStarts).toBe(0);
});

for (const stage of ['SUMMARY_REVIEW', 'VALIDATED', 'FAILED'] as const) {
  test(`restores ${stage} from a navigation hint without creating jobs`, async ({ page }) => {
    const { calls, legacy } = await setupDocumentWorkflow(page, { stage });
    await page.addInitScript(({ tenant, project, workflow }) => {
      sessionStorage.setItem(`wbs.ingestion.v1:${tenant}:active`, project);
      sessionStorage.setItem(`wbs.ingestion.v1:${tenant}:${project}`, JSON.stringify({
        version: 2, tenantId: tenant, projectId: project, workflowId: workflow,
      }));
    }, ids);
    await page.goto('/');
    if (stage === 'SUMMARY_REVIEW') {
      await expect(page.getByRole('heading', { name: /review project summary/i })).toBeVisible();
    } else if (stage === 'FAILED') {
      await expect(page.getByRole('button', { name: 'Retry failed step' })).toBeVisible();
    } else {
      await expect(page.getByText(/WBS Validation/).first()).toBeVisible();
    }
    expect(calls.uploadRequests).toBe(0);
    expect(legacy.ingestionStarts).toBe(0);
    expect(legacy.summaryStarts).toBe(0);
    expect(legacy.generationPayload).toBeNull();
  });
}


test('historical inputs keep saved edits visible without regeneration', async ({ page }) => {
  const { state, legacy, calls } = await setupDocumentWorkflow(page, { listSaved: true });
  state.input_compatibility = 'CHANGED';
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  await expect(page.getByText(/This saved WBS uses earlier inputs/)).toBeVisible();
  await expect(page.getByText('Saved delivery scope edit', { exact: true }).first()).toBeVisible();
  expect(legacy.generationPayload).toBeNull();
  expect(calls.uploadRequests).toBe(0);
});
