import { uploadProjectDocument } from './documentsApi';
import { createProject } from './projectsApi';
import { startSummary } from './summariesApi';
import { uploadTemplate } from './templatesApi';
import type { WorkflowSession } from './workflowTypes';

function projectNameFromFile(fileName: string): string {
  return fileName
    .replace(/\.[^/.]+$/, '')
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .slice(0, 200) || 'Untitled WBS Project';
}

export async function startWorkflow(
  tenantId: string,
  projectFile: File,
  templateFile: File | null,
  signal?: AbortSignal,
): Promise<WorkflowSession> {
  const project = await createProject(
    tenantId,
    projectNameFromFile(projectFile.name),
    `Created from ${projectFile.name}`,
    signal,
  );
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
