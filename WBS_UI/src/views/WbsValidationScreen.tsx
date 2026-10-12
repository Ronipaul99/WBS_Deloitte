import { useState, useEffect, useRef } from 'react';
import {
  Check,
  RotateCw,
  Target,
  AlertTriangle,
  Lightbulb,
  AlertCircle,
  X,
  RefreshCw,
  ArrowLeft,
  PlusCircle,
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
  onCreateNew?: () => void;
}

export default function WbsValidationScreen({
  jobId,
  onBackToResults,
  onViewUnmapped,
  onCreateNew,
}: WbsValidationScreenProps) {
  const [data, setData] = useState<WbsValidationPayload | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isReRunning, setIsReRunning] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<ValidationCheckItem | null>(null);

  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);
  const modalBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadData() {
      if (!jobId) {
        if (isMounted) {
          setErrorMessage('No valid Job ID was provided for validation.');
          setIsLoading(false);
        }
        return;
      }

      setIsLoading(true);
      setErrorMessage(null);

      try {
        const res = await getWbsValidation(jobId);
        if (isMounted) {
          setData(res);
        }
      } catch (err: unknown) {
        if (isMounted) {
          setErrorMessage(err instanceof Error ? err.message : 'Failed to execute WBS validation analysis.');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadData();

    return () => {
      isMounted = false;
    };
  }, [jobId]);

  const handleManualRefresh = async () => {
    setIsReRunning(true);
    setErrorMessage(null);

    try {
      const res = await getWbsValidation(jobId);
      setData(res);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to re-run WBS validation analysis.');
    } finally {
      setIsReRunning(false);
    }
  };

  useEffect(() => {
    if (selectedIssue) {
      lastActiveElementRef.current = document.activeElement as HTMLElement;
      setTimeout(() => {
        closeButtonRef.current?.focus();
      }, 50);
    } else if (lastActiveElementRef.current) {
      lastActiveElementRef.current.focus();
    }
  }, [selectedIssue]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!selectedIssue) return;

      if (e.key === 'Escape') {
        setSelectedIssue(null);
        return;
      }

      if (e.key === 'Tab' && modalBoxRef.current) {
        const focusableElements = modalBoxRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement?.focus();
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement?.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedIssue]);

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
          boxSizing: 'border-box',
          width: '100%',
        }}
      >
        <AlertTriangle size={32} color="#DC2626" style={{ margin: '0 auto 12px auto' }} />
        <h2 style={{ fontSize: '17px', fontWeight: 600, color: '#0F172A', margin: '0 0 8px 0' }}>Validation Failed</h2>
        <p style={{ fontSize: '13px', color: '#64748B', margin: '0 0 20px 0' }}>{errorMessage || 'Unable to retrieve validation records.'}</p>
        <button
          type="button"
          onClick={handleManualRefresh}
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
    wbsItems: { count: 0, phasesCount: 0, workPackagesCount: 0 },
    scopeCoverage: { percentage: 0, mapped: 0, total: 0 },
    itemsAdded: { count: 0, subtext: 'Not in template' },
    potentialGaps: { count: 0, subtext: 'Review recommended' },
  };

  return (
    <div
      style={{
        padding: '24px clamp(16px, 3vw, 32px)',
        maxWidth: '1440px',
        margin: '0 auto',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        backgroundColor: '#F8FAFC',
        minHeight: '100%',
        boxSizing: 'border-box',
        width: '100%',
      }}
    >
      <style>{`
        .kpi-cards-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
          margin-bottom: 24px;
          width: 100%;
          box-sizing: border-box;
        }
        @media (max-width: 900px) {
          .kpi-cards-grid {
            grid-template-columns: repeat(2, 1fr) !important;
          }
        }
        @media (max-width: 480px) {
          .kpi-cards-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      {/* Top Left Navigation */}
      {onBackToResults && (
        <div style={{ marginBottom: '14px' }}>
          <button
            type="button"
            onClick={onBackToResults}
            title="Back to WBS Structure"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              background: 'none',
              border: 'none',
              color: '#64748B',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
              padding: 0,
              transition: 'color 0.15s ease'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = '#1E293B')}
            onMouseLeave={(e) => (e.currentTarget.style.color = '#64748B')}
          >
            <ArrowLeft size={16} />
            <span>Back to WBS Structure</span>
          </button>
        </div>
      )}

      {/* Header Row */}
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
            Automated checks verifying scope alignment against {data.projectName}.
          </p>
        </div>

        {/* Header Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isReRunning}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '7px 14px',
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

          {onCreateNew && (
            <button
              type="button"
              onClick={onCreateNew}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '7px 16px',
                fontSize: '12.5px',
                border: 'none',
                borderRadius: '6px',
                backgroundColor: '#1A73E8',
                color: '#FFFFFF',
                cursor: 'pointer',
                fontWeight: 600,
                boxShadow: '0 1px 2px rgba(0,0,0,0.06)'
              }}
            >
              <PlusCircle size={14} />
              <span>Create New WBS</span>
            </button>
          )}
        </div>
      </div>

      {/* 4 Summary Cards */}
      <div className="kpi-cards-grid">
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
            boxSizing: 'border-box',
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
            boxSizing: 'border-box',
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
            boxSizing: 'border-box',
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
            boxSizing: 'border-box',
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

      {/* Two-Column Responsive Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))',
          gap: '24px',
          alignItems: 'start',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        {/* Left Column: Validation Checks */}
        <div
          style={{
            backgroundColor: '#FFFFFF',
            border: '1px solid #E2E8F0',
            borderRadius: '8px',
            padding: '24px',
            boxSizing: 'border-box',
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
                    borderBottom: '1px solid #F1F5F9',
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

        {/* Right Column: Unmapped Requirements & Recommendations */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', boxSizing: 'border-box' }}>
          <div
            style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              padding: '24px',
              boxSizing: 'border-box',
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
                    gridTemplateColumns: '150px 1fr',
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
                      gridTemplateColumns: '150px 1fr',
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

          <div
            style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              padding: '24px',
              boxSizing: 'border-box',
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

      {/* Accessible Dialog with Focus Trap */}
      {selectedIssue && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="issue-modal-title"
          aria-describedby="issue-modal-desc"
          onClick={() => setSelectedIssue(null)}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(15, 23, 42, 0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            padding: '16px',
            boxSizing: 'border-box',
          }}
        >
          <div
            ref={modalBoxRef}
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: '8px',
              width: '100%',
              maxWidth: '460px',
              padding: '22px',
              boxShadow: '0 10px 25px rgba(0,0,0,0.1)',
              boxSizing: 'border-box',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h3 id="issue-modal-title" style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>
                {selectedIssue.title}
              </h3>
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="Close dialog"
                onClick={() => setSelectedIssue(null)}
                style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#94A3B8' }}
              >
                <X size={16} />
              </button>
            </div>

            <p id="issue-modal-desc" style={{ fontSize: '13px', color: '#475569', marginBottom: '20px', lineHeight: '1.6' }}>
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