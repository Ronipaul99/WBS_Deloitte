import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, FileText, RefreshCw } from 'lucide-react';
import { useAuth } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import { getSummaryRequestStatus, validateSummaryStatus, getSummary, assertImportedSummary } from '../services/summariesApi';
import { getWorkflow } from '../services/documentWorkflowsApi';
import { sessionFromState } from '../services/workflowApi';
import { pollResource, PollingTimeoutError } from '../services/polling';
import type { ExternalSummaryStatus, ExternalSummarySubmission, WorkflowState, WorkflowSession } from '../services/workflowTypes';
import '../components/WorkflowSurfaces.css';

interface Props {
  tenantId: string;
  state: WorkflowState;
  initial: ExternalSummaryStatus | ExternalSummarySubmission;
  onBack: () => void;
  onResumed: (session: WorkflowSession) => void;
}

function label(value: ExternalSummaryStatus | null) {
  if (!value) return 'Submission pending';
  if (value.binding_state === 'STALE' || value.result_state === 'STALE') return 'Source or configuration changed';
  if (value.submission_state === 'SUBMISSION_UNKNOWN') return 'Submission outcome unknown';
  if (value.submission_state === 'REJECTED') return 'Submission failed';
  if (value.status === 'UNAVAILABLE') return 'Status unavailable';
  if (value.status === 'FAILED') return 'Summary failed';
  if (value.status === 'CANCELLED') return 'Summary cancelled';
  if (value.binding_state === 'WAITING_FOR_JOB') return 'Waiting for job visibility';
  if (value.binding_state !== 'VERIFIED') return 'Submission pending';
  if (value.result_state === 'IMPORTED') return 'Opening saved summary';
  if (value.result_state === 'IMPORT_PENDING') return 'Finalizing summary';
  if (['COMPLETED', 'completed'].includes(value.provider_status ?? '') && value.progress < 100) return 'Waiting for consistent completion';
  return value.status === 'QUEUED' ? 'Queued' : 'Generating summary';
}

