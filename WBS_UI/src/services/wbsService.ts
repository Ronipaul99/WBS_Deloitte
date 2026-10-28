import rawJobConfig from '../data/mockJobStatus.json';
import rawProcessingSnapshots from '../data/mockProcessingSnapshots.json';
import rawProjectSummary from '../data/mockProjectSummary.json';
import rawWbsResult from '../data/mockWbsResult.json';
import rawValidationResult from '../data/mockWbsValidation.json';

/* ==========================================================================
   Type Contracts & Exports
   ========================================================================== */

export type StepStatus = 'COMPLETED' | 'IN_PROGRESS' | 'PENDING' | 'FAILED';

export interface CurrentUserSession {
  username: string;
  name: string;
  initials: string;
  role: string;
  token?: string;
}

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
  type: string;
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
  templateDoc?: DocumentFileInfo;
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
  projectType: string;
  location: string;
  subtitle: string;
  targetCompletion: string;
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

export interface ProjectDocumentItem {
  id: string;
  name: string;
  size: string;
  type: string;
  category: string;
  version: string;
  status: string;
  uploadedAt: string;
  uploadedBy: string;
}

export interface WbsVersionRecord {
  id: string;
  name: string;
  version: string;
  description: string;
  status: 'Approved' | 'Under Review' | 'Draft' | 'Completed';
  generatedOn: string;
  createdBy: string;
  creatorInitials: string;
  creatorRole: string;
  scopeCoverage: number;
  wbsItemsCount: number;
  approvedOn?: string;
  approvedBy?: string;
}

export interface ProjectActivityItem {
  id: string;
  type: 'export' | 'version' | 'document' | 'validation';
  title: string;
  description: string;
  timestamp: string;
  user: string;
}

export interface ProjectEntity {
  id: string;
  code: string;
  name: string;
  subtitle: string;
  type: string;
  location: string;
  owner: string;
  ownerInitials: string;
  status: 'Processing' | 'Completed' | 'Draft WBS' | 'Under Review' | 'Approved' | 'Exported' | 'Archived' | 'Needs Attention';
  scopeCoverage: number;
  currentVersion: string;
  lastUpdated: string;
  createdAt: string;
  targetCompletion: string;
  documents: ProjectDocumentItem[];
  wbsVersions: WbsVersionRecord[];
  activityLogs: ProjectActivityItem[];
}

export interface TemplatePhaseItem {
  phaseNumber: number;
  phaseName: string;
  itemCount: number;
  subItems: string[];
}

export interface DynamicTemplateRecord {
  id: string;
  name: string;
  categories: string[];
  description: string;
  usageCount: number;
  lastUpdated: string;
  updatedBy: string;
  structure: TemplatePhaseItem[];
}

export interface ExportHistoryRecord {
  id: string;
  projectId: string;
  fileName: string;
  fileSize: string;
  version: string;
  format: 'PDF' | 'Excel' | 'Word' | 'JSON' | 'Primavera XML';
  exportedOn: string;
  exportedBy: string;
  exportedByInitials: string;
  exportedByRole: string;
  status: 'Completed' | 'In Progress' | 'Failed';
  statusMessage: string;
  includes: string[];
  fileContent?: string;
}

export interface AppSettingsPreferences {
  defaultWbsLevel: 'Level 1' | 'Level 2' | 'Level 3' | 'Level 4' | 'Level 5';
  defaultTemplateId: string;
  generationModel: string;
  embeddingModel: string;
  retrievedChunks: number;
  includeSourceEvidence: boolean;
  enableOcr: boolean;
  maxFileSizeMb: number;
  supportedFormats: string[];
}

/* ==========================================================================
   Session & Storage Utilities
   ========================================================================== */

const AUTH_STORAGE_KEY = 'wbs_genie_auth_session';
const SETTINGS_STORAGE_KEY = 'wbs_genie_app_settings';
const EXPORTS_GLOBAL_KEY = 'wbs_genie_all_exports';
const PROJECTS_STORAGE_KEY = 'wbs_genie_projects_store';

