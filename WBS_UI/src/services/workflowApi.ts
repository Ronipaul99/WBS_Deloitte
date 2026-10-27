import { getDocument, uploadProjectDocument } from './documentsApi';
import { getCurrentIngestion, startIngestion } from './ingestionApi';
import { getProject } from './projectsApi';
import { getTemplate, uploadTemplate } from './templatesApi';
import type { ProjectResponse, WorkflowSession } from './workflowTypes';
import type { StoredWorkflowContext } from './workflowSessionStorage';

function assertSessionScope(tenantId: string, session: WorkflowSession): WorkflowSession {
  if (
    session.project.tenant_id !== tenantId
    || session.document.tenant_id !== tenantId
    || session.document.project_id !== session.project.id
    || (session.template !== null && session.template.tenant_id !== tenantId)
    || session.initialIngestionStatus.document_id !== session.document.id
    || session.initialIngestionStatus.job_id !== session.ingestionJobId
    || session.initialIngestionStatus.processing_run_id !== session.processingRunId
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
): Promise<WorkflowSession> {
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
