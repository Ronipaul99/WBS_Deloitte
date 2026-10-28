import { useEffect, useRef, useState, type RefObject } from 'react';
import {
  Check,
  Sparkles,
  ChevronRight,
  FileText,
  ArrowRight,
  Loader2,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import {
  approveSummary,
  approveStructuredSummary,
  assertImportedSummary,
  isStructuredSummary,
  getSummary,
  updateSummary,
} from '../services/summariesApi';
import { ApiError } from '../services/apiClient';
import { getWorkflow } from '../services/documentWorkflowsApi';
import WorkflowDialog from '../components/WorkflowDialog';
import { startGeneration } from '../services/generationsApi';
import { presentSummary, summaryUpdateFromSections } from '../services/workflowPresentation';
import type {
  DocumentResponse,
  ExternalSummaryStatus,
  ProjectResponse,
  ProjectSummaryResponse,
  SummarySectionItem,
  TemplateResponse,
} from '../services/workflowTypes';
import { useAuth } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import './ReviewProjectSummaryScreen.css';

export type ReviewProjectSummaryScreenProps = {
  tenantId: string;
  project: ProjectResponse;
  document: DocumentResponse;
  template: TemplateResponse | null;
  workflowId?: string;
  expectedExternal?: ExternalSummaryStatus | null;
  navigationGuardRef?: RefObject<((proceed: () => void) => void) | null>;
  onProceedToAnalyze?: (generationJobId: string, summaryId: string) => void;
  onDiscard?: () => void;
};

const WORKFLOW_STAGES = [
  { key: 'create', label: 'Upload', stepNum: 1 },
  { key: 'doc_processing', label: 'Process Document', stepNum: 2 },
  { key: 'doc_summary', label: 'Review Summary', stepNum: 3 },
  { key: 'analyzing', label: 'Analyze Project', stepNum: 4 },
  { key: 'results', label: 'WBS Builder', stepNum: 5 },
  { key: 'validation', label: 'Validation', stepNum: 6 },
] as const;

function extractExtensionBadge(filename?: string): string {
  if (!filename) return 'FILE';
  const parts = filename.split('.');
  if (parts.length > 1) {
    const ext = parts.pop()?.toUpperCase() || '';
    if (ext === 'DOCX' || ext === 'DOC') return 'DOC';
    if (ext === 'XLSX' || ext === 'XLS' || ext === 'CSV') return 'XLS';
    return ext.slice(0, 4);
  }
  return 'FILE';
}

function getConfidenceSubtext(score: number): string {
  if (score >= 80) return 'Content was successfully extracted with high confidence.';
  if (score >= 60) return 'Content extracted with moderate confidence. Please review carefully.';
  return 'Low confidence extraction. Manual editing strongly recommended.';
}

export default function ReviewProjectSummaryScreen({
  tenantId,
  project,
  document,
  template,
  workflowId,
  expectedExternal,
  navigationGuardRef,
  onProceedToAnalyze,
  onDiscard,
}: ReviewProjectSummaryScreenProps) {
  const { can } = useAuth();
  const canUpdateSummary = can(PERMISSIONS.SUMMARY_UPDATE);
  const canGenerateWbs = can(PERMISSIONS.SUMMARY_APPROVE) && can(PERMISSIONS.WBS_GENERATE);
  const [data, setData] = useState<ProjectSummaryResponse | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<number | string>(1);
  const [editableSections, setEditableSections] = useState<SummarySectionItem[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isProceeding, setIsProceeding] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [confirm, setConfirm] = useState<'discard' | 'refresh' | null>(null);
  const [conflict, setConflict] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const mutationPending = useRef(false);
  const pendingNavigation = useRef<(() => void) | null>(null);
  const dirty = !!data && editableSections.some((s) => s.content !== data.sections.find((saved) => saved.id === s.id)?.content);
  useEffect(() => {
    if (!navigationGuardRef) return;
    navigationGuardRef.current = (proceed) => {
      if (!dirty) { proceed(); return; }
      pendingNavigation.current = proceed;
      setConfirm('discard');
    };
    return () => { navigationGuardRef.current = null; };
  }, [dirty, navigationGuardRef]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  useEffect(() => {
    let isActive = true;
    const loading = new AbortController();
    controller.current = loading;

    async function load() {
      try {
        setLoadError(null);
        const summary = await getSummary(tenantId, document.id, loading.signal);
        if (isStructuredSummary(summary) && !workflowId) throw new Error('The imported summary workflow is unavailable.');
        if (workflowId && (isStructuredSummary(summary) || expectedExternal)) {
          const current = await getWorkflow(tenantId, workflowId, loading.signal);
          if (isStructuredSummary(summary) || current.external_summary) {
            if (!isStructuredSummary(summary) || !current.external_summary || current.resume_screen !== 'doc_summary'
              || current.document_id !== document.id || current.project_id !== project.id
              || (expectedExternal && (current.external_summary.request_id !== expectedExternal.request_id
                || current.external_summary.job_id !== expectedExternal.job_id))
              || current.summary_id !== summary.id || current.summary_revision !== summary.revision
              || summary.structured_summary.generated_result.data.project_id !== project.id) {
              throw new Error('The imported summary is stale or unavailable. Refresh saved status.');
            }
            assertImportedSummary(summary, current.external_summary);
          }
        }
        if (!isActive) return;
        const res = presentSummary(summary, project, document);
        setData(res);
        setConflict(false);
        setSaveError(null);
        setSaveSuccess(false);
        setEditableSections(res.sections || []);
        if (res.sections && res.sections.length > 0) {
          setActiveSectionId(res.sections[0].id);
        }
      } catch (err: unknown) {
        if (!isActive) return;
        setLoadError(
          err instanceof Error ? err.message : 'Failed to retrieve project summary from the server.'
        );
      }
    }

    load();

    return () => {
      isActive = false;
      loading.abort();
      controller.current?.abort();
    };
  }, [document, project, retryNonce, tenantId, workflowId, expectedExternal]);

  if (loadError) {
    return (
      <div className="wbs-rev-container">
        <div className="app-missing-job-card">
          <div className="app-missing-job-icon-box">
            <AlertTriangle size={24} />
          </div>
          <h2 className="app-missing-job-title">Unable to Load Summary</h2>
          <p className="app-missing-job-desc">{loadError}</p>
          <div className="wbs-rev-error-actions">
            {onDiscard && (
              <button type="button" onClick={onDiscard} className="wbs-rev-btn-discard">
                Back to Document Upload
              </button>
            )}
            <button
              type="button"
              onClick={() => setRetryNonce((prev) => prev + 1)}
              className="app-missing-job-btn"
            >
              <RefreshCw size={14} /> Retry Connection
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="wbs-state-loading">
        <Loader2 size={34} color="#0284C7" className="wbs-spinner" />
        <span className="wbs-state-loading-text">Loading extracted project summary...</span>
      </div>
    );
  }

  const currentSection =
    editableSections.find((s) => s.id === activeSectionId) ||
    editableSections[0] || {
      id: 1, order: 1, maxLength: 2000,
      title: 'Summary Details',
      content: '',
      pages: [],
    };

  const handleContentChange = (val: string) => {
    setSaveSuccess(false);
    setSaveError(null);
    setEditableSections((prev) =>
      prev.map((s) => (s.id === currentSection.id ? { ...s, content: val } : s))
    );
  };

  const structured = isStructuredSummary(data.summary) ? data.summary : null;
  const overLimit = structured !== null && editableSections.some((s) => Array.from(s.content).length > s.maxLength);
  const savedState = (summary: typeof data.summary) => {
    const next = presentSummary(summary, project, document);
    setData(next);
    setEditableSections(next.sections);
    setConflict(false);
    setSaveSuccess(true);
  };
  const handleSaveDraft = async () => {
    if (!canUpdateSummary || mutationPending.current || overLimit) return;
    mutationPending.current = true;
    setIsSaving(true);
    setSaveError(null);
    const signal = controller.current?.signal;
    try {
      const payload = structured ? {
        format: 'external_summary_v1' as const, expected_revision: structured.revision,
        sections: editableSections.filter((s) => s.content !== data.sections.find((saved) => saved.id === s.id)?.content)
          .map((s) => ({ id: String(s.id), key: s.key!, content: s.content })),
      } : summaryUpdateFromSections(data.summary, editableSections);
      const summary = await updateSummary(tenantId, document.id, payload, signal);
      if (signal?.aborted) return;
      if (summary.id !== data.summary.id || (structured && (!isStructuredSummary(summary)
        || summary.provenance.request_id !== structured.provenance.request_id
        || summary.provenance.job_id !== structured.provenance.job_id
        || summary.provenance.processing_run_id !== structured.provenance.processing_run_id
        || ![structured.revision, structured.revision + 1].includes(summary.revision)))) throw new Error('The saved summary identity changed. Refresh and review.');
      savedState(summary);
    } catch (err: unknown) {
      if (signal?.aborted) return;
      setConflict(err instanceof ApiError && err.status === 409);
      setSaveError(err instanceof Error ? err.message : 'Failed to save summary draft changes.');
    } finally {
      mutationPending.current = false;
      if (!signal?.aborted) setIsSaving(false);
    }
  };
  const handleApprove = async () => {
    if (!structured || dirty || mutationPending.current || !can(PERMISSIONS.SUMMARY_APPROVE)) return;
    mutationPending.current = true;
    setIsProceeding(true); setSaveError(null);
    const signal = controller.current?.signal;
    try {
      const summary = await approveStructuredSummary(tenantId, document.id, structured.revision, signal);
      if (signal?.aborted) return;
      if (!isStructuredSummary(summary) || summary.id !== structured.id || summary.revision !== structured.revision
        || summary.provenance.request_id !== structured.provenance.request_id) throw new Error('Approval response does not match the reviewed revision.');
      savedState(summary);
    } catch (err: unknown) {
      if (signal?.aborted) return;
      setConflict(err instanceof ApiError && err.status === 409); setSaveError(err instanceof Error ? err.message : 'Unable to approve this revision.');
    } finally {
      mutationPending.current = false;
      if (!signal?.aborted) setIsProceeding(false);
    }
  };

  const handleProceed = async () => {
    if (structured || !canGenerateWbs || isProceeding) return;
    setIsProceeding(true);
    setSaveError(null);
    try {
      const updated = canUpdateSummary
        ? await updateSummary(
          tenantId,
          document.id,
          summaryUpdateFromSections(data.summary, editableSections),
        )
        : data.summary;
      const approved = await approveSummary(tenantId, document.id);
      const generation = await startGeneration(tenantId, project.id, {
        documentId: document.id,
        summaryId: approved.id || updated.id,
        templateId: template?.id ?? null,
        workflowId,
      });
      onProceedToAnalyze?.(generation.id, approved.id);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Unable to approve the summary and start WBS generation.');
    } finally {
      setIsProceeding(false);
    }
  };

  const fileBadge = extractExtensionBadge(data.document?.name);

  return (
    <div className="wbs-rev-container">
      <header className="wbs-rev-header">
        <h1 className="wbs-rev-title">Review Project Summary</h1>
        <p className="wbs-rev-subtitle">
          {structured ? 'Review the source-linked draft. Human approval is separate from factual verification.' : 'Review and edit the extracted summary before generating the WBS.'}
        </p>
      </header>

      {/* Dynamic Horizontal Flow Stepper */}
      <div className="wbs-rev-flow-stepper">
        {WORKFLOW_STAGES.map((stage, idx) => {
          const isPast = stage.stepNum < 3;
          const isCurrent = stage.stepNum === 3;

          return (
            <div key={stage.key} className="wbs-rev-flow-node-group">
              <div className="wbs-rev-flow-node">
                <div
                  className={`wbs-rev-flow-badge ${
                    isPast
                      ? 'wbs-rev-flow-badge-done'
                      : isCurrent
                      ? 'wbs-rev-flow-badge-active'
                      : 'wbs-rev-flow-badge-pending'
                  }`}
                >
                  {isPast && <Check size={12} strokeWidth={3} />}
                  {isCurrent && <span className="wbs-rev-flow-dot" />}
                </div>
                <div>
                  <div
                    className={`wbs-rev-flow-text-main ${
                      isCurrent ? 'wbs-rev-flow-text-active' : ''
                    }`}
                  >
                    {stage.label}
                  </div>
                  <div
                    className={`wbs-rev-flow-text-sub ${
                      isCurrent ? 'wbs-rev-flow-text-sub-active' : ''
                    }`}
                  >
                    {isPast ? 'Completed' : isCurrent ? 'In Progress' : 'Not Started'}
                  </div>
                </div>
              </div>
              {idx < WORKFLOW_STAGES.length - 1 && <div className="wbs-rev-flow-divider" />}
            </div>
          );
        })}
      </div>

      {saveError && (
        <div className="wbs-error-banner" role="alert" style={{ marginBottom: 16 }}>
          <AlertTriangle size={16} />
          <span>{saveError}</span>
        </div>
      )}

      {conflict && <p className="wbs-rev-review-notice">Your local text has been retained. <button type="button" className="wbs-rev-btn-save" onClick={() => setConfirm('refresh')}>Refresh and review saved version</button></p>}
      {structured && <p className="wbs-rev-review-notice" role="status">Revision {structured.revision} · {structured.is_approved ? 'Human-approved' : 'Awaiting human review'}{dirty ? ' · Unsaved changes' : ''}</p>}
      {/* 2-Column Content */}
      <div className="wbs-rev-body-grid">
        <div className="wbs-rev-sections-card">
          <div className="wbs-rev-sections-header">Project Summary Sections</div>
          {editableSections.map((sec) => {
            const isActive = sec.id === activeSectionId;
            return (
              <button
                type="button"
                key={sec.id}
                aria-current={isActive ? 'true' : undefined}
                onClick={() => setActiveSectionId(sec.id)}
                className={`wbs-rev-section-btn ${isActive ? 'wbs-rev-section-btn-active' : ''}`}
              >
                <div className="wbs-rev-section-btn-left">
                  <span
                    className={`wbs-rev-num-bubble ${
                      isActive ? 'wbs-rev-num-bubble-active' : ''
                    }`}
                  >
                    {sec.order}
                  </span>
                  <span className="wbs-rev-section-name">{sec.title}</span>
                </div>
                <ChevronRight size={14} color={isActive ? '#2563EB' : '#94A3B8'} />
              </button>
            );
          })}
        </div>

        <div className="wbs-rev-editor-card">
          <div className="wbs-rev-editor-top">
            <h2 id="summary-section-heading" className="wbs-rev-editor-title">{currentSection.title}</h2>
            <span className="wbs-rev-badge-ai">
              <Sparkles size={11} /> AI Draft
            </span>
          </div>
          <p className="wbs-rev-editor-desc">{structured ? 'Editable draft · original evidence preserved' : 'Editable AI-generated summary'}</p>
          {structured && <div className="wbs-rev-review-notice">
            <p>{currentSection.answerStatus === 'answered' ? 'Answered in generated draft' : 'Insufficient evidence in generated draft'}</p>
            {currentSection.truncated && <p>Evidence context was limited. Review the original evidence carefully.</p>}
            {currentSection.content !== currentSection.originalContent && <p>{structured.is_approved ? 'Human-edited content.' : 'Edited content requires review.'} Original citations do not establish support for edited claims.</p>}
          </div>}

          <textarea
            rows={10}
            maxLength={structured ? undefined : currentSection.maxLength}
            aria-labelledby="summary-section-heading"
            aria-describedby="summary-character-count"
            aria-invalid={Array.from(currentSection.content).length > currentSection.maxLength}
            className="wbs-rev-textarea"
            value={currentSection.content}
            readOnly={!canUpdateSummary || isSaving || isProceeding}
            onChange={(e) => handleContentChange(e.target.value)}
            placeholder="No content extracted for this section."
          />
          <div id="summary-character-count" className="wbs-rev-char-count">
            {Array.from(currentSection.content).length}/{currentSection.maxLength}
          </div>

          <div className="wbs-rev-ref-box">
            <div className="wbs-rev-ref-title">Source References</div>
            <p className="wbs-rev-ref-desc">
              {currentSection.referencesLabel ?? 'Content extracted from the following pages in your document:'}
            </p>
            <div>
              {currentSection.pages && currentSection.pages.length > 0 ? (
                currentSection.pages.map((page, i) => (
                  <span key={i} className="wbs-rev-pill-page">
                    <FileText size={12} /> {page}
                  </span>
                ))
              ) : (
                <span className="wbs-rev-pill-page-muted">No specific page references cited</span>
              )}
            </div>
          </div>

          {structured && <div className="wbs-rev-citations">
            <h3>Original generated evidence</h3>
            <p>Physical pages describe chunk coverage, not exact quote positions. Citation numbering is local to this section.</p>
            <p className="wbs-rev-citation-preview">{currentSection.content.split(/(\[\d+\])/g).map((part, index) => {
              const match = /^\[(\d+)\]$/.exec(part);
              const citation = match && currentSection.citations?.find((c) => c.citation_number === Number(match[1]));
              return citation ? <a key={index} href={`#citation-${currentSection.order}-${citation.citation_number}`}>{part}</a> : <span key={index}>{part}</span>;
            })}</p>
            {Array.from(currentSection.content.matchAll(/\[(\d+)\]/g)).some((m) => !currentSection.citations?.some((c) => c.citation_number === Number(m[1]))) && <p role="status">Unresolved citation markers remain plain text; no matching original evidence is recorded.</p>}
            {currentSection.citations?.map((citation) => <details key={citation.citation_number} id={`citation-${currentSection.order}-${citation.citation_number}`}>
              <summary>Citation [{citation.citation_number}] · Physical pages {citation.pages.join(', ')}</summary>
              <blockquote>{citation.quote}</blockquote>
            </details>)}
          </div>}

          <div className="wbs-rev-meta-box">
            <div className="wbs-rev-meta-left">
              <div className="wbs-rev-meta-badge-file">
                {fileBadge}
              </div>
              <div>
                <div className="wbs-rev-doc-name">{data.document?.name || 'Document'}</div>
                <div className="wbs-rev-doc-size">{data.document?.size || '0 MB'}</div>
              </div>
            </div>

            <div className="wbs-rev-confidence-right">
              <div className="wbs-rev-confidence-label-row">
                <span>Extraction Confidence</span>
                <span>{data.confidenceScore === null ? 'Not recorded' : `${data.confidenceScore}%`}</span>
              </div>
              <div className="wbs-rev-confidence-track" hidden={data.confidenceScore === null}>
                <div
                  className="wbs-rev-confidence-fill"
                  style={{ width: `${data.confidenceScore ?? 0}%` }}
                />
              </div>
              <span className="wbs-rev-confidence-subtext">
                {structured ? 'Extraction confidence is not summary accuracy or human approval.' : getConfidenceSubtext(data.confidenceScore ?? 0)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {structured && <div className="wbs-rev-provenance">
        <p>Model: {structured.structured_summary.generated_result.data.llm_model} · Question set: {structured.structured_summary.generated_result.data.question_set_id}</p>
        <p>Processing run: {structured.provenance.processing_run_id}</p>
        <p>{structured.structured_summary.generated_result.data.document_information.confidence_status}</p>
        <p>WBS generation is unavailable: this summary has no supported requirements register.</p>
      </div>}
      {overLimit && <p role="alert">A section exceeds its saved character limit. Text is preserved; shorten it before saving.</p>}
      <div className="wbs-rev-actions-row">
        {onDiscard && (
          <button type="button" onClick={() => dirty ? setConfirm('discard') : onDiscard?.()} className="wbs-rev-btn-discard">
            Discard Changes
          </button>
        )}
        {canUpdateSummary && (
          <button
            type="button"
            disabled={isSaving || isProceeding || overLimit || conflict}
            onClick={handleSaveDraft}
            className={`wbs-rev-btn-save ${saveSuccess ? 'wbs-rev-btn-save-success' : ''}`}
          >
            {isSaving ? (
              'Saving...'
            ) : saveSuccess ? (
              <>
                <Check size={14} /> Saved!
              </>
            ) : (
              'Save Draft'
            )}
          </button>
        )}
        {structured && <>
          {can(PERMISSIONS.SUMMARY_APPROVE) && <button type="button" className="wbs-rev-btn-save" disabled={dirty || isSaving || isProceeding || conflict || structured.is_approved} onClick={() => void handleApprove()}>{structured.is_approved ? 'Approved' : 'Approve summary'}</button>}
          <button type="button" className="wbs-rev-btn-generate" disabled title="No supported requirements register is available.">Generate WBS</button>
        </>}
        {!structured && onProceedToAnalyze && canGenerateWbs && (
          <button type="button" disabled={isSaving || isProceeding} onClick={handleProceed} className="wbs-rev-btn-generate">
            {isProceeding ? <><Loader2 size={14} className="wbs-spinner" /><span>Starting...</span></> : <><span>Generate WBS</span> <ArrowRight size={14} /></>}
          </button>
        )}
      </div>
      {confirm && <WorkflowDialog eyebrow="Unsaved draft" icon={<AlertTriangle size={25} />} children={<p>Choose Keep editing to preserve your local text.</p>} title={confirm === 'refresh' ? 'Review saved version?' : 'Discard unsaved changes?'} description="Your unsaved text will be discarded. Original generated evidence remains saved." onClose={() => { setConfirm(null); pendingNavigation.current = null; }}
        footer={<><button type="button" className="workflow-button workflow-button-secondary" onClick={() => { setConfirm(null); pendingNavigation.current = null; }}>Keep editing</button><button type="button" className="workflow-button workflow-button-primary" onClick={() => { const action = confirm; setConfirm(null); if (action === 'refresh') setRetryNonce((n) => n + 1); else { const proceed = pendingNavigation.current; pendingNavigation.current = null; if (proceed) proceed(); else onDiscard?.(); } }}>Discard changes</button></>} />}
    </div>
  );
}
