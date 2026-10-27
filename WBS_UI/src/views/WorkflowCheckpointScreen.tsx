import { useEffect, useState } from 'react';
import { getWorkflow } from '../services/documentWorkflowsApi';
import { sessionFromState } from '../services/workflowApi';
import { startIngestion } from '../services/ingestionApi';
import { startSummary } from '../services/summariesApi';
import { startGeneration } from '../services/generationsApi';
import { startValidation } from '../services/validationsApi';
import { retryJob } from '../services/jobsApi';
import { pollResource } from '../services/polling';
import type { WorkflowSession, WorkflowState } from '../services/workflowTypes';

interface Props {
  tenantId: string;
  state: WorkflowState;
  onResumed: (session: WorkflowSession) => void;
  onViewWbs: () => void;
  onBack: () => void;
}

export default function WorkflowCheckpointScreen({ tenantId, state, onResumed, onViewWbs, onBack }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (state.stage !== 'SUMMARIZING') return;
    const controller = new AbortController();
    void pollResource({
      signal: controller.signal,
      request: (signal) => getWorkflow(tenantId, state.workflow_id, signal),
      isTerminal: (next) => next.stage !== 'SUMMARIZING',
    }).then(async (next) => {
      const session = await sessionFromState(tenantId, next, controller.signal);
      if (!controller.signal.aborted) onResumed(session);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Status is temporarily unavailable.');
    });
    return () => controller.abort();
  }, [onResumed, state.stage, state.workflow_id, tenantId]);

  const act = async (action: string) => {
    setBusy(true);
    setError(null);
    try {
      if (action === 'start_ingestion' || (action === 'retry' && state.failed_stage === 'ingestion')) {
        await startIngestion(tenantId, state.document_id);
      } else if (action === 'start_summary') {
        await startSummary(tenantId, state.document_id, undefined, state.workflow_id);
      } else if (action === 'start_generation' && state.summary_id) {
        await startGeneration(tenantId, state.project_id, {
          documentId: state.document_id, summaryId: state.summary_id, templateId: state.template?.id ?? null,
          workflowId: state.workflow_id, expectedRevision: state.checkpoint_revision,
        });
      } else if (action === 'retry' && state.failed_stage === 'validation' && state.wbs_version_id) {
        await startValidation(tenantId, state.wbs_version_id, undefined, true);
      } else if (action === 'retry' && state.job) {
        await retryJob(tenantId, state.job.id);
      }
      const next = await getWorkflow(tenantId, state.workflow_id);
      onResumed(await sessionFromState(tenantId, next));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The saved workflow could not be continued.');
    } finally {
      setBusy(false);
    }
  };
  const labels: Record<string, string> = {
    start_ingestion: 'Start document processing', start_summary: 'Generate summary',
    start_generation: 'Generate WBS', retry: 'Retry failed step',
  };
  return (
    <section className="app-missing-job-card" aria-labelledby="saved-workflow-title">
      <h1 id="saved-workflow-title">{state.stage === 'INGESTED' ? 'Document processed successfully' : 'Continue saved work'}</h1>
      <p><strong>{state.document.file_name}</strong> · {state.project.name}</p>
      <p role="status">{state.stage.replaceAll('_', ' ').toLowerCase()}</p>
      {state.failed_stage && <p>The {state.failed_stage} step stopped. Earlier saved work is preserved.</p>}
      {state.source_requires_processing && <p>Document processing needs to be refreshed for the current processing version. Saved edits and results are preserved.</p>}
      {state.validation_stale && <p>The saved validation applies to an earlier WBS revision.</p>}
      {error && <p role="alert">{error}</p>}
      {state.allowed_actions.filter((action) => labels[action]).map((action) => (
        <button key={action} type="button" className="app-missing-job-btn" disabled={busy}
          onClick={() => void act(action)}>{labels[action]}</button>
      ))}
      {state.allowed_actions.includes('view_wbs') && <button type="button" disabled={busy} onClick={onViewWbs}>View saved WBS</button>}
      <button type="button" disabled={busy} onClick={() => void act('refresh')}>Check saved status</button>
      <button type="button" disabled={busy} onClick={onBack}>Back to project</button>
    </section>
  );
}
