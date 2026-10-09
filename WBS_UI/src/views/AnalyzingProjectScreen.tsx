import { useEffect, useState, useRef, useCallback } from 'react';
import { 
  Check, 
  Loader2, 
  FileText, 
  AlertTriangle, 
  RefreshCw 
} from 'lucide-react';
import {
  getJobStatus,
  JobStatusResponse,
  StepStatus,
} from '../services/wbsService';

const MAX_NETWORK_RETRIES = 4;
const BASE_POLL_INTERVAL_MS = 1500;

interface AnalyzingProjectScreenProps {
  jobId?: string;
  onAnalysisComplete?: () => void;
  onError?: (errorDetails: string) => void;
  onCancel?: () => void;
}

export default function AnalyzingProjectScreen({
  jobId = 'job_wbs_89412',
  onAnalysisComplete,
  onError,
  onCancel,
}: AnalyzingProjectScreenProps) {
  const [jobData, setJobData] = useState<JobStatusResponse | null>(null);
  const [isFatalError, setIsFatalError] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // References to eliminate memory leaks, closure lag, and duplicate in-flight requests
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isFetchingRef = useRef<boolean>(false);
  const consecutiveErrorsRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const isFatalErrorRef = useRef<boolean>(false);

  const clearActiveTimer = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const executePoll = useCallback(async () => {
    // In-flight guard: prevent duplicate requests or executions after unmount/failure
    if (!isMountedRef.current || isFetchingRef.current || isFatalErrorRef.current) {
      return;
    }

    isFetchingRef.current = true;

    try {
      const response = await getJobStatus(jobId);

      if (!isMountedRef.current) return;

      consecutiveErrorsRef.current = 0;
      setJobData(response);

      // 1. Success Terminal Condition
      if (response.overallStatus === 'COMPLETED') {
        clearActiveTimer();
        if (onAnalysisComplete) {
          onAnalysisComplete();
        }
        return;
      }

      // 2. Failure Terminal Condition
      if ((response.overallStatus as string) === 'FAILED') {
        clearActiveTimer();
        const failureReason = 
          (response as { errorMessage?: string | null }).errorMessage || 
          'AI analysis pipeline failed while decomposing project specifications.';
        
        isFatalErrorRef.current = true;
        setIsFatalError(true);
        setErrorMessage(failureReason);
        if (onError) {
          onError(failureReason);
        }
        return;
      }

      // 3. Adaptive Schedule: only queues next check after current request successfully returns
      timeoutRef.current = setTimeout(executePoll, BASE_POLL_INTERVAL_MS);
    } catch (err: unknown) {
      if (!isMountedRef.current) return;

      consecutiveErrorsRef.current += 1;
      console.warn(`[WBS Poller] Request failed (${consecutiveErrorsRef.current}/${MAX_NETWORK_RETRIES})`, err);

      if (consecutiveErrorsRef.current >= MAX_NETWORK_RETRIES) {
        clearActiveTimer();
        const networkFailure = 'Lost connectivity to analysis engine. Please verify network access and retry.';
        isFatalErrorRef.current = true;
        setIsFatalError(true);
        setErrorMessage(networkFailure);
        if (onError) {
          onError(networkFailure);
        }
        return;
      }

      // Exponential backoff retry cadence on intermittent drops
      timeoutRef.current = setTimeout(executePoll, BASE_POLL_INTERVAL_MS * 1.5);
    } finally {
      isFetchingRef.current = false;
    }
  }, [jobId, onAnalysisComplete, onError]);

  useEffect(() => {
    isMountedRef.current = true;
    consecutiveErrorsRef.current = 0;
    isFatalErrorRef.current = false;
    setIsFatalError(false);
    setErrorMessage(null);

    executePoll();

    return () => {
      isMountedRef.current = false;
      clearActiveTimer();
    };
  }, [jobId, executePoll]);

  const handleManualRetry = () => {
    clearActiveTimer();
    consecutiveErrorsRef.current = 0;
    isFatalErrorRef.current = false;
    setIsFatalError(false);
    setErrorMessage(null);
    executePoll();
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

    // Default indicator for unstarted / pending steps
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

  // Initial loading state
  if (!jobData && !isFatalError) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '380px',
          gap: '14px',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <style>{`
          @keyframes wbsSpin {
            from {
              transform: rotate(0deg);
            }
            to {
              transform: rotate(360deg);
            }
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

  // Fatal / Interrupted Pipeline View
  if (isFatalError) {
    return (
      <div
        style={{
          padding: '40px 32px',
          maxWidth: '650px',
          margin: '40px auto',
          backgroundColor: '#FFFFFF',
          borderRadius: '10px',
          border: '1px solid #FCA5A5',
          boxShadow: '0 4px 12px rgba(220, 38, 38, 0.06)',
          textAlign: 'center',
          fontFamily: 'system-ui, -apple-system, sans-serif',
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
          {errorMessage || 'The automated WBS generation process encountered an unrecoverable server exception.'}
        </p>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
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

  // Schema-safe fallbacks
  const safeTitle = jobData?.title || 'Analyzing Project & Generating WBS';
  const safeSubtitle = jobData?.subtitle || 'Processing contract documents, extracting scope items, and aligning with reference template...';
  const safeSteps = jobData?.steps || [];
  const safeSideCard = jobData?.sideCard || {
    title: 'Decomposing Requirements',
    description: 'The neural parser is correlating RFP deliverables with your standard WBS hierarchy.',
  };

  return (
    <div
      style={{
        padding: '36px 48px',
        maxWidth: '1150px',
        margin: '0 auto',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      <style>{`
        @keyframes wbsSpin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }
        .wbs-spinner {
          animation: wbsSpin 0.9s linear infinite !important;
          transform-origin: center center !important;
          display: block !important;
        }
      `}</style>

      {/* Screen Header */}
      <header style={{ marginBottom: '36px' }}>
        <h1
          style={{
            fontSize: '24px',
            fontWeight: 600,
            color: '#0F172A',
            margin: '0 0 6px 0',
          }}
        >
          {safeTitle}
        </h1>
        <p style={{ fontSize: '14px', color: '#64748B', margin: 0 }}>
          {safeSubtitle}
        </p>
      </header>

      {/* 2-Column Responsive Layout */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '48px',
          alignItems: 'start',
        }}
      >
        {/* Left Side: Pipeline Stepper */}
        <div
          style={{
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {safeSteps.map((step, index) => {
            const isLast = index === safeSteps.length - 1;
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

        {/* Right Side: Processing Info Card */}
        <div
          style={{
            backgroundColor: '#F8FAFC',
            borderRadius: '12px',
            border: '1px solid #E2E8F0',
            padding: '48px 32px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            minHeight: '340px',
          }}
        >
          <div
            style={{
              width: '100px',
              height: '120px',
              backgroundColor: '#EEF2F6',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '24px',
            }}
          >
            <FileText size={48} color="#3B82F6" strokeWidth={1.5} />
          </div>

          <h2
            style={{
              fontSize: '15px',
              fontWeight: 600,
              color: '#0F172A',
              marginBottom: '8px',
            }}
          >
            {safeSideCard.title}
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
            {safeSideCard.description}
          </p>
        </div>
      </div>
    </div>
  );
}