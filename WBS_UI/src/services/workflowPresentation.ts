import type {
  AnalysisStep,
  DocumentFileInfo,
  DocumentResponse,
  JobResponse,
  JobStatusResponse,
  ProcessingDocStatusResponse,
  ProjectResponse,
  ProjectSummaryResponse,
  RequirementRecord,
  ScopeCoverageData,
  SummaryResponse,
  SummarySectionItem,
  TemplateResponse,
  ValidationCheckItem,
  ValidationResponse,
  WbsNode,
  WbsResultPayload,
  WbsValidationPayload,
  WbsVersionResponse,
} from './workflowTypes';

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 Bytes';
  const units = ['Bytes', 'KB', 'MB', 'GB'];
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${Number((bytes / 1024 ** unit).toFixed(1))} ${units[unit]}`;
}

function documentType(fileName: string): DocumentFileInfo['type'] {
  const extension = fileName.split('.').pop()?.toLowerCase();
  if (extension && ['xls', 'xlsx', 'csv', 'xml'].includes(extension)) return 'excel';
  if (extension && ['doc', 'docx'].includes(extension)) return 'doc';
  return 'pdf';
}

function documentInfo(document: DocumentResponse): DocumentFileInfo {
  return {
    name: document.file_name,
    size: formatBytes(document.size_bytes),
    type: documentType(document.file_name),
    status: 'UPLOADED',
  };
}

function templateInfo(template: TemplateResponse): DocumentFileInfo {
  return {
    name: template.file_name,
    size: formatBytes(template.size_bytes),
    type: 'excel',
    status: 'UPLOADED',
  };
}

function stagedSteps(
  definitions: Array<Omit<AnalysisStep, 'status' | 'progress'>>,
  progress: number,
  failed: boolean,
): AnalysisStep[] {
  const stepWidth = 100 / definitions.length;
  return definitions.map((definition, index) => {
    const start = index * stepWidth;
    const end = (index + 1) * stepWidth;
    const status = progress >= end
      ? 'COMPLETED'
      : progress >= start
        ? failed ? 'FAILED' : 'IN_PROGRESS'
        : 'PENDING';
    return {
      ...definition,
      status,
      ...(status === 'IN_PROGRESS'
        ? { progress: Math.max(1, Math.min(99, Math.round(((progress - start) / stepWidth) * 100))) }
        : {}),
    };
  });
}

export function presentSummaryJob(
  job: JobResponse,
  document: DocumentResponse,
  template: TemplateResponse | null,
): ProcessingDocStatusResponse {
  const failed = job.status === 'FAILED' || job.status === 'CANCELLED';
  return {
    jobId: job.id,
    title: 'Processing Project Document',
    subtitle: job.current_step ?? `Extracting key scope items from ${document.file_name}`,
    projectDoc: documentInfo(document),
    ...(template ? { templateDoc: templateInfo(template) } : {}),
    steps: stagedSteps([
      { id: 'upload', stepCode: 'UPLOAD', title: 'Upload verified', description: 'The project document passed server validation.' },
      { id: 'extract', stepCode: 'EXTRACT', title: 'Extract document content', description: 'Reading project scope and technical requirements.' },
      { id: 'summarize', stepCode: 'SUMMARIZE', title: 'Build project summary', description: 'Organizing extracted content for review.' },
      { id: 'ready', stepCode: 'READY', title: 'Prepare review draft', description: 'Saving the tenant-scoped summary record.' },
    ], job.progress, failed),
    overallStatus: job.status === 'COMPLETED' ? 'COMPLETED' : failed ? 'FAILED' : 'PROCESSING',
    errorMessage: job.error_message,
  };
}

export function presentGenerationJob(job: JobResponse, projectName: string): JobStatusResponse {
  const failed = job.status === 'FAILED' || job.status === 'CANCELLED';
  return {
    jobId: job.id,
    overallStatus: job.status === 'COMPLETED' ? 'COMPLETED' : failed ? 'FAILED' : 'IN_PROGRESS',
    title: 'Generating Work Breakdown Structure',
    subtitle: job.current_step ?? `Decomposing the approved scope for ${projectName}`,
    sideCard: {
      title: 'Decomposing Requirements',
      description: `The approved ${projectName} scope is being mapped into a planner-ready hierarchy.`,
    },
    steps: stagedSteps([
      { id: 'requirements', stepCode: 'READ_REQUIREMENTS', title: 'Read approved requirements', description: 'Loading the approved document summary.' },
      { id: 'hierarchy', stepCode: 'BUILD_HIERARCHY', title: 'Build WBS hierarchy', description: 'Grouping deliverables into phases and work packages.' },
      { id: 'coverage', stepCode: 'MAP_SCOPE', title: 'Map scope coverage', description: 'Checking each requirement against the generated structure.' },
      { id: 'persist', stepCode: 'SAVE_VERSION', title: 'Save draft version', description: 'Persisting the WBS version in the selected workspace.' },
    ], job.progress, failed),
    errorMessage: job.error_message,
    resultPayload: job.result_payload,
  };
}

function requirementsText(requirements: RequirementRecord[]): string {
  return requirements
    .map((requirement) => stringValue(requirement.title).trim())
    .filter(Boolean)
    .join('\n');
}

export function presentSummary(
  summary: SummaryResponse,
  project: ProjectResponse,
  document: DocumentResponse,
): ProjectSummaryResponse {
  return {
    summary,
    projectName: project.name,
    document: documentInfo(document),
    confidenceScore: 85,
    sections: [
      { id: 1, title: 'Project Overview', content: summary.summary_text, pages: [] },
      { id: 2, title: 'Key Points', content: summary.key_points.join('\n'), pages: [] },
      { id: 3, title: 'Requirements', content: requirementsText(summary.requirements), pages: [] },
    ],
  };
}

export function summaryUpdateFromSections(
  current: SummaryResponse,
  sections: SummarySectionItem[],
): { summary_text: string; key_points: string[]; requirements: RequirementRecord[] } {
  const content = (id: number) => sections.find((section) => section.id === id)?.content.trim() ?? '';
  const lines = (id: number) => content(id).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return {
    summary_text: content(1),
    key_points: lines(2),
    requirements: lines(3).map((title, index) => ({
      ...(current.requirements[index] ?? {}),
      id: current.requirements[index]?.id ?? `REQ-${String(index + 1).padStart(3, '0')}`,
      title,
    })),
  };
}

function normalizeNode(value: unknown, indexPath: string, projectName: string, templateName: string): WbsNode {
  const source = record(value);
  const children = Array.isArray(source.children)
    ? source.children.map((child, index) => normalizeNode(child, `${indexPath}.${index + 1}`, projectName, templateName))
    : [];
  const type = source.type === 'Phase' ? 'Phase' : 'Work Package';
  const code = stringValue(source.code, indexPath);
  const name = stringValue(source.name, `WBS item ${indexPath}`);
  const description = stringValue(source.description, `Generated scope item for ${name}.`);
  return {
    id: stringValue(source.id, `node-${indexPath}`),
    code,
    name,
    type,
    parent: stringValue(source.parent, type === 'Phase' ? 'Root' : ''),
    source: stringValue(source.source, projectName),
    template: stringValue(source.template, templateName),
    confidence: numberValue(source.confidence, 0),
    isAiAdded: source.isAiAdded === true,
    description,
    evidence: {
      text: stringValue(record(source.evidence).text, description),
      document: stringValue(record(source.evidence).document, projectName),
      section: stringValue(record(source.evidence).section, `WBS ${code}`),
    },
    children,
  };
}

function scopeCoverage(value: Record<string, unknown>): ScopeCoverageData {
  const totalRequirements = numberValue(value.totalRequirements, 0);
  const mappedCount = numberValue(value.mappedCount, 0);
  return {
    overallScore: numberValue(value.overallScore, totalRequirements ? Math.round(mappedCount / totalRequirements * 100) : 0),
    totalRequirements,
    mappedCount,
    gapCount: numberValue(value.gapCount, Math.max(0, totalRequirements - mappedCount)),
    categories: Array.isArray(value.categories)
      ? value.categories.map((item) => {
        const category = record(item);
        return {
          category: stringValue(category.category, 'Project scope'),
          coverage: numberValue(category.coverage, 0),
          total: numberValue(category.total, 0),
        };
      })
      : [],
  };
}

export function presentWbs(
  version: WbsVersionResponse,
  project: ProjectResponse,
  template: TemplateResponse | null,
): WbsResultPayload {
  const coverage = scopeCoverage(version.scope_coverage);
  const rawUnmapped = Array.isArray(version.scope_coverage.unmappedRequirements)
    ? version.scope_coverage.unmappedRequirements
    : [];
  return {
    versionId: version.id,
    projectId: project.id,
    projectName: project.name,
    templateName: template?.name ?? 'Generated from project scope',
    version: `Draft v${version.version_number}.0`,
    generatedDate: new Date(version.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
    breadcrumbs: ['Projects', project.name, `Version ${version.version_number}`],
    scopeCoverage: coverage,
    aiInsights: [],
    unmappedRequirements: rawUnmapped.map((value, index) => {
      const item = record(value);
      return {
        id: stringValue(item.id, `unmapped-${index + 1}`),
        code: stringValue(item.code, `REQ-${index + 1}`),
        title: stringValue(item.title, 'Unmapped requirement'),
        sourceDoc: stringValue(item.sourceDoc, project.name),
        reason: stringValue(item.reason, 'No matching WBS work package was found.'),
      };
    }),
    wbsTree: version.tree.map((node, index) => normalizeNode(node, `${index + 1}.0`, project.name, template?.name ?? 'Generated baseline')),
  };
}

function flattenNodes(nodes: WbsNode[]): WbsNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children ?? [])]);
}

const CHECK_TITLES: Record<string, string> = {
  UNIQUE_WBS_CODES: 'Unique WBS codes',
  NON_EMPTY_NAMES: 'Complete deliverable names',
};

export function presentValidation(
  validation: ValidationResponse,
  wbs: WbsResultPayload,
): WbsValidationPayload {
  const result = record(validation.result);
  const rawSummary = record(result.summary);
  const checks = Array.isArray(result.checks) ? result.checks : [];
  const nodes = flattenNodes(wbs.wbsTree);
  const phases = nodes.filter((node) => node.type === 'Phase').length;
  const mapped = wbs.scopeCoverage.mappedCount;
  const total = wbs.scopeCoverage.totalRequirements;
  const gaps = numberValue(rawSummary.duplicateCodes) + numberValue(rawSummary.blankNames);
  const validationChecks: ValidationCheckItem[] = checks.map((value, index) => {
    const check = record(value);
    const code = stringValue(check.code, `CHECK-${index + 1}`);
    const status = check.status === 'PASSED' ? 'PASSED' : check.status === 'FAILED' ? 'FAILED' : 'WARNING';
    const details = Array.isArray(check.details) ? check.details.map(String) : [];
    return {
      id: code,
      title: CHECK_TITLES[code] ?? code.replaceAll('_', ' ').toLowerCase(),
      description: details.length ? details.join(', ') : status === 'PASSED' ? 'No issues found' : 'Review required',
      status,
      ...(status !== 'PASSED' ? { actionLabel: 'Review' } : {}),
    };
  });
  return {
    validationId: validation.id,
    projectName: wbs.projectName,
    version: wbs.version,
    breadcrumbs: wbs.breadcrumbs,
    summaryCards: {
      wbsItems: { count: nodes.length, phasesCount: phases, workPackagesCount: nodes.length - phases },
      scopeCoverage: { percentage: wbs.scopeCoverage.overallScore, mapped, total },
      itemsAdded: { count: nodes.filter((node) => node.isAiAdded).length, subtext: 'AI-added scope items' },
      potentialGaps: { count: gaps, subtext: gaps ? 'Items require review' : 'No structural gaps found' },
    },
    validationChecks,
    unmappedRequirements: wbs.unmappedRequirements.map((item) => ({ reference: item.code, summary: item.title })),
    aiRecommendations: gaps
      ? ['Resolve failed validation checks before publishing or exporting the WBS.']
      : ['The WBS passed the configured structural validation checks.'],
  };
}
