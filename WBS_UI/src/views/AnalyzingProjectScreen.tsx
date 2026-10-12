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
  getJobStatus,
  JobStatusResponse,
  StepStatus,
} from '../services/wbsService';
import './AnalyzingProjectScreen.css';

const MAX_NETWORK_RETRIES = 4;
const BASE_POLL_INTERVAL_MS = 1500;

interface AnalyzingProjectScreenProps {
  jobId: string;
  onAnalysisComplete?: () => void;
  onError?: (errorDetails: string) => void;
  onCancel?: () => void;
}

export default function AnalyzingProjectScreen({
  jobId,
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

    const currentJobId = jobId;
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
      if (!isActive || currentJobId !== jobId || isFetching) {
        return;
      }

      isFetching = true;

      try {
        const response = await getJobStatus(currentJobId);

        if (!isActive || currentJobId !== jobId) {
          return;
        }

        consecutiveErrors = 0;
        setJobData(response);

        if (response.overallStatus === 'COMPLETED') {
          clearTimer();
          if (onAnalysisCompleteRef.current) {
            onAnalysisCompleteRef.current();
          }
          return;
        }

        if (response.overallStatus === 'FAILED') {
          clearTimer();
          const failureReason = response.errorMessage || 
            'AI analysis pipeline failed while decomposing project specifications.';
          setIsFatalError(true);
          setErrorMessage(failureReason);
          if (onErrorRef.current) {
            onErrorRef.current(failureReason);
          }
          return;
        }

        timerId = setTimeout(poll, BASE_POLL_INTERVAL_MS);
      } catch {
        if (!isActive || currentJobId !== jobId) {
          return;
        }

        consecutiveErrors += 1;

        if (consecutiveErrors >= MAX_NETWORK_RETRIES) {
          clearTimer();
          const networkFailure = 'Lost connectivity to analysis engine. Please verify network access and retry.';
          setIsFatalError(true);
          setErrorMessage(networkFailure);
          if (onErrorRef.current) {
            onErrorRef.current(networkFailure);
          }
          return;
        }

        timerId = setTimeout(poll, BASE_POLL_INTERVAL_MS * 1.5);
      } finally {
        isFetching = false;
      }
    };

    poll();

    return () => {
      isActive = false;
      clearTimer();
    };
  }, [jobId, retryTrigger, isMissingJobId]);

  const handleManualRetry = () => {
    setIsFatalError(false);
    setErrorMessage(null);
    setRetryTrigger((prev) => prev + 1);
  };

  const renderIndicator = (status: StepStatus) => {
    if (status === 'COMPLETED') {
      return (
        <div className="wbs-indicator-completed">
          <Check size={16} strokeWidth={2.6} />
        </div>
      );
    }

    if (status === 'IN_PROGRESS') {
      return (
        <div className="wbs-indicator-in-progress">
          <Loader2
            size={16}
            color="#2563EB"
            className="wbs-spinner"
          />
        </div>
      );
    }

    return <div className="wbs-indicator-pending" />;
  };

  if (isMissingJobId) {
    return (
      <div className="wbs-missing-id-card">
        <div className="wbs-error-icon-box">
          <AlertTriangle size={24} />
        </div>
        <h2 className="wbs-card-title">
          Missing Job ID
        </h2>
        <p className="wbs-card-description">
          No active analysis job ID was provided. Please return to Step 1 and upload your project files.
        </p>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
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

        <h2 className="wbs-card-title">
          Analysis Pipeline Interrupted
        </h2>

        <p className="wbs-fatal-description">
          {errorMessage || 'The automated WBS generation process encountered an unrecoverable exception.'}
        </p>

        <div className="wbs-error-actions">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
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
            <RefreshCw size={14} />
            Retry Connection
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

  return (
    <div className="wbs-analysis-container">
      {/* Header with Cancel Button */}
      <header className="wbs-analysis-header">
        <div className="wbs-analysis-header-row">
          <h1 className="wbs-analysis-title">
            {jobData.title}
          </h1>

          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="wbs-cancel-btn"
            >
              <ArrowLeft size={14} /> Cancel Analysis
            </button>
          )}
        </div>
        <p className="wbs-analysis-subtitle">
          {jobData.subtitle}
        </p>
      </header>

      {/* Stepper Grid */}
      <div className="wbs-stepper-grid">
        <div className="wbs-stepper-track">
          {jobData.steps.map((step, index) => {
            const isLast = index === jobData.steps.length - 1;
            const isCompleted = step.status === 'COMPLETED';
            const isInactive = step.status !== 'COMPLETED' && step.status !== 'IN_PROGRESS';

            return (
              <div
                key={step.id}
                className="wbs-step-row"
              >
                {!isLast && (
                  <div
                    className={`wbs-step-line ${
                      isCompleted ? 'wbs-step-line-completed' : 'wbs-step-line-pending'
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
                </div>
              </div>
            );
          })}
        </div>

        <div className="wbs-side-card">
          <div className="wbs-side-card-icon-box">
            <FileText size={44} color="#3B82F6" strokeWidth={1.5} />
          </div>

          <h2 className="wbs-side-card-title">
            {jobData.sideCard.title}
          </h2>
          <p className="wbs-side-card-desc">
            {jobData.sideCard.description}
          </p>
        </div>
      </div>
    </div>
  );
}