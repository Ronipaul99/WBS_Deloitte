import { useState, useEffect, useRef } from 'react';
import {
  Check,
  RotateCw,
  Target,
  AlertTriangle,
  Lightbulb,
  X,
  RefreshCw,
  ArrowLeft,
} from 'lucide-react';
import {
  getValidation,
  startValidation,
} from '../services/validationsApi';
import { getWbsVersion } from '../services/wbsApi';
import { pollResource } from '../services/polling';
import { presentValidation, presentWbs } from '../services/workflowPresentation';
import type {
  ProjectResponse,
  TemplateResponse,
  ValidationCheckItem,
  WbsValidationPayload,
} from '../services/workflowTypes';
import { useAuth } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import './WbsValidationScreen.css';

interface WbsValidationScreenProps {
  tenantId: string;
  validationId: string;
  project: ProjectResponse;
  template: TemplateResponse | null;
  onBackToResults?: () => void;
  onViewUnmapped?: () => void;
  onCreateNew?: () => void;
}

async function fetchCompletedValidation(
  tenantId: string,
  validationId: string,
  project: ProjectResponse,
  template: TemplateResponse | null,
  signal: AbortSignal,
): Promise<WbsValidationPayload> {
  const validation = await pollResource({
    signal,
    request: (pollSignal) => getValidation(tenantId, validationId, pollSignal),
    isTerminal: (value) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(value.status),
  });
  if (validation.status !== 'COMPLETED') {
    throw new Error('Validation was cancelled or failed.');
  }
  const version = await getWbsVersion(tenantId, validation.wbs_version_id, signal);
  const wbs = presentWbs(version, project, template);
  return presentValidation(validation, wbs);
}

