import { useEffect, useState } from 'react';
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
  getSummary,
  updateSummary,
} from '../services/summariesApi';
import { startGeneration } from '../services/generationsApi';
import { presentSummary, summaryUpdateFromSections } from '../services/workflowPresentation';
import type {
  DocumentResponse,
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
  onProceedToAnalyze?: (generationJobId: string, summaryId: string) => void;
  onDiscard?: () => void;
};

const MAX_SECTION_CHARS = 2000;

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
  onProceedToAnalyze,
  onDiscard,
}: ReviewProjectSummaryScreenProps) {
  const { can } = useAuth();
  const canUpdateSummary = can(PERMISSIONS.SUMMARY_UPDATE);
  const canGenerateWbs = can(PERMISSIONS.SUMMARY_APPROVE) && can(PERMISSIONS.WBS_GENERATE);
  const [data, setData] = useState<ProjectSummaryResponse | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<number>(1);
  const [editableSections, setEditableSections] = useState<SummarySectionItem[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [isProceeding, setIsProceeding] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let isActive = true;

    async function load() {
      try {
        setLoadError(null);
        const summary = await getSummary(tenantId, document.id);
        if (!isActive) return;
        const res = presentSummary(summary, project, document);
        setData(res);
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
    };
  }, [document, project, retryNonce, tenantId]);

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
      id: 1,
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

  const handleSaveDraft = async () => {
    if (!canUpdateSummary) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      const summary = await updateSummary(
        tenantId,
        document.id,
        summaryUpdateFromSections(data.summary, editableSections),
      );
      setData((current) => current ? { ...current, summary } : current);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save summary draft changes.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleProceed = async () => {
    if (!canGenerateWbs || isProceeding) return;
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
          Review and edit the extracted summary before generating the WBS.
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
        <div className="wbs-error-banner" style={{ marginBottom: 16 }}>
          <AlertTriangle size={16} />
          <span>{saveError}</span>
        </div>
      )}

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
                onClick={() => setActiveSectionId(sec.id)}
                className={`wbs-rev-section-btn ${isActive ? 'wbs-rev-section-btn-active' : ''}`}
              >
                <div className="wbs-rev-section-btn-left">
                  <span
                    className={`wbs-rev-num-bubble ${
                      isActive ? 'wbs-rev-num-bubble-active' : ''
                    }`}
                  >
                    {sec.id}
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
            <h2 className="wbs-rev-editor-title">{currentSection.title}</h2>
            <span className="wbs-rev-badge-ai">
              <Sparkles size={11} /> AI Draft
            </span>
          </div>
          <p className="wbs-rev-editor-desc">Editable AI-generated summary</p>

          <textarea
            rows={10}
            maxLength={MAX_SECTION_CHARS}
            className="wbs-rev-textarea"
            value={currentSection.content}
            disabled={!canUpdateSummary}
            onChange={(e) => handleContentChange(e.target.value)}
            placeholder="No content extracted for this section."
          />
          <div className="wbs-rev-char-count">
            {currentSection.content.length}/{MAX_SECTION_CHARS}
          </div>

          <div className="wbs-rev-ref-box">
            <div className="wbs-rev-ref-title">Source References</div>
            <p className="wbs-rev-ref-desc">
              Content extracted from the following pages in your document:
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
                <span>{data.confidenceScore}%</span>
              </div>
              <div className="wbs-rev-confidence-track">
                <div
                  className="wbs-rev-confidence-fill"
                  style={{ width: `${data.confidenceScore}%` }}
                />
              </div>
              <span className="wbs-rev-confidence-subtext">
                {getConfidenceSubtext(data.confidenceScore)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="wbs-rev-actions-row">
        {onDiscard && (
          <button type="button" onClick={onDiscard} className="wbs-rev-btn-discard">
            Discard Changes
          </button>
        )}
        {canUpdateSummary && (
          <button
            type="button"
            disabled={isSaving || isProceeding}
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
        {onProceedToAnalyze && canGenerateWbs && (
          <button type="button" disabled={isSaving || isProceeding} onClick={handleProceed} className="wbs-rev-btn-generate">
            {isProceeding ? <><Loader2 size={14} className="wbs-spinner" /><span>Starting...</span></> : <><span>Generate WBS</span> <ArrowRight size={14} /></>}
          </button>
        )}
      </div>
    </div>
  );
}
