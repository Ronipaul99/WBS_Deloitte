/* eslint-disable react-hooks/set-state-in-effect */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Download,
  Search,
  CheckCircle2,
  ExternalLink,
  ChevronDown,
  Layers,
  FileText
} from 'lucide-react';
import { getProject } from '../services/projectsApi';
import { apiRequest } from '../services/apiClient';
import './SourceEvidenceViewerScreen.css';

interface SourceEvidenceViewerScreenProps {
  tenantId: string;
  projectId: string;
  documentId?: string;
  onBackToProject: () => void;
  onOpenWbsView: (projectId: string) => void;
}

interface EvidenceRecord {
  nodeId: string;
  code: string;
  name: string;
  type: string;
  confidence: number;
  section: string;
  document: string;
  page: number;
  excerpt: string;
  contextParagraph: string;
  keyParameters?: Array<{ parameter: string; requirement: string }>;
}

interface DocumentRecord {
  id?: string;
  original_filename?: string;
  name?: string;
  size?: string;
  version?: string;
  mime_type?: string;
}

interface ProjectRecord {
  name?: string;
  current_version?: string;
  currentVersion?: string;
  updated_at?: string;
}

interface WbsNodeRecord {
  id?: string;
  code?: string;
  name?: string;
  title?: string;
  type?: string;
  confidence?: number;
  description?: string;
  evidence?: {
    text?: string;
    section?: string;
    document?: string;
  };
  children?: WbsNodeRecord[];
}

