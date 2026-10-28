import type { WorkflowStage } from '../services/workflowTypes';

const labels: Record<WorkflowStage, string> = {
  DOCUMENT_READY: 'Ready to process', INGESTING: 'Processing document', INGESTED: 'Document processed',
  SUMMARIZING: 'Generating summary', SUMMARY_REVIEW: 'Summary ready for review',
  SUMMARY_APPROVED: 'Summary approved', GENERATING: 'Generating WBS', WBS_READY: 'WBS ready',
  VALIDATING: 'Validating WBS', VALIDATED: 'Validation complete', FAILED: 'Needs attention',
  CANCELLED: 'Cancelled',
};

export function workflowStageLabel(stage: WorkflowStage): string {
  return labels[stage] ?? 'Status unavailable';
}

export function workflowStageTone(stage: WorkflowStage): string {
  if (stage === 'FAILED' || stage === 'CANCELLED') return 'warning';
  if (['INGESTED', 'SUMMARY_APPROVED', 'WBS_READY', 'VALIDATED'].includes(stage)) return 'success';
  if (['INGESTING', 'SUMMARIZING', 'GENERATING', 'VALIDATING'].includes(stage)) return 'active';
  return 'neutral';
}

export function workflowDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date);
}

export function workflowFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Size unavailable';
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
