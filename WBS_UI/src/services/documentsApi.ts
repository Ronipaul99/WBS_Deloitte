import { apiDownload, apiRequest } from './apiClient';
import type {
  DocumentDeletionStatusResponse,
  DocumentResponse,
  JobResponse,
} from './workflowTypes';

export function readDocumentFile(tenantId: string, document: DocumentResponse, signal?: AbortSignal) {
  const base = (import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
  return apiDownload(`${base}/tenants/${tenantId}/documents/${document.id}/file`,
    ['application/pdf', 'text/plain', 'application/octet-stream'], { signal }, true, document.file_name);
}

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

export function listProjectDocuments(
  tenantId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<DocumentResponse[]> {
  return apiRequest(`/tenants/${tenantId}/projects/${projectId}/documents`, { signal });
}

export function getDocument(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<DocumentResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}`, { signal });
}

export function deleteDocument(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<JobResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}`, {
    method: 'DELETE',
    signal,
  });
}

export function getDocumentDeletion(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<DocumentDeletionStatusResponse> {
  return apiRequest(`/tenants/${tenantId}/documents/${documentId}/deletion`, { signal });
}
