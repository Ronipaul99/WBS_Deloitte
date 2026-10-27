import type { Page, Route } from '@playwright/test';

const IDS = {
  tenant: '00000000-0000-0000-0000-000000000001',
  project: '10000000-0000-0000-0000-000000000001',
  document: '20000000-0000-0000-0000-000000000001',
  template: '30000000-0000-0000-0000-000000000001',
  ingestionJob: '40000000-0000-4000-8000-000000000001',
  processingRun: '41000000-0000-4000-8000-000000000001',
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
  documentUploadDelayMs?: number;
  abortDocumentUpload?: boolean;
  ingestionStages?: string[];
  ingestionProgress?: number[];
  ingestionErrorCode?: string;
  ingestionStatusHttpError?: number;
  ingestionStatusHttpErrorAfter?: number;
  ingestionStatusDelayMs?: number;
  documentFileName?: string;
  projectDocuments?: Array<Record<string, unknown>>;
  deletionStages?: Array<'DELETING_OBJECTS' | 'RETRY_WAIT' | 'COMPLETED' | 'FAILED'>;
  unauthorizedIngestionPollOnce?: boolean;
  documentUploadError?: {
    code: string;
    message: string;
    status: number;
  };
}

export interface WorkflowMockState {
  projectCreates: number;
  documentUploads: number;
  templateUploads: number;
  ingestionStarts: number;
  ingestionPolls: number;
  summaryStarts: number;
  cancellationRequests: number;
  deletionStarts: number;
  deletionPolls: number;
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
    error_code: status === 'FAILED' ? 'DOCUMENT_INGESTION_FAILED' : null,
    error_message: status === 'FAILED' ? 'Document parser rejected the uploaded content.' : null,
    attempt_count: 0,
    result_payload: type === 'DOCUMENT_SUMMARY'
      ? { summary_id: IDS.summary }
      : { wbs_version_id: IDS.version },
    ...timestamps(),
  };
}

function ingestionStatus(stage: string, progress: number, errorCode?: string) {
  const failed = stage === 'FAILED';
  const completed = stage === 'COMPLETED';
  return {
    job_id: IDS.ingestionJob,
    processing_run_id: IDS.processingRun,
    document_id: IDS.document,
    status: failed ? 'FAILED' : completed ? 'COMPLETED' : stage === 'QUEUED' ? 'QUEUED' : 'IN_PROGRESS',
    stage,
    progress,
    attempt_count: stage === 'RETRY_WAIT' ? 1 : 0,
    maximum_attempts: 3,
    page_count: completed ? 4 : 0,
    worksheet_count: 0,
    block_count: completed ? 12 : 0,
    chunk_count: completed ? 8 : 0,
    extractor_name: completed ? 'secure_pdf' : null,
    extractor_version: completed ? '1.0.0' : null,
    embedding_provider: completed ? 'fastembed' : null,
    embedding_model: completed ? 'BAAI/bge-small-en-v1.5' : null,
    embedding_model_revision: completed ? 'approved-revision' : null,
    warning_codes: [],
    error_code: failed ? errorCode ?? 'DOCUMENT_MALFORMED' : null,
    error_message: failed ? 'private endpoint / object key / raw parser exception' : null,
    started_at: stage === 'QUEUED' ? null : timestamps().created_at,
    completed_at: completed ? timestamps().updated_at : null,
    failed_at: failed ? timestamps().updated_at : null,
    ...timestamps(),
  };
}