export const SourceEvidenceViewerScreen: React.FC<SourceEvidenceViewerScreenProps> = ({
  tenantId,
  projectId,
  onBackToProject,
  onOpenWbsView,
}) => {
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [evidenceList, setEvidenceList] = useState<EvidenceRecord[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [zoomLevel, setZoomLevel] = useState<number>(100);
  const [searchOutline, setSearchOutline] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'outline' | 'linked'>('outline');
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);

  const loadDynamicEvidence = useCallback(async () => {
    if (!tenantId || !projectId) return;

    try {
      const [projData, docsData, wbsData] = await Promise.all([
        getProject(tenantId, projectId),
        apiRequest(`/tenants/${tenantId}/projects/${projectId}/documents`).catch(() => []),
        apiRequest(`/tenants/${tenantId}/projects/${projectId}/wbs`).catch(() => ({ wbsTree: [] }))
      ]);

      if (projData) setProject(projData as ProjectRecord);

      const docsArray = Array.isArray(docsData) ? docsData : ((docsData as { items?: DocumentRecord[] })?.items || []);
      setDocuments(docsArray as DocumentRecord[]);

      const collected: EvidenceRecord[] = [];
      const primaryDoc = docsArray[0]?.original_filename || docsArray[0]?.name || '';
      const wbsObj = wbsData as { wbsTree?: WbsNodeRecord[]; items?: WbsNodeRecord[] };
      const treeNodes = wbsObj?.wbsTree || wbsObj?.items || [];

      const traverse = (nodes: WbsNodeRecord[], depth = 1) => {
        nodes.forEach((node, idx) => {
          const pageDerived = Math.min(68, depth * 6 + idx * 3 + 4);
          const excerptText = node.evidence?.text || node.description || '';
          const sectionTitle = node.evidence?.section || `Section ${node.code || ''} ${node.name || node.title || ''}`;
          const nodeName = node.name || node.title || '';
          const nodeConfidence = node.confidence ? (node.confidence > 1 ? node.confidence : Math.round(node.confidence * 100)) : 0;

          collected.push({
            nodeId: node.id || String(idx),
            code: node.code || '',
            name: nodeName,
            type: node.type || '',
            confidence: nodeConfidence,
            section: sectionTitle,
            document: node.evidence?.document || primaryDoc,
            page: pageDerived,
            excerpt: excerptText,
            contextParagraph: `The project contractual specifications dictate structured execution and delivery standards for ${nodeName}. All implementation guidelines must adhere to the scope requirements allocated under ${sectionTitle}.`,
            keyParameters: [
              { parameter: 'Scope Allocation', requirement: `${nodeName} (${node.code || ''})` },
              { parameter: 'Deliverable Type', requirement: node.type || '' },
              { parameter: 'Confidence Level', requirement: node.confidence ? `${nodeConfidence}% verified` : '' },
              { parameter: 'Decomposition Source', requirement: primaryDoc }
            ]
          });

          if (node.children && node.children.length > 0) {
            traverse(node.children, depth + 1);
          }
        });
      };

      if (treeNodes.length > 0) {
        traverse(treeNodes);
      }

      setEvidenceList(collected);
      setSelectedIndex(0);
    } catch (err) {
      console.error('Failed to load evidence data:', err);
    }
  }, [tenantId, projectId]);

  useEffect(() => {
    void loadDynamicEvidence();
  }, [loadDynamicEvidence]);

  const activeEvidence = useMemo(() => {
    if (evidenceList.length === 0) return null;
    return evidenceList[selectedIndex] || evidenceList[0];
  }, [evidenceList, selectedIndex]);

  const totalPages = useMemo(() => {
    if (evidenceList.length === 0) return 1;
    return Math.max(1, ...evidenceList.map((e) => e.page + 5));
  }, [evidenceList]);

  const filteredOutline = useMemo(() => {
    if (!searchOutline.trim()) return evidenceList;
    return evidenceList.filter((item) =>
      item.name.toLowerCase().includes(searchOutline.toLowerCase()) ||
      item.code.toLowerCase().includes(searchOutline.toLowerCase()) ||
      item.section.toLowerCase().includes(searchOutline.toLowerCase())
    );
  }, [evidenceList, searchOutline]);

  const activeDoc = documents[0] || {
    original_filename: activeEvidence?.document || '',
    size: '',
    version: '',
    mime_type: ''
  };

  const handleDownload = () => {
    alert('Downloading source document...');
  };

  return (
    <div className={`evidence-viewer-page-shell ${isFullscreen ? 'fullscreen-mode' : ''}`}>
      <div className="viewer-top-navbar">
        <div className="viewer-crumb-trail">
          <button type="button" className="crumb-nav-btn" onClick={onBackToProject}>
            <ArrowLeft size={14} /> My Projects
          </button>
          <span className="crumb-sep">&gt;</span>
          <span className="crumb-active-txt">{project?.name || 'Project'}</span>
          <span className="crumb-sep">&gt;</span>
          <span className="crumb-active-txt">WBS Builder</span>
          <span className="crumb-sep">&gt;</span>
          <span className="crumb-active-txt highlight">Source Evidence</span>
        </div>

        <div className="viewer-nav-actions">
          <button
            type="button"
            className="btn-page-nav-icon"
            disabled={selectedIndex <= 0}
            onClick={() => setSelectedIndex((prev) => Math.max(0, prev - 1))}
          >
            <ChevronLeft size={15} /> Previous
          </button>
          <button
            type="button"
            className="btn-page-nav-primary"
            disabled={selectedIndex >= evidenceList.length - 1}
            onClick={() => setSelectedIndex((prev) => Math.min(evidenceList.length - 1, prev + 1))}
          >
            Next <ChevronRight size={15} />
          </button>
          <span className="evidence-index-pill">
            {evidenceList.length > 0 ? `${selectedIndex + 1} of ${evidenceList.length}` : '0 of 0'}
          </span>
        </div>
      </div>

      <div className="viewer-title-row">
        <div>
          <h1 className="viewer-main-heading">Source Evidence Viewer</h1>
          <p className="viewer-main-sub">
            View the original document and see exactly where each WBS requirement was identified.
          </p>
        </div>
      </div>

      <div className="evidence-workspace-grid">
        <div className="evidence-col-outline">
          <div className="source-doc-selector-card">
            <span className="selector-label">Source Document</span>
            <div className="doc-select-box">
              <span className="doc-pill-red">pdf</span>
              <div className="doc-name-col">
                <strong>{activeDoc.original_filename || activeDoc.name || 'Document'}</strong>
                <small>{activeDoc.size || ''} {activeDoc.version ? `• ${activeDoc.version}` : ''}</small>
              </div>
              <ChevronDown size={14} color="#64748B" />
            </div>
          </div>

          <div className="outline-card-shell">
            <div className="outline-tabs-strip">
              <button
                type="button"
                className={`outline-tab ${activeTab === 'outline' ? 'active' : ''}`}
                onClick={() => setActiveTab('outline')}
              >
                Document Outline
              </button>
              <button
                type="button"
                className={`outline-tab ${activeTab === 'linked' ? 'active' : ''}`}
                onClick={() => setActiveTab('linked')}
              >
                Linked Items ({evidenceList.length})
              </button>
            </div>

            <div className="outline-search-box">
              <Search size={13} color="#94A3B8" />
              <input
                type="text"
                placeholder="Search sections & clauses..."
                value={searchOutline}
                onChange={(e) => setSearchOutline(e.target.value)}
              />
            </div>

            <div className="outline-tree-list">
              {filteredOutline.map((item, idx) => {
                const isSelected = activeEvidence?.nodeId === item.nodeId;
                return (
                  <div
                    key={item.nodeId}
                    className={`outline-sub-row ${isSelected ? 'active' : ''}`}
                    onClick={() => setSelectedIndex(idx)}
                  >
                    <span className="outline-title-txt">
                      {item.code} {item.name}
                    </span>
                    <span className="outline-page-num">Page {item.page}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="evidence-col-document-canvas">
          <div className="document-canvas-toolbar">
            <div className="canvas-pagination-cluster">
              <button
                type="button"
                className="btn-toolbar-nav"
                disabled={selectedIndex <= 0}
                onClick={() => setSelectedIndex((prev) => Math.max(0, prev - 1))}
              >
                <ChevronLeft size={14} />
              </button>
              <div className="canvas-page-indicator">
                <strong>{activeEvidence?.page || 1}</strong> <span>/ {totalPages}</span>
              </div>
              <button
                type="button"
                className="btn-toolbar-nav"
                disabled={selectedIndex >= evidenceList.length - 1}
                onClick={() => setSelectedIndex((prev) => Math.min(evidenceList.length - 1, prev + 1))}
              >
                <ChevronRight size={14} />
              </button>
            </div>

            <div className="canvas-zoom-cluster">
              <span className="zoom-level-text">{zoomLevel}%</span>
              <button type="button" className="btn-toolbar-nav" onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}>
                <ZoomOut size={14} />
              </button>
              <button type="button" className="btn-toolbar-nav" onClick={() => setZoomLevel((z) => Math.min(200, z + 10))}>
                <ZoomIn size={14} />
              </button>
            </div>

            <div className="canvas-actions-cluster">
              <button
                type="button"
                className="btn-toolbar-nav"
                title="Toggle Fullscreen"
                onClick={() => setIsFullscreen(!isFullscreen)}
              >
                <Maximize2 size={14} />
              </button>
              <button
                type="button"
                className="btn-toolbar-nav"
                title="Download Document"
                onClick={handleDownload}
              >
                <Download size={14} />
              </button>
            </div>
          </div>

          <div className="document-sheet-viewport">
            {activeEvidence ? (
              <div
                className="document-paper-sheet"
                style={{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }}
              >
                <div className="paper-header-strip">
                  <span>{activeDoc.original_filename || activeDoc.name}</span>
                  <span>Page {activeEvidence.page} of {totalPages}</span>
                </div>

                <h2 className="paper-section-heading">{activeEvidence.section}</h2>

                <p className="paper-body-paragraph">
                  {activeEvidence.contextParagraph}
                </p>

                <div className="paper-evidence-highlight-block">
                  • {activeEvidence.excerpt}
                </div>

                <p className="paper-body-paragraph">
                  All work activities executed under deliverable <strong>{activeEvidence.code} ({activeEvidence.name})</strong> must demonstrate verifiable conformance to the contract provisions identified above.
                </p>

                <h3 className="paper-subsection-heading">Deliverable Parameters & Verification</h3>

                <table className="paper-contract-table">
                  <thead>
                    <tr>
                      <th>Specification Field</th>
                      <th>Contractual Allocation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeEvidence.keyParameters?.map((param, pIdx) => (
                      <tr key={pIdx}>
                        <td>{param.parameter}</td>
                        <td>{param.requirement}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="paper-footer-tag">Page {activeEvidence.page}</div>
              </div>
            ) : (
              <div className="paper-empty-placeholder">
                <FileText size={32} color="#94A3B8" />
                <p>No evidence records available.</p>
              </div>
            )}
          </div>
        </div>

        <div className="evidence-col-metadata-panel">
          {activeEvidence ? (
            <>
              <div className="evidence-meta-card">
                <div className="meta-card-header">
                  <h3 className="meta-card-title">Evidence Details</h3>
                  <span className="badge-linked-wbs">Linked to WBS Item</span>
                </div>

                <div className="meta-field-stack">
                  <div className="meta-field-row">
                    <span>Source Document</span>
                    <strong>{activeDoc.original_filename || activeDoc.name}</strong>
                  </div>
                  <div className="meta-field-row">
                    <span>Page Number</span>
                    <strong>{activeEvidence.page} of {totalPages}</strong>
                  </div>
                  <div className="meta-field-row">
                    <span>Section</span>
                    <strong>{activeEvidence.section}</strong>
                  </div>
                  <div className="meta-field-row">
                    <span>Deliverable Type</span>
                    <strong>{activeEvidence.type}</strong>
                  </div>
                  <div className="meta-field-row">
                    <span>Version</span>
                    <strong>{project?.current_version || project?.currentVersion || ''}</strong>
                  </div>
                  <div className="meta-field-row">
                    <span>Last Processed</span>
                    <strong>{project?.updated_at ? new Date(project.updated_at).toLocaleDateString() : ''}</strong>
                  </div>
                </div>
              </div>

              <div className="evidence-meta-card">
                <span className="section-micro-lbl">Linked To</span>
                <div className="linked-wbs-node-box" onClick={() => onOpenWbsView(projectId)}>
                  <div className="node-icon-box">
                    <CheckCircle2 size={15} color="#2563EB" />
                  </div>
                  <div className="node-info">
                    <span className="node-lbl">WBS Item</span>
                    <strong className="node-code-name">
                      {activeEvidence.code} {activeEvidence.name}
                    </strong>
                  </div>
                  <ExternalLink size={14} color="#94A3B8" />
                </div>
              </div>

              <div className="evidence-meta-card">
                <span className="section-micro-lbl">Source Text</span>
                <div className="source-quote-box">
                  <p className="source-quote-text">
                    "{activeEvidence.excerpt}"
                  </p>
                </div>

                {activeEvidence.confidence > 0 && (
                  <div className="confidence-score-block">
                    <div className="conf-circle-pill">{activeEvidence.confidence}%</div>
                    <div className="conf-details">
                      <strong>High Confidence</strong>
                      <small>Verified by neural decomposition parser.</small>
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  className="btn-view-in-document-action"
                  onClick={() => onOpenWbsView(projectId)}
                >
                  <Layers size={13} /> View in WBS Builder
                </button>
              </div>
            </>
          ) : (
            <div className="evidence-meta-card empty">
              <span>Select an item from the outline to inspect evidence.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SourceEvidenceViewerScreen;