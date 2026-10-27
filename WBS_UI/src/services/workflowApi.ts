import { createWorkflowRequestKey } from './documentFingerprint';
import { apiRequest } from './apiClient';
import { getDocument, uploadProjectDocument } from './documentsApi';
import { getCurrentIngestion, startIngestion } from './ingestionApi';
import { getProject } from './projectsApi';
import { getTemplate, uploadTemplate } from './templatesApi';
import type { ProjectResponse, WorkflowSession } from './workflowTypes';
import type { StoredWorkflowContext } from './workflowSessionStorage';
import { configureWorkflowTemplate, getWorkflow, uploadStatus, uploadWorkflow, workflowCapabilities } from './documentWorkflowsApi';
import { pollResource } from './polling';
import type { WorkflowState } from './workflowTypes';

function assertSessionScope(tenantId: string, session: WorkflowSession): WorkflowSession {
  if (
    session.project.tenant_id !== tenantId
    || session.document.tenant_id !== tenantId
    || session.document.project_id !== session.project.id
    || (session.template !== null && session.template.tenant_id !== tenantId)
    || (session.initialIngestionStatus !== null && (
      session.initialIngestionStatus.document_id !== session.document.id
      || session.initialIngestionStatus.job_id !== session.ingestionJobId
      || session.initialIngestionStatus.processing_run_id !== session.processingRunId))
  ) {
    throw new Error('The saved document workflow no longer matches this workspace.');
  }
  return session;
}

export async function startWorkflow(
  tenantId: string,
  project: ProjectResponse,
  projectFile: File,
  templateFile: File | null,
  signal?: AbortSignal,
  verifiedHash: string | null = null,
  requestKey: string = createWorkflowRequestKey(),
): Promise<WorkflowSession> {
  const capabilities = await workflowCapabilities(tenantId, signal);
  if (capabilities.resume_enabled) {
    if (!capabilities.reuse_enabled) throw new Error('New uploads are temporarily paused. Existing work remains available.');
    let uploaded = await uploadWorkflow(tenantId, project.id, projectFile, requestKey, verifiedHash, signal);
    if (uploaded.disposition === 'UPLOAD_PENDING' && uploaded.upload_handle) {
      const handle = uploaded.upload_handle;
      uploaded = await pollResource({
        signal: signal ?? new AbortController().signal,
        request: (pollSignal) => uploadStatus(tenantId, handle, pollSignal),
        isTerminal: (value) => value.disposition !== 'UPLOAD_PENDING',
      });
    }
    if (!uploaded.workflow) throw new Error('The upload is still pending. Check existing documents again.');
    let state = uploaded.workflow;
    // A server-side race that reused a record must not upload/replace a selected template.
    if (uploaded.disposition === 'REUSED') return sessionFromState(tenantId, await getWorkflow(tenantId, state.workflow_id, signal), signal);
    if (templateFile) {
      const template = await uploadTemplate(tenantId, templateFile, signal);
      state = await configureWorkflowTemplate(tenantId, state, template.id, false, signal);
    }
    await startIngestion(tenantId, state.document_id, signal);
    return resumeWorkflow(tenantId, state.workflow_id, signal);
  }
  const document = await uploadProjectDocument(tenantId, project.id, projectFile, signal);
  const template = templateFile
    ? await uploadTemplate(tenantId, templateFile, signal)
    : null;
  const ingestionJob = await startIngestion(tenantId, document.id, signal);
  if (
    ingestionJob.tenant_id !== tenantId
    || ingestionJob.project_id !== project.id
    || ingestionJob.job_type !== 'DOCUMENT_INGESTION'
  ) {
    throw new Error('The ingestion response no longer matches this project workflow.');
  }
  const ingestionStatus = await getCurrentIngestion(tenantId, document.id, signal);

  return assertSessionScope(tenantId, {
    project,
    document,
    template,
    ingestionJobId: ingestionJob.id,
    processingRunId: ingestionStatus.processing_run_id,
    initialIngestionStatus: ingestionStatus,
    summaryId: null,
    generationJobId: null,
    wbsVersionId: null,
    validationId: null,
  });
}

export async function restoreWorkflow(
  tenantId: string,
  context: StoredWorkflowContext,
  signal?: AbortSignal,
): Promise<WorkflowSession> {
  if (context.tenantId !== tenantId) {
    throw new Error('The saved document workflow belongs to another workspace.');
  }
  if (context.version === 2) return resumeWorkflow(tenantId, context.workflowId, signal);
  const capabilities = await workflowCapabilities(tenantId, signal);
  if (capabilities.resume_enabled) {
    const states = await apiRequest<WorkflowState[]>(`/tenants/${tenantId}/document-workflows/documents/${context.documentId}`, { signal });
    if (states.length !== 1) throw new Error('Choose a saved workflow from the project to continue.');
    return resumeWorkflow(tenantId, states[0].workflow_id, signal);
  }
  const [project, document, template, ingestionStatus] = await Promise.all([
    getProject(tenantId, context.projectId, signal),
    getDocument(tenantId, context.documentId, signal),
    context.templateId ? getTemplate(tenantId, context.templateId, signal) : Promise.resolve(null),
    getCurrentIngestion(tenantId, context.documentId, signal),
  ]);
  return assertSessionScope(tenantId, {
    project,
    document,
    template,
    ingestionJobId: context.ingestionJobId,
    processingRunId: context.processingRunId,
    initialIngestionStatus: ingestionStatus,
    summaryId: null,
    generationJobId: null,
    wbsVersionId: null,
    validationId: null,
  });
}

export async function sessionFromState(tenantId: string, state: WorkflowState, signal?: AbortSignal): Promise<WorkflowSession> {
  const ingestion = state.resume_screen === 'doc_processing' && state.ingestion_job_id && state.processing_run_id
    ? await getCurrentIngestion(tenantId, state.document_id, signal) : null;
  return assertSessionScope(tenantId, {
    project: state.project, document: state.document, template: state.template,
    ingestionJobId: state.ingestion_job_id, processingRunId: state.processing_run_id,
    initialIngestionStatus: ingestion, summaryId: state.summary_id,
    generationJobId: state.generation_job_id, wbsVersionId: state.wbs_version_id,
    validationId: state.validation_stale ? null : state.validation_id,
    workflowId: state.workflow_id, recovery: state,
  });
}

export async function resumeWorkflow(tenantId: string, workflowId: string, signal?: AbortSignal): Promise<WorkflowSession> {
  return sessionFromState(tenantId, await getWorkflow(tenantId, workflowId, signal), signal);
}
