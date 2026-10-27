import { apiRequest } from './apiClient';
import type { ValidationResponse } from './workflowTypes';

export function startValidation(
  tenantId: string,
  versionId: string,
  signal?: AbortSignal,
  rerun = false,
): Promise<ValidationResponse> {
  return apiRequest(`/tenants/${tenantId}/wbs/${versionId}/validations${rerun ? '?rerun=true' : ''}`, {
    method: 'POST',
    signal,
  });
}

export function getValidation(
  tenantId: string,
  validationId: string,
  signal?: AbortSignal,
): Promise<ValidationResponse> {
  return apiRequest(`/tenants/${tenantId}/validations/${validationId}`, { signal });
}
