import { useEffect, useState } from 'react';
import { ArrowRight, FileText, History, Loader2, RefreshCw } from 'lucide-react';
import { projectWorkflows, workflowCapabilities } from '../services/documentWorkflowsApi';
import type { WorkflowState } from '../services/workflowTypes';
import WorkflowStatusBadge from './WorkflowStatusBadge';
import { workflowDate } from './workflowUi';
import './WorkflowSurfaces.css';

export default function SavedDocumentWorkflows({ tenantId, projectId, onContinue }: {
  tenantId: string; projectId: string; onContinue: (workflowId: string) => void;
}) {
  const key = `${tenantId}/${projectId}`;
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; workflows: WorkflowState[]; error: string | null } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void workflowCapabilities(tenantId, controller.signal).then(async (capabilities) => {
      const workflows = capabilities.resume_enabled
        ? await projectWorkflows(tenantId, projectId, controller.signal) : [];
      if (!controller.signal.aborted) setResult({ key: `${tenantId}/${projectId}`, workflows, error: null });
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setResult({ key: `${tenantId}/${projectId}`, workflows: [],
        error: reason instanceof Error ? reason.message : 'Saved work is temporarily unavailable.' });
    });
    return () => controller.abort();
  }, [projectId, tenantId, attempt]);
  const loading = result?.key !== key;
  const workflows = loading ? [] : result.workflows;
  const error = loading ? null : result.error;
  if (!loading && !workflows.length && !error) return null;
  return (
    <section className="workflow-saved" aria-label="Saved document workflows" aria-busy={loading}>
      <div className="workflow-saved-heading">
        <span className="workflow-history-icon" aria-hidden="true"><History size={18} /></span>
        <div><h2>Continue previous work</h2><p>Your documents, saved progress and results, in one place.</p></div>
        {!loading && workflows.length > 0 && <span className="workflow-count">{workflows.length} saved {workflows.length === 1 ? 'workflow' : 'workflows'}</span>}
      </div>
      {loading && <div className="workflow-saved-loading" role="status"><Loader2 size={17} className="workflow-spin" aria-hidden="true" />Loading saved work?</div>}
      {error && <div className="workflow-alert" role="alert"><span>{error}</span>
        <button type="button" className="workflow-text-button" onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={14} aria-hidden="true" />Try again</button>
      </div>}
      <ul className="workflow-saved-list">
        {workflows.map((workflow) => (
          <li className="workflow-saved-row" key={workflow.workflow_id}>
            <span className="workflow-file-icon" aria-hidden="true"><FileText size={21} strokeWidth={1.6} /></span>
            <div className="workflow-document-copy">
              <strong className="workflow-file-title">{workflow.document.file_name}</strong>
              <span className="workflow-meta">Uploaded {workflowDate(workflow.document.created_at)}</span>
            </div>
            <WorkflowStatusBadge stage={workflow.stage} needsRefresh={workflow.source_requires_processing} />
            <button type="button" className="workflow-button workflow-button-secondary"
              aria-label={`Continue ${workflow.document.file_name}`} onClick={() => onContinue(workflow.workflow_id)}>
              Continue <ArrowRight size={14} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
