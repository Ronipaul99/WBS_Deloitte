import { expect, test, type Page } from '@playwright/test';
import { ids, setupDocumentWorkflow } from './document-workflow-mocks';
import { mockAuthenticatedUser, VIEWER_PERMISSIONS, ADMIN_PERMISSIONS } from './auth-mocks';
import type { ExternalSummaryStatus, StructuredSummaryResponse, StructuredSummaryPatch } from '../src/services/workflowTypes';

const requestId = '92000000-0000-4000-8000-000000000001';
const jobId = '93000000-0000-4000-8000-000000000001';
const summaryId = '50000000-0000-0000-0000-000000000001';
const runId = '94000000-0000-4000-8000-000000000001';
const keys = ['project_overview', 'project_scope', 'key_deliverables', 'assumptions', 'constraints', 'exclusions', 'milestones_timeline'] as const;
const titles = ['Project Overview', 'Project Scope', 'Key Deliverables', 'Assumptions', 'Constraints', 'Exclusions', 'Milestones & Timeline'];
function metadata(): ExternalSummaryStatus {
  return { execution_backend: 'external_summary', request_id: requestId, job_id: jobId,
    document_id: ids.document, workflow_id: ids.workflow, job_type: 'DOCUMENT_SUMMERIZATION',
    submission_state: 'ACKNOWLEDGED', binding_state: 'VERIFIED', status: 'COMPLETED',
    provider_status: 'COMPLETED', progress: 100, current_step: 'SUMMARY:DONE', attempt_count: 1,
    updated_at: '2026-10-28T11:00:00Z', result_state: 'IMPORTED', summary_id: summaryId,
    summary_revision: 1, error_code: null, error_message: null, can_retry: false, can_cancel: false };
}
function summary(): StructuredSummaryResponse {
  return { id: summaryId, tenant_id: ids.tenant, document_id: ids.document,
    summary_text: '', key_points: [], requirements: [], is_approved: false, approved_at: null,
    created_at: '2026-10-28T11:00:00Z', updated_at: '2026-10-28T11:00:00Z', representation: 'external-summary-v1', revision: 1,
    provenance: { request_id: requestId, job_id: jobId, processing_run_id: runId, result_digest: 'a'.repeat(64), imported_revision: 1 },
    capabilities: { structured_review_available: true, can_generate_wbs: false, reason: 'REQUIREMENTS_CONTRACT_UNAVAILABLE' },
    structured_summary: { schema_version: 'external-summary-v1', edit_schema_version: 'section-edits-v1', current_sections: [],
      content_state: 'generated_unreviewed', canonical_validation: 'exact_quotes_chunk_page_coverage',
      generated_result: { status: 'success', message: 'Synthetic draft', data: {
        project_id: ids.project, document_id: ids.document, processing_run_id: runId,
        question_set_id: 'SYNTHETIC_V1', llm_model: 'synthetic-model',
        document_information: { filename: 'upstream-name.pdf', file_size: '1 MB', file_type: 'PDF', extraction_confidence: null, confidence_status: 'Not recorded; AI draft requires review.' },
        summary_sections: keys.map((key, i) => ({ id: `opaque:${key}`, key, order: i + 1, title: titles[i], badge: 'AI Draft', subtitle: 'Draft',
          content: i === 3 ? 'Evidence unavailable.' : `Synthetic ${titles[i]} caf\u00e9 \u{1f600}. [1]\n<script>text only</script>`,
          max_length: 200 + i, source_references: { label: 'Canonical physical pages', pages: i === 3 ? [] : [i + 1] },
          question_id: `Q${i}`, answer_status: i === 3 ? 'insufficient_evidence' : 'answered', evidence_context_truncated: i === 0,
          evidence_citations: i === 3 ? [] : [{ chunk_id: '95000000-0000-4000-8000-000000000001', citation_number: 1, quote: `Canonical quote for ${titles[i]}`, pages: [i + 1] }],
        })).reverse(),
      } },
    },
  };
}
async function setup(page: Page, options: { viewer?: boolean; progress?: boolean } = {}) {
  const context = await setupDocumentWorkflow(page, { listSaved: true, stage: options.progress ? 'SUMMARIZING' : 'SUMMARY_REVIEW' });
  if (options.viewer) await mockAuthenticatedUser(page, { role: 'VIEWER', permissions: VIEWER_PERMISSIONS });
  const runtime = { summary: summary(), status: metadata(), patches: [] as StructuredSummaryPatch[], approvals: 0,
    posts: 0, conflict: false, delay: null as Promise<void> | null, gets: 0 };
  Object.assign(context.state, { summary_id: summaryId, summary_revision: 1, summary_job_id: jobId,
    processing_run_id: runId, external_summary: runtime.status, allowed_actions: [] });
  await page.route(`**/documents/${ids.document}/summary**`, async (route) => {
    const request = route.request();
    if (request.url().includes('/requests/')) {
      if (options.progress && runtime.status.result_state === 'IMPORTED') { context.state.resume_screen = 'doc_summary'; context.state.stage = 'SUMMARY_REVIEW'; }
      return route.fulfill({ json: runtime.status });
    }
    if (request.method() === 'GET') { runtime.gets++; return route.fulfill({ json: runtime.summary }); }
    if (request.url().endsWith('/approve')) {
      runtime.approvals++;
      expect(request.postDataJSON()).toEqual({ format: 'external_summary_v1', expected_revision: runtime.summary.revision });
      runtime.summary.is_approved = true; runtime.summary.approved_at = '2026-10-28T12:00:00Z';
      return route.fulfill({ json: runtime.summary });
    }
    if (request.method() === 'PATCH') {
      const body = request.postDataJSON() as StructuredSummaryPatch;
      runtime.patches.push(body);
      if (runtime.delay) await runtime.delay;
      if (runtime.conflict) return route.fulfill({ status: 409, json: { detail: { code: 'SUMMARY_REVISION_CONFLICT', message: 'The saved summary changed. Refresh and review.' } } });
      expect(body.expected_revision).toBe(runtime.summary.revision);
      const edits = new Map(runtime.summary.structured_summary.current_sections.map((e) => [e.id, e]));
      body.sections.forEach((e) => edits.set(e.id, e));
      runtime.summary.structured_summary.current_sections = [...edits.values()];
      runtime.summary.structured_summary.content_state = 'edited_review_required';
      runtime.summary.revision++; runtime.summary.is_approved = false;
      context.state.summary_revision = runtime.summary.revision; runtime.status.summary_revision = runtime.summary.revision;
      return route.fulfill({ json: runtime.summary });
    }
    runtime.posts++;
    return route.fulfill({ status: 500, json: { detail: 'Generation must not be called' } });
  });
  const open = async (selectWorkspace = false) => {
    await page.goto('/');
    if (selectWorkspace) await page.getByRole('button', { name: /Test Workspace/ }).click();
    await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
    await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  };
  return { ...context, runtime, open };
}

