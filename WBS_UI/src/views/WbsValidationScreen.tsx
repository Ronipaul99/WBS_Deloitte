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
import './WbsValidationScreen.css';

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
      <div className="wbs-state-validating">
        <RotateCw size={30} color="#1A73E8" className="wbs-validation-spin" />
        <span className="wbs-state-validating-text">Validating WBS against Primavera P6 rules...</span>
      </div>
    );
  }

  if (errorMessage || !data) {
    return (
      <div className="wbs-state-error-wrapper">
        <AlertTriangle size={32} color="#DC2626" className="wbs-state-error-icon" />
        <h2 className="wbs-state-error-title">Validation Failed</h2>
        <p className="wbs-state-error-msg">{errorMessage || 'Unable to retrieve validation records.'}</p>
        <button
          type="button"
          onClick={handleManualRefresh}
          className="wbs-retry-validation-btn"
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
    <div className="wbs-validation-container">
      {/* Top Left Navigation */}
      {onBackToResults && (
        <div className="wbs-nav-back-wrapper">
          <button
            type="button"
            onClick={onBackToResults}
            title="Back to WBS Structure"
            className="wbs-nav-back-btn"
          >
            <ArrowLeft size={16} />
            <span>Back to WBS Structure</span>
          </button>
        </div>
      )}

      {/* Header Row */}
      <div className="wbs-validation-header-row">
        <div>
          <h1 className="wbs-validation-title">
            WBS Validation
          </h1>
          <p className="wbs-validation-subtitle">
            Automated checks verifying scope alignment against {data.projectName}.
          </p>
        </div>

        {/* Header Actions */}
        <div className="wbs-validation-header-actions">
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isReRunning}
            className="wbs-btn-refresh"
          >
            <RotateCw size={13} className={isReRunning ? 'wbs-validation-spin' : undefined} />
            <span>{isReRunning ? 'Validating...' : 'Re-run Validation'}</span>
          </button>

          {onCreateNew && (
            <button
              type="button"
              onClick={onCreateNew}
              className="wbs-btn-create-new"
            >
              <PlusCircle size={14} />
              <span>Create New WBS</span>
            </button>
          )}
        </div>
      </div>

      {/* 4 Summary Cards */}
      <div className="kpi-cards-grid">
        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-green">
            <Check size={18} strokeWidth={2.5} />
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">
              {summaryCards.wbsItems.count}
            </div>
            <div className="wbs-kpi-title">
              WBS Items
            </div>
            <div className="wbs-kpi-subtext">
              {summaryCards.wbsItems.phasesCount} Phases | {summaryCards.wbsItems.workPackagesCount} Work Packages
            </div>
          </div>
        </div>

        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-blue">
            <Target size={18} />
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">
              {summaryCards.scopeCoverage.percentage}%
            </div>
            <div className="wbs-kpi-title">
              Scope Coverage
            </div>
            <div className="wbs-kpi-subtext">
              {summaryCards.scopeCoverage.mapped} of {summaryCards.scopeCoverage.total} requirements mapped
            </div>
          </div>
        </div>

        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-amber">
            <span style={{ fontSize: '16px', fontWeight: 700 }}>!</span>
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">
              {summaryCards.itemsAdded.count}
            </div>
            <div className="wbs-kpi-title">
              Items Added
            </div>
            <div className="wbs-kpi-subtext">
              {summaryCards.itemsAdded.subtext}
            </div>
          </div>
        </div>

        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-red">
            <AlertTriangle size={18} />
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">
              {summaryCards.potentialGaps.count}
            </div>
            <div className="wbs-kpi-title">
              Potential Gaps
            </div>
            <div className="wbs-kpi-subtext">
              {summaryCards.potentialGaps.subtext}
            </div>
          </div>
        </div>
      </div>

      {/* Two-Column Responsive Grid */}
      <div className="wbs-validation-main-grid">
        {/* Left Column: Validation Checks */}
        <div className="wbs-checks-card">
          <h2 className="wbs-section-title">
            Validation Results
          </h2>

          <div className="wbs-checks-list">
            {validationChecks.map((check) => {
              const isPassed = check.status === 'PASSED';
              return (
                <div key={check.id} className="wbs-check-row">
                  <div className="wbs-check-body">
                    <div
                      className={`wbs-check-status-badge ${
                        isPassed ? 'wbs-status-pass' : 'wbs-status-warn'
                      }`}
                    >
                      {isPassed ? <Check size={12} strokeWidth={3} /> : <AlertCircle size={12} strokeWidth={3} />}
                    </div>

                    <div>
                      <div className="wbs-check-name">
                        {check.title}
                      </div>
                      <div className="wbs-check-desc">
                        {check.description}
                      </div>
                    </div>
                  </div>

                  {check.actionLabel && (
                    <button
                      type="button"
                      onClick={() => setSelectedIssue(check)}
                      className="wbs-check-action-btn"
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
        <div className="wbs-right-column">
          <div className="wbs-card-standard">
            <div className="wbs-unmapped-header-row">
              <h2 className="wbs-section-title" style={{ margin: 0 }}>
                Unmapped Requirements ({unmappedCount})
              </h2>
              {onViewUnmapped && (
                <button
                  type="button"
                  onClick={onViewUnmapped}
                  className="wbs-view-all-btn"
                >
                  View All
                </button>
              )}
            </div>

            {unmappedCount === 0 ? (
              <div className="wbs-empty-unmapped-banner">
                All requirements are mapped to WBS packages.
              </div>
            ) : (
              <div className="wbs-unmapped-table">
                <div className="wbs-unmapped-table-header">
                  <span>Reference</span>
                  <span>Requirement Summary</span>
                </div>
                {unmappedRequirements.map((req, idx) => (
                  <div
                    key={idx}
                    className={`wbs-unmapped-table-row ${
                      idx === unmappedCount - 1 ? '' : 'wbs-row-border'
                    }`}
                  >
                    <span className="wbs-req-reference">{req.reference}</span>
                    <span className="wbs-req-summary">{req.summary}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="wbs-card-standard">
            <div className="wbs-rec-header-row">
              <Lightbulb size={18} color="#1A73E8" />
              <h2 className="wbs-section-title" style={{ margin: 0 }}>
                AI Recommendations
              </h2>
            </div>

            <ul className="wbs-rec-list">
              {aiRecommendations.map((rec, idx) => (
                <li key={idx} className="wbs-rec-item">
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
          className="wbs-issue-backdrop"
        >
          <div
            ref={modalBoxRef}
            onClick={(e) => e.stopPropagation()}
            className="wbs-issue-dialog-box"
          >
            <div className="wbs-issue-dialog-header">
              <h3 id="issue-modal-title" className="wbs-issue-dialog-title">
                {selectedIssue.title}
              </h3>
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="Close dialog"
                onClick={() => setSelectedIssue(null)}
                className="wbs-issue-close-btn"
              >
                <X size={16} />
              </button>
            </div>

            <p id="issue-modal-desc" className="wbs-issue-dialog-desc">
              {selectedIssue.description}
            </p>

            <div className="wbs-issue-dialog-footer">
              <button
                type="button"
                onClick={() => setSelectedIssue(null)}
                className="wbs-dialog-btn-dismiss"
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
                  className="wbs-dialog-btn-confirm"
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