import type { APIResponse, Page } from '@playwright/test';
import {
  apiFetch,
  assertNoCredentialStorage,
  bearer,
  endpoint,
  expect,
  loginApi,
  loginPage,
  state,
  test,
} from './support';
import type { ApiSession } from './support';
import { textPdfBuffer } from '../pdf-fixtures';

interface LiveResources {
  projectId: string;
  documentId: string;
  summaryJobId: string;
  generationJobId: string;
  versionId: string;
  validationId: string;
  exportId: string;
  confidentialMarkers: string[];
}

async function expectStatus(response: APIResponse, status: number): Promise<APIResponse> {
  expect(response.status(), await response.text()).toBe(status);
  return response;
}

async function waitForJob(session: ApiSession, tenantId: string, jobId: string) {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const response = await apiFetch(session, `/tenants/${tenantId}/jobs/${jobId}`);
    await expectStatus(response, 200);
    const job = await response.json() as {
      status: string;
      error_message: string | null;
      result_payload: Record<string, unknown>;
    };
    if (job.status === 'COMPLETED') return job;
    if (['FAILED', 'CANCELLED'].includes(job.status)) {
      throw new Error(`Live job ${jobId} ended as ${job.status}: ${job.error_message ?? ''}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Live job ${jobId} did not complete before the test deadline.`);
}

async function createLiveResources(session: ApiSession): Promise<LiveResources> {
  const tenantId = state.tenant_b_id;
  const projectName = `Tenant B confidential ${state.run_id}`;
  const fileName = `tenant-b-confidential-${state.run_id}.pdf`;
  const projectResponse = await apiFetch(session, `/tenants/${tenantId}/projects`, {
    method: 'POST',
    data: { name: projectName, description: 'Tenant B private scope' },
  });
  await expectStatus(projectResponse, 201);
  const project = await projectResponse.json() as { id: string };

  const documentResponse = await apiFetch(
    session,
    `/tenants/${tenantId}/projects/${project.id}/documents`,
    {
      method: 'POST',
      multipart: {
        file: {
          name: fileName,
          mimeType: 'application/pdf',
          buffer: textPdfBuffer(),
        },
        kind: 'PROJECT',
      },
    },
  );
  await expectStatus(documentResponse, 201);
  const document = await documentResponse.json() as { id: string };

  const summaryResponse = await apiFetch(
    session,
    `/tenants/${tenantId}/documents/${document.id}/summary`,
    { method: 'POST' },
  );
  await expectStatus(summaryResponse, 202);
  const summaryJob = await summaryResponse.json() as { id: string };
  const completedSummary = await waitForJob(session, tenantId, summaryJob.id);
  const summaryId = String(completedSummary.result_payload.summary_id);

  await expectStatus(await apiFetch(
    session,
    `/tenants/${tenantId}/documents/${document.id}/summary/approve`,
    { method: 'POST' },
  ), 200);

  const generationResponse = await apiFetch(
    session,
    `/tenants/${tenantId}/projects/${project.id}/generations`,
    {
      method: 'POST',
      data: {
        document_id: document.id,
        template_id: null,
        summary_id: summaryId,
      },
    },
  );
  await expectStatus(generationResponse, 202);
  const generationJob = await generationResponse.json() as { id: string };
  const completedGeneration = await waitForJob(session, tenantId, generationJob.id);
  const versionId = String(completedGeneration.result_payload.wbs_version_id);

  const validationResponse = await apiFetch(
    session,
    `/tenants/${tenantId}/wbs/${versionId}/validations`,
    { method: 'POST' },
  );
  await expectStatus(validationResponse, 202);
  const validation = await validationResponse.json() as { id: string };

  const exportResponse = await apiFetch(
    session,
    `/tenants/${tenantId}/wbs/${versionId}/exports`,
    { method: 'POST', data: { format: 'json' } },
  );
  await expectStatus(exportResponse, 202);
  const exportFile = await exportResponse.json() as { id: string };

  return {
    projectId: project.id,
    documentId: document.id,
    summaryJobId: summaryJob.id,
    generationJobId: generationJob.id,
    versionId,
    validationId: validation.id,
    exportId: exportFile.id,
    confidentialMarkers: [projectName, fileName, project.id, document.id],
  };
}

async function assertConfidentialDenial(
  response: APIResponse,
  expectedStatus: number,
  markers: string[],
): Promise<void> {
  expect(response.status()).toBe(expectedStatus);
  const body = await response.text();
  for (const marker of markers) expect(body).not.toContain(marker);
}

async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1);
}