export default function ExternalSummaryProgress({ tenantId, state, initial, onBack, onResumed }: Props) {
  const { can } = useAuth();
  const canRead = can(PERMISSIONS.SUMMARY_READ) && can(PERMISSIONS.JOB_READ);
  const [view, setView] = useState<ExternalSummaryStatus | null>(() => {
    if (!('binding_state' in initial)) return null;
    try { return validateSummaryStatus(initial, state.document_id, state.workflow_id, initial.request_id); }
    catch { return null; }
  });
  const [observation, setObservation] = useState<'watching' | 'paused' | 'unavailable' | 'stopped'>('watching');
  const [check, setCheck] = useState(0);
  const knownJob = useRef(initial.job_id);
  useEffect(() => {
    if (!canRead) return;
    const controller = new AbortController();
    void pollResource({
      signal: controller.signal,
      initialIntervalMs: 2_000,
      maxIntervalMs: 5_000,
      timeoutMs: 120_000,
      request: (signal) => getSummaryRequestStatus(tenantId, state.document_id, initial.request_id,
        state.workflow_id, signal, knownJob.current),
      onUpdate: (next) => {
        if (controller.signal.aborted) return;
        knownJob.current = next.job_id ?? knownJob.current;
        setView(next);
      },
      isTerminal: (next) => ['FAILED', 'CANCELLED', 'UNAVAILABLE'].includes(next.status)
        || ['INVALID', 'STALE', 'IMPORTED'].includes(next.result_state),
    }).then(async (next) => {
      if (controller.signal.aborted) return;
      if (next.result_state === 'IMPORTED') {
        const fresh = await getWorkflow(tenantId, state.workflow_id, controller.signal);
        if (fresh.document_id !== state.document_id || fresh.project_id !== state.project_id
          || fresh.resume_screen !== 'doc_summary' || !fresh.external_summary
          || fresh.external_summary.request_id !== next.request_id || fresh.external_summary.job_id !== next.job_id
          || fresh.summary_id !== next.summary_id || fresh.summary_revision !== next.summary_revision) throw new Error('Imported workflow identity changed.');
        const summary = await getSummary(tenantId, state.document_id, controller.signal);
        assertImportedSummary(summary, fresh.external_summary);
        const session = await sessionFromState(tenantId, fresh, controller.signal);
        if (!controller.signal.aborted) onResumed(session);
      } else setObservation('stopped');
    })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setObservation(reason instanceof PollingTimeoutError ? 'paused' : 'unavailable');
      });
    return () => controller.abort();
  }, [canRead, check, onResumed, state.project_id, initial.job_id, initial.request_id, state.document_id, state.workflow_id, tenantId]);

  if (!canRead) return <section className="workflow-checkpoint">
    <button type="button" className="workflow-back" onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Back to project</button>
    <p className="workflow-alert" role="alert">Summary and job read permissions are required.</p>
  </section>;
  const heading = label(view);
  const staleRead = observation === 'paused' || observation === 'unavailable';
  const verified = view?.binding_state === 'VERIFIED';
  const status = observation === 'paused' ? 'Waiting paused. Generation may still be running.'
    : observation === 'unavailable' ? 'Status read unavailable. Showing the last known update.' : heading;
  return <section className="workflow-checkpoint" aria-labelledby="external-summary-title">
    <button type="button" className="workflow-back" onClick={onBack}><ArrowLeft size={15} aria-hidden="true" />Back to project</button>
    <header className="workflow-checkpoint-header"><div>
      <p className="workflow-eyebrow">Document workflow · Summary</p>
      <h1 id="external-summary-title">Summary progress</h1>
      <p className="workflow-description">Your request is saved. Leaving this page stops status checks, not generation.</p>
    </div></header>
    <div className="workflow-panel">
      <div className="workflow-document"><span className="workflow-file-icon"><FileText size={23} aria-hidden="true" /></span>
        <div className="workflow-document-copy"><strong className="workflow-file-title">{state.document.file_name}</strong>
          <p className="workflow-meta">{state.project.name}</p></div></div>
      <div className="workflow-next summary-progress-content">
        <p className="workflow-eyebrow">{staleRead ? 'Last known status' : 'Saved request'}</p>
        <h2>{heading}</h2>
        <p role="status" aria-live="polite" aria-atomic="true">{status}</p>
        {verified && <>
          <div className="summary-progress-label"><span>{staleRead ? 'Last reported progress' : 'Reported progress'}</span><strong>{view.progress}%</strong></div>
          <div className="summary-progress-track" role="progressbar" aria-label="Summary generation progress"
            aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.progress} aria-valuetext={`${view.progress}%${staleRead ? ', last known' : ''}`}>
            <span style={{ width: `${view.progress}%` }} /></div>
          <p className="summary-current-step">Current step: <strong>{view.current_step ?? 'Not reported'}</strong></p>
        </>}
        {view?.result_state === 'IMPORT_PENDING' && <div className="workflow-notice"><p>Generation is complete. Result import is pending and review is not available yet.</p></div>}
        {view?.status === 'IN_PROGRESS' && view.progress === 100 && <div className="workflow-notice"><p>The service still reports running. 100% progress alone does not confirm completion.</p></div>}
        {view?.error_code && <p className="workflow-alert" role="alert">{view.error_message ?? 'This request needs attention in its saved workflow.'} ({view.error_code})</p>}
        {staleRead && <p className="workflow-notice">Check status to read this same request again. No new summary will be submitted.</p>}
        <dl className="summary-progress-details">
          <div><dt>Request ID</dt><dd>{initial.request_id}</dd></div>
          <div><dt>Submission</dt><dd>{view?.submission_state ?? initial.submission_state}</dd></div>
          <div><dt>Binding</dt><dd>{view?.binding_state ?? 'Not verified'}</dd></div>
          {(view?.job_id ?? initial.job_id) && <><div><dt>Job ID {verified ? '' : '(not verified)'}</dt><dd>{view?.job_id ?? initial.job_id}</dd></div>
            <div><dt>Job type</dt><dd>DOCUMENT_SUMMERIZATION</dd></div></>}
          {view && <><div><dt>Application status</dt><dd>{view.status}</dd></div>
            <div><dt>Service status</dt><dd>{view.provider_status ?? 'Not reported'}</dd></div>
            <div><dt>Attempts reported</dt><dd>{view.attempt_count}</dd></div>
            <div><dt>Last update</dt><dd><time dateTime={view.updated_at}>{new Date(view.updated_at).toLocaleString()}</time></dd></div></>}
        </dl>
      </div>
      <footer className="workflow-panel-footer"><p className="workflow-meta">Remote retry and cancellation are unavailable.</p>
        <button type="button" className="workflow-button workflow-button-secondary" disabled={!canRead || observation === 'watching'}
          onClick={() => { setObservation('watching'); setCheck((value) => value + 1); }}>
          <RefreshCw size={14} aria-hidden="true" />{observation === 'watching' && canRead ? 'Checking status…' : 'Check status'}</button></footer>
    </div>
  </section>;
}
