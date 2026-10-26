import { apiRequest } from './apiClient';
import type { ScopeCoverageData, WbsNode, WbsVersionResponse } from './workflowTypes';

export function getLatestWbs(
  tenantId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<WbsVersionResponse> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/wbs/latest`, { signal });
}

export function listWbsVersions(
  tenantId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<WbsVersionResponse[]> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/wbs/versions`, { signal });
}

export function getWbsVersion(
  tenantId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<WbsVersionResponse> {
  return apiRequest(`/tenants/${tenantId}/wbs/${versionId}`, { signal });
}

export function updateWbs(
  tenantId: string,
  versionId: string,
  tree: WbsNode[],
  scopeCoverage?: ScopeCoverageData,
  signal?: AbortSignal,
): Promise<WbsVersionResponse> {
  return apiRequest(`/tenants/${tenantId}/wbs/${versionId}`, {
    method: 'PUT',
    body: JSON.stringify({
      tree,
      ...(scopeCoverage ? { scope_coverage: scopeCoverage } : {}),
    }),
    signal,
  });
}
