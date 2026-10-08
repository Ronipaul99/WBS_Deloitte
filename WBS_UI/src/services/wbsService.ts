import rawJobConfig from '../data/mockJobStatus.json';
import rawWbsResult from '../data/mockWbsResult.json';
import rawValidationResult from '../data/mockWbsValidation.json';

/* ==========================================================================
   Screen 2: Analyzing Project Pipeline Types
   ========================================================================== */

export type StepStatus = 'COMPLETED' | 'IN_PROGRESS' | 'PENDING' | 'FAILED';

export interface AnalysisStep {
  id: string;
  stepCode: string;
  title: string;
  description: string;
  status: StepStatus;
}

export interface SideCardConfig {
  title: string;
  description: string;
}

export interface JobStatusResponse {
  jobId: string;
  overallStatus: 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  title: string;
  subtitle: string;
  sideCard: SideCardConfig;
  steps: AnalysisStep[];
  errorMessage?: string | null;
}

interface RawConfig {
  jobId: string;
  title: string;
  subtitle: string;
  sideCard: SideCardConfig;
  steps: Array<{
    id: string;
    stepCode: string;
    title: string;
    description: string;
  }>;
}

/* ==========================================================================
   Screen 3: WBS Hierarchy & Scope Coverage Types
   ========================================================================== */

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
  evidence?: {
    text: string;
    document: string;
    section: string;
  };
  children?: WbsNode[];
}

export interface ScopeCategory {
  category: string;
  coverage: number;
  total: number;
}

export interface ScopeCoverageData {
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
  projectId: string;
  projectName: string;
  version: string;
  generatedDate: string;
  breadcrumbs: string[];
  scopeCoverage: ScopeCoverageData;
  aiInsights: AiInsightItem[];
  unmappedRequirements: UnmappedRequirement[];
  wbsTree: WbsNode[];
}

/* ==========================================================================
   Screen 4: WBS Validation Payload Types
   ========================================================================== */

export interface ValidationSummaryCards {
  wbsItems: {
    count: number;
    phasesCount: number;
    workPackagesCount: number;
  };
  scopeCoverage: {
    percentage: number;
    mapped: number;
    total: number;
  };
  itemsAdded: {
    count: number;
    subtext: string;
  };
  potentialGaps: {
    count: number;
    subtext: string;
  };
}

export interface ValidationCheckItem {
  id: string;
  title: string;
  description: string;
  status: 'PASSED' | 'WARNING' | 'FAILED';
  actionLabel?: string;
}

export interface UnmappedTableItem {
  reference: string;
  summary: string;
}

export interface WbsValidationPayload {
  jobId: string;
  projectName: string;
  version: string;
  breadcrumbs: string[];
  summaryCards: ValidationSummaryCards;
  validationChecks: ValidationCheckItem[];
  unmappedRequirements: UnmappedTableItem[];
  aiRecommendations: string[];
}

/* ==========================================================================
   Simulation State & Service Functions
   ========================================================================== */

const jobConfig = rawJobConfig as unknown as RawConfig;
let currentStepPointer = 0;

/**
 * Screen 1 -> Screen 2:
 * Initiates the generation job when the user clicks 'Generate Draft WBS'.
 * SWAP POINT: When backend middleware is deployed:
 *   const formData = new FormData();
 *   if (projectFile) formData.append('projectDocument', projectFile);
 *   if (templateFile) formData.append('referenceTemplate', templateFile);
 *   const res = await fetch('/api/v1/jobs/generate', { method: 'POST', body: formData });
 *   return await res.json();
 */
export async function createWbsGenerationJob(
  _projectFile?: File,
  _templateFile?: File
): Promise<{ jobId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 300));
  currentStepPointer = 0; // reset pointer for fresh simulation cycle
  return { jobId: jobConfig.jobId || `job_wbs_${Date.now().toString().slice(-6)}` };
}

/**
 * Screen 2:
 * Fetches status for the active analysis pipeline.
 * Steps advance across consecutive poll cycles until completed.
 * SWAP POINT: When backend middleware is deployed:
 *   const res = await fetch(`/api/v1/jobs/${jobId}/status`);
 *   return (await res.json()) as JobStatusResponse;
 */
export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  // Simulate network latency
  await new Promise((resolve) => setTimeout(resolve, 200));

  const steps: AnalysisStep[] = jobConfig.steps.map((step, index: number) => {
    let status: StepStatus = 'PENDING';
    if (index < currentStepPointer) {
      status = 'COMPLETED';
    } else if (index === currentStepPointer) {
      status = 'IN_PROGRESS';
    }
    return {
      id: step.id,
      stepCode: step.stepCode,
      title: step.title,
      description: step.description,
      status,
    };
  });

  const isCompleted = currentStepPointer >= jobConfig.steps.length;
  if (!isCompleted) {
    currentStepPointer++;
  }

  return {
    jobId: jobId || jobConfig.jobId,
    overallStatus: isCompleted ? 'COMPLETED' : 'IN_PROGRESS',
    title: jobConfig.title,
    subtitle: jobConfig.subtitle,
    sideCard: jobConfig.sideCard,
    steps,
    errorMessage: null,
  };
}

/**
 * Screen 2:
 * Resets the in-memory simulation step pointer.
 */
export function resetJobStatusSimulation(): void {
  currentStepPointer = 0;
}

// Formats present date into standard enterprise representation (e.g., "8 Oct 2026")
function getCurrentFormattedDate(): string {
  const now = new Date();
  return now.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * Screen 3:
 * Fetches WBS tree results, AI insights, and scope coverage.
 * SWAP POINT: When backend middleware is deployed:
 *   const res = await fetch(`/api/v1/jobs/${jobId}/results`);
 *   return (await res.json()) as WbsResultPayload;
 */
export async function getWbsResult(jobId: string): Promise<WbsResultPayload> {
  await new Promise((resolve) => setTimeout(resolve, 200));
  const payload = rawWbsResult as unknown as WbsResultPayload;
  return {
    ...payload,
    projectId: jobId || payload.projectId,
    generatedDate: getCurrentFormattedDate(),
  };
}

/**
 * Screen 3:
 * Persists user edits, structural moves, and scope additions to the backend.
 * SWAP POINT: When backend middleware is deployed:
 *   const res = await fetch(`/api/v1/jobs/${jobId}/wbs`, {
 *     method: 'PUT',
 *     headers: { 'Content-Type': 'application/json' },
 *     body: JSON.stringify({ wbsTree }),
 *   });
 *   return (await res.json());
 */
export async function updateWbsTree(
  _jobId: string,
  _wbsTree: WbsNode[]
): Promise<{ success: boolean; updatedAt: string }> {
  await new Promise((resolve) => setTimeout(resolve, 350));
  return {
    success: true,
    updatedAt: new Date().toISOString(),
  };
}

/**
 * Screen 4:
 * Fetches validation analysis, audit rule checks, and scope gap reports.
 * SWAP POINT: When backend middleware is deployed:
 *   const res = await fetch(`/api/v1/jobs/${jobId}/validation`);
 *   return (await res.json()) as WbsValidationPayload;
 */
export async function getWbsValidation(jobId: string): Promise<WbsValidationPayload> {
  await new Promise((resolve) => setTimeout(resolve, 200));
  const payload = rawValidationResult as unknown as WbsValidationPayload;
  return {
    ...payload,
    jobId: jobId || payload.jobId,
  };
}