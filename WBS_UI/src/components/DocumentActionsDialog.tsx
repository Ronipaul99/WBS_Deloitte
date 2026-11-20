import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Eye, FileText, LoaderCircle } from 'lucide-react';
import { documentWorkflows } from '../services/documentWorkflowsApi';
import { previewDocumentText, readDocumentFile } from '../services/documentsApi';
import type { DocumentResponse, WorkflowState } from '../services/workflowTypes';
import WorkflowDialog from './WorkflowDialog';
import WorkflowStatusBadge from './WorkflowStatusBadge';
import { workflowFileSize, workflowStageLabel } from './workflowUi';

interface Props {
  tenantId: string;
  document: DocumentResponse;
  onClose: () => void;
  onResume?: (id: string, signal?: AbortSignal) => Promise<boolean>;
}

export default function DocumentActionsDialog({ tenantId, document, onClose, onResume }: Props) {
  const [workflows, setWorkflows] = useState<WorkflowState[]>([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ url: string; type: string } | null>(null);
  const [textPreview, setTextPreview] = useState<Array<{ text: string; type: string; sheet: string | null; row: number | null }> | null>(null);
  const controller = useRef<AbortController | null>(null);
  const objectUrl = useRef<string | null>(null);

  useEffect(() => {
    const request = new AbortController();
    controller.current = request;
    documentWorkflows(tenantId, document.project_id, document.id, request.signal)
      .then((states) => {
        if (request.signal.aborted) return;
        setWorkflows(states);
        if (states.length === 1) setSelected(states[0].workflow_id);
      })
      .catch(() => {
        if (!request.signal.aborted) setLoadError('Saved workflows are unavailable. Close and reopen to retry. You can still view the document.');
      })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => {
      request.abort();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, [tenantId, document.id, document.project_id]);

  const viewDocument = async () => {
    if (preview || textPreview) return;
    setBusy(true);
    setError(null);
    try {
      const suffix = document.file_name.split('.').pop()?.toLowerCase();
      if (suffix === 'pdf') {
        const { blob } = await readDocumentFile(tenantId, document, controller.current?.signal);
        if (controller.current?.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        objectUrl.current = url;
        setPreview({ url, type: 'application/pdf' });
      } else {
        const result = await previewDocumentText(tenantId, document.id, controller.current?.signal);
        if (!controller.current?.signal.aborted) setTextPreview(result.blocks);
      }
    } catch {
      if (!controller.current?.signal.aborted) setError('The document could not be opened. Please try again.');
    } finally {
      if (!controller.current?.signal.aborted) setBusy(false);
    }
  };

  const goToWorkflow = async () => {
    if (!selected || !onResume) return;
    setBusy(true);
    setError(null);
    try {
      if (!await onResume(selected, controller.current?.signal) && !controller.current?.signal.aborted) {
        setError('This workflow could not be opened. Please try again.');
      }
    } catch {
      if (!controller.current?.signal.aborted) setError('This workflow could not be opened. Please try again.');
    } finally {
      if (!controller.current?.signal.aborted) setBusy(false);
    }
  };

  return <WorkflowDialog title="Your document" eyebrow="Project source material"
    description="View the original file or continue from its current saved workflow stage."
    icon={<FileText size={25} />} onClose={onClose} busy={busy}
    footer={<>
      <button type="button" className="workflow-button workflow-button-secondary" data-dialog-focus
        disabled={busy} onClick={() => void viewDocument()}><Eye size={16} /> {preview || textPreview ? 'Preview loaded' : 'View document'}</button>
      <button type="button" className="workflow-button workflow-button-primary"
        disabled={busy || loading || !selected || !onResume} onClick={() => void goToWorkflow()}>
        {busy ? <LoaderCircle size={16} className="workflow-spin" /> : <ArrowRight size={16} />} Go to workflow
      </button>
    </>}>
    <p className="workflow-file-title">{document.file_name}</p>
    <p className="workflow-meta">{workflowFileSize(document.size_bytes)} · Original document</p>
    {loading ? <p role="status" className="workflow-meta">Loading saved workflows…</p>
      : loadError ? <p className="workflow-alert" role="alert">{loadError}</p>
        : workflows.length === 0 ? <p className="workflow-notice">No saved workflow is available for this document.</p>
          : workflows.length === 1 ? <WorkflowStatusBadge stage={workflows[0].stage} />
            : <label className="document-workflow-select">Choose a saved workflow
              <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={busy}>
                <option value="">Select a workflow</option>
                {workflows.map((state) => <option key={state.workflow_id} value={state.workflow_id}>
                  {workflowStageLabel(state.stage)} · {state.template?.name ?? 'Default template'} · {state.workflow_id.slice(0, 8)}
                </option>)}
              </select>
            </label>}
    {error && <p role="alert" className="workflow-alert">{error}</p>}
    {preview && <div className="document-file-preview">
      <iframe src={preview.url} title={`Preview of ${document.file_name}`} />
      <a className="workflow-text-button" href={preview.url} download={document.file_name}>Download original file</a>
    </div>}
    {textPreview && <div className="document-text-preview" aria-label={`Preview of ${document.file_name}`}>
      {textPreview.map((block, index) => <p key={`${block.sheet ?? ''}-${block.row ?? ''}-${index}`}>
        {block.sheet && <strong>{block.sheet}{block.row ? ` · Row ${block.row}` : ''}: </strong>}{block.text}
      </p>)}
      {textPreview.length === 0 && <p className="workflow-notice">No readable content was found in this file.</p>}
      <button type="button" className="workflow-text-button" onClick={() => {
        void readDocumentFile(tenantId, document, controller.current?.signal).then(({ blob, fileName }) => {
          const link = URL.createObjectURL(blob);
          const anchor = window.document.createElement('a');
          anchor.href = link; anchor.download = fileName; anchor.click(); URL.revokeObjectURL(link);
        });
      }}>Download original file</button>
    </div>}
  </WorkflowDialog>;
}
