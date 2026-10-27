import { useEffect, useRef, useState } from 'react';
import {
  Check,
  Loader2,
  AlertTriangle,
  FileText,
  FileSpreadsheet,
  ArrowLeft,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { ApiError } from '../services/apiClient';
import { getCurrentIngestion } from '../services/ingestionApi';
import { PollingTimeoutError, pollResource } from '../services/polling';
import {
  isSupportedIngestionState,
  presentIngestionStatus,
} from '../services/workflowPresentation';
import type {
  DocumentResponse,
  IngestionStatusResponse,
  ProcessingDocStatusResponse,
  StepStatus,
  TemplateResponse,
} from '../services/workflowTypes';
import './ProcessingProjectDocumentScreen.css';

interface ProcessingProjectDocumentScreenProps {
  tenantId: string;
  jobId: string;
  processingRunId: string;
  document: DocumentResponse;
  template: TemplateResponse | null;
  initialStatus: IngestionStatusResponse;
  onBack: (completed: boolean) => void;
  onContinue?: () => void;
}

function safeConnectionMessage(reason: unknown): string {
  if (reason instanceof PollingTimeoutError) {
    return 'Processing is taking longer than expected. Check the status again in a moment.';
  }
  if (reason instanceof ApiError) {
    if (reason.status === 401) return 'Your session expired. Sign in again to check processing status.';
    if (reason.status === 403 || reason.status === 404) {
      return 'This document workflow is no longer available in the current workspace.';
    }
  }
  return 'The latest processing status is temporarily unavailable. Your ingestion has not been restarted.';
}

function validateStatus(
  value: IngestionStatusResponse,
  documentId: string,
  jobId: string,
  processingRunId: string,
): IngestionStatusResponse {
  if (
    value.document_id !== documentId
    || value.job_id !== jobId
    || value.processing_run_id !== processingRunId
  ) {
    throw new Error('The processing status did not match the active document workflow.');
  }
  if (!isSupportedIngestionState(value.status, value.stage)) {
    throw new Error('The processing service returned an unsupported state.');
  }
  return value;
}

export default function ProcessingProjectDocumentScreen({
  tenantId,
  jobId,
  processingRunId,
  document,
  template,
  initialStatus,
  onBack,
  onContinue,
}: ProcessingProjectDocumentScreenProps) {
  const initialStatusIsValid = initialStatus.document_id === document.id
    && initialStatus.job_id === jobId
    && initialStatus.processing_run_id === processingRunId
    && isSupportedIngestionState(initialStatus.status, initialStatus.stage);
  const [data, setData] = useState<ProcessingDocStatusResponse | null>(() => (
    initialStatusIsValid
      ? presentIngestionStatus(initialStatus, document, template, initialStatus.progress)
      : null
  ));
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [retryTrigger, setRetryTrigger] = useState(0);
  const highestProgress = useRef(initialStatusIsValid ? initialStatus.progress : 0);
  const headingRef = useRef<HTMLHeadingElement | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      try {
        setConnectionError(null);
        const status = await pollResource({
          signal: controller.signal,
          request: async (signal) => {
            const next = validateStatus(
              await getCurrentIngestion(tenantId, document.id, signal),
              document.id,
              jobId,
              processingRunId,
            );
            highestProgress.current = Math.max(highestProgress.current, next.progress);
            setData(presentIngestionStatus(next, document, template, highestProgress.current));
            return next;
          },
          isTerminal: (value) => value.status === 'COMPLETED' || value.status === 'FAILED',
        });
        if (controller.signal.aborted) return;
        highestProgress.current = Math.max(highestProgress.current, status.progress);
        setData(presentIngestionStatus(status, document, template, highestProgress.current));
      } catch (reason: unknown) {
        if (controller.signal.aborted) return;
        setConnectionError(safeConnectionMessage(reason));
      }
    };
    void run();
    return () => controller.abort();
  }, [document, jobId, processingRunId, retryTrigger, template, tenantId]);

  const handleCheckAgain = () => {
    setConnectionError(null);
    setRetryTrigger((prev) => prev + 1);
  };

  const renderIndicator = (status: StepStatus) => {
    if (status === 'COMPLETED') {
      return (
        <div className="wbs-proc-indicator wbs-proc-indicator-completed" aria-label="Completed">
          <Check size={14} strokeWidth={3} />
        </div>
      );
    }
    if (status === 'IN_PROGRESS') {
      return (
        <div className="wbs-proc-indicator wbs-proc-indicator-current" aria-label="In Progress">
          <Loader2 size={14} color="#2563EB" className="wbs-spinner" />
        </div>
      );
    }
    if (status === 'FAILED') {
      return (
        <div className="wbs-proc-indicator wbs-proc-indicator-failed" aria-label="Failed">
          <AlertTriangle size={13} color="#FFFFFF" />
        </div>
      );
    }
    return <div className="wbs-proc-indicator wbs-proc-indicator-pending" aria-label="Pending" />;
  };

  if (connectionError) {
    return (
      <div className="wbs-proc-container">
        <div className="app-missing-job-card" role="alert">
          <div className="app-missing-job-icon-box" style={{ backgroundColor: '#fee2e2', color: '#dc2626' }}>
            <AlertTriangle size={24} />
          </div>
          <h2 className="app-missing-job-title">Processing status unavailable</h2>
          <p className="app-missing-job-desc">{connectionError}</p>
          <div className="wbs-proc-error-actions">
            <button type="button" onClick={handleCheckAgain} className="app-missing-job-btn">
              <RefreshCw size={14} /> Check status again
            </button>
            <button type="button" onClick={() => onBack(false)} className="wbs-proc-back-btn">
              <ArrowLeft size={14} /> Back to project
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="wbs-state-loading" role="status" aria-live="polite">
        <Loader2 size={34} color="#0284C7" className="wbs-spinner" />
        <span className="wbs-state-loading-text">Checking document processing status...</span>
      </div>
    );
  }

  if (data.overallStatus === 'FAILED') {
    return (
      <div className="wbs-proc-container">
        <div className="app-missing-job-card" role="alert">
          <div className="app-missing-job-icon-box" style={{ backgroundColor: '#fee2e2', color: '#dc2626' }}>
            <AlertTriangle size={24} />
          </div>
          <h2 className="app-missing-job-title">Document processing stopped</h2>
          <p className="app-missing-job-desc">{data.errorMessage}</p>
          <button type="button" onClick={() => onBack(false)} className="app-missing-job-btn">
            <ArrowLeft size={14} /> Back to project
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="wbs-proc-container">
      <header className="wbs-proc-header">
        <div className="wbs-proc-header-row">
          <div>
            <h1 ref={headingRef} tabIndex={-1} className="wbs-proc-title">{data.title}</h1>
            <div className="wbs-proc-stage-label">{data.stage.replace('_', ' ').toLowerCase()}</div>
          </div>
          <span className="wbs-proc-progress-value">{data.progress}%</span>
        </div>
        <p className="wbs-proc-subtitle" aria-live="polite">{data.subtitle}</p>
        <div
          className="wbs-proc-overall-progress"
          role="progressbar"
          aria-label="Document processing progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={data.progress}
        >
          <div className="wbs-proc-overall-progress-fill" style={{ width: `${data.progress}%` }} />
        </div>
      </header>

      <div className="wbs-proc-files-banner">
        <div className="wbs-proc-file-card">
          <div className="wbs-proc-file-left">
            <div className={data.projectDoc.type === 'excel' ? 'wbs-proc-badge-excel' : 'wbs-proc-badge-pdf'}>
              {data.projectDoc.type === 'excel' ? (
                <FileSpreadsheet size={16} />
              ) : (
                <FileText size={16} />
              )}
            </div>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="wbs-proc-file-label">Project Document</div>
              <div className="wbs-proc-file-name">{data.projectDoc.name}</div>
              <div className="wbs-proc-file-size">{data.projectDoc.size}</div>
            </div>
          </div>
          <div className="wbs-proc-tag-success">
            <Check size={14} /> Uploaded successfully
          </div>
        </div>

        {data.templateDoc && (
          <div className="wbs-proc-file-card">
            <div className="wbs-proc-file-left">
              <div className="wbs-proc-badge-excel">
                <FileSpreadsheet size={16} />
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="wbs-proc-file-label">WBS Reference Template</div>
                <div className="wbs-proc-file-name">{data.templateDoc.name}</div>
                <div className="wbs-proc-file-size">{data.templateDoc.size}</div>
              </div>
            </div>
            <div className="wbs-proc-tag-success">
              <Check size={14} /> Uploaded successfully
            </div>
          </div>
        )}
      </div>

      <div className="wbs-proc-grid">
        <div className="wbs-proc-steps-card">
          <h2 className="wbs-proc-steps-title">Processing Steps</h2>
          <div aria-live="polite">
            {data.steps.map((step, idx) => {
              const isLast = idx === data.steps.length - 1;
              const isCompleted = step.status === 'COMPLETED';

              return (
                <div key={step.id} className="wbs-proc-step-row">
                  {!isLast && (
                    <div
                      className={`wbs-proc-line ${
                        isCompleted ? 'wbs-proc-line-completed' : ''
                      }`}
                    />
                  )}
                  {renderIndicator(step.status)}
                  <div className="wbs-proc-step-content">
                    <div className="wbs-proc-step-name">{step.title}</div>
                    <div className="wbs-proc-step-desc">{step.description}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="wbs-proc-side-card">
          <div className="wbs-proc-side-illustration">
            {data.overallStatus === 'COMPLETED'
              ? <ShieldCheck size={56} color="#16803c" strokeWidth={1.5} />
              : <FileText size={56} color="#2563EB" strokeWidth={1.5} />}
          </div>
          <h2 className="wbs-proc-side-title">{data.sideCard.title}</h2>
          <p className="wbs-proc-side-desc">{data.sideCard.description}</p>
          {data.overallStatus === 'PROCESSING' && (
            <p className="wbs-proc-background-note">You can leave this page and return without restarting processing.</p>
          )}
        </div>
      </div>

      <div className="wbs-proc-footer">
        {data.overallStatus === 'COMPLETED' && onContinue && (
          <button type="button" className="app-missing-job-btn" onClick={onContinue}>Continue saved work</button>
        )}
        <button
          type="button"
          onClick={() => onBack(data.overallStatus === 'COMPLETED')}
          className={data.overallStatus === 'COMPLETED' ? 'app-missing-job-btn' : 'wbs-proc-back-btn'}
        >
          <ArrowLeft size={14} /> Back to project
        </button>
      </div>
    </div>
  );
}
