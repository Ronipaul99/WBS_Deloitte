import { useId, useState, type RefObject } from 'react';
import { ArrowRight, Clock3, Files, FolderOpen, GitBranch, Loader2, ShieldCheck } from 'lucide-react';
import type { WorkflowCandidate } from '../services/workflowTypes';
import WorkflowDialog from './WorkflowDialog';
import WorkflowStatusBadge from './WorkflowStatusBadge';
import { workflowDate } from './workflowUi';

interface Props {
  candidates: WorkflowCandidate[];
  busy: boolean;
  error: string | null;
  hasTemplate: boolean;
  canUseTemplate: boolean;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  onContinue: (candidate: WorkflowCandidate, useTemplate: boolean) => void;
  onClose: () => void;
}

export default function DuplicateDocumentDialog({ candidates, busy, error, hasTemplate,
  canUseTemplate, onContinue, onClose, returnFocusRef }: Props) {
  const name = useId();
  const [selectedId, setSelectedId] = useState(candidates.find((c) => c.workflow_id)?.workflow_id);
  const selected = candidates.find((c) => c.workflow_id === selectedId && c.workflow_id);
  return (
    <WorkflowDialog title="This document already exists. Continue previous work?"
      eyebrow="Pick up where you left off" icon={<Files size={25} strokeWidth={1.7} />}
      description="We found saved work for this document. Continue from its last saved stage."
      busy={busy} onClose={onClose} returnFocusRef={returnFocusRef}
      footer={<>
        <button type="button" className="workflow-button workflow-button-secondary" disabled={busy}
          onClick={onClose}>Cancel</button>
        <button type="button" className="workflow-button workflow-button-primary"
          data-dialog-focus disabled={busy || !selected} onClick={() => selected && onContinue(selected, false)}>
          {busy ? <Loader2 size={16} className="workflow-spin" aria-hidden="true" /> : null}
          Continue previous work <ArrowRight size={16} aria-hidden="true" />
        </button>
      </>}>
      <fieldset className="workflow-choice-list" disabled={busy}>
        <legend className="workflow-field-label">{candidates.length > 1 ? 'Choose a saved workflow' : 'Your saved document'}</legend>
        {candidates.map((candidate, index) => (
          <label key={candidate.workflow_id ?? `${candidate.document_id}-${index}`}
            className={`workflow-choice${selected === candidate ? ' is-selected' : ''}${!candidate.workflow_id ? ' is-unavailable' : ''}`}>
            <input type="radio" name={name} value={candidate.workflow_id ?? ''}
              checked={selected === candidate} disabled={!candidate.workflow_id}
              onChange={() => setSelectedId(candidate.workflow_id)} />
            <span className="workflow-choice-body">
              <span className="workflow-file-title">{candidate.file_name}</span>
              <span className="workflow-meta"><FolderOpen size={14} aria-hidden="true" />{candidate.project_name}</span>
              <span className="workflow-meta"><Clock3 size={14} aria-hidden="true" />Saved {workflowDate(candidate.updated_at)}</span>
              <WorkflowStatusBadge stage={candidate.stage} />
              {candidate.requires_project_switch && <span className="workflow-project-notice">Continuing opens the original project.</span>}
              {!candidate.workflow_id && <span className="workflow-project-notice">This saved workflow is unavailable.</span>}
            </span>
          </label>
        ))}
      </fieldset>
      <div className="workflow-reassurance"><ShieldCheck size={17} aria-hidden="true" />
        <span>The existing document and saved work will be reused.</span>
      </div>
      {hasTemplate && <div className="workflow-template-note">
        <GitBranch size={18} aria-hidden="true" /><div>
          <p>Continuing keeps the saved template. Choose a new generation to use your selected template.</p>
          {canUseTemplate && <button type="button" className="workflow-text-button"
            disabled={busy || !selected} onClick={() => selected && onContinue(selected, true)}>
            Use selected template for new generation <ArrowRight size={14} aria-hidden="true" />
          </button>}
        </div>
      </div>}
      {busy && <p className="workflow-loading-copy" role="status">Opening your saved workflow…</p>}
      {error && <p className="workflow-alert" role="alert">{error}</p>}
    </WorkflowDialog>
  );
}