test('seven ordered sections, evidence namespaces, truthful confidence and responsive review', async ({ page }, testInfo) => {
  const { runtime, open } = await setup(page); await open();
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible();
  const nav = page.locator('.wbs-rev-section-btn');
  expect(await nav.allTextContents()).toEqual(titles.map((title, i) => `${i + 1}${title}`));
  await expect(page.getByRole('textbox', { name: 'Project Overview' })).toHaveValue(/caf\u00e9 \u{1f600}/u);
  await expect(page.getByText('Not recorded', { exact: true })).toBeVisible();
  await expect(page.locator('.wbs-rev-confidence-track')).toBeHidden();
  await expect(page.getByText('85%')).toHaveCount(0);
  await expect(page.getByText('original-scope.csv', { exact: true })).toBeVisible();
  await expect(page.getByText('upstream-name.pdf', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox')).not.toHaveValue(/\[1\]/);
  await page.getByText('Source 1 · Physical pages 1', { exact: true }).click();
  await expect(page.getByText('Canonical quote for Project Overview', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '[1]', exact: true })).toHaveCount(0);
  await nav.nth(1).click();
  await expect(page.getByRole('textbox')).not.toHaveValue(/\[1\]/);
  await expect(page.getByText('Source 1 · Physical pages 2', { exact: true })).toBeVisible();
  await nav.nth(3).click();
  await expect(page.getByText('Insufficient evidence in generated draft')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Generate WBS', exact: true })).toBeDisabled();
  await nav.first().click();
  await page.screenshot({ path: testInfo.outputPath('review-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('review-mobile.png'), fullPage: true });
  expect(runtime.posts).toBe(0);
});

test('stable edits survive section switch, save reload and explicit approval without WBS', async ({ page }) => {
  const { runtime, open } = await setup(page); await open();
  const original = structuredClone(runtime.summary.structured_summary.generated_result);
  await page.getByRole('textbox').fill('Human edit caf\u00e9 \u{1f600}\nSecond paragraph [99]');
  await expect(page.getByText(/Unresolved citation markers/)).toBeVisible();
  await page.locator('.wbs-rev-section-btn').nth(1).click();
  await page.getByRole('textbox').fill('Second section [1]');
  await page.locator('.wbs-rev-section-btn').first().click();
  await expect(page.getByRole('textbox')).toHaveValue('Human edit caf\u00e9 \u{1f600}\nSecond paragraph [99]');
  await expect(page.getByRole('button', { name: 'Approve summary', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Save Draft', exact: true }).click();
  await expect(page.getByText('Revision 2', { exact: false })).toBeVisible();
  expect(runtime.patches[0].sections.map((s) => s.key)).toEqual(['project_overview', 'project_scope']);
  expect(runtime.summary.structured_summary.generated_result).toEqual(original);
  await page.getByRole('button', { name: 'Approve summary', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approved', exact: true })).toBeDisabled();
  expect(runtime.approvals).toBe(1); expect(runtime.posts).toBe(0);
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('Human edit caf\u00e9 \u{1f600}\nSecond paragraph [99]');
  const browserData = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(browserData).not.toContain('Human edit');
});

test('conflict retains local text and refresh requires explicit discard', async ({ page }) => {
  const { runtime, open } = await setup(page); await open(); runtime.conflict = true;
  await page.getByRole('textbox').fill('Keep this local draft');
  await page.getByRole('button', { name: 'Save Draft', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('saved summary changed');
  await expect(page.getByRole('textbox')).toHaveValue('Keep this local draft');
  await page.getByRole('button', { name: 'Refresh and review saved version' }).click();
  await page.getByRole('button', { name: 'Keep editing' }).click();
  await expect(page.getByRole('textbox')).toHaveValue('Keep this local draft');
  await page.getByRole('button', { name: 'Refresh and review saved version' }).click();
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(page.getByRole('textbox')).toHaveValue(/Synthetic Project Overview/);
  expect(runtime.posts).toBe(0);
});

test('viewer sees read-only content and no save or approval controls', async ({ page }) => {
  const { open } = await setup(page, { viewer: true }); await open();
  await expect(page.getByRole('textbox')).toHaveAttribute('readonly', '');
  await expect(page.getByRole('button', { name: 'Save Draft' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Approve summary' })).toHaveCount(0);
});

test('imported progress refreshes and opens only matching persisted review', async ({ page }) => {
  const { runtime, state, open } = await setup(page, { progress: true });
  runtime.status.result_state = 'NOT_READY'; runtime.status.status = 'IN_PROGRESS'; runtime.status.provider_status = 'RUNNING';
  runtime.status.progress = 20; runtime.status.summary_id = null; runtime.status.summary_revision = null;
  state.summary_id = null; state.summary_revision = null;
  await page.clock.install(); await open();
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20');
  Object.assign(runtime.status, { status: 'COMPLETED', provider_status: 'COMPLETED', progress: 100, result_state: 'IMPORT_PENDING' });
  await page.clock.fastForward(5000);
  await expect(page.getByRole('heading', { name: 'Finalizing summary' })).toBeVisible();
  Object.assign(runtime.status, metadata()); state.summary_id = summaryId; state.summary_revision = 1;
  await page.clock.fastForward(5000);
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toBeVisible();
  expect(runtime.posts).toBe(0);
});

for (const kind of ['request', 'job', 'document', 'revision', 'incomplete', 'missing_category'] as const) {
  test(`rejects incompatible imported handoff: ${kind}`, async ({ page }) => {
    const { runtime, open } = await setup(page);
    if (kind === 'request') runtime.summary.provenance.request_id = '92000000-0000-4000-8000-000000000002';
    if (kind === 'job') runtime.summary.provenance.job_id = '93000000-0000-4000-8000-000000000002';
    if (kind === 'document') runtime.summary.document_id = '20000000-0000-0000-0000-000000000002';
    if (kind === 'revision') runtime.summary.revision = 2;
    if (kind === 'incomplete') { runtime.status.result_state = 'IMPORT_PENDING'; runtime.status.summary_id = null; runtime.status.summary_revision = null; }
    if (kind === 'missing_category') runtime.summary.structured_summary.generated_result.data.summary_sections.pop();
    await open();
    await expect(page.getByRole('heading', { name: 'Unable to Load Summary' })).toBeVisible();
    await expect(page.getByRole('textbox')).toHaveCount(0);
    expect(runtime.posts).toBe(0);
  });
}

test('numeric extraction confidence is recorded without accuracy claims', async ({ page }) => {
  const { runtime, open } = await setup(page);
  runtime.summary.structured_summary.generated_result.data.document_information.extraction_confidence = 71.5;
  await open(); await expect(page.getByText('71.5%', { exact: true })).toBeVisible();
  await expect(page.getByText('Extraction confidence is not summary accuracy or human approval.')).toBeVisible();
});

test('oversized edits are preserved and blocked without truncation', async ({ page }) => {
  const { open } = await setup(page); await open();
  await page.getByRole('textbox').fill('\u{1f600}'.repeat(201));
  await expect(page.getByRole('textbox')).toHaveValue('\u{1f600}'.repeat(201));
  await expect(page.getByText('201/200')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save Draft' })).toBeDisabled();
});


test('unsaved navigation uses the existing discard dialog', async ({ page }) => {
  const { open } = await setup(page); await open();
  await page.getByRole('textbox').fill('Local navigation draft');
  await page.getByRole('button', { name: 'My Projects', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Keep editing' }).click();
  await expect(page.getByRole('textbox')).toHaveValue('Local navigation draft');
  await page.getByRole('button', { name: 'My Projects', exact: true }).click();
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
});

for (const action of ['logout', 'tenant switch'] as const) {
  test(`${action} aborts delayed save without late review updates`, async ({ page }) => {
    const { runtime, open } = await setup(page);
    if (action === 'tenant switch') await mockAuthenticatedUser(page, { tenants: [
      { id: ids.tenant, name: 'Test Workspace', slug: 'test', role: 'ADMIN', permissions: ADMIN_PERMISSIONS },
      { id: '00000000-0000-0000-0000-000000000002', name: 'Other Workspace', slug: 'other', role: 'VIEWER', permissions: VIEWER_PERMISSIONS },
    ] });
    await open(action === 'tenant switch');
    let release = () => {};
    runtime.delay = new Promise<void>((resolve) => { release = resolve; });
    await page.getByRole('textbox').fill('Transient unsaved draft');
    await page.getByRole('button', { name: 'Save Draft', exact: true }).click();
    await expect.poll(() => runtime.patches.length).toBe(1);
    await page.route('**/auth/logout', (route) => route.fulfill({ status: 204 }));
    await page.getByRole('button', { name: 'Open profile menu' }).click();
    if (action === 'tenant switch') {
      // The normal workspace teardown action must not be blocked by draft warnings.
      await page.getByRole('menuitem', { name: 'Switch workspace', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Choose a workspace', exact: true })).toBeVisible();
    } else {
      await page.getByRole('menuitem', { name: 'Sign Out', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
    }
    release();
    await expect(page.getByRole('heading', { name: 'Review Project Summary' })).toHaveCount(0);
    expect(await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }))).not.toContain('Transient unsaved');
  });
}


test('keyboard section and citation controls preserve safe text rendering', async ({ page }) => {
  const { open } = await setup(page); await open();
  await page.locator('.wbs-rev-section-btn').nth(1).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('textbox', { name: 'Project Scope' })).toBeVisible();
  await page.locator('.wbs-rev-citations summary').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('Canonical quote for Project Scope', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveValue(/<script>text only<\/script>/);
  expect(await page.locator('.wbs-rev-editor-card script').count()).toBe(0);
});

test('legacy three-section editing and explicit WBS generation remain compatible', async ({ page }) => {
  const { legacy } = await setupDocumentWorkflow(page, { listSaved: true, stage: 'SUMMARY_REVIEW' });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Project Scope', exact: true }).click();
  await page.getByRole('button', { name: 'Continue original-scope.csv', exact: true }).click();
  await expect(page.locator('.wbs-rev-section-btn')).toHaveCount(3);
  await page.getByRole('textbox').fill('Legacy draft edit');
  await page.getByRole('button', { name: 'Save Draft', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Saved!', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Generate WBS', exact: true }).click();
  await expect.poll(() => legacy.generationPayload).not.toBeNull();
  expect(legacy.summaryStarts).toBe(0);
});
