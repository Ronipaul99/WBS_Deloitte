export type ProcessingStatus = 'QUEUED' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'CANCELLED';

export interface ProjectResponse {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  kind: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  lifecycle_status: 'ACTIVE' | 'DELETING' | 'DELETED';
  deletion_requested_at: string | null;
  deletion_completed_at: string | null;
  created_at: string;
}

export interface DocumentDeletionStatusResponse {
  document_id: string;
  job_id: string;
  status: ProcessingStatus;
  stage: 'QUEUED' | 'DELETING_OBJECTS' | 'RETRY_WAIT' | 'COMPLETED' | 'FAILED';
  progress: number;
  attempt_count: number;
  lifecycle_status: 'DELETING' | 'DELETED';
  deletion_requested_at: string;
  vectors_hidden_at: string;
  deletion_completed_at: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateResponse {
  id: string;
  tenant_id: string;
  name: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  is_active: boolean;
  created_at: string;
}

export interface JobResponse {
  id: string;
  tenant_id: string;
  project_id: string | null;
  workflow_id?: string | null;
  job_type: string;
  status: ProcessingStatus;
  progress: number;
  current_step: string | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  result_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type IngestionStage =
  | 'QUEUED'
  | 'SCANNING'
  | 'EXTRACTING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'PERSISTING'
  | 'ACTIVATING'
  | 'RETRY_WAIT'
  | 'COMPLETED'
  | 'FAILED';

export interface IngestionStatusResponse {
  job_id: string;
  processing_run_id: string;
  document_id: string;
  status: string;
  stage: string;
  progress: number;
  attempt_count: number;
  maximum_attempts: number;
  page_count: number;
  worksheet_count: number;
  block_count: number;
  chunk_count: number;
  extractor_name: string | null;
  extractor_version: string | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  embedding_model_revision: string | null;
  warning_codes: string[];
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RequirementRecord {
  id?: string;
  title?: string;
  source?: string;
  status?: string;
  [key: string]: unknown;
}

export interface SummaryResponse {
  id: string;
  tenant_id: string;
  document_id: string;
  summary_text: string;
  key_points: string[];
  requirements: RequirementRecord[];
  is_approved: boolean;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WbsVersionResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  generation_job_id: string | null;
  version_number: number;
  status: string;
  tree: Array<Record<string, unknown>>;
  scope_coverage: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ValidationResponse {
  id: string;
  tenant_id: string;
  wbs_version_id: string;
  status: ProcessingStatus;
  result: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type ExportFormat = 'json' | 'csv' | 'p6_xml';

export interface ExportResponse {
  id: string;
  tenant_id: string;
  project_id: string;
  wbs_version_id: string;
  format: ExportFormat;
  status: ProcessingStatus;
  file_name: string | null;
  download_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowSession {
  project: ProjectResponse;
  document: DocumentResponse;
  template: TemplateResponse | null;
  ingestionJobId: string | null;
  processingRunId: string | null;
  initialIngestionStatus: IngestionStatusResponse | null;
  summaryId: string | null;
  generationJobId: string | null;
  wbsVersionId: string | null;
  validationId: string | null;
  workflowId?: string;
  recovery?: WorkflowState;
}

export type WorkflowStage = 'DOCUMENT_READY' | 'INGESTING' | 'INGESTED' | 'SUMMARIZING'
  | 'SUMMARY_REVIEW' | 'SUMMARY_APPROVED' | 'GENERATING' | 'WBS_READY'
  | 'VALIDATING' | 'VALIDATED' | 'FAILED' | 'CANCELLED';

export interface WorkflowState {
  workflow_id: string;
  project_id: string;
  document_id: string;
  checkpoint_revision: number;
  stage: WorkflowStage;
  resume_screen: 'checkpoint' | 'doc_processing' | 'doc_summary' | 'analyzing' | 'results' | 'validation';
  project: ProjectResponse;
  document: DocumentResponse;
  template: TemplateResponse | null;
  processing_run_id: string | null;
  ingestion_job_id: string | null;
  summary_id: string | null;
  summary_revision: number | null;
  summary_job_id: string | null;
  generation_job_id: string | null;
  wbs_version_id: string | null;
  validation_id: string | null;
  validation_stale: boolean;
  input_compatibility: 'CURRENT' | 'CHANGED' | 'UNKNOWN';
  source_requires_processing?: boolean;
  job: JobResponse | null;
  failed_stage: 'ingestion' | 'summary' | 'generation' | 'validation' | null;
  allowed_actions: string[];
}

export interface WorkflowCandidate {
  workflow_id: string | null;
  document_id: string;
  project_id: string;
  project_name: string;
  file_name: string;
  stage: WorkflowStage;
  updated_at: string;
  requires_project_switch: boolean;
}

export interface ResolveDocumentResponse {
  disposition: 'NEW' | 'MATCH' | 'MULTIPLE_MATCHES' | 'UPLOAD_PENDING' | 'TEMPORARILY_UNAVAILABLE';
  candidates: WorkflowCandidate[];
  upload_handle: string | null;
}

export interface UploadWorkflowResponse {
  disposition: 'CREATED' | 'REUSED' | 'UPLOAD_PENDING';
  workflow: WorkflowState | null;
  upload_handle: string | null;
}

export type StepStatus = 'COMPLETED' | 'IN_PROGRESS' | 'PENDING' | 'FAILED';

export interface AnalysisStep {
  id: string;
  stepCode: string;
  title: string;
  description: string;
  status: StepStatus;
  progress?: number;
}

export interface JobStatusResponse {
  jobId: string;
  overallStatus: 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  title: string;
  subtitle: string;
  sideCard: { title: string; description: string };
  steps: AnalysisStep[];
  errorMessage?: string | null;
  resultPayload: Record<string, unknown>;
}

export interface DocumentFileInfo {
  name: string;
  size: string;
  type: 'pdf' | 'excel' | 'doc';
  status: 'UPLOADED' | 'FAILED';
}

export interface ProcessingDocStatusResponse {
  jobId: string;
  processingRunId: string;
  stage: string;
  progress: number;
  title: string;
  subtitle: string;
  sideCard: { title: string; description: string };
  projectDoc: DocumentFileInfo;
  templateDoc?: DocumentFileInfo;
  steps: AnalysisStep[];
  overallStatus: 'PROCESSING' | 'COMPLETED' | 'FAILED';
  errorCode?: string | null;
  errorMessage?: string | null;
}

export interface SummarySectionItem {
  id: number;
  title: string;
  content: string;
  pages: string[];
}

export interface ProjectSummaryResponse {
  summary: SummaryResponse;
  projectName: string;
  document: DocumentFileInfo;
  confidenceScore: number;
  sections: SummarySectionItem[];
}

export interface WbsNode {
  id: string;
  code: string;
  name: string;
  type: 'Phase' | 'Work Package';
  parent: string;
  source: string;
  template: string;
  confidence: number;
  isAiAdded?: boolean;
  description: string;
  evidence?: { text: string; document: string; section: string };
  children?: WbsNode[];
}

export interface ScopeCategory {
  category: string;
  coverage: number;
  total: number;
}

export interface ScopeCoverageData {
  [key: string]: unknown;
  overallScore: number;
  totalRequirements: number;
  mappedCount: number;
  gapCount: number;
  categories: ScopeCategory[];
}

export interface AiInsightItem {
  id: string;
  type: 'SCOPE_ADDITION' | 'RISK_WARNING' | 'OPTIMIZATION';
  title: string;
  impact: 'High' | 'Medium' | 'Low';
  description: string;
}

export interface UnmappedRequirement {
  id: string;
  code: string;
  title: string;
  sourceDoc: string;
  reason: string;
}

export interface WbsResultPayload {
  versionId: string;
  projectId: string;
  projectName: string;
  templateName: string;
  version: string;
  generatedDate: string;
  breadcrumbs: string[];
  scopeCoverage: ScopeCoverageData;
  aiInsights: AiInsightItem[];
  unmappedRequirements: UnmappedRequirement[];
  wbsTree: WbsNode[];
}

export interface ValidationCheckItem {
  id: string;
  title: string;
  description: string;
  status: 'PASSED' | 'WARNING' | 'FAILED';
  actionLabel?: string;
}

export interface WbsValidationPayload {
  validationId: string;
  projectName: string;
  version: string;
  breadcrumbs: string[];
  summaryCards: {
    wbsItems: { count: number; phasesCount: number; workPackagesCount: number };
    scopeCoverage: { percentage: number; mapped: number; total: number };
    itemsAdded: { count: number; subtext: string };
    potentialGaps: { count: number; subtext: string };
  };
  validationChecks: ValidationCheckItem[];
  unmappedRequirements: Array<{ reference: string; summary: string }>;
  aiRecommendations: string[];
}
