import type { Page } from '@playwright/test';
import type { WorkflowStage, WorkflowState } from '../src/services/workflowTypes';
import { mockAuthenticatedUser } from './auth-mocks';
import { mockWorkflowApi } from './workflow-mocks';

export const ids = {
  tenant: '00000000-0000-0000-0000-000000000001',
  project: '10000000-0000-0000-0000-000000000001',
  document: '20000000-0000-0000-0000-000000000001',
  workflow: '21000000-0000-4000-8000-000000000001',
  generation: '60000000-0000-0000-0000-000000000001',
  version: '70000000-0000-0000-0000-000000000001',
};

export function savedWorkflow(stage: WorkflowStage = 'WBS_READY'): WorkflowState {
  const dates = { created_at: '2026-10-28T10:00:00Z', updated_at: '2026-10-28T10:00:00Z' };
  const generated = ['WBS_READY', 'VALIDATED', 'VALIDATING', 'GENERATING'].includes(stage);
  const screen = stage === 'WBS_READY' ? 'results'
    : stage === 'SUMMARY_REVIEW' ? 'doc_summary' : stage === 'GENERATING' ? 'analyzing'
    : stage === 'VALIDATED' || stage === 'VALIDATING' ? 'validation' : 'checkpoint';
  return {
    workflow_id: ids.workflow, project_id: ids.project, document_id: ids.document,
    checkpoint_revision: 4, stage, resume_screen: screen,
    project: { id: ids.project, tenant_id: ids.tenant, name: 'Project Scope', description: 'Saved scope', status: 'ACTIVE', ...dates },
    document: { id: ids.document, tenant_id: ids.tenant, project_id: ids.project, kind: 'PROJECT',
      file_name: 'original-scope.csv', content_type: 'text/csv', size_bytes: 12,
      lifecycle_status: 'ACTIVE', deletion_requested_at: null, deletion_completed_at: null,
      created_at: dates.created_at },
    template: null, processing_run_id: null, ingestion_job_id: null,
    summary_id: stage === 'DOCUMENT_READY' ? null : '50000000-0000-0000-0000-000000000001',
    summary_revision: 2, summary_job_id: null,
    generation_job_id: generated ? ids.generation : null,
    wbs_version_id: ['WBS_READY', 'VALIDATED', 'VALIDATING'].includes(stage) ? ids.version : null,
    validation_id: ['VALIDATED', 'VALIDATING'].includes(stage) ? '80000000-0000-0000-0000-000000000001' : null,
    validation_stale: false, input_compatibility: 'CURRENT', job: null,
    failed_stage: stage === 'FAILED' ? 'generation' : null,
    allowed_actions: stage === 'FAILED' ? ['retry'] : ['view_wbs', 'edit_wbs', 'start_validation'],
  };
}

export async function setupDocumentWorkflow(page: Page, options: {
  stage?: WorkflowStage; match?: boolean; crossProject?: boolean; listSaved?: boolean;
} = {}) {
  await mockAuthenticatedUser(page);
  const legacy = await mockWorkflowApi(page);
  const state = savedWorkflow(options.stage);
  if (options.crossProject) {
    state.project_id = '10000000-0000-0000-0000-000000000002';
    state.project.id = state.project_id;
    state.document.project_id = state.project_id;
    state.project.name = 'Original delivery project';
  }
  const calls = { uploadRequests: 0, resolves: [] as Record<string, unknown>[], reads: 0 };
  await page.route('**/document-workflows/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const send = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path.endsWith('/capabilities')) return send({ resume_enabled: true, reuse_enabled: true, max_upload_bytes: 25 * 1024 * 1024 });
    if (path.endsWith('/resolve')) {
      calls.resolves.push(request.postDataJSON());
      if (options.match === false) return send({ disposition: 'NEW', candidates: [], upload_handle: null });
      return send({ disposition: 'MATCH', upload_handle: null, candidates: [{
        workflow_id: state.workflow_id, document_id: state.document_id, project_id: state.project_id,
        project_name: state.project.name, file_name: state.document.file_name, stage: state.stage,
        updated_at: state.project.updated_at, requires_project_switch: Boolean(options.crossProject),
      }] });
    }
    if (path.endsWith('/uploads')) {
      calls.uploadRequests += 1;
      return send({ disposition: 'REUSED', workflow: state, upload_handle: null });
    }
    if (path.includes('/projects/')) return send(options.listSaved ? [state] : []);
    if (path.endsWith(`/${state.workflow_id}`)) {
      calls.reads += 1;
      return send(state);
    }
    return send({ detail: 'Unexpected feature action' }, 500);
  });
  await page.route(`**/api/v1/tenants/${ids.tenant}/wbs/${ids.version}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      id: ids.version, tenant_id: ids.tenant, project_id: state.project_id,
      generation_job_id: ids.generation, version_number: 1, status: 'DRAFT',
      tree: [{ id: 'saved', code: '1', name: 'Saved delivery scope edit', type: 'Phase', children: [] }],
      scope_coverage: { overallScore: 100, totalRequirements: 1, mappedCount: 1, gapCount: 0 },
      created_at: state.project.created_at, updated_at: state.project.updated_at,
    }) });
  });
  if (options.listSaved) {
    await page.route(/\/api\/v1\/tenants\/[^/]+\/projects$/, async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([state.project]) });
    });
  }
  return { state, calls, legacy };
}
