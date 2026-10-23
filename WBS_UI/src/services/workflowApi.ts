import { uploadProjectDocument } from './documentsApi';
import { startSummary } from './summariesApi';
import { uploadTemplate } from './templatesApi';
import type { ProjectResponse, WorkflowSession } from './workflowTypes';

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
  const summaryJob = await startSummary(tenantId, document.id, signal);

  return {
    project,
    document,
    template,
    summaryJobId: summaryJob.id,
    summaryId: null,
    generationJobId: null,
    wbsVersionId: null,
    validationId: null,
  };
}
