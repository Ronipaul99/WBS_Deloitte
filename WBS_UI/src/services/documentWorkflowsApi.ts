import { ApiError, apiRequest } from './apiClient';
import type {
  ResolveDocumentResponse, UploadWorkflowResponse, WorkflowState,
} from './workflowTypes';

interface WorkflowCapabilities {
  resume_enabled: boolean;
  reuse_enabled: boolean;
  max_upload_bytes: number;
}

export async function workflowCapabilities(tenantId: string, signal?: AbortSignal): Promise<WorkflowCapabilities> {
  try {
    return await apiRequest(`/tenants/${tenantId}/document-workflows/capabilities`, { signal });
  } catch (error) {
    // A pre-feature backend has no capability endpoint. Other errors must not bypass the gate.
    if (error instanceof ApiError && error.status === 404) {
      return { resume_enabled: false, reuse_enabled: false, max_upload_bytes: 25 * 1024 * 1024 };
    }
    throw error;
  }
}

export function resolveDocument(tenantId: string, projectId: string, sha256: string, size: number,
  signal?: AbortSignal): Promise<ResolveDocumentResponse> {
  return apiRequest(`/tenants/${tenantId}/document-workflows/resolve`, {
    method: 'POST', body: JSON.stringify({ sha256, size_bytes: size, selected_project_id: projectId }), signal,
  });
}

export function uploadWorkflow(tenantId: string, projectId: string, file: File, key: string,
  sha256: string | null, signal?: AbortSignal): Promise<UploadWorkflowResponse> {
  const body = new FormData();
  body.set('file', file);
  body.set('project_id', projectId);
  if (sha256) body.set('sha256', sha256);
  return apiRequest(`/tenants/${tenantId}/document-workflows/uploads`, {
    method: 'POST', body, headers: { 'Idempotency-Key': key }, signal,
  });
}

export function uploadStatus(tenantId: string, handle: string, signal?: AbortSignal): Promise<UploadWorkflowResponse> {
  return apiRequest(`/tenants/${tenantId}/document-workflows/uploads/${handle}`, { signal });
}

export async function getWorkflow(tenantId: string, workflowId: string, signal?: AbortSignal): Promise<WorkflowState> {
  const state = await apiRequest<WorkflowState>(`/tenants/${tenantId}/document-workflows/${workflowId}`, { signal });
  const screens = ['checkpoint', 'doc_processing', 'doc_summary', 'analyzing', 'results', 'validation'];
  if (state.workflow_id !== workflowId || state.document.tenant_id !== tenantId
      || state.project.tenant_id !== tenantId || state.project.id !== state.project_id
      || state.document.id !== state.document_id || state.document.project_id !== state.project_id
      || (state.template && state.template.tenant_id !== tenantId) || !screens.includes(state.resume_screen)) {
    throw new Error('The saved workflow no longer matches this workspace.');
  }
  return state;
}

export function configureWorkflowTemplate(tenantId: string, state: WorkflowState, templateId: string | null,
  fork: boolean, signal?: AbortSignal): Promise<WorkflowState> {
  return apiRequest(`/tenants/${tenantId}/document-workflows/${state.workflow_id}/${fork ? 'fork' : 'template'}`, {
    method: fork ? 'POST' : 'PATCH',
    body: JSON.stringify({ template_id: templateId, expected_revision: state.checkpoint_revision }), signal,
  });
}

export function projectWorkflows(tenantId: string, projectId: string, signal?: AbortSignal): Promise<WorkflowState[]> {
  return apiRequest(`/tenants/${tenantId}/document-workflows/projects/${projectId}`, { signal });
}