export default function WbsValidationScreen({
  tenantId,
  validationId,
  project,
  template,
  onBackToResults,
  onViewUnmapped,
}: WbsValidationScreenProps) {
  const { can } = useAuth();
  const canRunValidation = can(PERMISSIONS.VALIDATION_RUN);
  const [data, setData] = useState<WbsValidationPayload | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isReRunning, setIsReRunning] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<ValidationCheckItem | null>(null);

  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);
  const modalBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function loadData() {
      if (!validationId) {
        setErrorMessage('No validation run was provided.');
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setErrorMessage(null);

      try {
        const res = await fetchCompletedValidation(
          tenantId,
          validationId,
          project,
          template,
          controller.signal,
        );
        if (!controller.signal.aborted) setData(res);
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setErrorMessage(err instanceof Error ? err.message : 'Failed to execute WBS validation analysis.');
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }

    loadData();

    return () => {
      controller.abort();
    };
  }, [project, template, tenantId, validationId]);

  const handleManualRefresh = async () => {
    if (!canRunValidation) return;
    setIsReRunning(true);
    setErrorMessage(null);

    try {
      const controller = new AbortController();
      const previous = await getValidation(tenantId, validationId, controller.signal);
      const started = await startValidation(tenantId, previous.wbs_version_id, controller.signal, true);
      const res = await fetchCompletedValidation(
        tenantId,
        started.id,
        project,
        template,
        controller.signal,
      );
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
        {canRunValidation && <button
          type="button"
          onClick={handleManualRefresh}
          className="wbs-retry-validation-btn"
        >
          <RefreshCw size={14} /> Retry Validation
        </button>}
      </div>
    );
  }

  const unmappedRequirements = data.unmappedRequirements ?? [];
  const validationChecks = data.validationChecks ?? [];
  const aiRecommendations = data.aiRecommendations ?? [];
  const summaryCards = data.summaryCards;

  return (
    <div className="wbs-validation-container">
      {/* Top Left Navigation Link */}
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

      {/* Header Row (No Breadcrumb bar) */}
      <div className="wbs-validation-header-row">
        <div>
          <h1 className="wbs-validation-title">WBS Validation</h1>
          <p className="wbs-validation-subtitle">
            AI-powered checks to ensure completeness, consistency and alignment with your template.
          </p>
        </div>

        {canRunValidation && <div className="wbs-validation-header-actions">
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isReRunning}
            className="wbs-btn-refresh-ref"
          >
            <RotateCw size={14} className={isReRunning ? 'wbs-validation-spin' : undefined} />
            <span>Re-run Validation</span>
          </button>
        </div>}
      </div>

      {/* 4 Summary KPI Cards */}
      <div className="kpi-cards-grid">
        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-green">
            <Check size={18} strokeWidth={3} />
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">{summaryCards.wbsItems.count}</div>
            <div className="wbs-kpi-title">WBS Items</div>
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
            <div className="wbs-kpi-val">{summaryCards.scopeCoverage.percentage}%</div>
            <div className="wbs-kpi-title">Scope Coverage</div>
            <div className="wbs-kpi-subtext">
              {summaryCards.scopeCoverage.mapped} of {summaryCards.scopeCoverage.total} requirements mapped
            </div>
          </div>
        </div>

        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-amber">
            <span style={{ fontSize: '15px', fontWeight: 800 }}>!</span>
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">{summaryCards.itemsAdded.count}</div>
            <div className="wbs-kpi-title">Items Added</div>
            <div className="wbs-kpi-subtext">{summaryCards.itemsAdded.subtext}</div>
          </div>
        </div>

        <div className="wbs-kpi-card">
          <div className="wbs-kpi-icon-badge wbs-kpi-badge-red">
            <AlertTriangle size={18} />
          </div>
          <div className="wbs-kpi-content">
            <div className="wbs-kpi-val">{summaryCards.potentialGaps.count}</div>
            <div className="wbs-kpi-title">Potential Gaps</div>
            <div className="wbs-kpi-subtext">{summaryCards.potentialGaps.subtext}</div>
          </div>
        </div>
      </div>

      {/* Two-Column Responsive Layout Matching Reference */}
      <div className="wbs-validation-main-grid">
        {/* Left Column: Validation Results */}
        <div className="wbs-checks-card">
          <h2 className="wbs-section-title">Validation Results</h2>

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
                      {isPassed ? (
                        <Check size={12} strokeWidth={3.2} />
                      ) : (
                        <span style={{ fontSize: '12px', fontWeight: 800 }}>!</span>
                      )}
                    </div>

                    <div>
                      <div className="wbs-check-name">{check.title}</div>
                      <div className="wbs-check-desc">{check.description}</div>
                    </div>
                  </div>

                  {check.actionLabel && (
                    <button
                      type="button"
                      onClick={() => {
                        if (check.title.toLowerCase().includes('no mapping') && onViewUnmapped) {
                          onViewUnmapped();
                        } else {
                          setSelectedIssue(check);
                        }
                      }}
                      className="wbs-check-action-link"
                    >
                      {check.actionLabel}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Unmapped & Recommendations */}
        <div className="wbs-right-column">
          <div className="wbs-card-standard">
            <div className="wbs-unmapped-header-row">
              <h2 className="wbs-section-title" style={{ margin: 0 }}>
                Unmapped Requirements ({unmappedRequirements.length})
              </h2>
              {onViewUnmapped && (
                <button
                  type="button"
                  onClick={onViewUnmapped}
                  className="wbs-view-all-link"
                >
                  View All
                </button>
              )}
            </div>

            <div className="wbs-unmapped-table">
              <div className="wbs-unmapped-table-header">
                <span>Reference</span>
                <span>Requirement Summary</span>
              </div>
              {unmappedRequirements.map((req, idx) => (
                <div
                  key={idx}
                  className={`wbs-unmapped-table-row ${
                    idx === unmappedRequirements.length - 1 ? '' : 'wbs-row-border'
                  }`}
                >
                  <span className="wbs-req-reference">{req.reference}</span>
                  <span className="wbs-req-summary">{req.summary}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="wbs-card-standard">
            <div className="wbs-rec-header-row">
              <div className="wbs-rec-bulb-icon">
                <Lightbulb size={18} color="#1A73E8" fill="#1A73E8" />
              </div>
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

      {/* Accessible Detail Dialog */}
      {selectedIssue && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setSelectedIssue(null)}
          className="wbs-issue-backdrop"
        >
          <div
            ref={modalBoxRef}
            onClick={(e) => e.stopPropagation()}
            className="wbs-issue-dialog-box"
          >
            <div className="wbs-issue-dialog-header">
              <h3 className="wbs-issue-dialog-title">{selectedIssue.title}</h3>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={() => setSelectedIssue(null)}
                className="wbs-issue-close-btn"
              >
                <X size={16} />
              </button>
            </div>
            <p className="wbs-issue-dialog-desc">{selectedIssue.description}</p>
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