export function getActiveUserSession(): CurrentUserSession | null {
  try {
    const raw = sessionStorage.getItem(AUTH_STORAGE_KEY) || localStorage.getItem(AUTH_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e: unknown) {
    console.warn('Failed reading session', e);
  }
  return null;
}

export function setActiveUserSession(
  username: string,
  role: string = 'Enterprise User'
): CurrentUserSession {
  const cleanUsername = username.trim();
  const segments = cleanUsername.split(/[\s._@-]+/).filter(Boolean);

  let derivedInitials = 'US';
  if (segments.length >= 2) {
    derivedInitials = (segments[0][0] + segments[1][0]).toUpperCase();
  } else if (cleanUsername.length >= 2) {
    derivedInitials = cleanUsername.slice(0, 2).toUpperCase();
  } else if (cleanUsername.length === 1) {
    derivedInitials = cleanUsername.toUpperCase();
  }

  const session: CurrentUserSession = {
    username: cleanUsername,
    name: cleanUsername,
    initials: derivedInitials,
    role,
    token: `auth_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
  };

  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
  return session;
}

export function clearUserSession(): void {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

const DEFAULT_SETTINGS: AppSettingsPreferences = {
  defaultWbsLevel: 'Level 3',
  defaultTemplateId: 'Enterprise Architecture Baseline',
  generationModel: 'Granite 3.3 2B (Local)',
  embeddingModel: 'BGE Small (Local)',
  retrievedChunks: 8,
  includeSourceEvidence: true,
  enableOcr: false,
  maxFileSizeMb: 50,
  supportedFormats: ['PDF', 'DOCX', 'XLSX'],
};

function readSettingsFromStorage(): AppSettingsPreferences {
  try {
    const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch (e: unknown) {
    console.warn('Failed reading settings', e);
  }
  return { ...DEFAULT_SETTINGS };
}

function writeSettingsToStorage(settings: AppSettingsPreferences): void {
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch (e: unknown) {
    console.warn('Failed saving settings', e);
  }
}

export async function getAppSettings(): Promise<AppSettingsPreferences> {
  return readSettingsFromStorage();
}

export async function saveAppSettings(
  updated: AppSettingsPreferences
): Promise<{ success: boolean; savedAt: string }> {
  writeSettingsToStorage(updated);
  return {
    success: true,
    savedAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  };
}

export async function resetAppSettingsToDefault(): Promise<AppSettingsPreferences> {
  writeSettingsToStorage(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS };
}

function readAllStoredExports(): ExportHistoryRecord[] {
  try {
    const raw = localStorage.getItem(EXPORTS_GLOBAL_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e: unknown) {
    console.warn('Failed reading exports:', e);
  }
  return [];
}

function writeAllStoredExports(list: ExportHistoryRecord[]): void {
  try {
    localStorage.setItem(EXPORTS_GLOBAL_KEY, JSON.stringify(list));
    window.dispatchEvent(new Event('wbs_export_added'));
  } catch (e: unknown) {
    console.warn('Failed saving exports:', e);
  }
}

function readStoredProjects(): Record<string, ProjectEntity> {
  try {
    const raw = localStorage.getItem(PROJECTS_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e: unknown) {
    console.warn('Failed reading projects', e);
  }
  return {};
}

function writeStoredProjects(data: Record<string, ProjectEntity>): void {
  try {
    localStorage.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(data));
  } catch (e: unknown) {
    console.warn('Failed saving projects', e);
  }
}

interface JobSessionState {
  projectDocName: string;
  projectDocSize: string;
  projectDocType: string;
  templateDocName: string | null;
  templateDocSize: string | null;
  templateDocType: string | null;
  projectTitle: string;
  docSnapshotIndex: number;
  analysisStepIndex: number;
  summarySections: SummarySectionItem[];
  summaryMetadata: {
    projectType: string;
    location: string;
    subtitle: string;
    targetCompletion: string;
    confidenceScore: number;
  };
  wbsResult: WbsResultPayload;
}

const activeSessions: Record<string, JobSessionState> = {};
let projectRegistry: Record<string, ProjectEntity> = readStoredProjects();
const templateRegistry: Record<string, DynamicTemplateRecord> = {};

function getFileExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop()!.toLowerCase() : '';
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function deriveProjectCode(jobId: string): string {
  const numericPart = jobId.replace(/\D/g, '').slice(-4) || '0001';
  const year = new Date().getFullYear();
  return `PRJ-${year}-${numericPart}`;
}

function parseLevelNumber(levelStr: string): number {
  const match = levelStr.match(/\d+/);
  return match ? parseInt(match[0], 10) : 3;
}

function pruneWbsTreeToLevel(
  nodes: WbsNode[],
  targetLevel: number,
  currentDepth: number = 1,
  includeEvidence: boolean = true
): WbsNode[] {
  return nodes.map((node) => {
    const cloned: WbsNode = { ...node };

    if (!includeEvidence) {
      delete cloned.evidence;
    }

    if (currentDepth >= targetLevel) {
      cloned.children = [];
    } else if (node.children && node.children.length > 0) {
      cloned.children = pruneWbsTreeToLevel(node.children, targetLevel, currentDepth + 1, includeEvidence);
    } else {
      cloned.children = [];
    }

    return cloned;
  });
}

function deriveDynamicIncludes(tree: WbsNode[]): string[] {
  const includesSet = new Set<string>();
  includesSet.add('Full WBS Structure');

  let hasDescriptions = false;
  let hasCodes = false;
  let maxDepth = 1;

  const traverse = (nodes: WbsNode[], depth: number) => {
    if (depth > maxDepth) maxDepth = depth;
    for (const node of nodes) {
      if (node.code && node.code.trim().length > 0) hasCodes = true;
      if (node.description && node.description.trim().length > 0) hasDescriptions = true;
      if (node.children && node.children.length > 0) traverse(node.children, depth + 1);
    }
  };

  traverse(tree, 1);

  if (hasCodes) includesSet.add('WBS Codes');
  if (hasDescriptions) includesSet.add('Descriptions');
  if (maxDepth >= 2) includesSet.add('All Levels');
  includesSet.add('Deliverables');

  return Array.from(includesSet);
}

function computeNextVersion(currentVersion: string): string {
  const match = currentVersion.match(/v?(\d+)\.(\d+)/);
  if (match) {
    const major = parseInt(match[1], 10);
    const minor = parseInt(match[2], 10) + 1;
    return `v${major}.${minor}`;
  }
  return 'v1.1';
}

export function syncProjectRecord(jobId: string, status: ProjectEntity['status']): ProjectEntity {
  const session = activeSessions[jobId];
  if (!session) {
    return projectRegistry[jobId];
  }

  const currentUser = getActiveUserSession();
  const userName = currentUser ? currentUser.name : 'Active User';
  const userInitials = currentUser ? currentUser.initials : 'AU';
  const userRole = currentUser ? currentUser.role : 'Project Owner';

  const flatNodes: WbsNode[] = [];
  const walk = (nodes: WbsNode[]) => {
    nodes.forEach((n) => {
      flatNodes.push(n);
      if (n.children && n.children.length > 0) walk(n.children);
    });
  };
  walk(session.wbsResult.wbsTree);

  const coverage = session.wbsResult.scopeCoverage.overallScore;
  const projectCode = deriveProjectCode(jobId);

  const projectDocuments: ProjectDocumentItem[] = [
    {
      id: `doc_${jobId}_primary`,
      name: session.projectDocName,
      size: session.projectDocSize,
      type: session.projectDocType,
      category: 'Project Scope',
      version: session.wbsResult.version,
      status: 'Processed',
      uploadedAt: session.wbsResult.generatedDate,
      uploadedBy: userName,
    },
  ];

  if (session.templateDocName && session.templateDocSize && session.templateDocType) {
    projectDocuments.push({
      id: `doc_${jobId}_template`,
      name: session.templateDocName,
      size: session.templateDocSize,
      type: session.templateDocType,
      category: 'Reference Structure',
      version: session.wbsResult.version,
      status: 'Active',
      uploadedAt: session.wbsResult.generatedDate,
      uploadedBy: userName,
    });
  }

  const existing = projectRegistry[jobId];
  const initialVersionStatus: WbsVersionRecord['status'] = status === 'Completed' ? 'Approved' : 'Draft';

  const versions: WbsVersionRecord[] = existing?.wbsVersions ? existing.wbsVersions : [
    {
      id: `ver_${jobId}_1`,
      name: `${session.projectTitle} WBS Baseline`,
      version: session.wbsResult.version,
      description: session.summaryMetadata.subtitle,
      status: initialVersionStatus,
      generatedOn: session.wbsResult.generatedDate,
      createdBy: userName,
      creatorInitials: userInitials,
      creatorRole: userRole,
      scopeCoverage: coverage,
      wbsItemsCount: flatNodes.length,
      approvedOn: session.wbsResult.generatedDate,
      approvedBy: userName,
    },
  ];

  const activities: ProjectActivityItem[] = existing?.activityLogs ? existing.activityLogs : [
    {
      id: `act_${Date.now()}_1`,
      type: 'document',
      title: 'Project Scope Document Processed',
      description: `Uploaded and extracted key requirements from ${session.projectDocName}`,
      timestamp: session.wbsResult.generatedDate,
      user: userName,
    },
    {
      id: `act_${Date.now()}_2`,
      type: 'version',
      title: `Version ${session.wbsResult.version} Baseline Generated`,
      description: `WBS structure generated with ${coverage}% scope coverage and ${flatNodes.length} items`,
      timestamp: session.wbsResult.generatedDate,
      user: userName,
    },
  ];

  const entity: ProjectEntity = {
    id: jobId,
    code: projectCode,
    name: session.projectTitle,
    subtitle: session.summaryMetadata.subtitle,
    type: session.summaryMetadata.projectType,
    location: session.summaryMetadata.location,
    owner: userName,
    ownerInitials: userInitials,
    status: status,
    scopeCoverage: coverage,
    currentVersion: session.wbsResult.version,
    lastUpdated: session.wbsResult.generatedDate,
    createdAt: session.wbsResult.generatedDate,
    targetCompletion: session.summaryMetadata.targetCompletion,
    documents: existing?.documents ? existing.documents : projectDocuments,
    wbsVersions: versions,
    activityLogs: activities,
  };

  projectRegistry[jobId] = entity;
  writeStoredProjects(projectRegistry);
  return entity;
}

export async function createWbsGenerationJob(
  projectFile?: File | null,
  templateFile?: File | null
): Promise<{ jobId: string }> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  if (!projectFile) throw new Error('A project scope document is required.');

  const currentSettings = readSettingsFromStorage();
  const maxBytes = currentSettings.maxFileSizeMb * 1024 * 1024;
  if (projectFile.size > maxBytes) {
    throw new Error(
      `File size (${(projectFile.size / (1024 * 1024)).toFixed(1)} MB) exceeds configured limit of ${currentSettings.maxFileSizeMb} MB.`
    );
  }

  const ext = getFileExtension(projectFile.name).toUpperCase();
  const allowed = currentSettings.supportedFormats.map((f: string) => f.toUpperCase());
  if (!allowed.includes(ext)) {
    throw new Error(
      `File type .${ext.toLowerCase()} is not enabled. Allowed formats: ${currentSettings.supportedFormats.join(', ')}`
    );
  }

  const jobId = `job_${Date.now()}`;
  const baseWbs: WbsResultPayload = JSON.parse(JSON.stringify(rawWbsResult));
  const summaryPayload = rawProjectSummary as unknown as ProjectSummaryResponse;

  baseWbs.projectId = jobId;
  baseWbs.projectName = projectFile.name.replace(/\.[^/.]+$/, '');
  baseWbs.templateName = templateFile ? templateFile.name : currentSettings.defaultTemplateId;
  baseWbs.version = 'v1.0';
  baseWbs.generatedDate = new Date().toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });

  const maxAllowedLevel = parseLevelNumber(currentSettings.defaultWbsLevel);
  baseWbs.wbsTree = pruneWbsTreeToLevel(
    baseWbs.wbsTree,
    maxAllowedLevel,
    1,
    currentSettings.includeSourceEvidence
  );

  baseWbs.unmappedRequirements = baseWbs.unmappedRequirements.map((req: UnmappedRequirement) => ({
    ...req,
    sourceDoc: projectFile.name,
  }));

  activeSessions[jobId] = {
    projectDocName: projectFile.name,
    projectDocSize: formatBytes(projectFile.size),
    projectDocType: getFileExtension(projectFile.name),
    templateDocName: templateFile ? templateFile.name : null,
    templateDocSize: templateFile ? formatBytes(templateFile.size) : null,
    templateDocType: templateFile ? getFileExtension(templateFile.name) : null,
    projectTitle: baseWbs.projectName,
    docSnapshotIndex: 0,
    analysisStepIndex: 0,
    summarySections: JSON.parse(JSON.stringify(summaryPayload.sections)),
    summaryMetadata: {
      projectType: summaryPayload.projectType,
      location: summaryPayload.location,
      subtitle: summaryPayload.subtitle,
      targetCompletion: summaryPayload.targetCompletion,
      confidenceScore: summaryPayload.confidenceScore,
    },
    wbsResult: baseWbs,
  };

  syncProjectRecord(jobId, 'Processing');
  return { jobId };
}

export async function getProcessingDocStatus(jobId: string): Promise<ProcessingDocStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const session = activeSessions[jobId];
  if (!session) throw new Error(`Active session for job "${jobId}" not found.`);

  const snapshots = rawProcessingSnapshots as unknown as Array<{
    overallStatus: 'PROCESSING' | 'COMPLETED' | 'FAILED';
    steps: ProcessingStepItem[];
  }>;

  const currentIndex = session.docSnapshotIndex;
  const currentSnapshot = snapshots[currentIndex];
  if (currentIndex < snapshots.length - 1) session.docSnapshotIndex = currentIndex + 1;

  return {
    jobId,
    title: 'Processing Project Document',
    subtitle: `Extracting key scope items from ${session.projectDocName}`,
    projectDoc: {
      name: session.projectDocName,
      size: session.projectDocSize,
      type: session.projectDocType,
      status: 'UPLOADED',
    },
    steps: currentSnapshot.steps,
    overallStatus: currentSnapshot.overallStatus,
    errorMessage: null,
  };
}

export async function getProjectSummary(jobId: string): Promise<ProjectSummaryResponse> {
  await new Promise((resolve) => setTimeout(resolve, 100));
  const session = activeSessions[jobId];
  if (!session) throw new Error(`Active session for job "${jobId}" not found.`);

  return {
    jobId,
    projectName: session.projectTitle,
    document: {
      name: session.projectDocName,
      size: session.projectDocSize,
      type: session.projectDocType,
      status: 'UPLOADED',
    },
    confidenceScore: session.summaryMetadata.confidenceScore,
    projectType: session.summaryMetadata.projectType,
    location: session.summaryMetadata.location,
    subtitle: session.summaryMetadata.subtitle,
    targetCompletion: session.summaryMetadata.targetCompletion,
    sections: JSON.parse(JSON.stringify(session.summarySections)),
  };
}

export async function saveProjectSummary(
  jobId: string,
  updatedSections: SummarySectionItem[]
): Promise<boolean> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = activeSessions[jobId];
  if (session) {
    session.summarySections = JSON.parse(JSON.stringify(updatedSections));
    syncProjectRecord(jobId, 'Processing');
  }
  return true;
}

export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const session = activeSessions[jobId];
  if (!session) throw new Error(`Active session for job "${jobId}" not found.`);

  const stepsDef = (rawJobConfig as unknown as { steps: AnalysisStep[] }).steps;
  const currentIndex = session.analysisStepIndex;
  const currentSettings = readSettingsFromStorage();

  const steps: AnalysisStep[] = stepsDef.map((step: AnalysisStep, idx: number) => {
    let status: StepStatus = 'PENDING';
    if (idx < currentIndex) status = 'COMPLETED';
    else if (idx === currentIndex) status = 'IN_PROGRESS';
    return { ...step, status };
  });

  const isCompleted = currentIndex >= stepsDef.length;
  if (!isCompleted) {
    session.analysisStepIndex = currentIndex + 1;
  } else {
    syncProjectRecord(jobId, 'Approved');
  }

  return {
    jobId,
    overallStatus: isCompleted ? 'COMPLETED' : 'IN_PROGRESS',
    title: (rawJobConfig as unknown as { title: string }).title,
    subtitle: `Analyzing with ${currentSettings.generationModel}`,
    sideCard: {
      title: 'Decomposing Requirements',
      description: `Neural parser is decomposing ${session.projectDocName}`,
    },
    steps,
    errorMessage: null,
  };
}

export function resetJobStatusSimulation(jobId?: string): void {
  if (jobId && activeSessions[jobId]) {
    activeSessions[jobId].analysisStepIndex = 0;
    activeSessions[jobId].docSnapshotIndex = 0;
  }
}

export async function getWbsResult(jobId: string): Promise<WbsResultPayload> {
  await new Promise((resolve) => setTimeout(resolve, 100));
  return activeSessions[jobId]?.wbsResult || rawWbsResult;
}

export async function updateWbsTree(
  jobId: string,
  wbsTree: WbsNode[],
  updatedUnmapped?: UnmappedRequirement[],
  updatedScopeCoverage?: ScopeCoverageData,
  options?: { isRegenerate?: boolean; reason?: string }
): Promise<{ success: boolean; newVersion: string; updatedAt: string }> {
  await new Promise((resolve) => setTimeout(resolve, 150));
  const session = activeSessions[jobId];
  const project = projectRegistry[jobId];
  const currentUser = getActiveUserSession();
  const userName = currentUser ? currentUser.name : 'Active User';
  const userInitials = currentUser ? currentUser.initials : 'AU';
  const userRole = currentUser ? currentUser.role : 'Project Owner';
  const now = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

  let updatedVersion = session?.wbsResult?.version || project?.currentVersion || 'v1.0';

  if (session) {
    const nextVer = computeNextVersion(session.wbsResult.version);
    session.wbsResult.version = nextVer;
    session.wbsResult.wbsTree = wbsTree;
    if (updatedUnmapped) session.wbsResult.unmappedRequirements = updatedUnmapped;
    if (updatedScopeCoverage) session.wbsResult.scopeCoverage = updatedScopeCoverage;
    updatedVersion = nextVer;
  }

  if (project) {
    project.currentVersion = updatedVersion;
    project.lastUpdated = now;
    if (updatedScopeCoverage) {
      project.scopeCoverage = updatedScopeCoverage.overallScore;
    }

    const flatNodesCount = wbsTree.length;
    const versionReason = options?.reason || (options?.isRegenerate ? 'WBS Regenerated' : 'WBS Structure Updated');

    const newVersionRecord: WbsVersionRecord = {
      id: `ver_${jobId}_${Date.now()}`,
      name: `${project.name} WBS Baseline`,
      version: updatedVersion,
      description: versionReason,
      status: 'Approved',
      generatedOn: now,
      createdBy: userName,
      creatorInitials: userInitials,
      creatorRole: userRole,
      scopeCoverage: project.scopeCoverage,
      wbsItemsCount: flatNodesCount,
      approvedOn: now,
      approvedBy: userName,
    };

    project.wbsVersions.unshift(newVersionRecord);

    project.activityLogs.unshift({
      id: `act_${Date.now()}`,
      type: 'version',
      title: `Version ${updatedVersion} Baseline Saved`,
      description: `${versionReason} by ${userName} with ${project.scopeCoverage}% scope coverage`,
      timestamp: now,
      user: userName,
    });

    writeStoredProjects(projectRegistry);
  }

  return { success: true, newVersion: updatedVersion, updatedAt: new Date().toISOString() };
}

export async function getWbsValidation(jobId: string): Promise<WbsValidationPayload> {
  await new Promise((resolve) => setTimeout(resolve, 100));
  const session = activeSessions[jobId];
  const baseValidation = rawValidationResult as unknown as WbsValidationPayload;

  if (session) {
    const flatNodes: WbsNode[] = [];
    const walk = (nodes: WbsNode[]) => {
      nodes.forEach((n) => {
        flatNodes.push(n);
        if (n.children && n.children.length > 0) walk(n.children);
      });
    };
    walk(session.wbsResult.wbsTree);

    const totalCount = flatNodes.length;
    const phasesCount = flatNodes.filter((n) => n.type === 'Phase').length;
    const workPackagesCount = totalCount - phasesCount;
    const unmapped = session.wbsResult.unmappedRequirements;
    const rawCoverage = session.wbsResult.scopeCoverage;
    const computedPercentage = Math.round(
      (rawCoverage.mappedCount / Math.max(1, rawCoverage.totalRequirements)) * 100
    );

    return {
      jobId,
      projectName: session.projectTitle,
      version: session.wbsResult.version,
      breadcrumbs: session.wbsResult.breadcrumbs,
      summaryCards: {
        wbsItems: { count: totalCount, phasesCount, workPackagesCount },
        scopeCoverage: {
          percentage: computedPercentage,
          mapped: rawCoverage.mappedCount,
          total: rawCoverage.totalRequirements,
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
      validationChecks: baseValidation.validationChecks,
      unmappedRequirements: unmapped.map((u: UnmappedRequirement) => ({ reference: u.code, summary: u.title })),
      aiRecommendations: baseValidation.aiRecommendations,
    };
  }

  return {
    ...baseValidation,
    jobId,
  };
}

export async function getAllProjects(): Promise<ProjectEntity[]> {
  await new Promise((resolve) => setTimeout(resolve, 30));
  projectRegistry = readStoredProjects();
  return Object.values(projectRegistry);
}

export async function getProjectById(projectId: string): Promise<ProjectEntity | null> {
  await new Promise((resolve) => setTimeout(resolve, 30));
  projectRegistry = readStoredProjects();
  return projectRegistry[projectId] || null;
}

export async function addDocumentToProject(
  projectId: string,
  file: File,
  category: string
): Promise<ProjectDocumentItem> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const project = projectRegistry[projectId];
  if (!project) throw new Error(`Project "${projectId}" was not found.`);

  const currentUser = getActiveUserSession();
  const userName = currentUser ? currentUser.name : project.owner;
  const now = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

  const newDoc: ProjectDocumentItem = {
    id: `doc_${Date.now()}`,
    name: file.name,
    size: formatBytes(file.size),
    type: getFileExtension(file.name),
    category,
    version: project.currentVersion,
    status: 'Processed',
    uploadedAt: now,
    uploadedBy: userName,
  };

  project.documents.unshift(newDoc);

  project.activityLogs.unshift({
    id: `act_${Date.now()}`,
    type: 'document',
    title: `Document Uploaded: ${file.name}`,
    description: `Categorized under ${category} (${formatBytes(file.size)})`,
    timestamp: now,
    user: userName,
  });

  writeStoredProjects(projectRegistry);
  return newDoc;
}

export async function getAllTemplates(): Promise<DynamicTemplateRecord[]> {
  await new Promise((resolve) => setTimeout(resolve, 50));
  return Object.values(templateRegistry);
}

export async function createCustomTemplate(
  name: string,
  category: string,
  description: string,
  phases: string[]
): Promise<DynamicTemplateRecord> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const id = `tpl_${Date.now()}`;
  const now = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  const currentUser = getActiveUserSession();
  const authorName = currentUser ? currentUser.name : 'System User';

  const newTpl: DynamicTemplateRecord = {
    id,
    name,
    categories: [category],
    description,
    usageCount: 0,
    lastUpdated: now,
    updatedBy: authorName,
    structure: phases.map((phaseTitle: string, idx: number) => ({
      phaseNumber: idx + 1,
      phaseName: phaseTitle,
      itemCount: 1,
      subItems: [`${phaseTitle} Execution`],
    })),
  };

  templateRegistry[id] = newTpl;
  return newTpl;
}

export async function getProjectExportHistory(projectId?: string): Promise<ExportHistoryRecord[]> {
  await new Promise((resolve) => setTimeout(resolve, 50));
  const allExports = readAllStoredExports();
  if (projectId) {
    return allExports.filter((item) => item.projectId === projectId);
  }
  return allExports;
}

export async function triggerNewProjectExport(
  projectId: string,
  format: 'PDF' | 'Excel' | 'Word' | 'JSON' | 'Primavera XML',
  options?: {
    customFilename?: string;
    includes?: string[];
    rawContent?: string;
  }
): Promise<ExportHistoryRecord> {
  await new Promise((resolve) => setTimeout(resolve, 100));

  const session = activeSessions[projectId];
  const project = projectRegistry[projectId] || Object.values(projectRegistry)[0];

  const currentUser = getActiveUserSession();
  const userName = currentUser ? currentUser.name : (project ? project.owner : 'Enterprise User');
  const userInitials = currentUser ? currentUser.initials : (project ? project.ownerInitials : 'EU');
  const userRole = currentUser ? currentUser.role : 'Project Planner';

  const ext = format === 'PDF' 
    ? 'pdf' 
    : format === 'Excel' 
    ? 'xlsx' 
    : format === 'Word' 
    ? 'docx' 
    : format === 'JSON' 
    ? 'json' 
    : 'xml';

  const projectName = project ? project.name : (session ? session.projectTitle : 'Project_WBS');
  const sanitizedTitle = projectName.replace(/[^a-zA-Z0-9_-]/g, '_');
  const version = project ? project.currentVersion : (session?.wbsResult?.version || 'v1.0');

  const now = new Date();
  const timeFormatted = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const dateFormatted = now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

  const liveTree = session?.wbsResult?.wbsTree || [];
  const nodeCount = liveTree.length;
  const computedBytes = Math.max(140000, nodeCount * 45000 + (format === 'PDF' ? 850000 : 320000));
  const calculatedFileSize = formatBytes(computedBytes);

  const dynamicIncludes = options?.includes || deriveDynamicIncludes(liveTree);
  const fileName = options?.customFilename || `${sanitizedTitle}_WBS_${version}.${ext}`;

  const newExport: ExportHistoryRecord = {
    id: `exp_${Date.now()}`,
    projectId: project ? project.id : projectId,
    fileName,
    fileSize: calculatedFileSize,
    version,
    format,
    exportedOn: `${dateFormatted}, ${timeFormatted}`,
    exportedBy: userName,
    exportedByInitials: userInitials,
    exportedByRole: userRole,
    status: 'Completed',
    statusMessage: 'Export completed successfully.',
    includes: dynamicIncludes,
    fileContent: options?.rawContent,
  };

  const currentList = readAllStoredExports();
  currentList.unshift(newExport);
  writeAllStoredExports(currentList);

  if (project) {
    project.activityLogs.unshift({
      id: `act_${Date.now()}`,
      type: 'export',
      title: `WBS Export Generated (${format})`,
      description: `Downloaded package ${fileName} (${calculatedFileSize})`,
      timestamp: `${dateFormatted}, ${timeFormatted}`,
      user: userName,
    });
    writeStoredProjects(projectRegistry);
  }

  return newExport;
}

export async function deleteExportHistoryRecord(exportId: string): Promise<boolean> {
  await new Promise((resolve) => setTimeout(resolve, 50));
  const currentList = readAllStoredExports();
  const filtered = currentList.filter((e) => e.id !== exportId);
  writeAllStoredExports(filtered);
  return true;
}

export async function deleteProjectRecord(projectId: string): Promise<ProjectEntity[]> {
  await new Promise((resolve) => setTimeout(resolve, 30));
  try {
    projectRegistry = readStoredProjects();

    let foundKey = '';
    for (const key of Object.keys(projectRegistry)) {
      if (key === projectId || projectRegistry[key].id === projectId) {
        foundKey = key;
        break;
      }
    }

    if (foundKey) {
      delete projectRegistry[foundKey];
      writeStoredProjects(projectRegistry);
    }

    if (activeSessions[projectId]) {
      delete activeSessions[projectId];
    }
  } catch (e: unknown) {
    console.warn('Failed deleting project record:', e);
  }

  projectRegistry = readStoredProjects();
  return Object.values(projectRegistry);
}