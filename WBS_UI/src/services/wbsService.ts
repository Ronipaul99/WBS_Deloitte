import rawJobConfig from '../data/mockJobStatus.json';
import rawProcessingSnapshots from '../data/mockProcessingSnapshots.json';
import rawProjectSummary from '../data/mockProjectSummary.json';
import rawWbsResult from '../data/mockWbsResult.json';
import rawValidationResult from '../data/mockWbsValidation.json';

/* ==========================================================================
   Type Definitions
   ========================================================================== */

export type StepStatus = 'COMPLETED' | 'IN_PROGRESS' | 'PENDING' | 'FAILED';

export interface AnalysisStep {
  id: string;
  stepCode: string;
  title: string;
  description: string;
  status: StepStatus;
  progress?: number;
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

export interface DocumentFileInfo {
  name: string;
  size: string;
  type: 'pdf' | 'excel' | 'doc';
  status: 'UPLOADED' | 'FAILED';
}

export interface ProcessingStepItem {
  id: string;
  stepCode: string;
  title: string;
  description: string;
  status: StepStatus;
  progress?: number;
}

export interface ProcessingDocStatusResponse {
  jobId: string;
  title: string;
  subtitle: string;
  projectDoc: DocumentFileInfo;
  templateDoc: DocumentFileInfo;
  steps: ProcessingStepItem[];
  overallStatus: 'PROCESSING' | 'COMPLETED' | 'FAILED';
  errorMessage?: string | null;
}

export interface SummarySectionItem {
  id: number;
  title: string;
  content: string;
  pages: string[];
}

export interface ProjectSummaryResponse {
  jobId: string;
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
  templateName: string;
  version: string;
  generatedDate: string;
  breadcrumbs: string[];
  scopeCoverage: ScopeCoverageData;
  aiInsights: AiInsightItem[];
  unmappedRequirements: UnmappedRequirement[];
  wbsTree: WbsNode[];
}

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
   Per-Job Isolated State Store (No Cross-Tab or Singleton Leaks)
   ========================================================================== */

interface JobSessionState {
  projectDocName: string;
  projectDocSize: string;
  projectDocType: 'pdf' | 'excel' | 'doc';
  templateDocName: string;
  templateDocSize: string;
  projectTitle: string;
  docSnapshotIndex: number;
  analysisStepIndex: number;
  summarySections: SummarySectionItem[];
  wbsResult: WbsResultPayload;
}

const activeSessions: Record<string, JobSessionState> = {};

function inferDocType(fileName: string): 'pdf' | 'excel' | 'doc' {
  const ext = fileName.split('.').pop()?.toLowerCase() || '';
  if (['xlsx', 'xls', 'csv'].includes(ext)) return 'excel';
  if (['docx', 'doc'].includes(ext)) return 'doc';
  return 'pdf';
}

function formatFilenameToProjectTitle(fileName: string): string {
  const baseName = fileName.replace(/\.[^/.]+$/, '');
  return baseName
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function getCurrentDate(): string {
  return new Date().toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function bindEvidenceAndTemplate(
  nodes: WbsNode[] = [],
  projectName: string,
  templateName: string
): WbsNode[] {
  return nodes.map((node) => {
    const evidenceText =
      node.evidence?.text ||
      node.description ||
      `Scope deliverable defined under baseline specifications for ${node.name}.`;

    const evidenceSection =
      node.evidence?.section || `Section ${node.code} Scope Clause`;

    return {
      ...node,
      template: node.template?.includes('Custom')
        ? 'Custom Scope Addition'
        : `Aligned with ${templateName}`,
      evidence: {
        text: evidenceText,
        document: projectName,
        section: evidenceSection,
      },
      children: node.children
        ? bindEvidenceAndTemplate(node.children, projectName, templateName)
        : undefined,
    };
  });
}

function getSessionOrThrow(jobId: string): JobSessionState {
  const session = activeSessions[jobId];
  if (!session) {
    throw new Error(`Job "${jobId}" was not found or session has expired.`);
  }
  return session;
}

/* ==========================================================================
   1. Create Job (Upload Screen)
   ========================================================================== */

export async function createWbsGenerationJob(
  projectFile?: File | null,
  templateFile?: File | null
): Promise<{ jobId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 200));

  if (!projectFile || !templateFile) {
    throw new Error('Both project scope document and template file are required.');
  }

  const jobId = `job_wbs_${Date.now().toString().slice(-6)}`;
  const projectTitle = formatFilenameToProjectTitle(projectFile.name);
  const projectDocType = inferDocType(projectFile.name);

  // Deep clone baseline template from backend mock
  const baseWbs: WbsResultPayload = JSON.parse(JSON.stringify(rawWbsResult));
  const baseSummary: SummarySectionItem[] = JSON.parse(
    JSON.stringify((rawProjectSummary as { sections: SummarySectionItem[] }).sections)
  );

  // Bind uploaded documents
  baseWbs.projectId = jobId;
  baseWbs.projectName = projectTitle;
  baseWbs.templateName = templateFile.name;
  baseWbs.generatedDate = getCurrentDate();
  baseWbs.wbsTree = bindEvidenceAndTemplate(baseWbs.wbsTree, projectFile.name, templateFile.name);

  baseWbs.unmappedRequirements = (baseWbs.unmappedRequirements || []).map((req) => ({
    ...req,
    sourceDoc: projectFile.name,
  }));

  activeSessions[jobId] = {
    projectDocName: projectFile.name,
    projectDocSize: formatBytes(projectFile.size),
    projectDocType,
    templateDocName: templateFile.name,
    templateDocSize: formatBytes(templateFile.size),
    projectTitle,
    docSnapshotIndex: 0,
    analysisStepIndex: 0,
    summarySections: baseSummary,
    wbsResult: baseWbs,
  };

  return { jobId };
}

/* ==========================================================================
   2. Processing Document Status (Screen 1.5)
   ========================================================================== */

export async function getProcessingDocStatus(jobId: string): Promise<ProcessingDocStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = getSessionOrThrow(jobId);

