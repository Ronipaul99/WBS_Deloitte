import { apiRequest } from './apiClient';
import type { ExternalSummaryStatus, ExternalSummarySubmission, RequirementRecord, SummaryResponse, SummarySubmissionResponse, StructuredSummaryResponse, StructuredSummaryPatch } from './workflowTypes';

export async function startSummary(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
  workflowId?: string,
): Promise<SummarySubmissionResponse> {
  const value = await apiRequest<SummarySubmissionResponse>(`/tenants/${tenantId}/documents/${documentId}/summary${workflowId ? `?workflow_id=${workflowId}` : ''}`, {
    method: 'POST',
    signal,
  });
  if (!value || typeof value !== 'object') throw new Error('Unsupported summary submission response.');
  if ('execution_backend' in value) {
    if (!isExternalSubmission(value) || !uuid.test(value.request_id) || value.document_id !== documentId
      || (value.job_id !== null && !uuid.test(value.job_id)) || value.job_type !== 'DOCUMENT_SUMMERIZATION'
      || !['QUEUED', 'UNAVAILABLE'].includes(value.status) || !text(value.submission_state, 24)
      || value.result_state !== 'NOT_READY' || value.summary_id !== null) {
      throw new Error('Unsupported summary submission response.');
    }
  } else if (value.tenant_id !== tenantId || value.job_type !== 'DOCUMENT_SUMMARY' || !uuid.test(value.id)) {
    throw new Error('Unsupported summary submission response.');
  }
  return value;
}

export function isExternalSubmission(value: SummarySubmissionResponse): value is ExternalSummarySubmission {
  return 'execution_backend' in value && value.execution_backend === 'external_summary';
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const text = (value: unknown, limit: number): value is string =>
  typeof value === 'string' && value.length <= limit
    && !Array.from(value).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127);
const nullableText = (value: unknown, limit: number) => value === null || text(value, limit);

export function validateSummaryStatus(value: ExternalSummaryStatus, documentId: string,
  workflowId: string, requestId: string, expectedJobId?: string | null): ExternalSummaryStatus {
  if (!value || value.execution_backend !== 'external_summary'
    || value.document_id !== documentId || value.workflow_id !== workflowId || value.request_id !== requestId
    || !uuid.test(requestId) || value.job_type !== 'DOCUMENT_SUMMERIZATION'
    || (value.job_id !== null && (typeof value.job_id !== 'string' || !uuid.test(value.job_id)))
    || (expectedJobId && value.job_id !== expectedJobId)
    || !['PENDING', 'WAITING_FOR_JOB', 'VERIFIED', 'UNAVAILABLE', 'STALE'].includes(value.binding_state)
    || !['QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED', 'UNAVAILABLE'].includes(value.status)
    || !['NOT_READY', 'IMPORT_PENDING', 'IMPORTED', 'INVALID', 'STALE'].includes(value.result_state)
    || !Number.isInteger(value.progress) || value.progress < 0 || value.progress > 100
    || !Number.isSafeInteger(value.attempt_count) || value.attempt_count < 0
    || !text(value.submission_state, 24) || !nullableText(value.provider_status, 24)
    || (value.provider_status !== null && !['RUNNING', 'QUEUED', 'COMPLETED', 'completed', 'FAILED', 'CANCELLED'].includes(value.provider_status))
    || !nullableText(value.current_step, 120) || !nullableText(value.error_code, 80)
    || !nullableText(value.error_message, 500) || !text(value.updated_at, 64) || !Number.isFinite(Date.parse(value.updated_at))
    || (value.result_state === 'IMPORTED'
      ? (!value.summary_id || !uuid.test(value.summary_id) || !Number.isSafeInteger(value.summary_revision) || (value.summary_revision ?? 0) < 1
        || value.binding_state !== 'VERIFIED' || !value.job_id || !['COMPLETED', 'completed'].includes(value.provider_status ?? ''))
      : value.summary_id !== null || value.summary_revision !== null) || value.can_retry !== false || value.can_cancel !== false
    || (value.binding_state === 'VERIFIED' && value.job_id === null)
    || (['IMPORT_PENDING', 'IMPORTED'].includes(value.result_state) && (value.status !== 'COMPLETED' || value.progress !== 100))
    || (value.status === 'COMPLETED' && (value.progress !== 100 || !['IMPORT_PENDING', 'IMPORTED'].includes(value.result_state)))) {
    throw new Error('Summary status does not match the saved request or supported metadata contract.');
  }
  return value;
}

export async function getSummaryRequestStatus(tenantId: string, documentId: string, requestId: string,
  workflowId: string, signal?: AbortSignal, expectedJobId?: string | null): Promise<ExternalSummaryStatus> {
  if (![tenantId, documentId, requestId, workflowId].every((id) => uuid.test(id))) {
    throw new Error('The saved summary request identity is unavailable.');
  }
  const value = await apiRequest<ExternalSummaryStatus>(
    `/tenants/${tenantId}/documents/${documentId}/summary/requests/${requestId}?workflow_id=${workflowId}`, { signal },
  );
  return validateSummaryStatus(value, documentId, workflowId, requestId, expectedJobId);
}

export async function getSummary(
  tenantId: string,
  documentId: string,
  signal?: AbortSignal,
): Promise<SummaryResponse> {
  const value = await apiRequest<SummaryResponse>(`/tenants/${tenantId}/documents/${documentId}/summary`, { signal });
  return validateSummary(value, tenantId, documentId);
}

