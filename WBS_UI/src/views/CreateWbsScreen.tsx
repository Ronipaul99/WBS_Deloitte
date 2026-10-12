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
    <div style={{ width: '100%', boxSizing: 'border-box' }}>
      <header style={{ marginBottom: '28px' }}>
        <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#0F172A', margin: '0 0 6px 0', letterSpacing: '-0.3px' }}>
          Create Work Breakdown Structure
        </h1>
        <p style={{ fontSize: '13.5px', color: '#64748B', margin: 0 }}>
          Ingest project requirements, cross-reference your industry template, and generate a Primavera P6-ready WBS.
        </p>
      </header>

      {submissionError && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 16px', backgroundColor: '#FEF2F2', border: '1px solid #FCA5A5', borderRadius: '8px', color: '#DC2626', marginBottom: '24px', fontSize: '13px' }}>
          <ShieldAlert size={18} />
          <span>{submissionError}</span>
        </div>
      )}

      {/* Upload Columns */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 340px), 1fr))', gap: '24px', marginBottom: '32px' }}>
        
        {/* Step 1: Project Scope */}
        <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '10px', padding: '24px', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <span style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#2563EB', color: '#FFFFFF', fontSize: '12px', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              1
            </span>
            <h2 style={{ fontSize: '15px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
              Project Scope Document
            </h2>
          </div>
          <p style={{ fontSize: '12.5px', color: '#64748B', margin: '0 0 16px 0', lineHeight: 1.5 }}>
            Upload your RFP, Scope of Work, Technical Specification, or BOQ document.
          </p>

          <div 
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDrop(e, 'project')}
            onClick={() => projectInputRef.current?.click()}
            style={{
              flex: 1,
              border: '2px dashed #CBD5E1',
              borderRadius: '8px',
              padding: '28px 16px',
              textAlign: 'center',
              backgroundColor: '#F8FAFC',
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'border-color 0.2s ease',
            }}
          >
            <FileUp size={34} color="#3B82F6" style={{ marginBottom: '10px' }} />
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', margin: '0 0 4px 0' }}>
              Click to upload or drag & drop
            </p>
            <span style={{ fontSize: '11px', color: '#64748B' }}>
              PDF, DOCX, XLSX up to 25MB
            </span>
            <input 
              ref={projectInputRef} 
              type="file" 
              accept=".pdf,.docx,.doc,.xlsx,.xls,.csv" 
              style={{ display: 'none' }}
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleProjectSelect(e.target.files[0]);
              }}
            />
          </div>

          {projectFile && (
            <div style={{ marginTop: '14px', padding: '10px 12px', backgroundColor: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <CheckCircle size={16} color="#16A34A" />
                <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#166534', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                  {projectFile.name}
                </span>
              </div>
              <button 
                type="button" 
                aria-label="Remove project file"
                onClick={() => { setProjectFile(null); if (projectInputRef.current) projectInputRef.current.value = ''; }} 
                style={{ background: 'none', border: 'none', color: '#166534', cursor: 'pointer' }}
              >
                <X size={15} />
              </button>
            </div>
          )}

          {projectFileError && (
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', fontSize: '12px' }}>
              <AlertCircle size={15} /> {projectFileError}
            </div>
          )}
        </div>

        {/* Step 2: Reference Template */}
        <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '10px', padding: '24px', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
            <span style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#2563EB', color: '#FFFFFF', fontSize: '12px', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              2
            </span>
            <h2 style={{ fontSize: '15px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
              Reference WBS Template
            </h2>
          </div>
          <p style={{ fontSize: '12.5px', color: '#64748B', margin: '0 0 16px 0', lineHeight: 1.5 }}>
            Upload your organization or domain baseline WBS hierarchy.
          </p>

          <div 
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDrop(e, 'template')}
            onClick={() => templateInputRef.current?.click()}
            style={{
              flex: 1,
              border: '2px dashed #CBD5E1',
              borderRadius: '8px',
              padding: '28px 16px',
              textAlign: 'center',
              backgroundColor: '#F8FAFC',
              cursor: 'pointer',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'border-color 0.2s ease',
            }}
          >
            <FileSpreadsheet size={34} color="#10B981" style={{ marginBottom: '10px' }} />
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', margin: '0 0 4px 0' }}>
              Click to upload or drag & drop
            </p>
            <span style={{ fontSize: '11px', color: '#64748B' }}>
              XLSX, CSV, XML (Primavera P6) up to 25MB
            </span>
            <input 
              ref={templateInputRef} 
              type="file" 
              accept=".xlsx,.xls,.csv,.xml" 
              style={{ display: 'none' }}
              onChange={(e: ChangeEvent<HTMLInputElement>) => {
                if (e.target.files && e.target.files[0]) handleTemplateSelect(e.target.files[0]);
              }}
            />
          </div>

          {templateFile && (
            <div style={{ marginTop: '14px', padding: '10px 12px', backgroundColor: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: '6px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <CheckCircle size={16} color="#16A34A" />
                <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#166534', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                  {templateFile.name}
                </span>
              </div>
              <button 
                type="button" 
                aria-label="Remove template file"
                onClick={() => { setTemplateFile(null); if (templateInputRef.current) templateInputRef.current.value = ''; }} 
                style={{ background: 'none', border: 'none', color: '#166534', cursor: 'pointer' }}
              >
                <X size={15} />
              </button>
            </div>
          )}

          {templateFileError && (
            <div style={{ marginTop: '12px', display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', fontSize: '12px' }}>
              <AlertCircle size={15} /> {templateFileError}
            </div>
          )}
        </div>
      </div>

      {/* Primary Action Button */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '10px' }}>
        <button
          type="button"
          disabled={!isFormValid || isSubmitting}
          onClick={handleGenerateClick}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 22px',
            backgroundColor: isFormValid && !isSubmitting ? '#2563EB' : '#94A3B8',
            color: '#FFFFFF',
            borderRadius: '6px',
            border: 'none',
            fontSize: '13.5px',
            fontWeight: 600,
            cursor: isFormValid && !isSubmitting ? 'pointer' : 'not-allowed',
            transition: 'background-color 0.15s ease'
          }}
        >
          <span>{isSubmitting ? 'Initializing Job...' : 'Generate Draft WBS'}</span>
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}