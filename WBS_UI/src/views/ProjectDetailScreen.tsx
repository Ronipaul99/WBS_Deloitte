/* eslint-disable react-hooks/set-state-in-effect */
import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  ArrowLeft,
  Calendar,
  User,
  MapPin,
  Plus,
  Layers,
  FileText,
  FileSpreadsheet,
  Upload,
  CheckCircle2,
  ChevronRight,
  ChevronDown,
  Download,
  Eye,
  Search,
  GitCompare,
  MoreVertical
} from 'lucide-react';
import { getProject } from '../services/projectsApi';
import { apiRequest } from '../services/apiClient';
import './ProjectDetailHubScreen.css';

interface ProjectRecord {
  id: string;
  name: string;
  description?: string;
  project_code?: string;
  code?: string;
  project_type?: string;
  type?: string;
  location?: string;
  owner?: string;
  created_at?: string;
  status?: string;
  scope_coverage?: number;
  scopeCoverage?: number;
  current_version?: string;
  currentVersion?: string;
}

interface DocumentRecord {
  id: string;
  original_filename?: string;
  name?: string;
  mime_type?: string;
  category?: string;
  version?: string;
  status?: string;
  created_at?: string;
  uploadedBy?: string;
  uploader?: string;
  size?: string;
}

interface GenerationRecord {
  id: string;
  name?: string;
  version?: string;
  status?: string;
  generatedOn?: string;
  created_at?: string;
  scopeCoverage?: number;
  wbsItemsCount?: number;
  items_count?: number;
  description?: string;
}

interface ProjectDetailScreenProps {
  tenantId: string;
  projectId: string;
  onBackToProjects: () => void;
  onOpenWbsView: (projectId: string) => void;
  onOpenEvidenceViewer: (projectId: string, documentId?: string) => void;
  onGenerateNewWbs: () => void;
}

export type HubTab = 'Overview' | 'Documents' | 'WBS' | 'Activity';

const DOCUMENT_FILTER_TABS = [
  'All Documents',
  'RFP',
  'SOW',
  'Technical Spec',
  'Reference WBS',
  'Others'
] as const;

