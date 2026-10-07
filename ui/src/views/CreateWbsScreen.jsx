import React, { useState } from 'react';
import { 
  FileText, 
  FileSpreadsheet, 
  X, 
  ArrowRight, 
  Info 
} from 'lucide-react';

export default function CreateWbsScreen({ onGenerateWbs }) {
  const [projectFile, setProjectFile] = useState(null);
  const [templateFile, setTemplateFile] = useState(null);

  const [drag1, setDrag1] = useState(false);
  const [drag2, setDrag2] = useState(false);

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const getBadge = (name) => {
    const ext = name.split('.').pop().toUpperCase();
    if (ext === 'PDF') return { label: 'PDF', bg: '#D93025' };
    if (['XLS', 'XLSX', 'CSV'].includes(ext)) return { label: 'XLS', bg: '#188038' };
    if (['DOC', 'DOCX'].includes(ext)) return { label: 'DOC', bg: '#1A73E8' };
    return { label: ext, bg: '#5F6368' };
  };

  const handleProjectSelect = (file) => {
    if (!file) return;
    setProjectFile({
      name: file.name,
      size: formatFileSize(file.size),
      badge: getBadge(file.name),
      raw: file
    });
  };

  const handleTemplateSelect = (file) => {
    if (!file) return;
    setTemplateFile({
      name: file.name,
      size: formatFileSize(file.size),
      badge: getBadge(file.name),
      raw: file
    });
  };

  const isReady = Boolean(projectFile && templateFile);

  const handleGenerateClick = (e) => {
    if (!isReady) {
      e.preventDefault();
      return;
    }
    if (onGenerateWbs) {
      onGenerateWbs(projectFile, templateFile);
    }
  };

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '22px' }}>
      
      {/* Title */}
      <div>
        <h1 style={{ 
          fontSize: '19px', 
          fontWeight: 700, 
          color: '#0F172A', 
          letterSpacing: '-0.3px', 
          margin: 0 
        }}>
          Create a New WBS
        </h1>
        <p style={{ 
          fontSize: '12px', 
          color: '#64748B', 
          marginTop: '4px' 
        }}>
          Upload your project document and a reference WBS template. The AI will analyze the content and generate a planner-ready WBS.
        </p>
      </div>

      {/* Dual Upload Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        
        {/* Card 1: Project Document */}
        <div style={{
          backgroundColor: '#FFFFFF',
          borderRadius: '8px',
          border: '1px solid #E2E8F0',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          minHeight: '270px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.03)'
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
              <span style={{
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
                flexShrink: 0
              }}>1</span>
              <h2 style={{ fontSize: '13px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
                Project Document
              </h2>
            </div>
            <p style={{ fontSize: '11.5px', color: '#64748B', marginBottom: '14px', marginTop: '1px' }}>
              Upload RFP, RFQ, RFI, BOQ, SOW or similar document.
            </p>

            {/* Drop Box */}
            <div 
              onDragOver={(e) => { e.preventDefault(); setDrag1(true); }}
              onDragLeave={() => setDrag1(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag1(false);
                if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                  handleProjectSelect(e.dataTransfer.files[0]);
                }
              }}
              style={{
                border: `1.5px dashed ${drag1 ? '#1A73E8' : '#CBD5E1'}`,
                backgroundColor: drag1 ? '#EFF6FF' : '#FAFCFE',
                borderRadius: '6px',
                padding: '24px 16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center'
              }}
            >
              <div style={{
                width: '36px',
                height: '36px',
                backgroundColor: '#E8F0FE',
                color: '#1A73E8',
                borderRadius: '50%',
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <FileText size={18} strokeWidth={2.2} />
              </div>
              <p style={{ fontSize: '11.5px', fontWeight: 500, color: '#334155', margin: 0 }}>
                Drag and drop your file here
              </p>
              <span style={{ fontSize: '10.5px', color: '#94A3B8', margin: '3px 0' }}>or</span>
              <label style={{
                padding: '5px 14px',
                border: '1px solid #1A73E8',
                color: '#1A73E8',
                fontSize: '11px',
                fontWeight: 600,
                borderRadius: '4px',
                cursor: 'pointer',
                backgroundColor: '#FFFFFF'
              }}>
                Browse Files
                <input 
                  type="file" 
                  style={{ display: 'none' }}
                  accept=".pdf,.doc,.docx,.txt"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      handleProjectSelect(e.target.files[0]);
                    }
                  }} 
                />
              </label>
            </div>
          </div>

          {projectFile && (
            <div style={{
              marginTop: '12px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              backgroundColor: '#F8FAFC',
              border: '1px solid #E2E8F0',
              borderRadius: '5px',
              fontSize: '11.5px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <span style={{
                  backgroundColor: projectFile.badge.bg,
                  color: '#FFFFFF',
                  fontWeight: 700,
                  padding: '2.5px 5px',
                  borderRadius: '3px',
                  fontSize: '8.5px',
                  flexShrink: 0
                }}>{projectFile.badge.label}</span>
                <div style={{ overflow: 'hidden' }}>
                  <p style={{ fontWeight: 600, color: '#1E293B', margin: 0, fontSize: '11.5px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                    {projectFile.name}
                  </p>
                  <p style={{ fontSize: '10px', color: '#94A3B8', margin: 0 }}>
                    {projectFile.size}
                  </p>
                </div>
              </div>
              <button 
                onClick={() => setProjectFile(null)} 
                title="Remove file"
                style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer', display: 'flex', padding: '2px' }}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>

        {/* Card 2: WBS Reference Template */}
        <div style={{
          backgroundColor: '#FFFFFF',
          borderRadius: '8px',
          border: '1px solid #E2E8F0',
          padding: '20px 22px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          minHeight: '270px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.03)'
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
              <span style={{
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
                flexShrink: 0
              }}>2</span>
              <h2 style={{ fontSize: '13px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
                WBS Reference Template
              </h2>
            </div>
            <p style={{ fontSize: '11.5px', color: '#64748B', marginBottom: '14px', marginTop: '1px' }}>
              Upload your domain-specific WBS template (Excel, PDF, CSV).
            </p>

            {/* Drop Box */}
            <div 
              onDragOver={(e) => { e.preventDefault(); setDrag2(true); }}
              onDragLeave={() => setDrag2(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag2(false);
                if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                  handleTemplateSelect(e.dataTransfer.files[0]);
                }
              }}
              style={{
                border: `1.5px dashed ${drag2 ? '#188038' : '#CBD5E1'}`,
                backgroundColor: drag2 ? '#E6F4EA' : '#FAFCFE',
                borderRadius: '6px',
                padding: '24px 16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center'
              }}
            >
              <div style={{
                width: '36px',
                height: '36px',
                backgroundColor: '#E6F4EA',
                color: '#188038',
                borderRadius: '50%',
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <FileSpreadsheet size={18} strokeWidth={2.2} />
              </div>
              <p style={{ fontSize: '11.5px', fontWeight: 500, color: '#334155', margin: 0 }}>
                Drag and drop your file here
              </p>
              <span style={{ fontSize: '10.5px', color: '#94A3B8', margin: '3px 0' }}>or</span>
              <label style={{
                padding: '5px 14px',
                border: '1px solid #1A73E8',
                color: '#1A73E8',
                fontSize: '11px',
                fontWeight: 600,
                borderRadius: '4px',
                cursor: 'pointer',
                backgroundColor: '#FFFFFF'
              }}>
                Browse Files
                <input 
                  type="file" 
                  style={{ display: 'none' }}
                  accept=".xlsx,.xls,.csv,.xml"
                  onChange={(e) => {
                    if (e.target.files && e.target.files[0]) {
                      handleTemplateSelect(e.target.files[0]);
                    }
                  }} 
                />
              </label>
            </div>
          </div>

          {templateFile && (
            <div style={{
              marginTop: '12px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              backgroundColor: '#F8FAFC',
              border: '1px solid #E2E8F0',
              borderRadius: '5px',
              fontSize: '11.5px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                <span style={{
                  backgroundColor: templateFile.badge.bg,
                  color: '#FFFFFF',
                  fontWeight: 700,
                  padding: '2.5px 5px',
                  borderRadius: '3px',
                  fontSize: '8.5px',
                  flexShrink: 0
                }}>{templateFile.badge.label}</span>
                <div style={{ overflow: 'hidden' }}>
                  <p style={{ fontWeight: 600, color: '#1E293B', margin: 0, fontSize: '11.5px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                    {templateFile.name}
                  </p>
                  <p style={{ fontSize: '10px', color: '#94A3B8', margin: 0 }}>
                    {templateFile.size}
                  </p>
                </div>
              </div>
              <button 
                onClick={() => setTemplateFile(null)} 
                title="Remove template"
                style={{ background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer', display: 'flex', padding: '2px' }}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Info Banner & CTA Button */}
      <div style={{
        backgroundColor: '#E8F0FE',
        border: '1px solid #D2E3FC',
        borderRadius: '6px',
        padding: '12px 18px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '14px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '18px',
            height: '18px',
            backgroundColor: '#1A73E8',
            borderRadius: '50%',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0
          }}>
            <Info size={12} strokeWidth={2.4} />
          </div>
          <p style={{ fontSize: '11.5px', color: '#174EA6', fontWeight: 500, margin: 0 }}>
            The AI will extract project scope, map it to your template, identify gaps, and generate a traceable first-draft WBS.
          </p>
        </div>

        {/* CTA Button */}
        <button
          onClick={handleGenerateClick}
          disabled={!isReady}
          title={!isReady ? "Please upload both documents to enable generation" : "Generate Draft WBS"}
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
            userSelect: 'none'
          }}
          onMouseEnter={(e) => {
            if (isReady) e.currentTarget.style.backgroundColor = '#1557B0';
          }}
          onMouseLeave={(e) => {
            if (isReady) e.currentTarget.style.backgroundColor = '#1A73E8';
          }}
        >
          Generate Draft WBS
          <ArrowRight size={12} strokeWidth={2.2} />
        </button>
      </div>

    </div>
  );
}