import { apiRequest } from './apiClient';
import type { DocumentResponse } from './workflowTypes';

export function uploadProjectDocument(
  tenantId: string,
  projectId: string,
  file: File,
  signal?: AbortSignal,
): Promise<DocumentResponse> {
  const body = new FormData();
  body.set('file', file);
  body.set('kind', 'PROJECT');
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/documents`, {
    method: 'POST',
    body,
    signal,
  });
}
