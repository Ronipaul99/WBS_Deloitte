import { apiDownload, apiRequest } from './apiClient';
import type { ExportFormat, ExportResponse } from './workflowTypes';

const CONTENT_TYPES: Record<ExportFormat, string[]> = {
  json: ['application/json'],
  csv: ['text/csv', 'application/csv', 'application/vnd.ms-excel'],
  p6_xml: ['application/xml', 'text/xml'],
};

export function startExport(
  tenantId: string,
  versionId: string,
  format: ExportFormat,
  signal?: AbortSignal,
): Promise<ExportResponse> {
  return apiRequest(`/tenants/${tenantId}/wbs/${versionId}/exports`, {
    method: 'POST',
    body: JSON.stringify({ format }),
    signal,
  });
}

export function getExport(
  tenantId: string,
  exportId: string,
  signal?: AbortSignal,
): Promise<ExportResponse> {
  return apiRequest(`/tenants/${tenantId}/exports/${exportId}`, { signal });
}

export function downloadExport(
  downloadUrl: string,
  format: ExportFormat,
  fileName: string,
  signal?: AbortSignal,
): Promise<{ blob: Blob; fileName: string }> {
  return apiDownload(downloadUrl, CONTENT_TYPES[format], { signal }, true, fileName);
}
