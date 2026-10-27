import { useEffect, useState, useRef, ChangeEvent, DragEvent } from 'react';
import { 
  FileUp, 
  CheckCircle, 
  AlertCircle, 
  X, 
  ArrowRight, 
  ShieldAlert, 
  FileSpreadsheet,
  Loader2,
  ArrowLeft,
} from 'lucide-react';
import { startWorkflow } from '../services/workflowApi';
import { ApiError } from '../services/apiClient';
import type { ProjectResponse, WorkflowSession } from '../services/workflowTypes';
import { useAuth } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import './CreateWbsScreen.css';

interface CreateWbsScreenProps {
  project: ProjectResponse;
  onWorkflowStarted?: (session: WorkflowSession) => void;
  onBack: () => void;
}

const MAX_UPLOAD_SIZE_MB = 25;

const ACCEPTED_PROJECT_EXTENSIONS = ['.pdf', '.docx', '.xlsx', '.csv'];
const ACCEPTED_TEMPLATE_EXTENSIONS = ['.xlsx', '.csv', '.xml'];

const UPLOAD_ERROR_MESSAGES: Record<string, string> = {
  UNSUPPORTED_DOCUMENT_FORMAT: 'Document format is not supported.',
  DOCUMENT_TYPE_MISMATCH: 'Uploaded content does not match the declared document type.',
  DOCUMENT_EMPTY: 'The uploaded document is empty.',
  DOCUMENT_TOO_LARGE: 'The uploaded document exceeds the configured size limit.',
  PDF_MALFORMED: 'The PDF structure could not be read.',
  PDF_ENCRYPTED: 'Password-protected PDFs are not supported.',
  OBJECT_STORAGE_UNAVAILABLE: 'Document storage is temporarily unavailable.',
  DOCUMENT_INGESTION_DISABLED: 'Document processing is not enabled for this environment.',
  DOCUMENT_INGESTION_UNREADY: 'Document processing is temporarily unavailable.',
};

function extractFileExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? '.' + parts.pop()!.toLowerCase() : '';
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function submissionErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code) {
    return UPLOAD_ERROR_MESSAGES[error.code] ?? 'The document upload could not be completed.';
  }
  if (error instanceof ApiError) return 'The document upload could not be completed.';
  return 'The document upload could not be completed. Please try again.';
}

