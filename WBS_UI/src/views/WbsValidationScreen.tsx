import { useState, useEffect, useCallback } from 'react';
import {
  Check,
  RotateCw,
  Target,
  AlertTriangle,
  Lightbulb,
  AlertCircle,
  X,
  RefreshCw,
} from 'lucide-react';
import {
  getWbsValidation,
  WbsValidationPayload,
  ValidationCheckItem,
} from '../services/wbsService';

interface WbsValidationScreenProps {
  jobId: string;
  onBackToResults?: () => void;
  onViewUnmapped?: () => void;
}

export default function WbsValidationScreen({
  jobId,
  onBackToResults,
  onViewUnmapped,
}: WbsValidationScreenProps) {
  const [data, setData] = useState<WbsValidationPayload | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isReRunning, setIsReRunning] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<ValidationCheckItem | null>(null);

  const fetchValidationData = useCallback(async (isManualRefresh = false) => {
    if (!jobId) {
      setErrorMessage('No valid Job ID was provided for validation.');
      setIsLoading(false);
      return;
    }

    if (isManualRefresh) setIsReRunning(true);
    else setIsLoading(true);

    setErrorMessage(null);

    try {
      const res = await getWbsValidation(jobId);
      setData(res);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to execute WBS validation analysis.');
    } finally {
      setIsLoading(false);
      setIsReRunning(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchValidationData();
  }, [fetchValidationData]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedIssue(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '420px',
          gap: '12px',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <RotateCw size={30} color="#1A73E8" style={{ animation: 'spin 1s linear infinite' }} />
        <span style={{ fontSize: '13px', color: '#64748B' }}>Validating WBS against Primavera P6 rules...</span>
      </div>
    );
  }

  if (errorMessage || !data) {
    return (
      <div
        style={{
          padding: '40px 32px',
          maxWidth: '500px',
          margin: '40px auto',
          textAlign: 'center',
          backgroundColor: '#FFFFFF',
          borderRadius: '8px',
          border: '1px solid #FCA5A5',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <AlertTriangle size={32} color="#DC2626" style={{ margin: '0 auto 12px auto' }} />
        <h2 style={{ fontSize: '17px', fontWeight: 600, color: '#0F172A', margin: '0 0 8px 0' }}>Validation Failed</h2>
        <p style={{ fontSize: '13px', color: '#64748B', margin: '0 0 20px 0' }}>{errorMessage || 'Unable to retrieve validation records.'}</p>
        <button
          onClick={() => fetchValidationData()}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 16px',
            backgroundColor: '#1A73E8',
            color: '#FFFFFF',
            borderRadius: '6px',
            border: 'none',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: 600,
          }}
        >
          <RefreshCw size={14} /> Retry Validation
        </button>
      </div>
    );
  }

  const unmappedRequirements = data.unmappedRequirements ?? [];
  const unmappedCount = unmappedRequirements.length;
  const validationChecks = data.validationChecks ?? [];
  const aiRecommendations = data.aiRecommendations ?? [];
  const summaryCards = data.summaryCards ?? {
    wbsItems: { count: 87, phasesCount: 6, workPackagesCount: 24 },
    scopeCoverage: { percentage: 91, mapped: 102, total: 112 },
    itemsAdded: { count: 5, subtext: 'Not in template' },
    potentialGaps: { count: 2, subtext: 'Review recommended' },
  };

  return (
    <div
      style={{
        padding: '24px 32px',
        maxWidth: '1440px',
        margin: '0 auto',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        backgroundColor: '#F8FAFC',
        minHeight: '100%',
      }}
    >
      {/* Header & Re-run Button */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px',
          marginBottom: '20px',
        }}
      >
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#0F172A', margin: '0 0 4px 0' }}>
            WBS Validation
          </h1>
          <p style={{ fontSize: '13px', color: '#64748B', margin: 0 }}>
            AI-powered checks to ensure completeness, consistency and alignment with your template.
          </p>
        </div>

        <button
          type="button"
          onClick={() => fetchValidationData(true)}
          disabled={isReRunning}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 16px',
            fontSize: '12.5px',
            border: '1px solid #CBD5E1',
            borderRadius: '6px',
            backgroundColor: '#FFFFFF',
            color: '#1E293B',
            cursor: isReRunning ? 'not-allowed' : 'pointer',
            fontWeight: 500,
          }}
        >
          <RotateCw size={13} style={{ animation: isReRunning ? 'spin 1s linear infinite' : 'none' }} />
          <span>{isReRunning ? 'Validating...' : 'Re-run Validation'}</span>
        </button>
      </div>

      {/* All 4 Summary KPI Cards in ONE Line */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gap: '16px',
          marginBottom: '24px',
        }}
      >
        {/* Card 1: WBS Items */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '18px 20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '14px',
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: '#16A34A',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Check size={18} strokeWidth={2.5} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#0F172A', lineHeight: 1 }}>
              {summaryCards.wbsItems.count}
            </div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', marginTop: '4px', whiteSpace: 'nowrap' }}>
              WBS Items
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {summaryCards.wbsItems.phasesCount} Phases | {summaryCards.wbsItems.workPackagesCount} Work Packages
            </div>
          </div>
        </div>

        {/* Card 2: Scope Coverage */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '18px 20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '14px',
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: '#2563EB',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Target size={18} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#0F172A', lineHeight: 1 }}>
              {summaryCards.scopeCoverage.percentage}%
            </div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', marginTop: '4px', whiteSpace: 'nowrap' }}>
              Scope Coverage
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {summaryCards.scopeCoverage.mapped} of {summaryCards.scopeCoverage.total} requirements mapped
            </div>
          </div>
        </div>

        {/* Card 3: Items Added */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '18px 20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '14px',
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: '#F59E0B',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: '16px', fontWeight: 700 }}>!</span>
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#0F172A', lineHeight: 1 }}>
              {summaryCards.itemsAdded.count}
            </div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', marginTop: '4px', whiteSpace: 'nowrap' }}>
              Items Added
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {summaryCards.itemsAdded.subtext}
            </div>
          </div>
        </div>

        {/* Card 4: Potential Gaps */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '18px 20px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '14px',
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: '#DC2626',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <AlertTriangle size={18} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '24px', fontWeight: 700, color: '#0F172A', lineHeight: 1 }}>
              {summaryCards.potentialGaps.count}
            </div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', marginTop: '4px', whiteSpace: 'nowrap' }}>
              Potential Gaps
            </div>
            <div style={{ fontSize: '11px', color: '#64748B', marginTop: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {summaryCards.potentialGaps.subtext}
            </div>
          </div>
        </div>
      </div>

      {/* Lower Two-Column Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(380px, 1fr) minmax(420px, 1.2fr)',
          gap: '24px',
          alignItems: 'start',
        }}
      >
        {/* Left Column: Validation Results */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '24px',
          }}
        >
          <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#0F172A', margin: '0 0 16px 0' }}>
            Validation Results
          </h2>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {validationChecks.map((check) => {
              const isPassed = check.status === 'PASSED';
              return (
                <div
                  key={check.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 0',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                    <div
                      style={{
                        width: '20px',
                        height: '20px',
                        borderRadius: '50%',
                        backgroundColor: isPassed ? '#16A34A' : '#F59E0B',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#FFFFFF',
                        flexShrink: 0,
                        marginTop: '2px',
                      }}
                    >
                      {isPassed ? <Check size={12} strokeWidth={3} /> : <AlertCircle size={12} strokeWidth={3} />}
                    </div>

                    <div>
                      <div style={{ fontSize: '13.5px', fontWeight: 600, color: '#1E293B' }}>
                        {check.title}
                      </div>
                      <div style={{ fontSize: '12px', color: '#64748B', marginTop: '2px' }}>
                        {check.description}
                      </div>
                    </div>
                  </div>

                  {check.actionLabel && (
                    <button
                      type="button"
                      onClick={() => setSelectedIssue(check)}
                      style={{
                        border: 'none',
                        background: 'none',
                        color: '#1A73E8',
                        fontSize: '12.5px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        padding: '4px 6px',
                      }}
                    >
                      {check.actionLabel}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Unmapped Requirements & AI Recommendations */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* Top Card: Unmapped Requirements */}
          <div
            style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              padding: '24px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
                Unmapped Requirements ({unmappedCount})
              </h2>
              {onViewUnmapped && (
                <button
                  type="button"
                  onClick={onViewUnmapped}
                  style={{
                    border: 'none',
                    background: 'none',
                    color: '#1A73E8',
                    fontSize: '12.5px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  View All
                </button>
              )}
            </div>

            {unmappedCount === 0 ? (
              <div style={{ padding: '12px 14px', backgroundColor: '#F0FDF4', color: '#15803D', borderRadius: '6px', fontSize: '12.5px' }}>
                All requirements are mapped to WBS packages.
              </div>
            ) : (
              <div style={{ border: '1px solid #E2E8F0', borderRadius: '6px', overflow: 'hidden' }}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '130px 1fr',
                    padding: '8px 14px',
                    backgroundColor: '#F8FAFC',
                    borderBottom: '1px solid #E2E8F0',
                    fontSize: '12px',
                    fontWeight: 600,
                    color: '#64748B',
                  }}
                >
                  <span>Reference</span>
                  <span>Requirement Summary</span>
                </div>
                {unmappedRequirements.map((req, idx) => (
                  <div
                    key={idx}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '130px 1fr',
                      padding: '10px 14px',
                      fontSize: '12.5px',
                      borderBottom: idx === unmappedCount - 1 ? 'none' : '1px solid #F1F5F9',
                      alignItems: 'center',
                    }}
                  >
                    <span style={{ fontWeight: 600, color: '#0F172A' }}>{req.reference}</span>
                    <span style={{ color: '#475569' }}>{req.summary}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Bottom Card: AI Recommendations */}
          <div
            style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              padding: '24px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
              <Lightbulb size={18} color="#1A73E8" />
              <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
                AI Recommendations
              </h2>
            </div>

            <ul
              style={{
                margin: 0,
                paddingLeft: '18px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}
            >
              {aiRecommendations.map((rec, idx) => (
                <li key={idx} style={{ fontSize: '13px', color: '#334155', lineHeight: '1.5' }}>
                  {rec}
                </li>
              ))}
            </ul>
          </div>

        </div>
      </div>

      {/* Issue Modal */}
      {selectedIssue && (
        <div
          onClick={() => setSelectedIssue(null)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(15, 23, 42, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '8px',
              width: '460px',
              padding: '22px',
              boxShadow: '0 10px 25px rgba(0,0,0,0.1)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>{selectedIssue.title}</h3>
              <button
                type="button"
                onClick={() => setSelectedIssue(null)}
                style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#94A3B8' }}
              >
                <X size={16} />
              </button>
            </div>

            <p style={{ fontSize: '13px', color: '#475569', marginBottom: '20px', lineHeight: '1.6' }}>
              {selectedIssue.description}
            </p>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setSelectedIssue(null)}
                style={{
                  padding: '6px 14px',
                  borderRadius: '5px',
                  border: '1px solid #CBD5E1',
                  backgroundColor: '#FFFFFF',
                  fontSize: '12.5px',
                  cursor: 'pointer',
                }}
              >
                Close
              </button>
              {onBackToResults && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedIssue(null);
                    onBackToResults();
                  }}
                  style={{
                    padding: '6px 14px',
                    borderRadius: '5px',
                    border: 'none',
                    backgroundColor: '#1A73E8',
                    color: '#FFFFFF',
                    fontSize: '12.5px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Go to Structure
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}