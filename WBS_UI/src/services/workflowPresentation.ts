import type {
  AnalysisStep,
  DocumentFileInfo,
  DocumentResponse,
  IngestionStatusResponse,
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

const INGESTION_ERROR_MESSAGES: Record<string, string> = {
  DOCUMENT_OBJECT_MISSING: 'The uploaded document is no longer available. Upload it again to continue.',
  OBJECT_STORAGE_UNAVAILABLE: 'Document storage is temporarily unavailable. Processing will resume automatically when possible.',
  DOCUMENT_INTEGRITY_FAILED: 'The uploaded document failed its integrity check and cannot be processed.',
  MALWARE_SCANNER_UNAVAILABLE: 'The document security scanner is temporarily unavailable.',
  DOCUMENT_REJECTED_MALWARE: 'The document was rejected by the security scan.',
  UNSUPPORTED_DOCUMENT_FORMAT: 'This document format is not supported.',
  DOCUMENT_ENCRYPTED: 'Password-protected documents cannot be processed.',
  DOCUMENT_MALFORMED: 'The document structure could not be read safely.',
  DOCUMENT_EXTRACTION_LIMIT_EXCEEDED: 'The document exceeds the configured processing limits.',
  DOCUMENT_NO_EXTRACTABLE_CONTENT: 'No usable text or table content was found in the document.',
  OCR_UNAVAILABLE: 'Text recognition is temporarily unavailable.',
  OCR_FAILED: 'Text recognition could not process this document.',
  DOCUMENT_PARSER_TIMEOUT: 'Document processing took longer than the permitted time.',
  DOCUMENT_PARSER_RESOURCE_EXHAUSTED: 'The document exceeded the available processing resources.',
  DOCUMENT_EXTRACTION_FAILED: 'The document content could not be extracted safely.',
  DOCUMENT_INGESTION_SCOPE_INVALID: 'The document workflow no longer matches this project.',
  DOCUMENT_INGESTION_STATE_CONFLICT: 'This document is already being processed in another workflow.',
  DOCUMENT_INGESTION_STATE_INCONSISTENT: 'The document workflow could not be verified.',
  DOCUMENT_INGESTION_TIMEOUT: 'Document processing timed out before completion.',
  DOCUMENT_INGESTION_FAILED: 'The document could not be processed.',
  DOCUMENT_INGESTION_ATTEMPTS_EXHAUSTED: 'Document processing could not recover after several attempts.',
};

const INGESTION_STAGES = new Set([
  'QUEUED',
  'SCANNING',
  'EXTRACTING',
  'CHUNKING',
  'EMBEDDING',
  'PERSISTING',
  'ACTIVATING',
  'RETRY_WAIT',
  'COMPLETED',
  'FAILED',
]);

const INGESTION_STATUSES = new Set(['QUEUED', 'IN_PROGRESS', 'COMPLETED', 'FAILED']);

export function isSupportedIngestionState(status: string, stage: string): boolean {
  return INGESTION_STATUSES.has(status) && INGESTION_STAGES.has(stage);
}

export function ingestionErrorMessage(code: string | null): string {
  return code && INGESTION_ERROR_MESSAGES[code]
    ? INGESTION_ERROR_MESSAGES[code]
    : 'The document could not be processed. Return to the project and try another document.';
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

export function presentIngestionStatus(
  ingestion: IngestionStatusResponse,
  document: DocumentResponse,
  template: TemplateResponse | null,
  displayedProgress = ingestion.progress,
): ProcessingDocStatusResponse {
  const failed = ingestion.status === 'FAILED' || ingestion.stage === 'FAILED';
  const completed = ingestion.status === 'COMPLETED' && ingestion.stage === 'COMPLETED';
  const retryWaiting = ingestion.stage === 'RETRY_WAIT';
  const progress = Math.max(0, Math.min(100, displayedProgress));
  const ingestionDefinitions: Array<Omit<AnalysisStep, 'status' | 'progress'>> = [
    { id: 'upload', stepCode: 'UPLOAD', title: 'Upload verified', description: 'The project document passed server validation.' },
    { id: 'queue', stepCode: 'QUEUED', title: 'Queue processing', description: 'The worker has accepted the tenant-scoped document.' },
    { id: 'scan', stepCode: 'SCANNING', title: 'Security scan', description: 'Checking the complete document before it can be read.' },
    { id: 'extract', stepCode: 'EXTRACTING', title: 'Extract document content', description: 'Reading supported text, tables, and source locations.' },
    { id: 'chunk', stepCode: 'CHUNKING', title: 'Organize document sections', description: 'Normalizing and grouping content into bounded sections.' },
    { id: 'embed', stepCode: 'EMBEDDING', title: 'Build search representation', description: 'Creating the local vector representation in bounded batches.' },
    { id: 'persist', stepCode: 'PERSISTING', title: 'Persist document index', description: 'Saving validated sections to the tenant-scoped index.' },
    { id: 'activate', stepCode: 'ACTIVATING', title: 'Finalize document', description: 'Reconciling counts and activating the completed processing run.' },
  ];
  const activeStageIndex = ingestionDefinitions.findIndex(
    (definition) => definition.stepCode === ingestion.stage,
  );
  const stageSteps = ingestionDefinitions.map((definition, index): AnalysisStep => {
    let status: AnalysisStep['status'] = 'PENDING';
    if (completed) status = 'COMPLETED';
    else if (index === 0 || (activeStageIndex >= 0 && index < activeStageIndex)) status = 'COMPLETED';
    else if (activeStageIndex === index) status = 'IN_PROGRESS';
    return { ...definition, status };
  });

  if (retryWaiting) {
    stageSteps.push({
      id: 'retry-wait',
      stepCode: 'RETRY_WAIT',
      title: 'Waiting to resume',
      description: 'The service is managing a bounded automatic retry.',
      status: 'IN_PROGRESS',
    });
  } else if (failed) {
    stageSteps.push({
      id: 'failed',
      stepCode: 'FAILED',
      title: 'Processing stopped',
      description: ingestionErrorMessage(ingestion.error_code),
      status: 'FAILED',
    });
  }
  return {
    jobId: ingestion.job_id,
    processingRunId: ingestion.processing_run_id,
    stage: ingestion.stage,
    progress,
    title: completed ? 'Document processed successfully' : failed ? 'Document processing stopped' : 'Processing project document',
    subtitle: completed
      ? 'The document is ready for the next project milestone.'
      : retryWaiting
        ? 'Processing is paused while the service prepares an automatic retry.'
        : 'The secure ingestion pipeline is preparing this document for later WBS generation.',
    sideCard: completed
      ? {
          title: 'Document ready',
          description: `${ingestion.chunk_count} searchable sections are ready for the next milestone.`,
        }
      : retryWaiting
        ? {
            title: 'Waiting to resume',
            description: `Attempt ${Math.min(ingestion.attempt_count, ingestion.maximum_attempts)} of ${ingestion.maximum_attempts} is being managed by the processing service.`,
          }
        : {
            title: 'Building the document index',
            description: 'The file is scanned, read, organized, and stored securely before it becomes ready.',
          },
    projectDoc: documentInfo(document),
    ...(template ? { templateDoc: templateInfo(template) } : {}),
    steps: stageSteps,
    overallStatus: completed ? 'COMPLETED' : failed ? 'FAILED' : 'PROCESSING',
    errorCode: ingestion.error_code,
    errorMessage: failed ? ingestionErrorMessage(ingestion.error_code) : null,
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
  if (summary.representation === 'external-summary-v1') {
    const stored = summary.structured_summary;
    return { summary, projectName: project.name, document: documentInfo(document),
      confidenceScore: stored.generated_result.data.document_information.extraction_confidence,
      sections: [...stored.generated_result.data.summary_sections].sort((a, b) => a.order - b.order).map((section) => ({
        id: section.id, key: section.key, order: section.order, title: section.title,
        content: stored.current_sections.find((edit) => edit.id === section.id)?.content ?? section.content,
        originalContent: section.content, maxLength: section.max_length,
        pages: section.source_references.pages.map(String), referencesLabel: section.source_references.label,
        answerStatus: section.answer_status, truncated: section.evidence_context_truncated,
        citations: section.evidence_citations,
      })),
    };
  }
  return {
    summary,
    projectName: project.name,
    document: documentInfo(document),
    confidenceScore: 85,
    sections: [
      { id: 1, order: 1, maxLength: 2000, title: 'Project Overview', content: summary.summary_text, pages: [] },
      { id: 2, order: 2, maxLength: 2000, title: 'Key Points', content: summary.key_points.join('\n'), pages: [] },
      { id: 3, order: 3, maxLength: 2000, title: 'Requirements', content: requirementsText(summary.requirements), pages: [] },
    ],
  };
}

export function summaryUpdateFromSections(
  current: SummaryResponse,
  sections: SummarySectionItem[],
): { summary_text: string; key_points: string[]; requirements: RequirementRecord[] } {
  if (current.representation === 'external-summary-v1') throw new Error('Use the stable structured section patch contract.');
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
