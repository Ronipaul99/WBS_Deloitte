import { apiRequest } from './apiClient';
import type { IngestionStatusResponse, JobResponse } from './workflowTypes';

export function startIngestion(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/ingestions`, {
    method: 'POST',
    signal,
  });
}

export function getCurrentIngestion(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<IngestionStatusResponse> {
  return apiRequest(
    `/tenants/${tenantId}/documents/${documentId}/ingestions/current`,
    { signal },
  );
}