export const ProjectDetailScreen: React.FC<ProjectDetailScreenProps> = ({
  tenantId,
  projectId,
  onBackToProjects,
  onOpenWbsView,
  onOpenEvidenceViewer,
  onGenerateNewWbs,
}) => {
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [generations, setGenerations] = useState<GenerationRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<HubTab>('Overview');
  const [docFilterTab, setDocFilterTab] = useState<string>('All Documents');
  const [docSearch, setDocSearch] = useState('');
  const [versionSearch, setVersionSearch] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState<string>('');
  const [activeDocMenuId, setActiveDocMenuId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fetchProjectData = useCallback(async () => {
    if (!tenantId || !projectId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const [projData, docsData, genData] = await Promise.all([
        getProject(tenantId, projectId),
        apiRequest(`/tenants/${tenantId}/projects/${projectId}/documents`).catch(() => []),
        apiRequest(`/tenants/${tenantId}/projects/${projectId}/generations`).catch(() => [])
      ]);

      setProject(projData as ProjectRecord);
      
      const docsArray = Array.isArray(docsData) ? docsData : ((docsData as { items?: DocumentRecord[] })?.items || []);
      const gensArray = Array.isArray(genData) ? genData : ((genData as { items?: GenerationRecord[] })?.items || []);
      
      setDocuments(docsArray as DocumentRecord[]);
      setGenerations(gensArray as GenerationRecord[]);

      if (gensArray.length > 0 && gensArray[0]) {
        setSelectedVersionId(gensArray[0].id);
      }
      setError(null);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load project details.';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [tenantId, projectId]);

  useEffect(() => {
    void fetchProjectData();
  }, [fetchProjectData]);

  const handleUploadDocument = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0 || !tenantId || !projectId) return;
    const file = e.target.files[0];
    const formData = new FormData();
    formData.append('file', file);

    try {
      await apiRequest(`/tenants/${tenantId}/projects/${projectId}/documents`, {
        method: 'POST',
        body: formData,
      });
      await fetchProjectData();
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to upload document.';
      alert(errorMessage);
    }
  };

  const handleExportWbs = async (format: 'PDF' | 'Excel') => {
    alert(`Exporting WBS as ${format}...`);
  };

  const filteredDocuments = useMemo(() => {
    return documents.filter((doc) => {
      const fileName = doc.original_filename || doc.name || '';
      const fileType = doc.mime_type || doc.category || '';
      const matchesSearch =
        fileName.toLowerCase().includes(docSearch.toLowerCase()) ||
        fileType.toLowerCase().includes(docSearch.toLowerCase());

      if (docFilterTab === 'All Documents') return matchesSearch;
      if (docFilterTab === 'RFP') return matchesSearch && (fileType.includes('RFP') || fileName.toLowerCase().includes('rfp'));
      if (docFilterTab === 'SOW') return matchesSearch && (fileType.includes('SOW') || fileName.toLowerCase().includes('sow') || fileName.toLowerCase().includes('scope'));
      if (docFilterTab === 'Technical Spec') return matchesSearch && (fileType.includes('Technical') || fileName.toLowerCase().includes('spec'));
      if (docFilterTab === 'Reference WBS') return matchesSearch && (fileType.includes('Reference') || fileName.toLowerCase().includes('template'));
      return matchesSearch;
    });
  }, [documents, docFilterTab, docSearch]);

  const docTabCounts = useMemo(() => {
    return {
      'All Documents': documents.length,
      'RFP': documents.filter((d) => (d.mime_type || d.category || '').includes('RFP') || (d.original_filename || d.name || '').toLowerCase().includes('rfp')).length,
      'SOW': documents.filter((d) => (d.mime_type || d.category || '').includes('SOW') || (d.original_filename || d.name || '').toLowerCase().includes('scope')).length,
      'Technical Spec': documents.filter((d) => (d.mime_type || d.category || '').includes('Technical') || (d.original_filename || d.name || '').toLowerCase().includes('spec')).length,
      'Reference WBS': documents.filter((d) => (d.mime_type || d.category || '').includes('Reference') || (d.original_filename || d.name || '').toLowerCase().includes('template')).length,
      'Others': 0,
    };
  }, [documents]);

  const versionsList = useMemo(() => {
    if (!versionSearch.trim()) return generations;
    return generations.filter((v) =>
      (v.version || '').toLowerCase().includes(versionSearch.toLowerCase()) ||
      (v.name || '').toLowerCase().includes(versionSearch.toLowerCase())
    );
  }, [generations, versionSearch]);

  const selectedVersion = useMemo(() => {
    return generations.find((v) => v.id === selectedVersionId) || generations[0] || null;
  }, [generations, selectedVersionId]);

  if (loading) {
    return (
      <div className="hub-loading-container">
        <span>Loading live project details...</span>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="hub-loading-container">
        <span>{error || 'Project not found.'}</span>
      </div>
    );
  }

  const renderFileIcon = (type: string) => {
    const ext = (type || '').toLowerCase();
    if (ext.includes('pdf')) return <span className="doc-type-icon pdf">pdf</span>;
    if (ext.includes('xls') || ext.includes('csv')) return <span className="doc-type-icon excel"><FileSpreadsheet size={13} /></span>;
    if (ext.includes('doc')) return <span className="doc-type-icon word"><FileText size={13} /></span>;
    return <span className="doc-type-icon xml">pdf</span>;
  };

  const pCode = project.project_code || project.code || '';
  const pType = project.project_type || project.type || '';
  const pLocation = project.location || '';
  const pOwner = project.owner || '';
  const pCreated = project.created_at ? new Date(project.created_at).toLocaleDateString() : '';
  const pStatus = project.status || 'Active';
  const pCoverage = project.scope_coverage ?? project.scopeCoverage ?? 0;
  const pVersion = project.current_version || project.currentVersion || '';

  return (
    <div className="project-hub-page-shell">
      <div className="hub-breadcrumb-bar">
        <button type="button" className="btn-back-crumb" onClick={onBackToProjects}>
          <ArrowLeft size={14} /> My Projects
        </button>
        <span className="crumb-sep">&gt;</span>
        <span className="crumb-project-name">{project.name}</span>
        {activeTab === 'WBS' && (
          <>
            <span className="crumb-sep">&gt;</span>
            <span className="crumb-project-name">WBS Version History</span>
          </>
        )}
      </div>

      <div className="hub-header-banner">
        <div className="header-left-col">
          <span className="badge-active-project">{pStatus}</span>
          <h1 className="project-display-title">{project.name}</h1>
          <p className="project-display-subtitle">{project.description}</p>

          <div className="project-meta-inline-strip">
            {pCode && (
              <div className="meta-pair-block">
                <FileText size={20} className="meta-icon" />
                <div className="meta-text-col">
                  <span className="meta-lbl">Project Code</span>
                  <span className="meta-val">{pCode}</span>
                </div>
              </div>
            )}

            {pCode && pType && <div className="meta-divider" />}

            {pType && (
              <div className="meta-pair-block">
                <Layers size={20} className="meta-icon" />
                <div className="meta-text-col">
                  <span className="meta-lbl">Type</span>
                  <span className="meta-val">{pType}</span>
                </div>
              </div>
            )}

            {pType && pLocation && <div className="meta-divider" />}

            {pLocation && (
              <div className="meta-pair-block">
                <MapPin size={20} className="meta-icon" />
                <div className="meta-text-col">
                  <span className="meta-lbl">Location</span>
                  <span className="meta-val">{pLocation}</span>
                </div>
              </div>
            )}

            {pLocation && pOwner && <div className="meta-divider" />}

            {pOwner && (
              <div className="meta-pair-block">
                <User size={20} className="meta-icon" />
                <div className="meta-text-col">
                  <span className="meta-lbl">Owner</span>
                  <span className="meta-val">{pOwner}</span>
                </div>
              </div>
            )}

            {pOwner && pCreated && <div className="meta-divider" />}

            {pCreated && (
              <div className="meta-pair-block">
                <Calendar size={20} className="meta-icon" />
                <div className="meta-text-col">
                  <span className="meta-lbl">Created On</span>
                  <span className="meta-val">{pCreated}</span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="header-right-col">
          <button type="button" className="btn-generate-new-wbs" onClick={onGenerateNewWbs}>
            <Plus size={15} /> Generate New WBS
          </button>
          <div className="header-menu-wrap">
            <button type="button" className="btn-header-more">
              <MoreVertical size={16} />
            </button>
          </div>
        </div>
      </div>

      <div className="hub-nav-tabs-strip">
        <button type="button" className={`hub-nav-tab ${activeTab === 'Overview' ? 'active' : ''}`} onClick={() => setActiveTab('Overview')}>Overview</button>
        <button type="button" className={`hub-nav-tab ${activeTab === 'Documents' ? 'active' : ''}`} onClick={() => setActiveTab('Documents')}>Documents</button>
        <button type="button" className={`hub-nav-tab ${activeTab === 'WBS' ? 'active' : ''}`} onClick={() => setActiveTab('WBS')}>WBS</button>
        <button type="button" className={`hub-nav-tab ${activeTab === 'Activity' ? 'active' : ''}`} onClick={() => setActiveTab('Activity')}>Activity</button>
      </div>

      {activeTab === 'Overview' && (
        <div className="hub-tab-body overview-grid">
          <div className="hub-overview-kpis-row">
            <div className="overview-kpi-card">
              <div className="kpi-icon-round blue"><FileText size={22} /></div>
              <div className="kpi-info-col">
                <span className="kpi-figure">{generations.length}</span>
                <span className="kpi-tag-title">Total WBS Generated</span>
                <small className="kpi-tag-sub">for this project</small>
              </div>
            </div>

            <div className="overview-kpi-card">
              <div className="kpi-icon-round purple"><Layers size={22} /></div>
              <div className="kpi-info-col">
                <span className="kpi-figure">{pVersion || 'N/A'}</span>
                <span className="kpi-tag-title">Latest Version</span>
                <small className="kpi-tag-sub">Baseline WBS</small>
              </div>
            </div>

            <div className="overview-kpi-card">
              <div className="kpi-icon-round green"><CheckCircle2 size={22} /></div>
              <div className="kpi-info-col">
                <span className="kpi-figure">{pCoverage}%</span>
                <span className="kpi-tag-title">Latest Coverage</span>
                <small className="kpi-tag-sub">Scope coverage in latest WBS</small>
              </div>
            </div>
          </div>

          <div className="overview-lower-layout">
            <div className="overview-versions-card">
              <div className="section-title-header">
                <h3 className="section-heading">WBS Generated Under This Project</h3>
                <p className="section-subheading">All WBS versions generated for this project.</p>
              </div>

              {generations.length === 0 ? (
                <p className="section-subheading" style={{ padding: '20px 0' }}>No WBS versions generated yet.</p>
              ) : (
                <table className="overview-table">
                  <thead>
                    <tr>
                      <th>WBS Name</th>
                      <th>Version</th>
                      <th>Status</th>
                      <th>Generated On</th>
                      <th>Scope Coverage</th>
                      <th>WBS Items</th>
                      <th className="align-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {generations.map((v) => (
                      <tr key={v.id}>
                        <td><strong className="wbs-row-title">{v.name || 'WBS Version'}</strong></td>
                        <td><span className="wbs-ver-code">{v.version || 'v1.0'}</span></td>
                        <td>
                          <span className={`wbs-status-badge ${(v.status || 'Draft').toLowerCase().replace(/\s+/g, '-')}`}>
                            {v.status || 'Draft'}
                          </span>
                        </td>
                        <td><span className="meta-date">{v.generatedOn || (v.created_at ? new Date(v.created_at).toLocaleDateString() : '')}</span></td>
                        <td>
                          <div className="coverage-bar-cell">
                            <div className="coverage-progress-track">
                              <div className="coverage-progress-fill" style={{ width: `${v.scopeCoverage || pCoverage}%`, backgroundColor: '#10B981' }} />
                            </div>
                            <span className="coverage-percent-text">{v.scopeCoverage || pCoverage}%</span>
                          </div>
                        </td>
                        <td><span className="wbs-items-count">{v.wbsItemsCount || v.items_count || 0} items</span></td>
                        <td className="align-right">
                          <button type="button" className="btn-table-open-wbs" onClick={() => onOpenWbsView(project.id)}>
                            <Layers size={13} /> Open WBS
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="overview-documents-sidebar">
              <div className="sidebar-header-row">
                <div className="sidebar-title-cluster">
                  <FileText size={18} color="#2563EB" />
                  <h3 className="sidebar-heading">Project Documents</h3>
                </div>
                <button type="button" className="btn-sidebar-upload" onClick={() => fileInputRef.current?.click()}>
                  <Upload size={13} /> Upload Document
                </button>
              </div>

              <div className="sidebar-docs-list">
                {documents.length === 0 ? (
                  <p className="section-subheading" style={{ padding: '10px 0' }}>No documents uploaded.</p>
                ) : (
                  documents.map((doc) => {
                    const docName = doc.original_filename || doc.name || 'Document';
                    const docType = doc.mime_type || doc.category || 'PDF';
                    const docDate = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '';
                    return (
                      <div key={doc.id} className="sidebar-doc-row" onClick={() => onOpenEvidenceViewer(project.id, doc.id)}>
                        <div className="doc-left-cluster">
                          {renderFileIcon(docType)}
                          <div>
                            <strong className="doc-name">{docName}</strong>
                            <div className="doc-meta">{docDate} {doc.size ? `• ${doc.size}` : ''}</div>
                          </div>
                        </div>
                        <button type="button" className="btn-doc-inspect"><ChevronRight size={14} /></button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Documents' && (
        <div className="hub-tab-body documents-tab-layout">
          <div className="documents-main-area">
            <div className="docs-page-title-row">
              <div>
                <h2 className="docs-main-title">Project Documents</h2>
                <p className="docs-main-sub">Manage all documents for this project. Upload new documents, view versions and processing status.</p>
              </div>
              <button type="button" className="btn-upload-primary" onClick={() => fileInputRef.current?.click()}>
                <Plus size={14} /> Upload Document <ChevronDown size={14} />
              </button>
            </div>

            <div className="docs-filter-strip">
              <div className="docs-pills-row">
                {DOCUMENT_FILTER_TABS.map((tab) => {
                  const count = docTabCounts[tab] ?? 0;
                  const isSel = docFilterTab === tab;
                  return (
                    <button key={tab} type="button" className={`doc-filter-pill ${isSel ? 'active' : ''}`} onClick={() => setDocFilterTab(tab)}>
                      <span>{tab}</span>
                      <span className={`doc-pill-count ${isSel ? 'active' : ''}`}>{count}</span>
                    </button>
                  );
                })}
              </div>
              <div className="docs-search-field">
                <Search size={14} color="#94A3B8" />
                <input type="text" placeholder="Search documents..." value={docSearch} onChange={(e) => setDocSearch(e.target.value)} />
              </div>
            </div>

            <div className="documents-table-container">
              <table className="documents-data-table">
                <thead>
                  <tr>
                    <th>Name ↑↓</th>
                    <th>Type ↑↓</th>
                    <th>Version ↑↓</th>
                    <th>Status ↑↓</th>
                    <th>Uploaded On ↑↓</th>
                    <th>Uploaded By</th>
                    <th className="align-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocuments.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="td-empty-notice" style={{ textAlign: 'center', padding: '30px', color: '#64748B' }}>
                        No documents found.
                      </td>
                    </tr>
                  ) : (
                    filteredDocuments.map((doc) => {
                      const isMenuOpen = activeDocMenuId === doc.id;
                      const docName = doc.original_filename || doc.name || 'Document';
                      const docType = doc.mime_type || doc.category || 'Document';
                      const docDate = doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '';
                      return (
                        <tr key={doc.id} onClick={() => onOpenEvidenceViewer(project.id, doc.id)} className="clickable-doc-row">
                          <td>
                            <div className="doc-name-cell">
                              {renderFileIcon(docType)}
                              <div>
                                <strong className="doc-primary-name">{docName}</strong>
                                <div className="doc-size-text">{doc.size || ''}</div>
                              </div>
                            </div>
                          </td>
                          <td><span className="category-pill">{docType}</span></td>
                          <td><span className="ver-sub">{doc.version || 'v1'}</span></td>
                          <td><span className="doc-status-badge processed"><CheckCircle2 size={11} /> {doc.status || 'Processed'}</span></td>
                          <td><span className="meta-date">{docDate}</span></td>
                          <td><span className="author-name">{doc.uploadedBy || doc.uploader || ''}</span></td>
                          <td className="align-right" onClick={(e) => e.stopPropagation()}>
                            <div className="doc-actions-cluster">
                              <button type="button" className="btn-doc-action" onClick={() => onOpenEvidenceViewer(project.id, doc.id)}>
                                <Eye size={14} />
                              </button>
                              <button type="button" className="btn-doc-action" onClick={() => handleExportWbs('PDF')}>
                                <Download size={14} />
                              </button>
                              <div className="relative-menu-anchor">
                                <button type="button" className="btn-doc-action" onClick={() => setActiveDocMenuId(isMenuOpen ? null : doc.id)}>
                                  <MoreVertical size={14} />
                                </button>
                                {isMenuOpen && (
                                  <div className="dropdown-menu-sheet">
                                    <button type="button" onClick={() => onOpenEvidenceViewer(project.id, doc.id)}>
                                      <Eye size={13} color="#2563EB" /> Source Evidence Viewer
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="documents-right-sidebar">
            <div className="sidebar-card">
              <div className="sidebar-card-title-row">
                <h3 className="sidebar-card-title">Project Information</h3>
              </div>
              <div className="keyvalue-meta-stack">
                {pCode && <div className="kv-row"><span>Project Code</span><strong>{pCode}</strong></div>}
                <div className="kv-row"><span>Project Name</span><strong>{project.name}</strong></div>
                {pType && <div className="kv-row"><span>Project Type</span><strong>{pType}</strong></div>}
                {pLocation && <div className="kv-row"><span>Location</span><strong>{pLocation}</strong></div>}
                {pOwner && <div className="kv-row"><span>Owner</span><strong>{pOwner}</strong></div>}
                {pCreated && <div className="kv-row"><span>Created On</span><strong>{pCreated}</strong></div>}
                <div className="kv-row"><span>Status</span><span className="status-green-pill">{pStatus}</span></div>
              </div>
            </div>

            <div className="sidebar-card">
              <h3 className="sidebar-card-title">Quick Actions</h3>
              <div className="quick-actions-menu">
                <button type="button" className="quick-action-link" onClick={onGenerateNewWbs}>
                  <div className="qa-left"><Plus size={15} color="#2563EB" /> <span>Generate New WBS</span></div>
                  <ChevronRight size={14} color="#94A3B8" />
                </button>
                <button type="button" className="quick-action-link" onClick={() => setActiveTab('WBS')}>
                  <div className="qa-left"><Layers size={15} color="#059669" /> <span>View WBS List</span></div>
                  <ChevronRight size={14} color="#94A3B8" />
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'WBS' && (
        <div className="hub-tab-body version-history-layout">
          <div className="versions-timeline-col">
            <div className="vh-header-row">
              <div>
                <h2 className="vh-heading">WBS Version History</h2>
                <p className="vh-sub">All versions of WBS generated for this project. You can view, compare, restore or export any version.</p>
              </div>
              <div className="vh-search-box">
                <Search size={14} color="#94A3B8" />
                <input type="text" placeholder="Search version name..." value={versionSearch} onChange={(e) => setVersionSearch(e.target.value)} />
              </div>
            </div>

            <div className="version-timeline-stack">
              {versionsList.length === 0 ? (
                <p className="section-subheading" style={{ padding: '20px 0' }}>No WBS version history available.</p>
              ) : (
                versionsList.map((ver) => {
                  const isSelected = selectedVersion?.id === ver.id;
                  return (
                    <div key={ver.id} className={`version-timeline-card ${isSelected ? 'card-selected' : ''}`} onClick={() => setSelectedVersionId(ver.id)}>
                      <div className="timeline-node-dot" />
                      <div className="ver-main-col">
                        <div className="ver-title-line">
                          <span className="ver-code-badge">{ver.version || 'v1.0'}</span>
                          <span className={`status-pill-small ${(ver.status || 'Draft').toLowerCase().replace(/\s+/g, '-')}`}>
                            {ver.status || 'Draft'}
                          </span>
                        </div>
                        <h4 className="ver-title-name">{ver.name || 'Baseline WBS'}</h4>
                        <p className="ver-desc-snippet">{ver.description}</p>
                      </div>
                      <div className="ver-coverage-col">
                        <span className="col-sub-lbl">Coverage</span>
                        <strong className="coverage-text">{ver.scopeCoverage || pCoverage}%</strong>
                      </div>
                      <div className="ver-meta-col">
                        <span className="col-sub-lbl">Created On</span>
                        <span className="col-val-text">{ver.generatedOn || (ver.created_at ? new Date(ver.created_at).toLocaleDateString() : '')}</span>
                      </div>
                      <div className="ver-open-btn-col" onClick={(e) => e.stopPropagation()}>
                        <button type="button" className="btn-open-wbs-direct" onClick={() => onOpenWbsView(project.id)}>
                          Open
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {selectedVersion && (
            <div className="versions-detail-panel">
              <div className="version-detail-card">
                <div className="vd-header-row">
                  <h3 className="vd-title">Version Details</h3>
                  <span className="status-pill-small approved">{selectedVersion.status || 'Approved'}</span>
                </div>
                <div className="vd-meta-table">
                  <div className="vd-row"><span>Version</span><strong>{selectedVersion.version || 'v1.0'}</strong></div>
                  <div className="vd-row"><span>Version Name</span><strong>{selectedVersion.name || 'WBS'}</strong></div>
                  <div className="vd-row"><span>Coverage</span><strong>{selectedVersion.scopeCoverage || pCoverage}%</strong></div>
                  <div className="vd-row"><span>Status</span><strong className="status-green-text">{selectedVersion.status || 'Approved'}</strong></div>
                </div>
              </div>

              <div className="version-actions-card">
                <h3 className="vd-title">Version Actions</h3>
                <div className="va-buttons-stack">
                  <button type="button" className="va-btn-row" onClick={() => onOpenWbsView(project.id)}>
                    <div className="va-left"><Layers size={15} color="#2563EB" /> <span>Open in WBS Builder</span></div>
                    <ChevronRight size={14} color="#94A3B8" />
                  </button>
                  <button type="button" className="va-btn-row" onClick={() => onOpenEvidenceViewer(project.id)}>
                    <div className="va-left"><GitCompare size={15} color="#059669" /> <span>View Linked Source Evidence</span></div>
                    <ChevronRight size={14} color="#94A3B8" />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === 'Activity' && (
        <div className="hub-tab-body activity-log-view">
          <div className="activity-card-container">
            <h3 className="section-heading">Project Activity & Audit Trail</h3>
            <div className="activity-timeline">
              <div className="activity-item">
                <div className="act-bullet blue" />
                <div className="act-info">
                  <strong>Project Initialized</strong>
                  <p>Created baseline project workspace records in live database</p>
                  <small>{pCreated} {pOwner ? `• by ${pOwner}` : ''}</small>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <input ref={fileInputRef} type="file" style={{ display: 'none' }} onChange={(e) => void handleUploadDocument(e)} />
    </div>
  );
};

export default ProjectDetailScreen;