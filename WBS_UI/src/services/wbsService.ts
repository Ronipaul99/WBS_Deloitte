import rawJobConfig from '../data/mockJobStatus.json';
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
   Stateful Pipeline & Singletons
   ========================================================================== */

const jobConfig = rawJobConfig as unknown as {
  title: string;
  subtitle: string;
  sideCard: SideCardConfig;
  steps: Array<{ id: string; stepCode: string; title: string; description: string }>;
};

const jobStepPointers: Record<string, number> = {};

let activeProjectDocName = 'Uploaded_Scope_Document.pdf';
let activeTemplateDocName = 'Domain_Baseline_Template.xlsx';
let activeProjectTitle = rawWbsResult.projectName || 'Capital Engineering Project';

let currentWbsResult: WbsResultPayload = JSON.parse(JSON.stringify(rawWbsResult));
const currentValidation: WbsValidationPayload = JSON.parse(JSON.stringify(rawValidationResult));

function formatFilenameToProjectName(fileName: string): string {
  const withoutExt = fileName.replace(/\.[^/.]+$/, '');
  return withoutExt
    .replace(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getCurrentFormattedDate(): string {
  const now = new Date();
  return now.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function rebindTreeMetadata(nodes: WbsNode[], documentName: string, templateName: string): WbsNode[] {
  return nodes.map((node) => ({
    ...node,
    template: node.template.includes('Custom') ? 'Custom Scope Addition' : `Aligned with ${templateName}`,
    evidence: node.evidence ? { ...node.evidence, document: documentName } : undefined,
    children: node.children ? rebindTreeMetadata(node.children, documentName, templateName) : undefined,
  }));
}

export async function createWbsGenerationJob(
  projectFile?: File | null,
  templateFile?: File | null
): Promise<{ jobId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 300));

  const newJobId = `job_wbs_${Date.now().toString().slice(-6)}`;
  jobStepPointers[newJobId] = 0;

  currentWbsResult = JSON.parse(JSON.stringify(rawWbsResult));

  if (projectFile) {
    activeProjectDocName = projectFile.name;
    activeProjectTitle = formatFilenameToProjectName(projectFile.name);
  } else {
    activeProjectTitle = currentWbsResult.projectName || 'Capital Project';
  }

  if (templateFile) {
    activeTemplateDocName = templateFile.name;
  }

  currentWbsResult.projectId = newJobId;
  currentWbsResult.projectName = activeProjectTitle;
  currentWbsResult.templateName = activeTemplateDocName;
  currentWbsResult.generatedDate = getCurrentFormattedDate();
  currentWbsResult.wbsTree = rebindTreeMetadata(
    currentWbsResult.wbsTree,
    activeProjectDocName,
    activeTemplateDocName
  );

  currentWbsResult.unmappedRequirements = currentWbsResult.unmappedRequirements.map((req) => ({
    ...req,
    sourceDoc: activeProjectDocName,
  }));

  return { jobId: newJobId };
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, 200));

  if (!jobId) {
    throw new Error('Valid Job ID is required to poll pipeline status.');
  }

  if (jobStepPointers[jobId] === undefined) {
    jobStepPointers[jobId] = 0;
  }

  const currentPointer = jobStepPointers[jobId];

  const steps: AnalysisStep[] = jobConfig.steps.map((step, index: number) => {
    let status: StepStatus = 'PENDING';
    if (index < currentPointer) {
      status = 'COMPLETED';
    } else if (index === currentPointer) {
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

  const isCompleted = currentPointer >= jobConfig.steps.length;
  if (!isCompleted) {
    jobStepPointers[jobId] = currentPointer + 1;
  }

  return {
    jobId,
    overallStatus: isCompleted ? 'COMPLETED' : 'IN_PROGRESS',
    title: jobConfig.title,
    subtitle: `Processing ${activeProjectDocName} against ${activeTemplateDocName}...`,
    sideCard: {
      title: 'Decomposing Requirements',
      description: `Neural parser is aligning deliverables from ${activeProjectDocName} into ${activeTemplateDocName}.`,
    },
    steps,
    errorMessage: null,
  };
}

export function resetJobStatusSimulation(jobId?: string): void {
  if (jobId) {
    jobStepPointers[jobId] = 0;
  } else {
    Object.keys(jobStepPointers).forEach((id) => {
      jobStepPointers[id] = 0;
    });
  }
}

export async function getWbsResult(jobId: string): Promise<WbsResultPayload> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  return {
    ...currentWbsResult,
    projectId: jobId || currentWbsResult.projectId,
    generatedDate: getCurrentFormattedDate(),
  };
}

export async function updateWbsTree(
  _jobId: string,
  _wbsTree: WbsNode[],
  _updatedUnmapped?: UnmappedRequirement[],
  _updatedScopeCoverage?: ScopeCoverageData
): Promise<{ success: boolean; updatedAt: string }> {
  void _jobId;
  await new Promise((resolve) => setTimeout(resolve, 200));

  currentWbsResult.wbsTree = _wbsTree;
  if (_updatedUnmapped) {
    currentWbsResult.unmappedRequirements = _updatedUnmapped;
  }
  if (_updatedScopeCoverage) {
    currentWbsResult.scopeCoverage = _updatedScopeCoverage;
  }

  return {
    success: true,
    updatedAt: new Date().toISOString(),
  };
}

export async function getWbsValidation(jobId: string): Promise<WbsValidationPayload> {
  await new Promise((resolve) => setTimeout(resolve, 150));

  const flat: WbsNode[] = [];
  const walk = (nodes: WbsNode[]) => {
    nodes.forEach((node) => {
      flat.push(node);
      if (node.children && node.children.length > 0) {
        walk(node.children);
      }
    });
  };
  walk(currentWbsResult.wbsTree);

  const phases = flat.filter((n) => n.type === 'Phase').length;
  const workPackages = flat.length - phases;
  const sc = currentWbsResult.scopeCoverage || {
    overallScore: 0,
    mappedCount: 0,
    totalRequirements: 0,
    gapCount: 0,
  };
  const itemsAdded = flat.filter((n) => n.isAiAdded).length;
  const unmapped = currentWbsResult.unmappedRequirements || [];

  const dynamicRecommendations: string[] = [];
  if (unmapped.length > 0) {
    dynamicRecommendations.push(
      `Evaluate ${unmapped.length} unmapped requirements (${unmapped.map((u) => u.code).join(', ')}) for insertion into engineering packages.`
    );
  }
  const aiAddedNodes = flat.filter((n) => n.isAiAdded);
  if (aiAddedNodes.length > 0) {
    dynamicRecommendations.push(
      `Cross-check scope addition "${aiAddedNodes[0].name}" (${aiAddedNodes[0].code}) with procurement milestones.`
    );
  }
  dynamicRecommendations.push(
    `Verify Primavera P6 activity ID syntax across all ${workPackages} terminal work packages prior to schedule baseline freeze.`
  );

  return {
    ...currentValidation,
    jobId: jobId || currentWbsResult.projectId,
    projectName: currentWbsResult.projectName,
    summaryCards: {
      wbsItems: {
        count: flat.length,
        phasesCount: phases,
        workPackagesCount: workPackages,
      },
      scopeCoverage: {
        percentage: sc.overallScore,
        mapped: sc.mappedCount,
        total: sc.totalRequirements,
      },
      itemsAdded: {
        count: itemsAdded,
        subtext: 'Not in template',
      },
      potentialGaps: {
        count: unmapped.length,
        subtext: 'Review recommended',
      },
    },
    unmappedRequirements: unmapped.map((r) => ({
      reference: `${r.code} (${activeProjectDocName})`,
      summary: `${r.title} — ${r.reason}`,
    })),
    aiRecommendations: dynamicRecommendations,
  };
}