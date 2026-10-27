import { useEffect, useState, useRef } from 'react';
import { 
  Check, 
  Loader2, 
  FileText, 
  AlertTriangle, 
  RefreshCw,
  ArrowLeft
} from 'lucide-react';
import {
  cancelJob,
  getJob,
} from '../services/jobsApi';
import { pollResource } from '../services/polling';
import { presentGenerationJob } from '../services/workflowPresentation';
import type { JobStatusResponse, StepStatus } from '../services/workflowTypes';
import './AnalyzingProjectScreen.css';

interface AnalyzingProjectScreenProps {
  tenantId: string;
  jobId: string;
  projectName: string;
  onAnalysisComplete?: (wbsVersionId: string) => void;
  onError?: (errorDetails: string) => void;
  onCancel?: () => void;
}

export default function AnalyzingProjectScreen({
  tenantId,
  jobId,
  projectName,
  onAnalysisComplete,
  onError,
  onCancel,
}: AnalyzingProjectScreenProps) {
  const [jobData, setJobData] = useState<JobStatusResponse | null>(null);
  const [isFatalError, setIsFatalError] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryTrigger, setRetryTrigger] = useState<number>(0);

  const isMissingJobId = !jobId || jobId.trim() === '';

  const onAnalysisCompleteRef = useRef(onAnalysisComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onAnalysisCompleteRef.current = onAnalysisComplete;
  }, [onAnalysisComplete]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    if (isMissingJobId) {
      return;
    }

    const controller = new AbortController();
    const run = async () => {
      try {
        const job = await pollResource({
          signal: controller.signal,
          request: async (signal) => {
            const nextJob = await getJob(tenantId, jobId, signal);
            setJobData(presentGenerationJob(nextJob, projectName));
            return nextJob;
          },
          isTerminal: (value) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(value.status),
        });
        if (controller.signal.aborted) return;
        if (job.status === 'COMPLETED') {
          const versionId = job.result_payload.wbs_version_id;
          if (typeof versionId !== 'string' || !versionId) {
            throw new Error('Generation completed without a WBS version identifier.');
          }
          onAnalysisCompleteRef.current?.(versionId);
          return;
        }
        const reason = job.error_message || 'WBS generation was cancelled or failed.';
        setIsFatalError(true);
        setErrorMessage(reason);
        onErrorRef.current?.(reason);
      } catch (err: unknown) {
        if (controller.signal.aborted) return;
        const reason = err instanceof Error ? err.message : 'Lost connectivity to the analysis engine.';
        setIsFatalError(true);
        setErrorMessage(reason);
        onErrorRef.current?.(reason);
      }
    };
    void run();
    return () => controller.abort();
  }, [isMissingJobId, jobId, projectName, retryTrigger, tenantId]);

  const handleManualRetry = () => {
    setIsFatalError(false);
    setErrorMessage(null);
    setRetryTrigger((prev) => prev + 1);
  };

  const handleCancel = async () => {
    try {
      await cancelJob(tenantId, jobId);
    } catch {
      // The workspace is still cleared if the server job already became terminal.
    }
    onCancel?.();
  };

  const renderIndicator = (status: StepStatus) => {
    if (status === 'COMPLETED') {
      return (
        <div className="wbs-indicator-completed" aria-label="Step completed">
          <Check size={16} strokeWidth={2.6} />
        </div>
      );
    }

    if (status === 'IN_PROGRESS') {
      return (
        <div className="wbs-indicator-in-progress" aria-label="Step in progress">
          <Loader2
            size={16}
            color="#2563EB"
            className="wbs-spinner"
          />
        </div>
      );
    }

    if (status === 'FAILED') {
      return (
        <div className="wbs-indicator-failed" aria-label="Step failed">
          <AlertTriangle size={15} color="#DC2626" />
        </div>
      );
    }

    return <div className="wbs-indicator-pending" aria-label="Step pending" />;
  };

  if (isMissingJobId) {
    return (
      <div className="wbs-missing-id-card">
        <div className="wbs-error-icon-box">
          <AlertTriangle size={24} />
        </div>
        <h2 className="wbs-card-title">Missing Job ID</h2>
        <p className="wbs-card-description">
          No active analysis job ID was provided. Please return to Step 1 and upload your project files.
        </p>
        {onCancel && (
          <button
            type="button"
            onClick={handleCancel}
            className="wbs-btn-primary"
          >
            Back to Document Upload
          </button>
        )}
      </div>
    );
  }

  if (isFatalError) {
    return (
      <div className="wbs-fatal-error-card">
        <div className="wbs-error-icon-box">
          <AlertTriangle size={24} strokeWidth={2.2} />
        </div>

        <h2 className="wbs-card-title">Analysis Pipeline Interrupted</h2>

        <p className="wbs-fatal-description">
          {errorMessage || 'The automated WBS generation process encountered an unrecoverable exception.'}
        </p>

        <div className="wbs-error-actions">
          {onCancel && (
            <button
              type="button"
              onClick={handleCancel}
              className="wbs-btn-secondary"
            >
              Cancel & Return
            </button>
          )}

          <button
            type="button"
            onClick={handleManualRetry}
            className="wbs-btn-primary"
          >
            <RefreshCw size={14} /> Retry Connection
          </button>
        </div>
      </div>
    );
  }

  if (!jobData) {
    return (
      <div className="wbs-init-loading">
        <Loader2
          size={36}
          color="#0284C7"
          className="wbs-spinner"
        />
        <p className="wbs-init-loading-text">
          Initializing AI pipeline inspection...
        </p>
      </div>
    );
  }

  const sideCardTitle = jobData.sideCard?.title || 'Decomposing Requirements';
  const sideCardDescription =
    jobData.sideCard?.description ||
    'Aligning project deliverables with WBS hierarchy standard.';

  return (
    <div className="wbs-analysis-container">
      {/* Header with Cancel Button */}
      <header className="wbs-analysis-header">
        <div className="wbs-analysis-header-row">
          <h1 className="wbs-analysis-title">{jobData.title}</h1>

          {onCancel && (
            <button
              type="button"
              onClick={handleCancel}
              className="wbs-cancel-btn"
            >
              <ArrowLeft size={14} /> Cancel Analysis
            </button>
          )}
        </div>
        <p className="wbs-analysis-subtitle">{jobData.subtitle}</p>
      </header>

      {/* Stepper Grid */}
      <div className="wbs-stepper-grid">
        <div className="wbs-stepper-track" aria-live="polite">
          {jobData.steps.map((step, index) => {
            const isLast = index === jobData.steps.length - 1;
            const isCompleted = step.status === 'COMPLETED';
            const isInProgress = step.status === 'IN_PROGRESS';
            const isFailed = step.status === 'FAILED';
            const isInactive = !isCompleted && !isInProgress && !isFailed;
            const progressVal = (step as { progress?: number }).progress;

            return (
              <div key={step.id} className="wbs-step-row">
                {!isLast && (
                  <div
                    className={`wbs-step-line ${
                      isCompleted
                        ? 'wbs-step-line-completed'
                        : isFailed
                        ? 'wbs-step-line-failed'
                        : 'wbs-step-line-pending'
                    }`}
                  />
                )}

                <div className="wbs-step-indicator-wrapper">
                  {renderIndicator(step.status)}
                </div>

                <div className="wbs-step-body">
                  <div
                    className={`wbs-step-title ${
                      isInactive ? 'wbs-step-title-inactive' : 'wbs-step-title-active'
                    }`}
                  >
                    {step.title}
                  </div>
                  <div
                    className={`wbs-step-desc ${
                      isInactive ? 'wbs-step-desc-inactive' : 'wbs-step-desc-active'
                    }`}
                  >
                    {step.description}
                  </div>

                  {isInProgress && typeof progressVal === 'number' && (
                    <div className="wbs-step-progress-track">
                      <div
                        className="wbs-step-progress-fill"
                        style={{ width: `${progressVal}%` }}
                      />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="wbs-side-card">
          <div className="wbs-side-card-icon-box">
            <FileText size={44} color="#3B82F6" strokeWidth={1.5} />
          </div>

          <h2 className="wbs-side-card-title">{sideCardTitle}</h2>
          <p className="wbs-side-card-desc">{sideCardDescription}</p>
        </div>
      </div>
    </div>
  );
}
