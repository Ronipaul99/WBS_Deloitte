import { useEffect, useState } from 'react';
import { projectWorkflows, workflowCapabilities } from '../services/documentWorkflowsApi';
import type { WorkflowState } from '../services/workflowTypes';

export default function SavedDocumentWorkflows({ tenantId, projectId, onContinue }: {
  tenantId: string; projectId: string; onContinue: (workflowId: string) => void;
}) {
  const [workflows, setWorkflows] = useState<WorkflowState[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void workflowCapabilities(tenantId, controller.signal).then(async (capabilities) => {
      if (capabilities.resume_enabled) {
        const states = await projectWorkflows(tenantId, projectId, controller.signal);
        if (!controller.signal.aborted) setWorkflows(states);
      }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Saved work is temporarily unavailable.');
    });
    return () => controller.abort();
  }, [projectId, tenantId]);
  if (!workflows.length && !error) return null;
  return (
    <section className="project-section" aria-label="Saved document workflows">
      <h2>Continue previous work</h2>
      {error && <p role="alert">{error}</p>}
      {workflows.map((workflow) => (
        <div key={workflow.workflow_id} className="wbs-proc-file-card">
          <p>{workflow.document.file_name} · {workflow.stage.replaceAll('_', ' ').toLowerCase()}</p>
          <button type="button" className="project-primary-button" onClick={() => onContinue(workflow.workflow_id)}>
            Continue {workflow.document.file_name}
          </button>
        </div>
      ))}
    </section>
  );
}
