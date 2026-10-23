import { apiRequest } from './apiClient';
import type { JobResponse, RequirementRecord, SummaryResponse } from './workflowTypes';

export function startSummary(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/summary`, {
    method: 'POST',
    signal,
  });
}

export function getSummary(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<SummaryResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/summary`, { signal });
}

export function updateSummary(
  tenantId: string,
  documentId: string,
  payload: {
    summary_text: string;
    key_points: string[];
    requirements: RequirementRecord[];
  },
  signal?: AbortSignal,
): Promise<SummaryResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/summary`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
    signal,
  });
}

export function approveSummary(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<SummaryResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/summary/approve`, {
    method: 'POST',
    signal,
  });
}
