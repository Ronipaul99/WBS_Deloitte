import type { WorkflowSession } from './workflowTypes';

const STORAGE_PREFIX = 'wbs.ingestion.v1';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface LegacyWorkflowContext {
  version: 1;
  tenantId: string;
  projectId: string;
  documentId: string;
  ingestionJobId: string;
  processingRunId: string;
  templateId: string | null;
}

export type StoredWorkflowContext = LegacyWorkflowContext | {
  version: 2;
  tenantId: string;
  projectId: string;
  workflowId: string;
};

function activeKey(tenantId: string): string {
  return `${STORAGE_PREFIX}:${tenantId}:active`;
}

function contextKey(tenantId: string, projectId: string): string {
  return `${STORAGE_PREFIX}:${tenantId}:${projectId}`;
}

function isIdentifier(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

function isStoredContext(value: unknown): value is StoredWorkflowContext {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<LegacyWorkflowContext> & { workflowId?: unknown };
  if ((value as { version?: unknown }).version === 2) {
    return isIdentifier(candidate.tenantId) && isIdentifier(candidate.projectId)
      && isIdentifier(candidate.workflowId);
  }
  return candidate.version === 1
    && isIdentifier(candidate.tenantId)
    && isIdentifier(candidate.projectId)
    && isIdentifier(candidate.documentId)
    && isIdentifier(candidate.ingestionJobId)
    && isIdentifier(candidate.processingRunId)
    && (candidate.templateId === null || isIdentifier(candidate.templateId));
}

export function saveWorkflowContext(tenantId: string, session: WorkflowSession): void {
  if (!session.workflowId && (!session.ingestionJobId || !session.processingRunId)) return;
  const context: StoredWorkflowContext = session.workflowId ? {
    version: 2, tenantId, projectId: session.project.id, workflowId: session.workflowId,
  } : {
    version: 1,
    tenantId,
    projectId: session.project.id,
    documentId: session.document.id,
    ingestionJobId: session.ingestionJobId!,
    processingRunId: session.processingRunId!,
    templateId: session.template?.id ?? null,
  };
  try {
    const previousProjectId = sessionStorage.getItem(activeKey(tenantId));
    if (previousProjectId && previousProjectId !== session.project.id) {
      sessionStorage.removeItem(contextKey(tenantId, previousProjectId));
    }
    sessionStorage.setItem(contextKey(tenantId, session.project.id), JSON.stringify(context));
    sessionStorage.setItem(activeKey(tenantId), session.project.id);
  } catch {
    // The in-memory workflow remains usable when browser session storage is unavailable.
  }
}

export function readWorkflowContext(tenantId: string): StoredWorkflowContext | null {
  let key: string | null = null;
  try {
    const projectId = sessionStorage.getItem(activeKey(tenantId));
    if (!isIdentifier(projectId)) {
      sessionStorage.removeItem(activeKey(tenantId));
      return null;
    }
    key = contextKey(tenantId, projectId);
    const raw = sessionStorage.getItem(key);
    if (!raw) {
      sessionStorage.removeItem(activeKey(tenantId));
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (isStoredContext(parsed) && parsed.tenantId === tenantId && parsed.projectId === projectId) {
      return parsed;
    }
    sessionStorage.removeItem(key);
    sessionStorage.removeItem(activeKey(tenantId));
  } catch {
    try {
      if (key) sessionStorage.removeItem(key);
      sessionStorage.removeItem(activeKey(tenantId));
    } catch {
      // Browser storage is unavailable.
    }
    return null;
  }
  return null;
}

export function clearWorkflowContext(tenantId: string, projectId?: string): void {
  try {
    const activeProjectId = sessionStorage.getItem(activeKey(tenantId));
    const targetProjectId = projectId ?? activeProjectId;
    if (targetProjectId) sessionStorage.removeItem(contextKey(tenantId, targetProjectId));
    if (!projectId || activeProjectId === projectId) sessionStorage.removeItem(activeKey(tenantId));
  } catch {
    // There is no persistent context to clear when session storage is unavailable.
  }
}
