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
        <div
          style={{
            width: '28px',
            height: '28px',
            borderRadius: '50%',
            backgroundColor: '#16A34A',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFFFFF',
            zIndex: 2,
            transition: 'all 0.35s ease-in-out',
            boxShadow: '0 0 0 3px #DCFCE7',
          }}
        >
          <Check size={16} strokeWidth={2.6} />
        </div>
      );
    }

    if (status === 'IN_PROGRESS') {
      return (
        <div
          style={{
            width: '28px',
            height: '28px',
            borderRadius: '50%',
            border: '2.5px solid #2563EB',
            backgroundColor: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 2,
            boxShadow: '0 0 0 3px #DBEAFE',
          }}
        >
          <Loader2
            size={16}
            color="#2563EB"
            className="wbs-spinner"
          />
        </div>
      );
    }

    return (
      <div
        style={{
          width: '28px',
          height: '28px',
          borderRadius: '50%',
          backgroundColor: '#CBD5E1',
          zIndex: 2,
          transition: 'all 0.3s ease',
        }}
      />
    );
  };

  if (isMissingJobId) {
    return (
      <div
        style={{
          padding: '40px 24px',
          maxWidth: '600px',
          margin: '40px auto',
          backgroundColor: '#FFFFFF',
          borderRadius: '10px',
          border: '1px solid #E2E8F0',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.05)',
          textAlign: 'center',
          boxSizing: 'border-box',
          width: '100%',
        }}
      >
        <div
          style={{
            width: '48px',
            height: '48px',
            backgroundColor: '#FEF2F2',
            color: '#DC2626',
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 16px auto',
          }}
        >
          <AlertTriangle size={24} />
        </div>
        <h2 style={{ fontSize: '18px', fontWeight: 600, color: '#0F172A', margin: '0 0 8px 0' }}>
          Missing Job ID
        </h2>
        <p style={{ fontSize: '13px', color: '#64748B', lineHeight: '1.6', margin: '0 0 20px 0' }}>
          No active analysis job ID was provided. Please return to Step 1 and upload your project files.
        </p>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: '8px 18px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: '6px',
              border: 'none',
              backgroundColor: '#0284C7',
              color: '#FFFFFF',
              cursor: 'pointer',
            }}
          >
            Back to Document Upload
          </button>
        )}
      </div>
    );
  }

  if (isFatalError) {
    return (
      <div
        style={{
          padding: '40px 24px',
          maxWidth: '650px',
          margin: '40px auto',
          backgroundColor: '#FFFFFF',
          borderRadius: '10px',
          border: '1px solid #FCA5A5',
          boxShadow: '0 4px 12px rgba(220, 38, 38, 0.06)',
          textAlign: 'center',
          boxSizing: 'border-box',
          width: '100%',
        }}
      >
        <div
          style={{
            width: '48px',
            height: '48px',
            backgroundColor: '#FEE2E2',
            color: '#DC2626',
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 16px auto',
          }}
        >
          <AlertTriangle size={24} strokeWidth={2.2} />
        </div>

        <h2 style={{ fontSize: '18px', fontWeight: 600, color: '#0F172A', margin: '0 0 8px 0' }}>
          Analysis Pipeline Interrupted
        </h2>

        <p style={{ fontSize: '13px', color: '#64748B', lineHeight: '1.6', margin: '0 0 24px 0' }}>
          {errorMessage || 'The automated WBS generation process encountered an unrecoverable exception.'}
        </p>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px', flexWrap: 'wrap' }}>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              style={{
                padding: '8px 18px',
                fontSize: '13px',
                fontWeight: 500,
                borderRadius: '6px',
                border: '1px solid #CBD5E1',
                backgroundColor: '#FFFFFF',
                color: '#475569',
                cursor: 'pointer',
              }}
            >
              Cancel & Return
            </button>
          )}

          <button
            type="button"
            onClick={handleManualRetry}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 18px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: '6px',
              border: 'none',
              backgroundColor: '#0284C7',
              color: '#FFFFFF',
              cursor: 'pointer',
            }}
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
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '380px',
          gap: '14px',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <style>{`
          @keyframes wbsSpin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          .wbs-spinner {
            animation: wbsSpin 0.9s linear infinite !important;
            transform-origin: center center !important;
            display: block !important;
          }
        `}</style>
        <Loader2
          size={36}
          color="#0284C7"
          className="wbs-spinner"
        />
        <p style={{ fontSize: '13.5px', color: '#64748B', margin: 0, fontWeight: 500 }}>
          Initializing AI pipeline inspection...
        </p>
      </div>
    );
  }

  return (
    <div
      style={{
        padding: '24px clamp(16px, 3vw, 36px)',
        maxWidth: '1150px',
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      <style>{`
        @keyframes wbsSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .wbs-spinner {
          animation: wbsSpin 0.9s linear infinite !important;
          transform-origin: center center !important;
          display: block !important;
        }
      `}</style>

      {/* Header with Cancel Button */}
      <header style={{ marginBottom: '32px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', marginBottom: '6px' }}>
          <h1
            style={{
              fontSize: '22px',
              fontWeight: 700,
              color: '#0F172A',
              margin: 0,
              letterSpacing: '-0.3px',
            }}
          >
            {jobData.title}
          </h1>

          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid #CBD5E1',
                backgroundColor: '#FFFFFF',
                color: '#475569',
                fontSize: '12px',
                fontWeight: 500,
                cursor: 'pointer'
              }}
            >
              <ArrowLeft size={14} /> Cancel Analysis
            </button>
          )}
        </div>
        <p style={{ fontSize: '13.5px', color: '#64748B', margin: 0 }}>
          {jobData.subtitle}
        </p>
      </header>

      {/* Stepper Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 280px), 1fr))',
          gap: '32px',
          alignItems: 'start',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            width: '100%',
            boxSizing: 'border-box',
          }}
        >
          {jobData.steps.map((step, index) => {
            const isLast = index === jobData.steps.length - 1;
            const isCompleted = step.status === 'COMPLETED';
            const isInactive = step.status !== 'COMPLETED' && step.status !== 'IN_PROGRESS';

            return (
              <div
                key={step.id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  minHeight: '62px',
                  position: 'relative',
                }}
              >
                {!isLast && (
                  <div
                    style={{
                      position: 'absolute',
                      top: '28px',
                      left: '13px',
                      bottom: '0px',
                      width: '2px',
                      backgroundColor: isCompleted ? '#16A34A' : '#E2E8F0',
                      transition: 'background-color 0.4s ease',
                      zIndex: 1,
                    }}
                  />
                )}

                <div style={{ marginRight: '16px', flexShrink: 0 }}>
                  {renderIndicator(step.status)}
                </div>

                <div style={{ paddingBottom: '18px' }}>
                  <div
                    style={{
                      fontSize: '14px',
                      fontWeight: 600,
                      color: isInactive ? '#94A3B8' : '#1E293B',
                      lineHeight: '20px',
                      transition: 'color 0.3s ease',
                    }}
                  >
                    {step.title}
                  </div>
                  <div
                    style={{
                      fontSize: '13px',
                      color: isInactive ? '#CBD5E1' : '#64748B',
                      marginTop: '2px',
                      transition: 'color 0.3s ease',
                    }}
                  >
                    {step.description}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            backgroundColor: '#F8FAFC',
            borderRadius: '12px',
            border: '1px solid #E2E8F0',
            padding: '40px 24px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            minHeight: '320px',
            boxSizing: 'border-box',
            width: '100%',
          }}
        >
          <div
            style={{
              width: '90px',
              height: '110px',
              backgroundColor: '#EEF2F6',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '20px',
            }}
          >
            <FileText size={44} color="#3B82F6" strokeWidth={1.5} />
          </div>

          <h2
            style={{
              fontSize: '15px',
              fontWeight: 600,
              color: '#0F172A',
              marginBottom: '8px',
            }}
          >
            {jobData.sideCard.title}
          </h2>
          <p
            style={{
              fontSize: '13px',
              color: '#64748B',
              maxWidth: '280px',
              lineHeight: '1.5',
              margin: 0,
            }}
          >
            {jobData.sideCard.description}
          </p>
        </div>
      </div>
    </div>
  );
}