export async function updateSummary(
  tenantId: string,
  documentId: string,
  payload: StructuredSummaryPatch | {
    summary_text: string;
    key_points: string[];
    requirements: RequirementRecord[];
  },
  signal?: AbortSignal,
): Promise<SummaryResponse> {
  const value = await apiRequest<SummaryResponse>(`/tenants/${tenantId}/documents/${documentId}/summary`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
    signal,
  });
  return validateSummary(value, tenantId, documentId);
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

export function isStructuredSummary(value: SummaryResponse): value is StructuredSummaryResponse {
  return value.representation === 'external-summary-v1';
}

export function assertImportedSummary(summary: SummaryResponse, status: ExternalSummaryStatus) {
  validateSummaryStatus(status, summary.document_id, status.workflow_id, status.request_id, status.job_id);
  if (!isStructuredSummary(summary) || status.result_state !== 'IMPORTED' || status.binding_state !== 'VERIFIED'
    || summary.id !== status.summary_id || summary.revision !== status.summary_revision
    || summary.document_id !== status.document_id || summary.provenance.request_id !== status.request_id
    || summary.provenance.job_id !== status.job_id) throw new Error('The imported summary does not match this saved request. Refresh saved status.');
}

export function validateSummary(value: SummaryResponse, tenantId: string, documentId: string): SummaryResponse {
  const fail = () => { throw new Error('The saved summary does not match the supported review contract.'); };
  if (!value || value.tenant_id !== tenantId || value.document_id !== documentId || !uuid.test(value.id)) return fail();
  if (value.representation && value.representation !== 'external-summary-v1') return fail();
  if (!isStructuredSummary(value)) return value;
  const stored = value.structured_summary;
  const data = stored?.generated_result?.data;
  const sections = data?.summary_sections;
  const keys = ['project_overview', 'project_scope', 'key_deliverables', 'assumptions', 'constraints', 'exclusions', 'milestones_timeline'];
  const points = (v: unknown, max: number) => typeof v === 'string' && Array.from(v).length <= max;
  const pages = (v: unknown): v is number[] => Array.isArray(v) && v.length <= 500 && new Set(v).size === v.length && v.every((n) => Number.isInteger(n) && n > 0 && n <= 100000);
  if (!Number.isSafeInteger(value.revision) || value.revision < 1 || !data || data.document_id !== documentId
    || !uuid.test(data.project_id) || !uuid.test(data.processing_run_id)
    || stored.schema_version !== 'external-summary-v1' || stored.canonical_validation !== 'exact_quotes_chunk_page_coverage'
    || stored.generated_result.status !== 'success'
    || !['generated_unreviewed', 'edited_review_required'].includes(stored.content_state)
    || stored.edit_schema_version !== 'section-edits-v1'
    || !Array.isArray(sections) || sections.length !== 7
    || new Set(sections.map((s) => s.id)).size !== 7 || new Set(sections.map((s) => s.order)).size !== 7
    || new Set(sections.map((s) => s.key)).size !== 7
    || !sections.every((s) => points(s.id, 80) && s.id.length > 0 && keys.includes(s.key)
      && Number.isInteger(s.order) && s.order >= 1 && s.order <= 7 && points(s.title, 160)
      && Number.isInteger(s.max_length) && s.max_length >= 1 && s.max_length <= 20000 && points(s.content, s.max_length)
      && ['answered', 'insufficient_evidence'].includes(s.answer_status) && typeof s.evidence_context_truncated === 'boolean'
      && points(s.source_references?.label, 300) && pages(s.source_references?.pages)
      && Array.isArray(s.evidence_citations) && s.evidence_citations.length <= 100
      && s.evidence_citations.every((c, i) => c.citation_number === i + 1 && uuid.test(c.chunk_id) && points(c.quote, 20000) && pages(c.pages)))
    || !value.provenance || !uuid.test(value.provenance.request_id) || !uuid.test(value.provenance.job_id)
    || value.provenance.processing_run_id !== data.processing_run_id
    || !Array.isArray(stored.current_sections) || stored.current_sections.length > 7
    || new Set(stored.current_sections.map((s) => s.id)).size !== stored.current_sections.length
    || !stored.current_sections.every((e) => sections.some((s) => s.id === e.id && s.key === e.key && points(e.content, s.max_length)))
    || value.capabilities?.structured_review_available !== true || value.capabilities.can_generate_wbs !== false
    || !data.document_information || (data.document_information.extraction_confidence !== null
      && (typeof data.document_information.extraction_confidence !== 'number' || !Number.isFinite(data.document_information.extraction_confidence)
        || data.document_information.extraction_confidence < 0 || data.document_information.extraction_confidence > 100))) return fail();
  return value;
}

export async function approveStructuredSummary(tenantId: string, documentId: string, expectedRevision: number, signal?: AbortSignal): Promise<SummaryResponse> {
  const value = await apiRequest<SummaryResponse>(`/tenants/${tenantId}/documents/${documentId}/summary/approve`, {
    method: 'POST', body: JSON.stringify({ format: 'external_summary_v1', expected_revision: expectedRevision }), signal,
  });
  return validateSummary(value, tenantId, documentId);
}
