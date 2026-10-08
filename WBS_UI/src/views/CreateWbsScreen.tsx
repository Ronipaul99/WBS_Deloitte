import { useState, useRef, DragEvent, ChangeEvent, MouseEvent, ReactNode } from 'react';
import { 
  FileText, 
  FileSpreadsheet, 
  X, 
  ArrowRight, 
  Info,
  AlertCircle,
  Loader2
} from 'lucide-react';

const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB
const ALLOWED_PROJECT_EXTS = ['pdf', 'doc', 'docx', 'txt'];
const ALLOWED_TEMPLATE_EXTS = ['xlsx', 'xls', 'csv', 'xml'];

export interface FileBadge {
  label: string;
  bg: string;
}

export interface UploadedFileState {
  name: string;
  size: string;
  sizeBytes: number;
  badge: FileBadge;
  raw: File;
}

interface CreateWbsScreenProps {
  isLoading?: boolean;
  onGenerateWbs?: (projectFile: UploadedFileState, templateFile: UploadedFileState) => void;
}

interface FileUploadCardProps {
  stepNumber: number;
  title: string;
  description: string;
  inputId: string;
  allowedExtensions: string[];
  acceptedMimeTypes: string;
  icon: ReactNode;
  iconBgColor: string;
  iconColor: string;
  activeBorderColor: string;
  activeBgColor: string;
  fileState: UploadedFileState | null;
  errorMessage: string | null;
  onFileSelect: (file: File) => void;
  onFileRemove: () => void;
}