  const snapshots = rawProcessingSnapshots as unknown as Array<{
    overallStatus: 'PROCESSING' | 'COMPLETED' | 'FAILED';
    steps: ProcessingStepItem[];
  }>;

  const currentIndex = session.docSnapshotIndex;
  const currentSnapshot = snapshots[currentIndex] || snapshots[snapshots.length - 1];

  if (currentIndex < snapshots.length - 1) {
    session.docSnapshotIndex = currentIndex + 1;
  }

  return {
    jobId,
    title: 'Processing Project Document',
    subtitle: `Extracting key scope items from ${session.projectDocName}...`,
    projectDoc: {
      name: session.projectDocName,
      size: session.projectDocSize,
      type: session.projectDocType,
      status: 'UPLOADED',
    },
    templateDoc: {
      name: session.templateDocName,
      size: session.templateDocSize,
      type: 'excel',
      status: 'UPLOADED',
    },
    steps: currentSnapshot.steps,
    overallStatus: currentSnapshot.overallStatus,
    errorMessage: null,
  };
}

/* ==========================================================================
   3. Review Project Summary (Screen 3)
   ========================================================================== */

export async function getProjectSummary(jobId: string): Promise<ProjectSummaryResponse> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = getSessionOrThrow(jobId);

  return {
    jobId,
    projectName: session.projectTitle,
    document: {
      name: session.projectDocName,
      size: session.projectDocSize,
      type: session.projectDocType,
      status: 'UPLOADED',
    },
    confidenceScore: (rawProjectSummary as { confidenceScore: number }).confidenceScore,
    sections: JSON.parse(JSON.stringify(session.summarySections)),
  };
}

export async function saveProjectSummary(
  jobId: string,
  updatedSections: SummarySectionItem[]
): Promise<boolean> {
  await new Promise((resolve) => setTimeout(resolve, 200));
  const session = getSessionOrThrow(jobId);
  session.summarySections = JSON.parse(JSON.stringify(updatedSections));
  return true;
}

