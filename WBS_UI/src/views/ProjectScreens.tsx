import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  FileText,
  FolderKanban,
  Layers3,
  LoaderCircle,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import {
  deleteDocument,
  getDocumentDeletion,
  listProjectDocuments,
} from '../services/documentsApi';
import { createProject, listProjects } from '../services/projectsApi';
import { listWbsVersions } from '../services/wbsApi';
import type {
  DocumentDeletionStatusResponse,
  DocumentResponse,
  ProjectResponse,
  WbsVersionResponse,
} from '../services/workflowTypes';
import './ProjectScreens.css';
import SavedDocumentWorkflows from '../components/SavedDocumentWorkflows';
import DocumentActionsDialog from '../components/DocumentActionsDialog';

interface CreateProjectScreenProps {
  tenantId: string;
  onCreated: (project: ProjectResponse) => void;
  onCancel: () => void;
}

interface ProjectsScreenProps {
  tenantId: string;
  canCreateProject: boolean;
  onCreateProject: () => void;
  onOpenProject: (project: ProjectResponse) => void;
}

interface ProjectWorkspaceScreenProps {
  tenantId: string;
  project: ProjectResponse;
  canCreateWbs: boolean;
  canDeleteDocument: boolean;
  onBack: () => void;
  onCreateWbs: () => void;
  onOpenWbs: (versionId: string) => void;
  onResumeWorkflow?: (workflowId: string, signal?: AbortSignal) => Promise<boolean>;
}

function countWbsItems(nodes: Array<Record<string, unknown>>): number {
  return nodes.reduce((total, node) => {
    const children = Array.isArray(node.children)
      ? node.children as Array<Record<string, unknown>>
      : [];
    return total + 1 + countWbsItems(children);
  }, 0);
}