test.describe.serial('live tenant authorization and WBS workflow', () => {
  test('enforces the Viewer, Editor, and Admin permission families', async () => {
    const viewer = await loginApi(state.emails.viewer_a);
    const editor = await loginApi(state.emails.editor_a);

    await expectStatus(await apiFetch(
      viewer,
      `/tenants/${state.tenant_a_id}/projects`,
    ), 200);
    await expectStatus(await apiFetch(
      viewer,
      `/tenants/${state.tenant_a_id}/projects`,
      { method: 'POST', data: { name: 'Viewer must not create' } },
    ), 403);
    await expectStatus(await apiFetch(
      viewer,
      `/tenants/${state.tenant_a_id}/members`,
    ), 403);
    await expectStatus(await apiFetch(
      editor,
      `/tenants/${state.tenant_a_id}/members`,
    ), 403);
    await expectStatus(await apiFetch(
      editor,
      `/tenants/${state.tenant_a_id}/projects`,
      { method: 'POST', data: { name: `Editor project ${state.run_id}` } },
    ), 201);

    await viewer.context.dispose();
    await editor.context.dispose();
  });

  test('does not disclose Tenant B resources when their IDs are replayed in Tenant A', async () => {
    const adminB = await loginApi(state.emails.admin_b);
    const resources = await createLiveResources(adminB);
    const adminA = await loginApi(state.emails.admin_a);
    const tenantA = state.tenant_a_id;

    const checks = [
      apiFetch(adminA, `/tenants/${tenantA}/projects/${resources.projectId}`),
      apiFetch(adminA, `/tenants/${tenantA}/documents/${resources.documentId}`),
      apiFetch(adminA, `/tenants/${tenantA}/jobs/${resources.summaryJobId}`),
      apiFetch(adminA, `/tenants/${tenantA}/jobs/${resources.generationJobId}`),
      apiFetch(adminA, `/tenants/${tenantA}/wbs/${resources.versionId}`, {
        method: 'PUT',
        data: { tree: [] },
      }),
      apiFetch(adminA, `/tenants/${tenantA}/validations/${resources.validationId}`),
      apiFetch(adminA, `/tenants/${tenantA}/exports/${resources.exportId}`),
    ];
    for (const response of await Promise.all(checks)) {
      await assertConfidentialDenial(response, 404, resources.confidentialMarkers);
    }

    const directTenantB = await apiFetch(
      adminA,
      `/tenants/${state.tenant_b_id}/projects/${resources.projectId}`,
    );
    await assertConfidentialDenial(directTenantB, 403, resources.confidentialMarkers);

    await adminA.context.dispose();
    await adminB.context.dispose();
  });

  test('applies role changes and membership removal to an already-issued token', async () => {
    const admin = await loginApi(state.emails.admin_a);
    const viewer = await loginApi(state.emails.viewer_a);
    const memberPath = `/tenants/${state.tenant_a_id}/members/${state.user_ids.viewer_a}`;

    await expectStatus(await apiFetch(admin, memberPath, {
      method: 'PATCH',
      data: { role: 'EDITOR' },
    }), 200);
    await expectStatus(await apiFetch(
      viewer,
      `/tenants/${state.tenant_a_id}/projects`,
      { method: 'POST', data: { name: `Runtime role project ${state.run_id}` } },
    ), 201);

    await expectStatus(await apiFetch(admin, memberPath, { method: 'DELETE' }), 204);
    await expectStatus(await apiFetch(
      viewer,
      `/tenants/${state.tenant_a_id}/projects`,
    ), 403);

    await viewer.context.dispose();
    await admin.context.dispose();
  });

  test('rejects simultaneous demotion and removal of the final active administrator', async () => {
    const admin = await loginApi(state.emails.final_admin);
    const path = `/tenants/${state.final_admin_tenant_id}/members/${state.user_ids.final_admin}`;
    const headers = bearer(admin.token);
    const [demotion, removal] = await Promise.all([
      admin.context.patch(endpoint(path), { headers, data: { role: 'EDITOR' } }),
      admin.context.delete(endpoint(path), { headers }),
    ]);
    expect([demotion.status(), removal.status()].sort()).toEqual([409, 409]);
    await admin.context.dispose();
  });

  test('completes document upload and ingestion through the live UI', async ({ page }) => {
    await loginPage(page, state.emails.editor_a);
    await page.getByRole('button', { name: 'Create project', exact: true }).click();
    await page.getByLabel('Project name').fill(`Live project ${state.run_id}`);
    await page.getByLabel('Description Optional').fill('Live browser workflow project');
    await page.getByRole('button', { name: 'Create project', exact: true }).click();
    await expect(page.getByRole('heading', { name: `Live project ${state.run_id}` })).toBeVisible();
    await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Create Work Breakdown Structure' })).toBeVisible();

    await page.locator('input[type="file"]').first().setInputFiles({
      name: `live-scope-${state.run_id}.pdf`,
      mimeType: 'application/pdf',
      buffer: textPdfBuffer(),
    });
    await expect(page.getByRole('button', { name: 'Process Document' })).toBeEnabled();
    await page.getByRole('button', { name: 'Process Document' }).click();
    await expect(page.getByRole('heading', { name: 'Document processed successfully' })).toBeVisible({ timeout: 180_000 });
    await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
    await assertNoCredentialStorage(page);
  });

  test('switches multi-tenant workspaces without retaining prior workspace UI state', async ({ page }) => {
    await loginPage(page, state.emails.multi);
    await expect(page.getByRole('heading', { name: 'Choose a workspace' })).toBeVisible();
    await page.getByRole('button', { name: /Tenant A/ }).click();
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();

    await page.getByRole('button', { name: 'Open profile menu' }).click();
    await page.getByRole('menuitem', { name: 'Switch workspace' }).click();
    await expect(page.getByRole('heading', { name: 'Choose a workspace' })).toBeVisible();
    await page.getByRole('button', { name: /Tenant B/ }).click();
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'My Projects' })).toHaveCount(0);
  });

  test('removes protected UI after logout and remains protected after back navigation', async ({ page }) => {
    await loginPage(page, state.emails.editor_a);
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();
    await page.getByRole('button', { name: 'Open profile menu' }).click();
    await page.getByRole('menuitem', { name: 'Profile Details' }).click();
    await expect(page.getByRole('heading', { name: 'Account settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Open profile menu' }).click();
    await page.getByRole('menuitem', { name: 'Sign Out' }).click();
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByText('Create Work Breakdown Structure')).toHaveCount(0);
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByText('Account settings')).toHaveCount(0);
  });

  test('has no horizontal overflow at desktop and mobile widths', async ({ page }) => {
    await loginPage(page, state.emails.editor_a);
    await expect(page.getByRole('heading', { name: /Welcome back/ })).toBeVisible();

    await page.setViewportSize({ width: 1440, height: 900 });
    await assertNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await assertNoHorizontalOverflow(page);
  });
});