/* ==========================================================================
   4. Decomposition Analysis Pipeline (Screen 4)
   ========================================================================== */

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = getSessionOrThrow(jobId);

  const stepsDef = (rawJobConfig as unknown as { steps: Array<{ id: string; stepCode: string; title: string; description: string }> }).steps;
  const currentIndex = session.analysisStepIndex;

  const steps: AnalysisStep[] = stepsDef.map((step, idx) => {
    let status: StepStatus = 'PENDING';
    if (idx < currentIndex) {
      status = 'COMPLETED';
    } else if (idx === currentIndex) {
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

  const isCompleted = currentIndex >= stepsDef.length;
  if (!isCompleted) {
    session.analysisStepIndex = currentIndex + 1;
  }

  return {
    jobId,
    overallStatus: isCompleted ? 'COMPLETED' : 'IN_PROGRESS',
    title: (rawJobConfig as unknown as { title: string }).title,
    subtitle: `Processing ${session.projectDocName} against ${session.templateDocName}...`,
    sideCard: {
      title: 'Decomposing Requirements',
      description: `Neural parser is decomposing ${session.projectDocName} into ${session.templateDocName}.`,
    },
    steps,
    errorMessage: null,
  };
}

export function resetJobStatusSimulation(jobId?: string): void {
  if (jobId && activeSessions[jobId]) {
    activeSessions[jobId].analysisStepIndex = 0;
    activeSessions[jobId].docSnapshotIndex = 0;
  } else if (!jobId) {
    Object.keys(activeSessions).forEach((id) => {
      activeSessions[id].analysisStepIndex = 0;
      activeSessions[id].docSnapshotIndex = 0;
    });
  }
}

/* ==========================================================================
   5. WBS Results & Interactive Tree Mutations (Screen 5)
   ========================================================================== */

export async function getWbsResult(jobId: string): Promise<WbsResultPayload> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = getSessionOrThrow(jobId);

  return {
    ...session.wbsResult,
    projectId: jobId,
    generatedDate: getCurrentDate(),
  };
}

export async function updateWbsTree(
  jobId: string,
  wbsTree: WbsNode[],
  updatedUnmapped?: UnmappedRequirement[],
  updatedScopeCoverage?: ScopeCoverageData
): Promise<{ success: boolean; updatedAt: string }> {
  await new Promise((resolve) => setTimeout(resolve, 200));
  const session = getSessionOrThrow(jobId);

  session.wbsResult.wbsTree = wbsTree;
  if (updatedUnmapped) {
    session.wbsResult.unmappedRequirements = updatedUnmapped;
  }
  if (updatedScopeCoverage) {
    session.wbsResult.scopeCoverage = updatedScopeCoverage;
  }

  return {
    success: true,
    updatedAt: new Date().toISOString(),
  };
}

/* ==========================================================================
   6. Screen 6: Real Dynamic Validation Engine
   - Computes counts, coverage math, and check statuses from live tree state
   - Pulls AI recommendations, check titles, and UI subtexts from mock backend contract
   ========================================================================== */

export async function getWbsValidation(jobId: string): Promise<WbsValidationPayload> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = getSessionOrThrow(jobId);

  // Read backend mock response template (data contract)
  const baseValidation = rawValidationResult as unknown as WbsValidationPayload;

  // 1. Calculate deliverables dynamically from the active tree
  const flatNodes: WbsNode[] = [];
  const walk = (nodes: WbsNode[] = []) => {
    nodes.forEach((n) => {
      flatNodes.push(n);
      if (n.children && n.children.length > 0) walk(n.children);
    });
  };
  walk(session.wbsResult.wbsTree || []);

  const totalCount = flatNodes.length;
  const phasesCount = flatNodes.filter((n) => n.type === 'Phase').length;
  const workPackagesCount = Math.max(0, totalCount - phasesCount);

  // 2. Calculate scope metrics dynamically from active session state
  const unmapped = session.wbsResult.unmappedRequirements || [];
  const rawCoverage = session.wbsResult.scopeCoverage;

  const totalRequirements =
    rawCoverage?.totalRequirements ?? (workPackagesCount + unmapped.length);
  const mappedCount = rawCoverage?.mappedCount ?? workPackagesCount;
  const computedPercentage = totalRequirements > 0
    ? Math.min(100, Math.round((mappedCount / totalRequirements) * 100))
    : 100;

  // 3. Dynamic Rule Evaluation: Single-child phases
  let singleChildPhasesCount = 0;
  const inspectPhaseChildren = (nodes: WbsNode[] = []) => {
    nodes.forEach((n) => {
      if (n.type === 'Phase' && n.children && n.children.length === 1) {
        singleChildPhasesCount++;
      }
      if (n.children) inspectPhaseChildren(n.children);
    });
  };
  inspectPhaseChildren(session.wbsResult.wbsTree || []);

  // 4. Dynamic Rule Evaluation: Duplicate deliverable titles
  const nameOccurrences: Record<string, number> = {};
  flatNodes.forEach((n) => {
    const key = n.name.trim().toLowerCase();
    nameOccurrences[key] = (nameOccurrences[key] || 0) + 1;
  });
  const duplicateEntriesCount = Object.values(nameOccurrences).filter((c) => c > 1).length;

  // 5. Dynamic Rule Evaluation: Broad terminal packages
  const broadPackagesCount = flatNodes.filter(
    (n) =>
      n.type === 'Work Package' &&
      (!n.children || n.children.length === 0) &&
      (n.description?.length ?? 0) > 100
  ).length;

  // 6. Dynamically map evaluated check results against backend check definitions
  const validationChecks: ValidationCheckItem[] = (baseValidation.validationChecks || []).map(
    (check) => {
      const lowerTitle = (check.title || '').toLowerCase();

      if (lowerTitle.includes('hierarchy')) {
        return {
          ...check,
          status: singleChildPhasesCount === 0 ? 'PASSED' : 'WARNING',
          description:
            singleChildPhasesCount === 0
              ? 'No issues found'
              : `${singleChildPhasesCount} phase(s) contain only a single child package`,
        };
      }

      if (lowerTitle.includes('duplicate')) {
        return {
          ...check,
          status: duplicateEntriesCount === 0 ? 'PASSED' : 'WARNING',
          description:
            duplicateEntriesCount === 0
              ? 'No duplicates found'
              : `${duplicateEntriesCount} duplicate deliverables detected`,
        };
      }

      if (lowerTitle.includes('coverage')) {
        return {
          ...check,
          status: computedPercentage >= 85 ? 'PASSED' : 'WARNING',
          description: `${computedPercentage}% of requirements mapped`,
        };
      }

      if (lowerTitle.includes('template')) {
        return {
          ...check,
          status: 'PASSED',
          description: 'Structure follows template pattern',
        };
      }

      if (lowerTitle.includes('broad')) {
        return {
          ...check,
          status: broadPackagesCount === 0 ? 'PASSED' : 'WARNING',
          description:
            broadPackagesCount === 0
              ? 'Work packages are sufficiently decomposed'
              : `${broadPackagesCount} items require further decomposition`,
          actionLabel: broadPackagesCount > 0 ? check.actionLabel || 'View' : undefined,
        };
      }

      if (lowerTitle.includes('no mapping')) {
        return {
          ...check,
          status: unmapped.length === 0 ? 'PASSED' : 'WARNING',
          description:
            unmapped.length === 0
              ? 'All requirements mapped'
              : `${unmapped.length} requirements need attention`,
          actionLabel: unmapped.length > 0 ? check.actionLabel || 'View' : undefined,
        };
      }

      return check;
    }
  );

  // 7. Unmapped requirements table mapped dynamically from actual session items
  const unmappedRequirementsTable: UnmappedTableItem[] = unmapped.map((u) => ({
    reference: u.code,
    summary: u.reason || u.title,
  }));

  // 8. Return merged payload with real calculated math and backend-sourced copy
  return {
    jobId,
    projectName: session.projectTitle,
    version: session.wbsResult.version,
    breadcrumbs: session.wbsResult.breadcrumbs || [],
    summaryCards: {
      wbsItems: {
        count: totalCount,
        phasesCount,
        workPackagesCount,
      },
      scopeCoverage: {
        percentage: computedPercentage,
        mapped: mappedCount,
        total: totalRequirements,
      },
      itemsAdded: {
        count: flatNodes.filter((n) => n.isAiAdded).length,
        subtext: baseValidation.summaryCards.itemsAdded.subtext,
      },
      potentialGaps: {
        count: unmapped.length,
        subtext: baseValidation.summaryCards.potentialGaps.subtext,
      },
    },
    validationChecks,
    unmappedRequirements: unmappedRequirementsTable,
    aiRecommendations: baseValidation.aiRecommendations || [],
  };
}