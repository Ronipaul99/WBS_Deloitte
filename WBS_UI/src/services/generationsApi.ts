import { createWorkflowRequestKey } from './documentFingerprint';
import { apiRequest } from './apiClient';
import type { JobResponse } from './workflowTypes';

export function startGeneration(
  tenantId: string,
  projectId: string,
  input: { documentId: string; summaryId: string; templateId: string | null;
    workflowId?: string; regenerate?: boolean; expectedRevision?: number },
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/generations`, {
    method: 'POST',
    body: JSON.stringify({
      document_id: input.documentId,
      summary_id: input.summaryId,
      ...(input.workflowId ? { workflow_id: input.workflowId } : {}),
      ...(input.regenerate ? { regenerate: true } : {}),
      ...(input.regenerate ? { request_key: createWorkflowRequestKey() } : {}),
      ...(input.expectedRevision ? { expected_revision: input.expectedRevision } : {}),
      ...(input.templateId ? { template_id: input.templateId } : {}),
    }),
    signal,
  });
}
