import type { Page, Route } from '@playwright/test';

const IDS = {
  tenant: '00000000-0000-0000-0000-000000000001',
  project: '10000000-0000-0000-0000-000000000001',
  document: '20000000-0000-0000-0000-000000000001',
  template: '30000000-0000-0000-0000-000000000001',
  summaryJob: '40000000-0000-0000-0000-000000000001',
  summary: '50000000-0000-0000-0000-000000000001',
  generationJob: '60000000-0000-0000-0000-000000000001',
  version: '70000000-0000-0000-0000-000000000001',
  validation: '80000000-0000-0000-0000-000000000001',
  export: '90000000-0000-0000-0000-000000000001',
} as const;

interface WorkflowMockOptions {
  failSummaryJob?: boolean;
  refreshDuringGenerationPoll?: boolean;
}

export interface WorkflowMockState {
  templateUploads: number;
  generationPayload: Record<string, unknown> | null;
  refreshDuringGenerationPoll: boolean;
  requestPaths: string[];
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function timestamps() {
  return { created_at: '2026-10-22T10:00:00Z', updated_at: '2026-10-22T10:00:00Z' };
}

function job(id: string, type: string, status = 'COMPLETED') {
  return {
    id,
    tenant_id: IDS.tenant,
    project_id: IDS.project,
    job_type: type,
    status,
    progress: status === 'COMPLETED' || status === 'FAILED' ? 100 : 45,
    current_step: status === 'COMPLETED' ? 'Complete' : 'Processing',
    error_message: status === 'FAILED' ? 'Document parser rejected the uploaded content.' : null,
    result_payload: type === 'DOCUMENT_SUMMARY'
      ? { summary_id: IDS.summary }
      : { wbs_version_id: IDS.version },
    ...timestamps(),
  };
}

export async function mockWorkflowApi(
  page: Page,
  options: WorkflowMockOptions = {},
): Promise<WorkflowMockState> {
  const state: WorkflowMockState = {
    templateUploads: 0,
    generationPayload: null,
    refreshDuringGenerationPoll: false,
    requestPaths: [],
  };
  let summaryPolls = 0;
  let generationPolls = 0;

  await page.route('**/api/v1/tenants/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    state.requestPaths.push(path);

    if (method === 'POST' && path.endsWith('/projects')) {
      return json(route, {
        id: IDS.project,
        tenant_id: IDS.tenant,
        name: 'Project Scope',
        description: 'Created from project-scope.pdf',
        status: 'ACTIVE',
        ...timestamps(),
      }, 201);
    }
    if (method === 'POST' && path.endsWith(`/projects/${IDS.project}/documents`)) {
      return json(route, {
        id: IDS.document,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        kind: 'PROJECT',
        file_name: 'project-scope.pdf',
        content_type: 'application/pdf',
        size_bytes: 13,
        created_at: timestamps().created_at,
      }, 201);
    }
    if (method === 'POST' && path.endsWith('/templates')) {
      state.templateUploads += 1;
      return json(route, {
        id: IDS.template,
        tenant_id: IDS.tenant,
        name: 'reference-template',
        file_name: 'reference-template.xlsx',
        content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        size_bytes: 12,
        is_active: true,
        created_at: timestamps().created_at,
      }, 201);
    }
    if (method === 'POST' && path.endsWith(`/documents/${IDS.document}/summary`)) {
      return json(route, job(IDS.summaryJob, 'DOCUMENT_SUMMARY'), 202);
    }
    if (method === 'GET' && path.endsWith(`/jobs/${IDS.summaryJob}`)) {
      summaryPolls += 1;
      return json(route, job(
        IDS.summaryJob,
        'DOCUMENT_SUMMARY',
        options.failSummaryJob ? 'FAILED' : summaryPolls <= 2 ? 'IN_PROGRESS' : 'COMPLETED',
      ));
    }
    if (method === 'POST' && path.endsWith(`/jobs/${IDS.summaryJob}/cancel`)) {
      return json(route, job(IDS.summaryJob, 'DOCUMENT_SUMMARY', 'CANCELLED'));
    }
    if (method === 'GET' && path.endsWith(`/documents/${IDS.document}/summary`)) {
      return json(route, {
        id: IDS.summary,
        tenant_id: IDS.tenant,
        document_id: IDS.document,
        summary_text: 'A tenant-scoped project summary.',
        key_points: ['Install the main system', 'Complete commissioning'],
        requirements: [{ id: 'REQ-001', title: 'Commission the system', source: 'project-scope.pdf' }],
        is_approved: false,
        approved_at: null,
        ...timestamps(),
      });
    }
    if (method === 'PATCH' && path.endsWith(`/documents/${IDS.document}/summary`)) {
      const payload = request.postDataJSON() as Record<string, unknown>;
      return json(route, {
        id: IDS.summary,
        tenant_id: IDS.tenant,
        document_id: IDS.document,
        summary_text: payload.summary_text,
        key_points: payload.key_points,
        requirements: payload.requirements,
        is_approved: false,
        approved_at: null,
        ...timestamps(),
      });
    }
    if (method === 'POST' && path.endsWith(`/documents/${IDS.document}/summary/approve`)) {
      return json(route, {
        id: IDS.summary,
        tenant_id: IDS.tenant,
        document_id: IDS.document,
        summary_text: 'A tenant-scoped project summary.',
        key_points: ['Install the main system', 'Complete commissioning'],
        requirements: [{ id: 'REQ-001', title: 'Commission the system' }],
        is_approved: true,
        approved_at: timestamps().updated_at,
        ...timestamps(),
      });
    }
    if (method === 'POST' && path.endsWith(`/projects/${IDS.project}/generations`)) {
      state.generationPayload = request.postDataJSON() as Record<string, unknown>;
      return json(route, job(IDS.generationJob, 'WBS_GENERATION', 'QUEUED'), 202);
    }
    if (method === 'GET' && path.endsWith(`/jobs/${IDS.generationJob}`)) {
      generationPolls += 1;
      if (options.refreshDuringGenerationPoll && generationPolls === 1) {
        state.refreshDuringGenerationPoll = true;
        return route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"expired"}' });
      }
      return json(route, job(
        IDS.generationJob,
        'WBS_GENERATION',
        generationPolls === 1 ? 'IN_PROGRESS' : 'COMPLETED',
      ));
    }
    if (method === 'POST' && path.endsWith(`/jobs/${IDS.generationJob}/cancel`)) {
      return json(route, job(IDS.generationJob, 'WBS_GENERATION', 'CANCELLED'));
    }
    if (method === 'GET' && path.endsWith(`/projects/${IDS.project}/wbs/latest`)) {
      return json(route, {
        id: IDS.version,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        generation_job_id: IDS.generationJob,
        version_number: 1,
        status: 'DRAFT',
        tree: [{
          id: 'phase-1',
          code: '1.0',
          name: 'Project Scope',
          type: 'Phase',
          parent: 'Root',
          description: 'Generated project phase',
          children: [{
            id: 'package-1',
            code: '1.1',
            name: 'Commission the system',
            type: 'Work Package',
            parent: 'phase-1',
            description: 'Complete system commissioning',
            children: [],
          }],
        }],
        scope_coverage: { overallScore: 100, totalRequirements: 1, mappedCount: 1, gapCount: 0 },
        ...timestamps(),
      });
    }
    if (method === 'PUT' && path.endsWith(`/wbs/${IDS.version}`)) {
      return json(route, { id: IDS.version, ...(request.postDataJSON() as object) });
    }
    if (method === 'POST' && path.endsWith(`/wbs/${IDS.version}/validations`)) {
      return json(route, {
        id: IDS.validation,
        tenant_id: IDS.tenant,
        wbs_version_id: IDS.version,
        status: 'QUEUED',
        result: {},
        ...timestamps(),
      }, 202);
    }
    if (method === 'GET' && path.endsWith(`/validations/${IDS.validation}`)) {
      return json(route, {
        id: IDS.validation,
        tenant_id: IDS.tenant,
        wbs_version_id: IDS.version,
        status: 'COMPLETED',
        result: {
          summary: { wbsItems: 2, duplicateCodes: 0, blankNames: 0 },
          checks: [
            { code: 'UNIQUE_WBS_CODES', status: 'PASSED', details: [] },
            { code: 'NON_EMPTY_NAMES', status: 'PASSED', details: [] },
          ],
          scopeCoverage: { overallScore: 100, totalRequirements: 1, mappedCount: 1, gapCount: 0 },
        },
        ...timestamps(),
      });
    }
    if (method === 'POST' && path.endsWith(`/wbs/${IDS.version}/exports`)) {
      const payload = request.postDataJSON() as { format: string };
      return json(route, {
        id: IDS.export,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        wbs_version_id: IDS.version,
        format: payload.format,
        status: 'QUEUED',
        file_name: null,
        download_url: null,
        ...timestamps(),
      }, 202);
    }
    if (method === 'GET' && path.endsWith(`/exports/${IDS.export}`)) {
      return json(route, {
        id: IDS.export,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        wbs_version_id: IDS.version,
        format: 'json',
        status: 'COMPLETED',
        file_name: 'wbs-v1.json',
        download_url: `/api/v1/tenants/${IDS.tenant}/exports/${IDS.export}/download`,
        ...timestamps(),
      });
    }
    if (method === 'GET' && path.endsWith(`/exports/${IDS.export}/download`)) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Content-Disposition': 'attachment; filename="wbs-v1.json"' },
        body: JSON.stringify([{ code: '1.0', name: 'Project Scope' }]),
      });
    }

    return json(route, { detail: `Unhandled workflow route: ${method} ${path}` }, 500);
  });
  return state;
}
