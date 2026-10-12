import { useState, useRef, ChangeEvent, DragEvent } from 'react';
import { 
  FileUp, 
  CheckCircle, 
  AlertCircle, 
  X, 
  ArrowRight, 
  ShieldAlert, 
  FileSpreadsheet 
} from 'lucide-react';
import { createWbsGenerationJob } from '../services/wbsService';
import './CreateWbsScreen.css';

interface CreateWbsScreenProps {
  onGenerateWbs?: (jobId: string) => void;
}

const ALLOWED_PROJECT_MIMES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'text/csv'
];

const ALLOWED_TEMPLATE_MIMES = [
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
  'text/csv',
  'application/xml',
  'text/xml'
];

export default function CreateWbsScreen({ onGenerateWbs }: CreateWbsScreenProps) {
  const [projectFile, setProjectFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);

  const [projectFileError, setProjectFileError] = useState<string | null>(null);
  const [templateFileError, setTemplateFileError] = useState<string | null>(null);

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  const projectInputRef = useRef<HTMLInputElement | null>(null);
  const templateInputRef = useRef<HTMLInputElement | null>(null);

  const validateFile = (file: File, allowedTypes: string[], maxMb: number = 25): string | null => {
    if (file.size > maxMb * 1024 * 1024) {
      return `File exceeds maximum upload size of ${maxMb}MB.`;
    }
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    const isMimeValid = allowedTypes.includes(file.type);
    const isExtValid = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv', '.xml'].includes(ext);

    if (!isMimeValid && !isExtValid) {
      return 'Unsupported file format. Please upload an accepted document type.';
    }
    return null;
  };

  const handleProjectSelect = (file: File) => {
    const error = validateFile(file, ALLOWED_PROJECT_MIMES);
    if (error) {
      setProjectFile(null);
      setProjectFileError(error);
      if (projectInputRef.current) projectInputRef.current.value = '';
    } else {
      setProjectFile(file);
      setProjectFileError(null);
    }
  };

  const handleTemplateSelect = (file: File) => {
    const error = validateFile(file, ALLOWED_TEMPLATE_MIMES);
    if (error) {
      setTemplateFile(null);
      setTemplateFileError(error);
      if (templateInputRef.current) templateInputRef.current.value = '';
    } else {
      setTemplateFile(file);
      setTemplateFileError(null);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>, type: 'project' | 'template') => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (type === 'project') handleProjectSelect(file);
      else handleTemplateSelect(file);
    }
  };

  const handleGenerateClick = async () => {
    if (!projectFile || !templateFile) return;

    setIsSubmitting(true);
    setSubmissionError(null);

    try {
      const { jobId } = await createWbsGenerationJob(projectFile, templateFile);
      if (onGenerateWbs) {
        onGenerateWbs(jobId);
      }
    } catch (err: unknown) {
      setSubmissionError(err instanceof Error ? err.message : 'Failed to initialize AI analysis job.');
      setIsSubmitting(false);
    }
  };

  const isFormValid = Boolean(projectFile && templateFile && !projectFileError && !templateFileError);

  return (
    <div className="wbs-create-container">
      <header className="wbs-create-header">
        <h1 className="wbs-create-title">
          Create Work Breakdown Structure
        </h1>
        <p className="wbs-create-subtitle">
          Upload your project document and a reference WBS template. The AI will analyze the content and generate a planner-ready WBS
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
            <span className="wbs-step-badge">
              1
            </span>
            <h2 className="wbs-step-title">
              Project Scope Document
            </h2>
          </div>
          <p className="wbs-step-description">
            Upload your RFP, Scope of Work, Technical Specification, or BOQ document.
          </p>

          <div 
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDrop(e, 'project')}
            onClick={() => projectInputRef.current?.click()}
            className="wbs-dropzone"
          >
            <FileUp size={34} color="#3B82F6" className="wbs-dropzone-icon" />
            <p className="wbs-dropzone-label">
              Click to upload or drag & drop
            </p>
            <span className="wbs-dropzone-hint">
              PDF, DOCX, XLSX up to 25MB
            </span>
            <input 
              ref={projectInputRef} 
              type="file" 
              accept=".pdf,.docx,.doc,.xlsx,.xls,.csv" 
              className="wbs-file-input-hidden"
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleProjectSelect(e.target.files[0]);
              }}
            />
          </div>

          {projectFile && (
            <div className="wbs-file-selected">
              <div className="wbs-file-info">
                <CheckCircle size={16} color="#16A34A" />
                <span className="wbs-file-name">
                  {projectFile.name}
                </span>
              </div>
              <button 
                type="button" 
                aria-label="Remove project file"
                onClick={() => { setProjectFile(null); if (projectInputRef.current) projectInputRef.current.value = ''; }} 
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
            <span className="wbs-step-badge">
              2
            </span>
            <h2 className="wbs-step-title">
              Reference WBS Template
            </h2>
          </div>
          <p className="wbs-step-description">
            Upload your organization or domain baseline WBS hierarchy.
          </p>

          <div 
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDrop(e, 'template')}
            onClick={() => templateInputRef.current?.click()}
            className="wbs-dropzone"
          >
            <FileSpreadsheet size={34} color="#10B981" className="wbs-dropzone-icon" />
            <p className="wbs-dropzone-label">
              Click to upload or drag & drop
            </p>
            <span className="wbs-dropzone-hint">
              XLSX, CSV, XML (Primavera P6) up to 25MB
            </span>
            <input 
              ref={templateInputRef} 
              type="file" 
              accept=".xlsx,.xls,.csv,.xml" 
              className="wbs-file-input-hidden"
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleTemplateSelect(e.target.files[0]);
              }}
            />
          </div>

          {templateFile && (
            <div className="wbs-file-selected">
              <div className="wbs-file-info">
                <CheckCircle size={16} color="#16A34A" />
                <span className="wbs-file-name">
                  {templateFile.name}
                </span>
              </div>
              <button 
                type="button" 
                aria-label="Remove template file"
                onClick={() => { setTemplateFile(null); if (templateInputRef.current) templateInputRef.current.value = ''; }} 
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
          <span>{isSubmitting ? 'Initializing Job...' : 'Generate Draft WBS'}</span>
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}