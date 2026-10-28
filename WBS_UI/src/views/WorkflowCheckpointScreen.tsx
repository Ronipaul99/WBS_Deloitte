import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CheckCircle2, CircleAlert, FileText, FolderOpen, History, Loader2, RefreshCw } from 'lucide-react';
import { getWorkflow } from '../services/documentWorkflowsApi';
import { sessionFromState } from '../services/workflowApi';
import { startIngestion } from '../services/ingestionApi';
import { startSummary } from '../services/summariesApi';
import { startGeneration } from '../services/generationsApi';
import { startValidation } from '../services/validationsApi';
import { retryJob } from '../services/jobsApi';
import { pollResource } from '../services/polling';
import type { WorkflowSession, WorkflowState } from '../services/workflowTypes';
import WorkflowDialog from '../components/WorkflowDialog';
import WorkflowStatusBadge from '../components/WorkflowStatusBadge';
import { workflowFileSize } from '../components/workflowUi';
import '../components/WorkflowSurfaces.css';

function WorkflowProgress({ state }: { state: WorkflowState }) {
  const positions: Record<string, number> = {
    DOCUMENT_READY: 0, INGESTING: 0, INGESTED: 1, SUMMARIZING: 1, SUMMARY_REVIEW: 1,
    SUMMARY_APPROVED: 2, GENERATING: 2, WBS_READY: 3, VALIDATING: 3, VALIDATED: 4,
  };
  const stages = ['ingestion', 'summary', 'generation', 'validation'];
  const stopped = state.stage === 'FAILED' || state.stage === 'CANCELLED';
  const current = state.source_requires_processing ? 0
    : stopped ? Math.max(0, stages.indexOf(state.failed_stage ?? 'ingestion'))
      : positions[state.stage] ?? 0;
  return <ol className="workflow-progress" aria-label="Workflow progress">
    {['Processing', 'Summary', 'WBS', 'Validation'].map((label, index) => {
      const done = index < current;
      const active = index === current;
      const needsAttention = active && (stopped || state.source_requires_processing);
      return <li key={label} className={done ? 'is-done' : needsAttention ? 'is-stopped' : active ? 'is-current' : ''}
        aria-current={active ? 'step' : undefined}>
        <span className="workflow-step-node" aria-hidden="true">{done ? <Check size={14} /> : needsAttention ? <CircleAlert size={14} /> : index + 1}</span>
        <span className="workflow-step-label">{label}</span>
        <span className="workflow-step-state">{done ? 'Complete' : needsAttention ? 'Needs attention' : active ? 'Current step' : 'Upcoming'}</span>
      </li>;
    })}
  </ol>;
}

function DocumentContext({ state }: { state: WorkflowState }) {
  return <div className="workflow-document">
    <span className="workflow-file-icon" aria-hidden="true"><FileText size={23} strokeWidth={1.6} /></span>
    <div className="workflow-document-copy">
      <strong className="workflow-file-title">{state.document.file_name}</strong>
      <p className="workflow-meta"><FolderOpen size={13} aria-hidden="true" />{state.project.name}
        <span aria-hidden="true">·</span>{workflowFileSize(state.document.size_bytes)}</p>
    </div>
  </div>;
}

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
  const complete = state.stage === 'INGESTED' && !state.source_requires_processing;
  const actions = state.allowed_actions.filter((action) => labels[action]);
  const nextCopy: Record<string, [string, string]> = {
    start_ingestion: ['Prepare your document', 'Process this document to extract its content and prepare it for the next step.'],
    start_summary: ['Your next step: generate a summary', 'Create a summary from the processed document, then review it before generating your WBS.'],
    start_generation: ['Ready to build your WBS', 'Continue from the approved summary and the saved workflow settings.'],
    retry: ['Continue from the step that stopped', 'Earlier saved work is preserved. Retry when you are ready to continue.'],
  };
  const next = nextCopy[actions[0]] ?? ['Your progress is saved',
    state.stage === 'SUMMARIZING' ? 'Your summary is being generated. This view will update when it is ready.'
      : 'Check the latest status or open the available results to continue.'];
  const actionButtons = <>
    {actions.map((action, index) => <button key={action} type="button"
      className={`workflow-button workflow-button-${index === 0 ? 'primary' : 'secondary'}`}
      data-dialog-focus={index === 0 ? '' : undefined} disabled={busy} onClick={() => void act(action)}>
      {busy ? <Loader2 size={16} className="workflow-spin" aria-hidden="true" /> : null}
      {labels[action]}<ArrowRight size={15} aria-hidden="true" />
    </button>)}
    {state.allowed_actions.includes('view_wbs') && <button type="button"
      className={`workflow-button workflow-button-${actions.length ? 'secondary' : 'primary'}`}
      disabled={busy} onClick={onViewWbs}>View saved WBS<ArrowRight size={15} aria-hidden="true" /></button>}
  </>;
  const notices = <>
    {state.failed_stage && <div className="workflow-notice"><CircleAlert size={17} aria-hidden="true" /><p>The {state.failed_stage} step stopped. Earlier saved work is preserved.</p></div>}
    {state.source_requires_processing && <div className="workflow-notice"><RefreshCw size={17} aria-hidden="true" /><p>Document processing needs to be refreshed for the current processing version. Saved edits and results are preserved.</p></div>}
    {state.validation_stale && <div className="workflow-notice"><CircleAlert size={17} aria-hidden="true" /><p>The saved validation applies to an earlier WBS revision.</p></div>}
    {error && <p className="workflow-alert" role="alert">{error}</p>}
  </>;
  if (complete) return <WorkflowDialog title="Document processed successfully" eyebrow="Ready for the next step"
    description="Your document has been processed. Continue with a summary when you are ready."
    icon={<CheckCircle2 size={27} strokeWidth={1.7} />} tone="success" busy={busy} onClose={onBack}
    footer={<>
      <button type="button" className="workflow-button workflow-button-secondary" disabled={busy} onClick={onBack}>Back to project</button>
      {actionButtons}
    </>}>
    <div className="workflow-success-document"><DocumentContext state={state} /><WorkflowProgress state={state} /></div>
    <div className="workflow-success-note"><h3>{next[0]}</h3><p>{next[1]}</p></div>
    {notices}
  </WorkflowDialog>;
  return (
    <section className="workflow-checkpoint" aria-labelledby="saved-workflow-title" aria-busy={busy}>
      <button type="button" className="workflow-back" disabled={busy} onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Back to project</button>
      <header className="workflow-checkpoint-header"><div><p className="workflow-eyebrow">Document workflow</p>
        <h1 id="saved-workflow-title">Continue saved work</h1>
        <p className="workflow-description">Everything you have saved is here. Continue from the next available step.</p></div>
        <div role="status"><WorkflowStatusBadge stage={state.stage} needsRefresh={state.source_requires_processing} /></div>
      </header>
      <div className="workflow-panel">
        <DocumentContext state={state} />
        <WorkflowProgress state={state} />
        <div className="workflow-next"><h3>{next[0]}</h3><p>{next[1]}</p>{notices}</div>
        <footer className="workflow-panel-footer">
          <button type="button" className="workflow-button workflow-button-quiet" disabled={busy} onClick={() => void act('refresh')}>
            <RefreshCw size={14} className={busy ? 'workflow-spin' : ''} aria-hidden="true" />Check saved status
          </button>
          <div className="workflow-actions">{actionButtons}</div>
        </footer>
      </div>
      <p className="workflow-reassurance"><History size={15} aria-hidden="true" />Continuing uses this document’s saved workflow.</p>
    </section>
  );
}