export async function mockWorkflowApi(
  page: Page,
  options: WorkflowMockOptions = {},
): Promise<WorkflowMockState> {
  const state: WorkflowMockState = {
    projectCreates: 0,
    documentUploads: 0,
    templateUploads: 0,
    ingestionStarts: 0,
    ingestionPolls: 0,
    summaryStarts: 0,
    cancellationRequests: 0,
    deletionStarts: 0,
    deletionPolls: 0,
    generationPayload: null,
    refreshDuringGenerationPoll: false,
    requestPaths: [],
  };
  let summaryPolls = 0;
  let generationPolls = 0;
  const ingestionStages = options.ingestionStages ?? ['QUEUED', 'COMPLETED'];
  const stageProgress: Record<string, number> = {
    QUEUED: 0,
    SCANNING: 10,
    EXTRACTING: 30,
    CHUNKING: 50,
    EMBEDDING: 65,
    PERSISTING: 80,
    ACTIVATING: 95,
    RETRY_WAIT: 95,
    COMPLETED: 100,
    FAILED: 100,
  };

  await page.route('**/api/v1/tenants/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    state.requestPaths.push(path);

    if (method === 'GET' && path.endsWith('/document-workflows/capabilities')) {
      return json(route, { resume_enabled: false, reuse_enabled: false, max_upload_bytes: 25 * 1024 * 1024 });
    }

    if (method === 'GET' && path.endsWith('/projects')) {
      return json(route, []);
    }
    if (method === 'POST' && path.endsWith('/projects')) {
      state.projectCreates += 1;
      const payload = request.postDataJSON() as { name: string; description?: string | null };
      return json(route, {
        id: IDS.project,
        tenant_id: IDS.tenant,
        name: payload.name,
        description: payload.description ?? null,
        status: 'ACTIVE',
        ...timestamps(),
      }, 201);
    }
    if (method === 'GET' && path.endsWith(`/projects/${IDS.project}`)) {
      return json(route, {
        id: IDS.project,
        tenant_id: IDS.tenant,
        name: 'Project Scope',
        description: 'POC delivery scope',
        status: 'ACTIVE',
        ...timestamps(),
      });
    }
    if (method === 'POST' && path.endsWith(`/projects/${IDS.project}/documents`)) {
      state.documentUploads += 1;
      if (options.documentUploadDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.documentUploadDelayMs));
      }
      if (options.abortDocumentUpload) return route.abort('failed');
      if (options.documentUploadError) {
        return json(
          route,
          {
            detail: {
              code: options.documentUploadError.code,
              message: options.documentUploadError.message,
            },
          },
          options.documentUploadError.status,
        );
      }
      return json(route, {
        id: IDS.document,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        kind: 'PROJECT',
        file_name: options.documentFileName ?? 'project-scope.pdf',
        content_type: 'application/pdf',
        size_bytes: 13,
        lifecycle_status: 'ACTIVE',
        deletion_requested_at: null,
        deletion_completed_at: null,
        created_at: timestamps().created_at,
      }, 201);
    }
    if (method === 'GET' && path.endsWith(`/projects/${IDS.project}/documents`)) {
      return json(route, options.projectDocuments ?? []);
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
    if (method === 'GET' && path.endsWith(`/documents/${IDS.document}`)) {
      return json(route, {
        id: IDS.document,
        tenant_id: IDS.tenant,
        project_id: IDS.project,
        kind: 'PROJECT',
        file_name: options.documentFileName ?? 'project-scope.pdf',
        content_type: 'application/pdf',
        size_bytes: 13,
        lifecycle_status: 'ACTIVE',
        deletion_requested_at: null,
        deletion_completed_at: null,
        created_at: timestamps().created_at,
      });
    }
    if (method === 'DELETE' && path.endsWith(`/documents/${IDS.document}`)) {
      state.deletionStarts += 1;
      return json(route, job('42000000-0000-4000-8000-000000000001', 'DOCUMENT_DELETION', 'QUEUED'), 202);
    }
    if (method === 'GET' && path.endsWith(`/documents/${IDS.document}/deletion`)) {
      state.deletionPolls += 1;
      const stages = options.deletionStages ?? ['COMPLETED'];
      const stage = stages[Math.min(state.deletionPolls - 1, stages.length - 1)];
      const completed = stage === 'COMPLETED';
      const failed = stage === 'FAILED';
      return json(route, {
        document_id: IDS.document,
        job_id: '42000000-0000-4000-8000-000000000001',
        status: completed ? 'COMPLETED' : failed ? 'FAILED' : 'IN_PROGRESS',
        stage,
        progress: completed || failed ? 100 : stage === 'RETRY_WAIT' ? 60 : 50,
        attempt_count: stage === 'RETRY_WAIT' ? 1 : 0,
        lifecycle_status: completed ? 'DELETED' : 'DELETING',
        deletion_requested_at: timestamps().created_at,
        vectors_hidden_at: timestamps().created_at,
        deletion_completed_at: completed ? timestamps().updated_at : null,
        error_code: failed ? 'DOCUMENT_DELETION_STORAGE_UNAVAILABLE' : null,
        ...timestamps(),
      });
    }
    if (method === 'GET' && path.endsWith(`/templates/${IDS.template}`)) {
      return json(route, {
        id: IDS.template,
        tenant_id: IDS.tenant,
        name: 'reference-template',
        file_name: 'reference-template.xlsx',
        content_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        size_bytes: 12,
        is_active: true,
        created_at: timestamps().created_at,
      });
    }
    if (method === 'POST' && path.endsWith(`/documents/${IDS.document}/ingestions`)) {
      state.ingestionStarts += 1;
      return json(route, job(IDS.ingestionJob, 'DOCUMENT_INGESTION', 'QUEUED'), 202);
    }
    if (method === 'GET' && path.endsWith(`/documents/${IDS.document}/ingestions/current`)) {
      state.ingestionPolls += 1;
      if (options.unauthorizedIngestionPollOnce && state.ingestionPolls === 2) {
        state.refreshDuringGenerationPoll = true;
        return json(route, { detail: 'expired' }, 401);
      }
      if (options.ingestionStatusDelayMs && state.ingestionPolls > 1) {
        await new Promise((resolve) => setTimeout(resolve, options.ingestionStatusDelayMs));
      }
      if (
        options.ingestionStatusHttpError
        && state.ingestionPolls >= (options.ingestionStatusHttpErrorAfter ?? 1)
      ) {
        return json(route, { detail: 'private infrastructure response' }, options.ingestionStatusHttpError);
      }
      const index = Math.min(state.ingestionPolls - 1, ingestionStages.length - 1);
      const stage = ingestionStages[index];
      const progress = options.ingestionProgress?.[index] ?? stageProgress[stage] ?? 0;
      return json(route, ingestionStatus(stage, progress, options.ingestionErrorCode));
    }
    if (method === 'POST' && path.endsWith(`/documents/${IDS.document}/summary`)) {
      state.summaryStarts += 1;
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
      state.cancellationRequests += 1;
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
      state.cancellationRequests += 1;
      return json(route, job(IDS.generationJob, 'WBS_GENERATION', 'CANCELLED'));
    }
    if (
      method === 'GET'
      && (
        path.endsWith(`/projects/${IDS.project}/wbs/latest`)
        || path.endsWith(`/wbs/${IDS.version}`)
      )
    ) {
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
    if (method === 'GET' && path.endsWith(`/projects/${IDS.project}/wbs/versions`)) {
      return json(route, []);
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

export async function createProjectAndOpenWbs(
  page: Page,
  name = 'Project Scope',
): Promise<void> {
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Project name').fill(name);
  await page.getByLabel('Description Optional').fill('POC delivery scope');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByRole('button', { name: 'Create new WBS', exact: true }).click();
}
