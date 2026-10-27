import { apiRequest } from './apiClient';
import type { ProjectResponse } from './workflowTypes';

export function listProjects(
  tenantId: string,
  signal?: AbortSignal,
): Promise<ProjectResponse[]> {
  return apiRequest(`/tenants/${tenantId}/projects`, { signal });
}

export function createProject(
  tenantId: string,
  name: string,
  description: string | null,
  signal?: AbortSignal,
): Promise<ProjectResponse> {
  return apiRequest(`/tenants/${tenantId}/projects`, {
    method: 'POST',
    body: JSON.stringify({ name, description }),
    signal,
  });
}

export function getProject(
  tenantId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectResponse> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}`, { signal });
}