export default function CreateWbsScreen({ project, onWorkflowStarted, onBack }: CreateWbsScreenProps) {
  const { activeTenant, can } = useAuth();
  const canUploadProject = can(PERMISSIONS.DOCUMENT_UPLOAD);
  const canUploadTemplate = can(PERMISSIONS.TEMPLATE_MANAGE);
  const canProcess = canUploadProject && can(PERMISSIONS.DOCUMENT_PROCESS);
  const [projectFile, setProjectFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);

  const [projectFileError, setProjectFileError] = useState<string | null>(null);
  const [templateFileError, setTemplateFileError] = useState<string | null>(null);

  const [isDraggingProject, setIsDraggingProject] = useState<boolean>(false);
  const [isDraggingTemplate, setIsDraggingTemplate] = useState<boolean>(false);

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const projectInputRef = useRef<HTMLInputElement | null>(null);
  const templateInputRef = useRef<HTMLInputElement | null>(null);
  const requestControllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestControllerRef.current?.abort(), []);

  const validateFile = (file: File, allowedExtensions: string[], maxMb: number = MAX_UPLOAD_SIZE_MB): string | null => {
    if (file.size > maxMb * 1024 * 1024) {
      return `File exceeds maximum upload size of ${maxMb}MB.`;
    }
    const ext = extractFileExtension(file.name);
    if (!allowedExtensions.includes(ext)) {
      return `Unsupported file format (${ext || 'no extension'}). Accepted formats: ${allowedExtensions.join(', ')}`;
    }
    return null;
  };

  const handleProjectSelect = (file: File) => {
    if (isSubmitting) return;
    const error = validateFile(file, ACCEPTED_PROJECT_EXTENSIONS);
    if (error) {
      setProjectFile(null);
      setProjectFileError(error);
    } else {
      setProjectFile(file);
      setProjectFileError(null);
    }
    if (projectInputRef.current) projectInputRef.current.value = '';
  };

  const handleTemplateSelect = (file: File) => {
    if (isSubmitting) return;
    const error = validateFile(file, ACCEPTED_TEMPLATE_EXTENSIONS);
    if (error) {
      setTemplateFile(null);
      setTemplateFileError(error);
    } else {
      setTemplateFile(file);
      setTemplateFileError(null);
    }
    if (templateInputRef.current) templateInputRef.current.value = '';
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>, type: 'project' | 'template') => {
    e.preventDefault();
    if (type === 'project') setIsDraggingProject(true);
    else setIsDraggingTemplate(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>, type: 'project' | 'template') => {
    e.preventDefault();
    if (type === 'project') setIsDraggingProject(false);
    else setIsDraggingTemplate(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>, type: 'project' | 'template') => {
    e.preventDefault();
    if (isSubmitting) return;
    if ((type === 'project' && !canUploadProject) || (type === 'template' && !canUploadTemplate)) return;
    if (type === 'project') setIsDraggingProject(false);
    else setIsDraggingTemplate(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (type === 'project') handleProjectSelect(file);
      else handleTemplateSelect(file);
    }
  };

  const handleGenerateClick = async () => {
    if (
      !projectFile
      || !activeTenant
      || isSubmitting
      || requestControllerRef.current
      || !canProcess
    ) return;

    setIsSubmitting(true);
    setSubmissionError(null);
    const controller = new AbortController();
    requestControllerRef.current = controller;

    try {
      const session = await startWorkflow(
        activeTenant.id,
        project,
        projectFile,
        templateFile,
        controller.signal,
      );
      onWorkflowStarted?.(session);
    } catch (err: unknown) {
      if (!controller.signal.aborted) setSubmissionError(submissionErrorMessage(err));
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        setIsSubmitting(false);
      }
    }
  };

  const isFormValid = Boolean(projectFile && !projectFileError && canProcess);

  return (
    <div className="wbs-create-container">
      <button type="button" className="wbs-back-button" onClick={onBack} disabled={isSubmitting}>
        <ArrowLeft size={15} aria-hidden="true" />
        {project.name}
      </button>
      <header className="wbs-create-header">
        <h1 className="wbs-create-title">
          Create Work Breakdown Structure
        </h1>
        <p className="wbs-create-subtitle">
          Upload the scope document for <strong>{project.name}</strong> so it can be scanned, read, and prepared securely. Add a reference WBS template when a later generation step should follow an existing hierarchy.
        </p>
      </header>

      {submissionError && (
        <div className="wbs-error-banner">
          <ShieldAlert size={18} />
          <span>{submissionError}</span>
        </div>
      )}

      {/* Upload Columns */}
      <div className="wbs-upload-grid">
        
        {/* Step 1: Project Scope */}
        <div className="wbs-upload-card">
          <div className="wbs-step-header">
            <span className="wbs-step-badge">1</span>
            <h2 className="wbs-step-title">Project Scope Document</h2>
          </div>
          <p className="wbs-step-description">
            Upload your RFP, Scope of Work, Technical Specification, or BOQ document.
          </p>

          <div 
            onDragOver={(e) => handleDragOver(e, 'project')}
            onDragLeave={(e) => handleDragLeave(e, 'project')}
            onDrop={(e) => handleDrop(e, 'project')}
            onClick={() => canUploadProject && !isSubmitting && projectInputRef.current?.click()}
            onKeyDown={(event) => {
              if (
                canUploadProject
                && !isSubmitting
                && (event.key === 'Enter' || event.key === ' ')
              ) {
                event.preventDefault();
                projectInputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={canUploadProject && !isSubmitting ? 0 : -1}
            aria-label="Upload project scope document"
            aria-disabled={!canUploadProject || isSubmitting}
            className={`wbs-dropzone ${isDraggingProject ? 'wbs-dropzone-active' : ''}`}
          >
            <FileUp size={34} color="#3B82F6" className="wbs-dropzone-icon" />
            <p className="wbs-dropzone-label">
              Click to upload or drag & drop
            </p>
            <span className="wbs-dropzone-hint">
              PDF, DOCX, XLSX, CSV up to {MAX_UPLOAD_SIZE_MB}MB
            </span>
            <input 
              ref={projectInputRef} 
              type="file" 
              accept={ACCEPTED_PROJECT_EXTENSIONS.join(',')} 
              className="wbs-file-input-hidden"
              disabled={!canUploadProject || isSubmitting}
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleProjectSelect(e.target.files[0]);
              }}
            />
          </div>

          {projectFile && (
            <div className="wbs-file-selected">
              <div className="wbs-file-info">
                <CheckCircle size={16} color="#16A34A" />
                <span className="wbs-file-name">{projectFile.name}</span>
                <span className="wbs-file-size-tag">({formatBytes(projectFile.size)})</span>
              </div>
              <button 
                type="button" 
                aria-label="Remove project file"
                disabled={isSubmitting}
                onClick={() => { 
                  setProjectFile(null); 
                  if (projectInputRef.current) projectInputRef.current.value = ''; 
                }} 
                className="wbs-remove-file-btn"
              >
                <X size={15} />
              </button>
            </div>
          )}

          {projectFileError && (
            <div className="wbs-field-error">
              <AlertCircle size={15} /> {projectFileError}
            </div>
          )}
        </div>

        {/* Step 2: Reference Template */}
        <div className="wbs-upload-card">
          <div className="wbs-step-header">
            <span className="wbs-step-badge">2</span>
            <h2 className="wbs-step-title">Reference WBS Template</h2>
            <span className="wbs-optional-label">Optional</span>
          </div>
          <p className="wbs-step-description">
            Upload your organization or domain baseline WBS hierarchy.
          </p>

          <div 
            onDragOver={(e) => handleDragOver(e, 'template')}
            onDragLeave={(e) => handleDragLeave(e, 'template')}
            onDrop={(e) => handleDrop(e, 'template')}
            onClick={() => canUploadTemplate && !isSubmitting && templateInputRef.current?.click()}
            onKeyDown={(event) => {
              if (
                canUploadTemplate
                && !isSubmitting
                && (event.key === 'Enter' || event.key === ' ')
              ) {
                event.preventDefault();
                templateInputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={canUploadTemplate && !isSubmitting ? 0 : -1}
            aria-label="Upload reference WBS template"
            aria-disabled={!canUploadTemplate || isSubmitting}
            className={`wbs-dropzone ${isDraggingTemplate ? 'wbs-dropzone-active' : ''}`}
          >
            <FileSpreadsheet size={34} color="#10B981" className="wbs-dropzone-icon" />
            <p className="wbs-dropzone-label">
              Click to upload or drag & drop
            </p>
            <span className="wbs-dropzone-hint">
              XLSX, CSV, XML (Primavera P6) up to {MAX_UPLOAD_SIZE_MB}MB
            </span>
            <input 
              ref={templateInputRef} 
              type="file" 
              accept={ACCEPTED_TEMPLATE_EXTENSIONS.join(',')} 
              className="wbs-file-input-hidden"
              disabled={!canUploadTemplate || isSubmitting}
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleTemplateSelect(e.target.files[0]);
              }}
            />
          </div>

          {templateFile && (
            <div className="wbs-file-selected">
              <div className="wbs-file-info">
                <CheckCircle size={16} color="#16A34A" />
                <span className="wbs-file-name">{templateFile.name}</span>
                <span className="wbs-file-size-tag">({formatBytes(templateFile.size)})</span>
              </div>
              <button 
                type="button" 
                aria-label="Remove template file"
                disabled={isSubmitting}
                onClick={() => { 
                  setTemplateFile(null); 
                  if (templateInputRef.current) templateInputRef.current.value = ''; 
                }} 
                className="wbs-remove-file-btn"
              >
                <X size={15} />
              </button>
            </div>
          )}

          {templateFileError && (
            <div className="wbs-field-error">
              <AlertCircle size={15} /> {templateFileError}
            </div>
          )}
        </div>
      </div>

      {/* Primary Action Button */}
      <div className="wbs-action-row">
        <button
          type="button"
          disabled={!isFormValid || isSubmitting}
          onClick={handleGenerateClick}
          className={`wbs-generate-btn ${
            isFormValid && !isSubmitting ? 'wbs-generate-btn-active' : 'wbs-generate-btn-disabled'
          }`}
        >
          {isSubmitting ? (
            <>
              <Loader2 size={16} className="wbs-spinner" />
              <span>Starting processing...</span>
            </>
          ) : (
            <>
              <span>Process Document</span>
              <ArrowRight size={16} />
            </>
          )}
        </button>
      </div>
    </div>
  );
}
