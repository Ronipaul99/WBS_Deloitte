import { apiRequest } from './apiClient';
import type { JobResponse } from './workflowTypes';

export function startGeneration(
  tenantId: string,
  projectId: string,
  input: { documentId: string; summaryId: string; templateId: string | null },
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/generations`, {
    method: 'POST',
    body: JSON.stringify({
      document_id: input.documentId,
      summary_id: input.summaryId,
      ...(input.templateId ? { template_id: input.templateId } : {}),
    }),
    signal,
  });
}
