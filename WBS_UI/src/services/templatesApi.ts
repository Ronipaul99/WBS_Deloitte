import { apiRequest } from './apiClient';
import type { TemplateResponse } from './workflowTypes';

export function uploadTemplate(
  tenantId: string,
  file: File,
  signal?: AbortSignal,
): Promise<TemplateResponse> {
  const body = new FormData();
  body.set('file', file);
  body.set('name', file.name.replace(/\.[^/.]+$/, ''));
  return apiRequest(`/tenants/${tenantId}/templates`, {
    method: 'POST',
    body,
    signal,
  });
}

export function getTemplate(
  tenantId: string,
  templateId: string,
  signal?: AbortSignal,
): Promise<TemplateResponse> {
  return apiRequest(`/tenants/${tenantId}/templates/${templateId}`, { signal });
}
