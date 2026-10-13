import { useEffect, useState, useRef } from 'react';
import {
  Check,
  Loader2,
  AlertTriangle,
  FileText,
  FileSpreadsheet,
  ArrowLeft,
  RefreshCw,
} from 'lucide-react';
import {
  getProcessingDocStatus,
  ProcessingDocStatusResponse,
  StepStatus,
} from '../services/wbsService';
import './ProcessingProjectDocumentScreen.css';

interface ProcessingProjectDocumentScreenProps {
  jobId: string;
  onProcessingComplete?: () => void;
  onBack?: () => void;
  onCancel?: () => void;
}

const BASE_POLL_INTERVAL_MS = 1400;
const MAX_NETWORK_RETRIES = 4;
const MAX_BACKOFF_INTERVAL_MS = 5000;

export default function ProcessingProjectDocumentScreen({
  jobId,
  onProcessingComplete,
  onBack,
  onCancel,
}: ProcessingProjectDocumentScreenProps) {
  const [data, setData] = useState<ProcessingDocStatusResponse | null>(null);
  const [isFatalError, setIsFatalError] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryTrigger, setRetryTrigger] = useState<number>(0);

  const onProcessingCompleteRef = useRef(onProcessingComplete);
  useEffect(() => {
    onProcessingCompleteRef.current = onProcessingComplete;
  }, [onProcessingComplete]);

  useEffect(() => {
    if (!jobId || jobId.trim() === '') return;

    let isActive = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;
    let consecutiveErrors = 0;
    let isFetching = false;

    const clearTimer = () => {
      if (timerId) {
        clearTimeout(timerId);
        timerId = null;
      }
    };

    const poll = async () => {
      if (!isActive || isFetching) return;
      isFetching = true;

      try {
        const response = await getProcessingDocStatus(jobId);
        if (!isActive) return;

        consecutiveErrors = 0;
        setData(response);

        if (response.overallStatus === 'COMPLETED') {
          clearTimer();
          isActive = false;
          if (onProcessingCompleteRef.current) {
            onProcessingCompleteRef.current();
          }
          return;
        }

        if (response.overallStatus === 'FAILED') {
          clearTimer();
          isActive = false;
          setIsFatalError(true);
          setErrorMessage(response.errorMessage || 'Document processing failed.');
          return;
        }

        timerId = setTimeout(poll, BASE_POLL_INTERVAL_MS);
      } catch (err: unknown) {
        if (!isActive) return;

        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_NETWORK_RETRIES) {
          clearTimer();
          isActive = false;
          setIsFatalError(true);
          setErrorMessage(
            err instanceof Error ? err.message : 'Lost connection to document processing engine.'
          );
          return;
        }

        const backoffMs = Math.min(
          BASE_POLL_INTERVAL_MS * Math.pow(1.5, consecutiveErrors),
          MAX_BACKOFF_INTERVAL_MS
        );
        timerId = setTimeout(poll, backoffMs);
      } finally {
        isFetching = false;
      }
    };

    poll();

    return () => {
      isActive = false;
      clearTimer();
    };
  }, [jobId, retryTrigger]);

  const handleManualRetry = () => {
    setIsFatalError(false);
    setErrorMessage(null);
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

  if (isFatalError) {
    return (
      <div className="wbs-proc-container">
        <div className="app-missing-job-card">
          <div className="app-missing-job-icon-box" style={{ backgroundColor: '#fee2e2', color: '#dc2626' }}>
            <AlertTriangle size={24} />
          </div>
          <h2 className="app-missing-job-title">Document Extraction Interrupted</h2>
          <p className="app-missing-job-desc">{errorMessage}</p>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
            {onCancel && (
              <button type="button" onClick={onCancel} className="wbs-proc-cancel-btn">
                Cancel
              </button>
            )}
            <button type="button" onClick={handleManualRetry} className="app-missing-job-btn">
              <RefreshCw size={14} /> Retry
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
        <span className="wbs-state-loading-text">Connecting to extraction pipeline...</span>
      </div>
    );
  }

  return (
    <div className="wbs-proc-container">
      <header className="wbs-proc-header">
        <div className="wbs-proc-header-row">
          <h1 className="wbs-proc-title">Processing Project Document</h1>
          {onCancel && (
            <button type="button" onClick={onCancel} className="wbs-proc-cancel-btn">
              Cancel
            </button>
          )}
        </div>
        <p className="wbs-proc-subtitle">
          We are extracting key information from your uploaded project file to prepare an editable summary.
        </p>
      </header>

      {/* Uploaded Documents Status Banner */}
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
      </div>

      {/* Stepper & Side Card */}
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

        {/* Side Card Matching Reference Exactly */}
        <div className="wbs-proc-side-card">
          <div className="wbs-proc-side-illustration">
            <FileText size={56} color="#2563EB" strokeWidth={1.5} />
          </div>
          <h2 className="wbs-proc-side-title">Preparing your summary draft</h2>
          <p className="wbs-proc-side-desc">
            This may take a few moments depending on file size and complexity.
          </p>
        </div>
      </div>

      <div className="wbs-proc-footer">
        {onBack && (
          <button type="button" onClick={onBack} className="wbs-proc-back-btn">
            <ArrowLeft size={14} /> Back
          </button>
        )}
      </div>
    </div>
  );
}