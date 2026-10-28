import { createHash } from 'node:crypto';
import { textPdfBuffer } from '../pdf-fixtures';
import { apiFetch, expect, loginApi, loginPage, state, test } from './support';

test('real API and browser reuse a renamed document and recover after losing browser storage', async ({ page }) => {
  test.skip(process.env.DOCUMENT_WORKFLOW_RESUME_ENABLED !== 'true', 'Feature-specific isolated harness required');
  const session = await loginApi(state.emails.admin_a);
  const tenant = state.tenant_a_id;
  const base = `/tenants/${tenant}`;
  const content = Buffer.from('Task,Description\n1,Isolated document recovery\n');
  try {
    const create = await apiFetch(session, `${base}/projects`, {
      method: 'POST', data: { name: `Recovery ${state.run_id}` },
    });
    expect(create.status(), await create.text()).toBe(201);
    const project = await create.json() as { id: string; name: string };
    const first = await apiFetch(session, `${base}/document-workflows/uploads`, {
      method: 'POST', multipart: { project_id: project.id, file: { name: 'original.csv', mimeType: 'text/csv', buffer: content } },
    });
    expect(first.status(), await first.text()).toBe(201);
    const original = await first.json() as { workflow: { workflow_id: string; document_id: string } };
    const second = await apiFetch(session, `${base}/projects/${project.id}/documents`, {
      method: 'POST', multipart: { file: { name: 'renamed.csv', mimeType: 'text/csv', buffer: content } },
    });
    expect(second.status(), await second.text()).toBe(200);
    expect((await second.json() as { id: string }).id).toBe(original.workflow.document_id);
    const resolved = await apiFetch(session, `${base}/document-workflows/resolve`, {
      method: 'POST', data: { sha256: createHash('sha256').update(content).digest('hex'),
        size_bytes: content.length, selected_project_id: project.id },
    });
    expect(resolved.status()).toBe(200);
    expect((await resolved.json() as { disposition: string }).disposition).toBe('MATCH');
    const sideEffects: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/(uploads|documents|ingestions|summary|generations|validations)$/.test(new URL(request.url()).pathname)) {
        sideEffects.push(new URL(request.url()).pathname);
      }
    });
    await loginPage(page, state.emails.admin_a);
    await page.getByRole('button', { name: `Open ${project.name}`, exact: true }).click();
    await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
    await page.locator('input[type="file"]').first().setInputFiles({ name: 'renamed-again.csv', mimeType: 'text/csv', buffer: content });
    await page.getByRole('button', { name: 'Process Document', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'This document already exists. Continue previous work?' })).toBeVisible();
    await page.getByRole('button', { name: 'Continue previous work', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Start document processing', exact: true })).toBeVisible();
    await page.evaluate(() => sessionStorage.clear());
    await page.reload();
    await page.getByRole('button', { name: `Open ${project.name}`, exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Project documents', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create new WBS', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Open document original.csv', exact: true }).click();
    const documentDialog = page.getByRole('dialog', { name: 'Your document', exact: true });
    await documentDialog.getByRole('button', { name: 'View document', exact: true }).click();
    await expect(page.frameLocator('iframe[title="Preview of original.csv"]').locator('body'))
      .toContainText('Isolated document recovery');
    await documentDialog.getByRole('button', { name: 'Go to workflow', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Start document processing', exact: true })).toBeVisible();
    expect(sideEffects).toEqual([]);
    const documents = await apiFetch(session, `${base}/projects/${project.id}/documents`);
    expect((await documents.json() as unknown[]).length).toBe(1);
  } finally {
    await session.context.dispose();
  }
});

test('browser uploads a new PDF with idempotency preflight and reports disabled ingestion', async ({ page }) => {
  test.skip(process.env.DOCUMENT_WORKFLOW_RESUME_ENABLED !== 'true', 'Feature-specific isolated harness required');
  test.skip(process.env.DOCUMENT_INGESTION_ENABLED !== 'false', 'Disabled-ingestion smoke contract');
  const session = await loginApi(state.emails.admin_a);
  const base = `/tenants/${state.tenant_a_id}`;
  try {
    const created = await apiFetch(session, `${base}/projects`, {
      method: 'POST', data: { name: `PDF upload ${state.run_id}` },
    });
    expect(created.status()).toBe(201);
    const project = await created.json() as { id: string; name: string };
    await loginPage(page, state.emails.admin_a);
    await page.getByRole('button', { name: `Open ${project.name}`, exact: true }).click();
    await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'synthetic-upload.pdf', mimeType: 'application/pdf', buffer: textPdfBuffer(),
    });
    const uploaded = page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/document-workflows/uploads'));
    const ingestion = page.waitForResponse((response) => response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/ingestions'));
    await page.getByRole('button', { name: 'Process Document', exact: true }).click();
    const uploadResponse = await uploaded;
    expect(uploadResponse.status()).toBe(201);
    expect(uploadResponse.request().headers()['idempotency-key']).toBeTruthy();
    const body = await uploadResponse.json() as { workflow: { document_id: string; workflow_id: string } };
    const unavailable = await ingestion;
    expect(unavailable.status()).toBe(503);
    expect((await unavailable.json() as { detail: { code: string } }).detail.code).toBe('DOCUMENT_INGESTION_DISABLED');
    const resumed = await apiFetch(session, `${base}/document-workflows/${body.workflow.workflow_id}`);
    expect(resumed.status()).toBe(200);
    expect((await resumed.json() as { document_id: string }).document_id).toBe(body.workflow.document_id);
    const documents = await apiFetch(session, `${base}/projects/${project.id}/documents`);
    expect((await documents.json() as unknown[]).length).toBe(1);
  } finally {
    await session.context.dispose();
  }
});
