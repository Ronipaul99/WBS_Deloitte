import { apiRequest } from './apiClient';
import type { JobResponse } from './workflowTypes';

export function getJob(
  tenantId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/jobs/${jobId}`, { signal });
}

export function cancelJob(
  tenantId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/jobs/${jobId}/cancel`, {
    method: 'POST',
    signal,
  });
}

export function retryJob(
  tenantId: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/jobs/${jobId}/retry`, {
    method: 'POST',
    signal,
  });
}