function formatCoverage(version: WbsVersionResponse): string {
  const score = version.scope_coverage.overallScore;
  return typeof score === 'number' ? `${Math.round(score)}%` : 'Not available';
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

export function CreateProjectScreen({
  tenantId,
  onCreated,
  onCancel,
}: CreateProjectScreenProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestControllerRef.current?.abort(), []);

  const trimmedName = name.trim();
  const canSubmit = trimmedName.length > 0 && !isSubmitting;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;

    setIsSubmitting(true);
    setError(null);
    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      const project = await createProject(
        tenantId,
        trimmedName,
        description.trim() || null,
        controller.signal,
      );
      onCreated(project);
    } catch (reason: unknown) {
      if (controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : 'The project could not be created.');
      setIsSubmitting(false);
    } finally {
      if (requestControllerRef.current === controller) requestControllerRef.current = null;
    }
  };

  return (
    <div className="project-page project-create-page">
      <button type="button" className="project-back-button" onClick={onCancel}>
        <ArrowLeft size={15} aria-hidden="true" />
        My Projects
      </button>

      <header className="project-page-header">
        <p className="project-eyebrow">New project</p>
        <h1>Create a project</h1>
        <p>Set up the project workspace first. You can add the scope document and generate its WBS next.</p>
      </header>

      <form className="project-form" onSubmit={handleSubmit} noValidate>
        <div className="project-form-heading">
          <span className="project-form-icon"><FolderKanban size={20} aria-hidden="true" /></span>
          <div>
            <h2>Project details</h2>
            <p>Use a clear name that your planning team will recognize.</p>
          </div>
        </div>

        {error && <div className="project-form-error" role="alert">{error}</div>}

        <label className="project-field" htmlFor="project-name">
          <span>Project name <strong aria-hidden="true">*</strong></span>
          <input
            id="project-name"
            name="projectName"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            autoComplete="off"
            autoFocus
            required
            placeholder="e.g. Smart Office Fit-Out"
          />
          <small>{name.length}/200</small>
        </label>

        <label className="project-field" htmlFor="project-description">
          <span>Description <em>Optional</em></span>
          <textarea
            id="project-description"
            name="projectDescription"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={5000}
            rows={4}
            placeholder="Briefly describe the project scope or delivery objective."
          />
          <small>{description.length}/5000</small>
        </label>

        <div className="project-form-actions">
          <button type="button" className="project-secondary-button" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </button>
          <button type="submit" className="project-primary-button" disabled={!canSubmit}>
            {isSubmitting ? (
              <><LoaderCircle size={16} className="project-spinner" /> Creating project...</>
            ) : (
              <>Create project <ArrowRight size={16} aria-hidden="true" /></>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

export function ProjectsScreen({
  tenantId,
  canCreateProject,
  onCreateProject,
  onOpenProject,
}: ProjectsScreenProps) {
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listProjects(tenantId, controller.signal)
      .then(setProjects)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Projects could not be loaded.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [tenantId, reloadKey]);

  const retryLoad = () => {
    setLoading(true);
    setError(null);
    setReloadKey((value) => value + 1);
  };

  return (
    <div className="project-page">
      <header className="project-list-header">
        <div>
          <p className="project-eyebrow">Workspace portfolio</p>
          <h1>My Projects</h1>
          <p>Open a project to manage its documents and create a WBS.</p>
        </div>
        {canCreateProject && (
          <button type="button" className="project-primary-button" onClick={onCreateProject}>
            <Plus size={16} aria-hidden="true" />
            Create project
          </button>
        )}
      </header>

      {loading ? (
        <div className="project-list-state" role="status">
          <LoaderCircle size={22} className="project-spinner" />
          Loading projects...
        </div>
      ) : error ? (
        <div className="project-list-state project-list-error" role="alert">
          <span>{error}</span>
          <button type="button" className="project-secondary-button" onClick={retryLoad}>
            <RefreshCw size={14} aria-hidden="true" /> Retry
          </button>
        </div>
      ) : projects.length === 0 ? (
        <div className="project-empty-state">
          <span><FolderKanban size={24} aria-hidden="true" /></span>
          <h2>No projects yet</h2>
          <p>Create a project to establish the workspace for its documents and WBS.</p>
          {canCreateProject && (
            <button type="button" className="project-primary-button" onClick={onCreateProject}>
              <Plus size={16} aria-hidden="true" /> Create first project
            </button>
          )}
        </div>
      ) : (
        <div className="project-list" aria-label="Projects">
          {projects.map((project) => (
            <button
              type="button"
              className="project-list-row"
              key={project.id}
              onClick={() => onOpenProject(project)}
              aria-label={`Open ${project.name}`}
            >
              <span className="project-list-mark" aria-hidden="true">
                {project.name.trim().charAt(0).toUpperCase() || 'P'}
              </span>
              <span className="project-list-copy">
                <strong>{project.name}</strong>
                <small>{project.description || 'Project planning workspace'}</small>
              </span>
              <span className="project-list-meta">
                <span>{project.status}</span>
                <time dateTime={project.updated_at}>Updated {formatDate(project.updated_at)}</time>
              </span>
              <ArrowRight size={16} className="project-list-arrow" aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ProjectWorkspaceScreen({
  tenantId,
  project,
  canCreateWbs,
  canDeleteDocument,
  onResumeWorkflow,
  onBack,
  onCreateWbs,
  onOpenWbs,
}: ProjectWorkspaceScreenProps) {
  const [versions, setVersions] = useState<WbsVersionResponse[]>([]);
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [loadingVersions, setLoadingVersions] = useState(true);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [documentReloadKey, setDocumentReloadKey] = useState(0);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [deletionStatuses, setDeletionStatuses] = useState<
    Record<string, DocumentDeletionStatusResponse>
  >({});
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedDocument, setSelectedDocument] = useState<DocumentResponse | null>(null);
  const initials = useMemo(
    () => project.name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'P',
    [project.name],
  );

  useEffect(() => {
    const controller = new AbortController();
    listWbsVersions(tenantId, project.id, controller.signal)
      .then(setVersions)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setVersionsError(reason instanceof Error ? reason.message : 'WBS versions could not be loaded.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingVersions(false);
      });
    return () => controller.abort();
  }, [project.id, reloadKey, tenantId]);

  useEffect(() => {
    const controller = new AbortController();
    listProjectDocuments(tenantId, project.id, controller.signal)
      .then(setDocuments)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setDocumentsError(
            reason instanceof Error ? reason.message : 'Project documents could not be loaded.',
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingDocuments(false);
      });
    return () => controller.abort();
  }, [documentReloadKey, project.id, tenantId]);

  useEffect(() => {
    const deletingDocuments = documents.filter(
      (document) => document.lifecycle_status === 'DELETING',
    );
    if (deletingDocuments.length === 0) return undefined;

    const controller = new AbortController();
    let timeoutId: number | undefined;
    const checkStatuses = async () => {
      try {
        const statuses = await Promise.all(
          deletingDocuments.map((document) => (
            getDocumentDeletion(tenantId, document.id, controller.signal)
          )),
        );
        if (controller.signal.aborted) return;
        setDeletionStatuses((current) => {
          const next = { ...current };
          statuses.forEach((status) => { next[status.document_id] = status; });
          return next;
        });
        const completedIds = new Set(
          statuses
            .filter((status) => status.lifecycle_status === 'DELETED')
            .map((status) => status.document_id),
        );
        if (completedIds.size > 0) {
          setDocuments((current) => current.filter((document) => !completedIds.has(document.id)));
        }
        if (statuses.every((status) => status.stage === 'COMPLETED' || status.stage === 'FAILED')) {
          return;
        }
      } catch {
        // A later bounded poll can recover transient status failures.
      }
      if (!controller.signal.aborted) timeoutId = window.setTimeout(checkStatuses, 2000);
    };
    void checkStatuses();
    return () => {
      controller.abort();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [documents, tenantId]);

  const retryVersions = () => {
    setLoadingVersions(true);
    setVersionsError(null);
    setReloadKey((value) => value + 1);
  };

  const retryDocuments = () => {
    setLoadingDocuments(true);
    setDocumentsError(null);
    setDocumentReloadKey((value) => value + 1);
  };

  const handleDeleteDocument = async (document: DocumentResponse) => {
    if (!canDeleteDocument || document.lifecycle_status !== 'ACTIVE') return;
    setDeletingDocumentId(document.id);
    setDocumentsError(null);
    try {
      await deleteDocument(tenantId, document.id);
      setDocuments((current) => current.map((item) => (
        item.id === document.id
          ? { ...item, lifecycle_status: 'DELETING', deletion_requested_at: new Date().toISOString() }
          : item
      )));
      setConfirmDeleteId(null);
    } catch {
      setDocumentsError('Deletion could not be started. Check the connection and try again.');
    } finally {
      setDeletingDocumentId(null);
    }
  };

  return (
    <div className="project-page">
      <button type="button" className="project-back-button" onClick={onBack}>
        <ArrowLeft size={15} aria-hidden="true" />
        My Projects
      </button>

      <header className="project-workspace-header">
        <span className="project-workspace-mark" aria-hidden="true">{initials}</span>
        <div className="project-workspace-title">
          <p className="project-eyebrow">Project workspace</p>
          <h1>{project.name}</h1>
          <p>{project.description || 'Add the project scope document to begin WBS generation.'}</p>
        </div>
        <span className="project-status"><ShieldCheck size={14} aria-hidden="true" /> {project.status}</span>
      </header>

      <section className="project-workspace-summary" aria-label="Project details">
        <div>
          <CalendarDays size={17} aria-hidden="true" />
          <span><small>Created</small><strong>{formatDate(project.created_at)}</strong></span>
        </div>
        <div>
          <FileText size={17} aria-hidden="true" />
          <span>
            <small>Documents</small>
            <strong>{loadingDocuments ? 'Loading...' : documents.length}</strong>
          </span>
        </div>
        <div>
          <FolderKanban size={17} aria-hidden="true" />
          <span>
            <small>WBS versions</small>
            <strong>{loadingVersions ? 'Loading...' : versions.length}</strong>
          </span>
        </div>
      </section>

      {onResumeWorkflow && <SavedDocumentWorkflows tenantId={tenantId} projectId={project.id} onContinue={onResumeWorkflow} />}

      <section className="project-document-history" aria-labelledby="project-documents-title">
        <div className="project-document-heading">
          <div>
            <p className="project-eyebrow">Source material</p>
            <h2 id="project-documents-title">Project documents</h2>
            <p>Uploaded scope documents and their lifecycle status.</p>
          </div>
        </div>

        {loadingDocuments ? (
          <div className="project-document-state" role="status">
            <LoaderCircle size={21} className="project-spinner" /> Loading project documents...
          </div>
        ) : documentsError ? (
          <div className="project-document-state project-list-error" role="alert">
            <span>{documentsError}</span>
            <button type="button" className="project-secondary-button" onClick={retryDocuments}>
              <RefreshCw size={14} aria-hidden="true" /> Retry
            </button>
          </div>
        ) : documents.length === 0 ? (
          <div className="project-document-state">
            <FileText size={21} aria-hidden="true" /> No project documents uploaded yet.
          </div>
        ) : (
          <div className="project-document-list" aria-label="Project documents">
            {documents.map((document) => {
              const status = deletionStatuses[document.id];
              const isDeleting = document.lifecycle_status === 'DELETING';
              const deletionFailed = status?.stage === 'FAILED';
              const isConfirming = confirmDeleteId === document.id;
              return (
                <div className="project-document-row" key={document.id}>
                  <span className="project-document-icon"><FileText size={16} aria-hidden="true" /></span>
                  <button type="button" className="project-document-copy project-document-open"
                    aria-label={`Open document ${document.file_name}`}
                    disabled={document.lifecycle_status !== 'ACTIVE'}
                    onClick={() => setSelectedDocument(document)}>
                    <strong title={document.file_name}>{document.file_name}</strong>
                    <small>
                      {Math.max(1, Math.ceil(document.size_bytes / 1024)).toLocaleString()} KB
                      {' · '}Uploaded {formatDate(document.created_at)}
                    </small>
                  </button>
                  <span
                    className={`project-document-status${deletionFailed ? ' is-failed' : ''}`}
                    role={isDeleting ? 'status' : undefined}
                    aria-live={isDeleting ? 'polite' : undefined}
                  >
                    {deletionFailed
                      ? 'Cleanup needs attention'
                      : isDeleting
                        ? status?.stage === 'RETRY_WAIT' ? 'Cleanup retry scheduled' : 'Deleting'
                        : 'Available'}
                  </span>
                  <span className="project-document-actions">
                    {isConfirming ? (
                      <>
                        <button
                          type="button"
                          className="project-danger-button"
                          onClick={() => void handleDeleteDocument(document)}
                          disabled={deletingDocumentId === document.id}
                        >
                          {deletingDocumentId === document.id
                            ? <LoaderCircle size={14} className="project-spinner" aria-label="Starting deletion" />
                            : <Trash2 size={14} aria-hidden="true" />}
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="project-icon-button"
                          onClick={() => setConfirmDeleteId(null)}
                          aria-label={`Cancel deletion of ${document.file_name}`}
                        >
                          <X size={15} aria-hidden="true" />
                        </button>
                      </>
                    ) : canDeleteDocument && !isDeleting ? (
                      <button
                        type="button"
                        className="project-icon-button"
                        onClick={() => setConfirmDeleteId(document.id)}
                        aria-label={`Delete ${document.file_name}`}
                        title="Delete document"
                      >
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    ) : null}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="project-wbs-history" aria-labelledby="project-wbs-title">
        <div className="project-wbs-heading">
          <div>
            <p className="project-eyebrow">Project deliverables</p>
            <h2 id="project-wbs-title">Work breakdown structures</h2>
            <p>Review every generated version or start a new WBS from another project scope document.</p>
          </div>
          {canCreateWbs && (
            <button type="button" className="project-primary-button" onClick={onCreateWbs}>
              <Plus size={16} aria-hidden="true" /> Create new WBS
            </button>
          )}
        </div>

        {loadingVersions ? (
          <div className="project-wbs-state" role="status">
            <LoaderCircle size={21} className="project-spinner" /> Loading WBS versions...
          </div>
        ) : versionsError ? (
          <div className="project-wbs-state project-list-error" role="alert">
            <span>{versionsError}</span>
            <button type="button" className="project-secondary-button" onClick={retryVersions}>
              <RefreshCw size={14} aria-hidden="true" /> Retry
            </button>
          </div>
        ) : versions.length === 0 ? (
          <div className="project-wbs-empty">
            <span><Layers3 size={23} aria-hidden="true" /></span>
            <div>
              <h3>No WBS versions yet</h3>
              <p>Create the first WBS for this project by uploading its scope document.</p>
            </div>
            {!canCreateWbs && <span className="project-read-only">Read-only access</span>}
          </div>
        ) : (
          <div className="project-wbs-list" aria-label="Previous WBS versions">
            <div className="project-wbs-list-header" aria-hidden="true">
              <span>WBS</span>
              <span>Status</span>
              <span>Items</span>
              <span>Coverage</span>
              <span>Created</span>
            </div>
            {versions.map((version) => (
              <button
                type="button"
                className="project-wbs-row"
                key={version.id}
                onClick={() => onOpenWbs(version.id)}
                aria-label={`Open WBS version ${version.version_number}`}
              >
                <span className="project-wbs-name">
                  <span className="project-wbs-version-icon"><Layers3 size={16} aria-hidden="true" /></span>
                  <span><strong>WBS version {version.version_number}</strong><small>Generated project structure</small></span>
                </span>
                <span><span className="project-wbs-status">{version.status}</span></span>
                <strong>{countWbsItems(version.tree)}</strong>
                <strong>{formatCoverage(version)}</strong>
                <time dateTime={version.created_at}>{formatDate(version.created_at)}</time>
              </button>
            ))}
          </div>
        )}
      </section>
      {selectedDocument && <DocumentActionsDialog key={selectedDocument.id} tenantId={tenantId}
        document={selectedDocument} onClose={() => setSelectedDocument(null)} onResume={onResumeWorkflow} />}
    </div>
  );
}