function formatFileSize(bytes: number): string {
  if (!bytes || bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function getBadge(name: string): FileBadge {
  const ext = name.split('.').pop()?.toUpperCase() || 'FILE';
  if (ext === 'PDF') return { label: 'PDF', bg: '#D93025' };
  if (['XLS', 'XLSX', 'CSV'].includes(ext)) return { label: 'XLS', bg: '#188038' };
  if (['DOC', 'DOCX'].includes(ext)) return { label: 'DOC', bg: '#1A73E8' };
  if (ext === 'XML') return { label: 'XML', bg: '#007064' };
  return { label: ext, bg: '#5F6368' };
}

function FileUploadCard({
  stepNumber,
  title,
  description,
  inputId,
  allowedExtensions,
  acceptedMimeTypes,
  icon,
  iconBgColor,
  iconColor,
  activeBorderColor,
  activeBgColor,
  fileState,
  errorMessage,
  onFileSelect,
  onFileRemove,
}: FileUploadCardProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      onFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      onFileSelect(e.target.files[0]);
      e.target.value = ''; // Clears browser cache so re-uploading the same file works
    }
  };

  const handleRemove = () => {
    if (inputRef.current) {
      inputRef.current.value = '';
    }
    onFileRemove();
  };

  return (
    <div
      style={{
        backgroundColor: '#FFFFFF',
        borderRadius: '8px',
        border: '1px solid #E2E8F0',
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minHeight: '270px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
          <span
            style={{
              width: '18px',
              height: '18px',
              borderRadius: '50%',
              backgroundColor: '#1A73E8',
              color: '#FFFFFF',
              fontSize: '10.5px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            {stepNumber}
          </span>
          <h2 style={{ fontSize: '13px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
            {title}
          </h2>
        </div>
        <p style={{ fontSize: '11.5px', color: '#64748B', marginBottom: '14px', marginTop: '1px' }}>
          {description}
        </p>

        {/* Drop Zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          style={{
            border: `1.5px dashed ${isDragging ? activeBorderColor : '#CBD5E1'}`,
            backgroundColor: isDragging ? activeBgColor : '#FAFCFE',
            borderRadius: '6px',
            padding: '24px 16px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            transition: 'border-color 0.15s ease, background-color 0.15s ease',
          }}
        >
          {/* pointerEvents: 'none' stops child elements from triggering dragleave flickering */}
          <div
            style={{
              pointerEvents: 'none',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            <div
              style={{
                width: '36px',
                height: '36px',
                backgroundColor: iconBgColor,
                color: iconColor,
                borderRadius: '50%',
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {icon}
            </div>
            <p style={{ fontSize: '11.5px', fontWeight: 500, color: '#334155', margin: 0 }}>
              Drag and drop your file here
            </p>
            <span style={{ fontSize: '10.5px', color: '#94A3B8', margin: '3px 0' }}>or</span>
          </div>

          <label
            htmlFor={inputId}
            style={{
              padding: '5px 14px',
              border: '1px solid #1A73E8',
              color: '#1A73E8',
              fontSize: '11px',
              fontWeight: 600,
              borderRadius: '4px',
              cursor: 'pointer',
              backgroundColor: '#FFFFFF',
              display: 'inline-block',
            }}
          >
            Browse Files
          </label>
          <input
            id={inputId}
            ref={inputRef}
            type="file"
            accept={acceptedMimeTypes}
            onChange={handleInputChange}
            style={{ display: 'none' }}
          />

          <span style={{ fontSize: '10px', color: '#94A3B8', marginTop: '8px', pointerEvents: 'none' }}>
            Supported formats: {allowedExtensions.map((e) => `.${e}`).join(', ')} (up to 25 MB)
          </span>
        </div>

        {/* Validation Error Banner */}
        {errorMessage && (
          <div
            style={{
              marginTop: '10px',
              padding: '8px 10px',
              backgroundColor: '#FEF2F2',
              border: '1px solid #FCA5A5',
              borderRadius: '5px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '11px',
              color: '#B91C1C',
            }}
          >
            <AlertCircle size={14} style={{ flexShrink: 0 }} />
            <span>{errorMessage}</span>
          </div>
        )}
      </div>

      {/* Selected File Card */}
      {fileState && (
        <div
          style={{
            marginTop: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            backgroundColor: '#F8FAFC',
            border: '1px solid #E2E8F0',
            borderRadius: '5px',
            fontSize: '11.5px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
            <span
              style={{
                backgroundColor: fileState.badge.bg,
                color: '#FFFFFF',
                fontWeight: 700,
                padding: '2.5px 5px',
                borderRadius: '3px',
                fontSize: '8.5px',
                flexShrink: 0,
              }}
            >
              {fileState.badge.label}
            </span>
            <div style={{ overflow: 'hidden' }}>
              <p
                style={{
                  fontWeight: 600,
                  color: '#1E293B',
                  margin: 0,
                  fontSize: '11.5px',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                  whiteSpace: 'nowrap',
                }}
              >
                {fileState.name}
              </p>
              <p style={{ fontSize: '10px', color: '#94A3B8', margin: 0 }}>
                {fileState.size}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleRemove}
            aria-label={`Remove file ${fileState.name}`}
            style={{
              background: 'none',
              border: 'none',
              color: '#94A3B8',
              cursor: 'pointer',
              display: 'flex',
              padding: '2px',
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

export default function CreateWbsScreen({ isLoading = false, onGenerateWbs }: CreateWbsScreenProps) {
  const [projectFile, setProjectFile] = useState<UploadedFileState | null>(null);
  const [templateFile, setTemplateFile] = useState<UploadedFileState | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);

  const validateFile = (file: File, allowedExts: string[]): string | null => {
    // 1. Explicitly check and block image files (both by MIME type and common image extensions)
    const isImageMime = file.type && file.type.startsWith('image/');
    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const imageExtensions = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'heic'];

    if (isImageMime || imageExtensions.includes(ext)) {
      return 'Image files (.png, .jpg, etc.) are not allowed. Please upload a project document.';
    }

    // 2. Strict allowed extension check
    if (!allowedExts.includes(ext)) {
      return `Invalid format (.${ext || 'unknown'}). Allowed: ${allowedExts.map((e) => `.${e}`).join(', ')}`;
    }

    // 3. Strict size limit check
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `File exceeds 25 MB limit (${formatFileSize(file.size)}).`;
    }

    return null;
  };

  const handleProjectSelect = (file: File) => {
    const error = validateFile(file, ALLOWED_PROJECT_EXTS);
    if (error) {
      setProjectError(error);
      return;
    }
    setProjectError(null);
    setProjectFile({
      name: file.name,
      size: formatFileSize(file.size),
      sizeBytes: file.size,
      badge: getBadge(file.name),
      raw: file,
    });
  };

  const handleTemplateSelect = (file: File) => {
    const error = validateFile(file, ALLOWED_TEMPLATE_EXTS);
    if (error) {
      setTemplateError(error);
      return;
    }
    setTemplateError(null);
    setTemplateFile({
      name: file.name,
      size: formatFileSize(file.size),
      sizeBytes: file.size,
      badge: getBadge(file.name),
      raw: file,
    });
  };

  const isReady = Boolean(projectFile && templateFile && !isLoading);

  const handleGenerateClick = (e: MouseEvent<HTMLButtonElement>) => {
    if (!isReady || !projectFile || !templateFile) {
      e.preventDefault();
      return;
    }
    if (onGenerateWbs) {
      onGenerateWbs(projectFile, templateFile);
    }
  };

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '22px' }}>
      
      {/* Header */}
      <div>
        <h1
          style={{
            fontSize: '19px',
            fontWeight: 700,
            color: '#0F172A',
            letterSpacing: '-0.3px',
            margin: 0,
          }}
        >
          Create a New WBS
        </h1>
        <p style={{ fontSize: '12px', color: '#64748B', marginTop: '4px' }}>
          Upload your project document and a reference WBS template. The AI will analyze the content and generate a planner-ready WBS.
        </p>
      </div>

      {/* Dual Upload Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
        
        {/* Step 1: Project Document */}
        <FileUploadCard
          stepNumber={1}
          title="Project Document"
          description="Upload RFP, RFQ, RFI, BOQ, SOW or similar document."
          inputId="project-document-input"
          allowedExtensions={ALLOWED_PROJECT_EXTS}
          acceptedMimeTypes=".pdf,.doc,.docx,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
          icon={<FileText size={18} strokeWidth={2.2} />}
          iconBgColor="#E8F0FE"
          iconColor="#1A73E8"
          activeBorderColor="#1A73E8"
          activeBgColor="#EFF6FF"
          fileState={projectFile}
          errorMessage={projectError}
          onFileSelect={handleProjectSelect}
          onFileRemove={() => {
            setProjectFile(null);
            setProjectError(null);
          }}
        />

        {/* Step 2: Reference Template */}
        <FileUploadCard
          stepNumber={2}
          title="WBS Reference Template"
          description="Upload your domain-specific WBS template (Excel, XML, CSV)."
          inputId="template-document-input"
          allowedExtensions={ALLOWED_TEMPLATE_EXTS}
          acceptedMimeTypes=".xlsx,.xls,.csv,.xml,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv,text/xml,application/xml"
          icon={<FileSpreadsheet size={18} strokeWidth={2.2} />}
          iconBgColor="#E6F4EA"
          iconColor="#188038"
          activeBorderColor="#188038"
          activeBgColor="#E6F4EA"
          fileState={templateFile}
          errorMessage={templateError}
          onFileSelect={handleTemplateSelect}
          onFileRemove={() => {
            setTemplateFile(null);
            setTemplateError(null);
          }}
        />

      </div>

      {/* Info Banner & CTA */}
      <div
        style={{
          backgroundColor: '#E8F0FE',
          border: '1px solid #D2E3FC',
          borderRadius: '6px',
          padding: '12px 18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '14px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '18px',
              height: '18px',
              backgroundColor: '#1A73E8',
              borderRadius: '50%',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Info size={12} strokeWidth={2.4} />
          </div>
          <p style={{ fontSize: '11.5px', color: '#174EA6', fontWeight: 500, margin: 0 }}>
            The AI will extract project scope, map it to your template, identify gaps, and generate a traceable first-draft WBS.
          </p>
        </div>

        {/* CTA Button */}
        <button
          type="button"
          onClick={handleGenerateClick}
          disabled={!isReady}
          title={!isReady ? 'Please upload valid documents for both steps to enable generation' : 'Generate Draft WBS'}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 16px',
            backgroundColor: isReady ? '#1A73E8' : '#A0C5F8',
            color: '#FFFFFF',
            fontSize: '11.5px',
            fontWeight: 600,
            borderRadius: '4px',
            border: 'none',
            cursor: isReady ? 'pointer' : 'not-allowed',
            opacity: isReady ? 1 : 0.8,
            boxShadow: isReady ? '0 1px 2px rgba(0,0,0,0.08)' : 'none',
            flexShrink: 0,
            transition: 'all 0.15s ease',
            userSelect: 'none',
          }}
        >
          {isLoading ? (
            <>
              <Loader2 size={13} className="animate-spin" />
              <span>Analyzing Documents...</span>
            </>
          ) : (
            <>
              <span>Generate Draft WBS</span>
              <ArrowRight size={12} strokeWidth={2.2} />
            </>
          )}
        </button>
      </div>

    </div>
  );
}