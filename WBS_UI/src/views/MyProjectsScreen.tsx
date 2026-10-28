/* eslint-disable react-hooks/set-state-in-effect */
import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Search,
  Plus,
  ChevronDown,
  LayoutGrid,
  List as ListIcon,
  FilterX,
  ChevronLeft,
  ChevronRight,
  MoreVertical,
  ExternalLink,
  FileDown,
  CheckCircle2,
  Clock,
  RefreshCw,
  AlertTriangle,
  FolderKanban,
  FileText,
  Trash2,
  X
} from 'lucide-react';
import { listProjects } from '../services/projectsApi';
import { apiRequest } from '../services/apiClient';
import './MyProjectsScreen.css';

interface ProjectItem {
  id: string;
  tenant_id: string;
  name: string;
  description?: string | null;
  status?: string;
  project_code?: string;
  code?: string;
  project_type?: string;
  type?: string;
  scope_coverage?: number;
  scopeCoverage?: number;
  current_version?: string;
  currentVersion?: string;
  version?: string;
  owner?: string;
  updated_at?: string;
  lastUpdated?: string;
}

interface MyProjectsScreenProps {
  tenantId: string;
  currentUserName?: string;
  onNavigate: (view: string, meta?: Record<string, unknown>) => void;
}

type SortField = 'name' | 'wbsStatus' | 'lastUpdated';
type ViewMode = 'table' | 'cards';

const STATUS_FILTER_TABS = [
  'All Projects',
  'Processing',
  'Draft',
  'Under Review',
  'Approved',
  'Exported',
  'Archived'
] as const;

export const MyProjectsScreen: React.FC<MyProjectsScreenProps> = ({
  tenantId,
  currentUserName = '',
  onNavigate,
}) => {
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('table');
  const [activeTab, setActiveTab] = useState<string>('All Projects');

  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('All Types');
  const [statusFilter, setStatusFilter] = useState('All Status');
  const [ownerFilter, setOwnerFilter] = useState('All Owners');

  const [sortField, setSortField] = useState<SortField>('lastUpdated');
  const [sortAsc, setSortAsc] = useState<boolean>(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage] = useState(10);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);

  const [projectToDelete, setProjectToDelete] = useState<{ id: string; name: string } | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);

  const menuRef = useRef<HTMLDivElement | null>(null);

  const fetchProjectsList = useCallback(async () => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await listProjects(tenantId);
      const projArray = Array.isArray(data) ? data : ((data as { items?: ProjectItem[] })?.items || []);
      setProjects(projArray as ProjectItem[]);
      setError(null);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load projects from backend.';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchProjectsList();
  }, [fetchProjectsList]);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setActiveMenuId(null);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  const confirmDeleteProject = async () => {
    if (!projectToDelete || isDeleting || !tenantId) return;
    setIsDeleting(true);
    try {
      await apiRequest(`/tenants/${tenantId}/projects/${projectToDelete.id}`, { method: 'DELETE' });
      await fetchProjectsList();
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete project.';
      alert(errorMessage);
    } finally {
      setIsDeleting(false);
      setProjectToDelete(null);
      setActiveMenuId(null);
    }
  };

  const totalCount = projects.length;
  const approvedCount = projects.filter((p) => {
    const s = (p.status || '').toLowerCase();
    return s === 'approved' || s === 'active';
  }).length;
  const underReviewCount = projects.filter((p) => (p.status || '').toLowerCase() === 'under review').length;
  const processingCount = projects.filter((p) => (p.status || '').toLowerCase() === 'processing').length;
  const needsAttentionCount = projects.filter((p) => (p.status || '').toLowerCase() === 'needs attention').length;

  const approvedPercent = totalCount > 0 ? Math.round((approvedCount / totalCount) * 100) : 0;
  const underReviewPercent = totalCount > 0 ? Math.round((underReviewCount / totalCount) * 100) : 0;
  const processingPercent = totalCount > 0 ? Math.round((processingCount / totalCount) * 100) : 0;
  const needsAttentionPercent = totalCount > 0 ? Math.round((needsAttentionCount / totalCount) * 100) : 0;

  const isDraftStatus = (statusVal: string) => {
    const s = String(statusVal || '').toLowerCase();
    return s.includes('draft');
  };

  const tabCounts = useMemo(() => {
    return {
      'All Projects': projects.length,
      'Processing': projects.filter((p) => (p.status || '').toLowerCase() === 'processing').length,
      'Draft': projects.filter((p) => isDraftStatus(p.status || '')).length,
      'Under Review': projects.filter((p) => (p.status || '').toLowerCase() === 'under review').length,
      'Approved': projects.filter((p) => {
        const s = (p.status || '').toLowerCase();
        return s === 'approved' || s === 'active';
      }).length,
      'Exported': projects.filter((p) => (p.status || '').toLowerCase() === 'exported').length,
      'Archived': projects.filter((p) => (p.status || '').toLowerCase() === 'archived').length,
    };
  }, [projects]);

  const distinctTypes = useMemo(() => {
    const set = new Set(projects.map((p) => p.project_type || p.type).filter(Boolean));
    return ['All Types', ...Array.from(set)];
  }, [projects]);

  const distinctStatuses = useMemo(() => {
    const set = new Set(projects.map((p) => p.status).filter(Boolean));
    return ['All Status', ...Array.from(set)];
  }, [projects]);

  const distinctOwners = useMemo(() => {
    const set = new Set(projects.map((p) => p.owner || currentUserName).filter(Boolean));
    return ['All Owners', ...Array.from(set)];
  }, [projects, currentUserName]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  const filteredProjects = useMemo(() => {
    return projects
      .filter((p) => {
        const pStatus = p.status || '';
        if (activeTab === 'Processing' && pStatus.toLowerCase() !== 'processing') return false;
        if (activeTab === 'Draft' && !isDraftStatus(pStatus)) return false;
        if (activeTab === 'Under Review' && pStatus.toLowerCase() !== 'under review') return false;
        if (activeTab === 'Approved' && pStatus.toLowerCase() !== 'approved' && pStatus.toLowerCase() !== 'active') return false;
        if (activeTab === 'Exported' && pStatus.toLowerCase() !== 'exported') return false;
        if (activeTab === 'Archived' && pStatus.toLowerCase() !== 'archived') return false;

        const pName = p.name || '';
        const pCode = p.project_code || p.code || '';
        const pOwner = p.owner || currentUserName;

        const matchesSearch =
          pName.toLowerCase().includes(searchQuery.toLowerCase()) ||
          pCode.toLowerCase().includes(searchQuery.toLowerCase()) ||
          pOwner.toLowerCase().includes(searchQuery.toLowerCase());

        const pType = p.project_type || p.type || 'General Workstream';
        const matchesType = typeFilter === 'All Types' || pType === typeFilter;
        const matchesStatus = statusFilter === 'All Status' || pStatus === statusFilter;
        const matchesOwner = ownerFilter === 'All Owners' || pOwner === ownerFilter;

        return matchesSearch && matchesType && matchesStatus && matchesOwner;
      })
      .sort((a, b) => {
        let valA = a.name;
        let valB = b.name;
        if (sortField === 'wbsStatus') {
          valA = a.status || '';
          valB = b.status || '';
        } else if (sortField === 'lastUpdated') {
          valA = a.updated_at || a.lastUpdated || '';
          valB = b.updated_at || b.lastUpdated || '';
        }
        const cmp = String(valA || '').localeCompare(String(valB || ''));
        return sortAsc ? cmp : -cmp;
      });
  }, [projects, activeTab, searchQuery, typeFilter, statusFilter, ownerFilter, sortField, sortAsc, currentUserName]);

  const totalPages = Math.max(1, Math.ceil(filteredProjects.length / rowsPerPage));
  const paginatedProjects = filteredProjects.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  );

  const clearAllFilters = () => {
    setSearchQuery('');
    setTypeFilter('All Types');
    setStatusFilter('All Status');
    setOwnerFilter('All Owners');
    setActiveTab('All Projects');
    setCurrentPage(1);
  };

  const hasActiveFilters =
    Boolean(searchQuery) ||
    typeFilter !== 'All Types' ||
    statusFilter !== 'All Status' ||
    ownerFilter !== 'All Owners' ||
    activeTab !== 'All Projects';

  const renderStatusBadge = (status: string) => {
    if (!status) return null;
    const s = status.toLowerCase();
    if (s.includes('approved') || s.includes('active')) {
      return <span className="wbs-status-pill approved"><CheckCircle2 size={12} /> {status}</span>;
    }
    if (s.includes('review')) {
      return <span className="wbs-status-pill under-review"><Clock size={12} /> {status}</span>;
    }
    if (s.includes('process')) {
      return <span className="wbs-status-pill processing"><RefreshCw size={12} className="spin-inline" /> {status}</span>;
    }
    if (s.includes('attention')) {
      return <span className="wbs-status-pill needs-attention"><AlertTriangle size={12} /> {status}</span>;
    }
    if (s.includes('export')) {
      return <span className="wbs-status-pill exported"><FileDown size={12} /> {status}</span>;
    }
    return <span className="wbs-status-pill draft"><FileText size={12} /> {status}</span>;
  };

  return (
    <div className="my-projects-page-shell">
      <div className="my-projects-header-row">
        <div>
          <h1 className="my-projects-title">My Projects</h1>
          <p className="my-projects-subtitle">
            Manage all your projects and their WBS generation activities.
          </p>
        </div>

        <button
          type="button"
          className="btn-primary-create-wbs"
          onClick={() => onNavigate('create-wbs')}
        >
          <Plus size={15} /> Create New WBS <ChevronDown size={14} />
        </button>
      </div>

      <div className="my-projects-kpi-grid">
        <div className="project-kpi-card">
          <div className="kpi-icon-square blue"><FolderKanban size={22} /></div>
          <div className="kpi-meta-block">
            <span className="kpi-main-number">{totalCount}</span>
            <span className="kpi-title-label">Total Projects</span>
            <small className="kpi-subtext">Live database sync</small>
          </div>
        </div>
        <div className="project-kpi-card">
          <div className="kpi-icon-square green"><CheckCircle2 size={22} /></div>
          <div className="kpi-meta-block">
            <span className="kpi-main-number">{approvedCount}</span>
            <span className="kpi-title-label">Approved WBS</span>
            <small className="kpi-subtext">{approvedPercent}% of total</small>
          </div>
        </div>
        <div className="project-kpi-card">
          <div className="kpi-icon-square amber"><Clock size={22} /></div>
          <div className="kpi-meta-block">
            <span className="kpi-main-number">{underReviewCount}</span>
            <span className="kpi-title-label">Under Review</span>
            <small className="kpi-subtext">{underReviewPercent}% of total</small>
          </div>
        </div>
        <div className="project-kpi-card">
          <div className="kpi-icon-square purple"><RefreshCw size={22} /></div>
          <div className="kpi-meta-block">
            <span className="kpi-main-number">{processingCount}</span>
            <span className="kpi-title-label">Processing</span>
            <small className="kpi-subtext">{processingPercent}% of total</small>
          </div>
        </div>
        <div className="project-kpi-card">
          <div className="kpi-icon-square red"><AlertTriangle size={22} /></div>
          <div className="kpi-meta-block">
            <span className="kpi-main-number">{needsAttentionCount}</span>
            <span className="kpi-title-label">Needs Attention</span>
            <small className="kpi-subtext">{needsAttentionPercent}% of total</small>
          </div>
        </div>
      </div>

      <div className="my-projects-tabs-row">
        <div className="filter-pills-cluster">
          {STATUS_FILTER_TABS.map((tab) => {
            const count = tabCounts[tab] ?? 0;
            const isSelected = activeTab === tab;
            return (
              <button
                key={tab}
                type="button"
                className={`filter-tab-pill ${isSelected ? 'active' : ''}`}
                onClick={() => { setActiveTab(tab); setCurrentPage(1); }}
              >
                <span>{tab}</span>
                <span className={`pill-counter ${isSelected ? 'active-count' : ''}`}>{count}</span>
              </button>
            );
          })}
        </div>

        <div className="view-mode-toggle-group">
          <button
            type="button"
            className={`btn-view-toggle ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => setViewMode('table')}
          >
            <ListIcon size={15} /> <span>Table</span>
          </button>
          <button
            type="button"
            className={`btn-view-toggle ${viewMode === 'cards' ? 'active' : ''}`}
            onClick={() => setViewMode('cards')}
          >
            <LayoutGrid size={15} /> <span>Cards</span>
          </button>
        </div>
      </div>

      <div className="my-projects-controls-strip">
        <div className="projects-search-field">
          <Search size={15} color="#94A3B8" />
          <input
            type="text"
            placeholder="Search by project name, code or owner..."
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
          />
        </div>

        <div className="projects-dropdowns-cluster">
          <div className="select-pill-wrapper">
            <label className="select-inline-label">Project Type</label>
            <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setCurrentPage(1); }}>
              {distinctTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div className="select-pill-wrapper">
            <label className="select-inline-label">Status</label>
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }}>
              {distinctStatuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="select-pill-wrapper">
            <label className="select-inline-label">Owner</label>
            <select value={ownerFilter} onChange={(e) => { setOwnerFilter(e.target.value); setCurrentPage(1); }}>
              {distinctOwners.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>

          {hasActiveFilters && (
            <button type="button" className="btn-clear-project-filters" onClick={clearAllFilters}>
              <FilterX size={14} /> Clear Filters
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="projects-loading-box">
          <RefreshCw size={24} className="spin-inline" color="#2563EB" />
          <span>Loading live project repository...</span>
        </div>
      ) : error ? (
        <div className="projects-empty-card">
          <AlertTriangle size={32} color="#DC2626" />
          <h3>Error Loading Projects</h3>
          <p>{error}</p>
        </div>
      ) : paginatedProjects.length === 0 ? (
        <div className="projects-empty-card">
          <FolderKanban size={40} color="#94A3B8" />
          <h3>No Projects Found</h3>
          <p>There are no projects matching your current filters or search terms.</p>
          <button type="button" className="btn-primary-create-wbs" onClick={clearAllFilters}>
            Clear Filters
          </button>
        </div>
      ) : viewMode === 'table' ? (
        <div className="projects-table-container">
          <table className="projects-data-table">
            <thead>
              <tr>
                <th onClick={() => handleSort('name')} className="sortable-head">
                  Project Name {sortField === 'name' ? (sortAsc ? '↑' : '↓') : '↑↓'}
                </th>
                <th>Project Code</th>
                <th>Project Type</th>
                <th onClick={() => handleSort('wbsStatus')} className="sortable-head">
                  WBS Status {sortField === 'wbsStatus' ? (sortAsc ? '↑' : '↓') : '↑↓'}
                </th>
                <th>Scope Coverage</th>
                <th>Current Version</th>
                <th>Owner</th>
                <th onClick={() => handleSort('lastUpdated')} className="sortable-head">
                  Last Updated {sortField === 'lastUpdated' ? (sortAsc ? '↑' : '↓') : '↑↓'}
                </th>
                <th className="align-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedProjects.map((p, index) => {
                const isMenuOpen = activeMenuId === p.id;
                const isNearBottom = index >= paginatedProjects.length - 2 && paginatedProjects.length > 2;
                
                const pCode = p.project_code || p.code || p.id.substring(0, 8).toUpperCase();
                const pType = p.project_type || p.type || 'Standard';
                const pStatus = p.status || '';
                const pCoverage = p.scope_coverage ?? p.scopeCoverage ?? 0;
                const pVersion = p.current_version || p.currentVersion || p.version || 'v1.0';
                const pOwner = p.owner || currentUserName || 'Workspace User';
                
                const ownerInitials = pOwner ? pOwner.split(' ').map((n: string) => n[0]).join('').substring(0, 2).toUpperCase() : 'WU';
                const lastUpdatedText = p.updated_at ? new Date(p.updated_at).toLocaleDateString() : (p.lastUpdated || '');

                return (
                  <tr key={p.id} className="project-table-row" onClick={() => onNavigate('project-detail', { projectId: p.id })}>
                    <td>
                      <div className="project-title-cell">
                        <div className="project-name-bold">{p.name}</div>
                        <div className="project-subtitle-sub">{p.description}</div>
                      </div>
                    </td>
                    <td><span className="project-code-tag">{pCode}</span></td>
                    <td><span className="project-type-tag">{pType}</span></td>
                    <td>{renderStatusBadge(pStatus)}</td>
                    <td>
                      <div className="coverage-bar-cell">
                        <div className="coverage-progress-track">
                          {pCoverage > 0 && (
                            <div
                              className="coverage-progress-fill"
                              style={{
                                width: `${pCoverage}%`,
                                backgroundColor: pCoverage >= 85 ? '#10B981' : pCoverage >= 50 ? '#3B82F6' : '#F59E0B'
                              }}
                            />
                          )}
                        </div>
                        <span className="coverage-percent-text">{pCoverage}%</span>
                      </div>
                    </td>
                    <td><span className="project-version-label">{pVersion}</span></td>
                    <td>
                      <div className="owner-cluster">
                        {ownerInitials && <span className="owner-avatar-pill">{ownerInitials}</span>}
                        <span className="owner-name-label">{pOwner}</span>
                      </div>
                    </td>
                    <td><span className="last-updated-text">{lastUpdatedText}</span></td>
                    <td className="align-right" onClick={(e) => e.stopPropagation()}>
                      <div className="row-action-anchor" ref={isMenuOpen ? menuRef : null}>
                        <button
                          type="button"
                          className="btn-action-more"
                          onClick={() => setActiveMenuId(isMenuOpen ? null : p.id)}
                        >
                          <MoreVertical size={15} />
                        </button>
                        {isMenuOpen && (
                          <div className="project-context-dropdown" style={isNearBottom ? { bottom: '100%', top: 'auto', marginBottom: '4px' } : undefined}>
                            <button type="button" onClick={() => { onNavigate('project-detail', { projectId: p.id }); setActiveMenuId(null); }}>
                              <ExternalLink size={13} color="#2563EB" /> View Project Hub
                            </button>
                            <hr className="dropdown-divider-line" />
                            <button
                              type="button"
                              className="dropdown-delete-btn"
                              onClick={(e) => {
                                e.stopPropagation();
                                setActiveMenuId(null);
                                setProjectToDelete({ id: p.id, name: p.name });
                              }}
                            >
                              <Trash2 size={13} color="#DC2626" /> Delete Project
                            </button>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="projects-pagination-strip">
            <span className="pagination-count-summary">
              Showing {(currentPage - 1) * rowsPerPage + 1} to {Math.min(currentPage * rowsPerPage, filteredProjects.length)} of {filteredProjects.length} projects
            </span>
            <div className="pagination-controls-block">
              <button type="button" className="btn-page-nav" disabled={currentPage === 1} onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}>
                <ChevronLeft size={15} />
              </button>
              {Array.from({ length: totalPages }).map((_, idx) => (
                <button
                  key={idx}
                  type="button"
                  className={`btn-page-number ${currentPage === idx + 1 ? 'active' : ''}`}
                  onClick={() => setCurrentPage(idx + 1)}
                >
                  {idx + 1}
                </button>
              ))}
              <button type="button" className="btn-page-nav" disabled={currentPage === totalPages} onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}>
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="projects-cards-grid">
          {paginatedProjects.map((p) => {
            const pCode = p.project_code || p.code || p.id.substring(0, 8).toUpperCase();
            const pType = p.project_type || p.type || 'Standard';
            const pStatus = p.status || '';
            const pCoverage = p.scope_coverage ?? p.scopeCoverage ?? 0;
            const pVersion = p.current_version || p.currentVersion || p.version || 'v1.0';
            const pOwner = p.owner || currentUserName || 'Workspace User';
            const ownerInitials = pOwner ? pOwner.split(' ').map((n: string) => n[0]).join('').substring(0, 2).toUpperCase() : 'WU';

            return (
              <div key={p.id} className="project-grid-card" onClick={() => onNavigate('project-detail', { projectId: p.id })}>
                <div className="card-top-header">
                  <div className="card-badge-row">
                    {pCode && <span className="project-code-tag">{pCode}</span>}
                    {renderStatusBadge(pStatus)}
                  </div>
                  <h3 className="card-project-name">{p.name}</h3>
                  <p className="card-project-subtitle">{p.description}</p>
                </div>
                <div className="card-body-metrics">
                  <div className="card-metric-line">
                    <span>Scope Coverage</span>
                    <strong>{pCoverage}%</strong>
                  </div>
                  <div className="coverage-progress-track">
                    {pCoverage > 0 && <div className="coverage-progress-fill" style={{ width: `${pCoverage}%`, backgroundColor: '#10B981' }} />}
                  </div>
                  <div className="card-meta-details-row">
                    {pType && <div><span className="meta-sub">Type:</span> <strong>{pType}</strong></div>}
                    {pVersion && <div><span className="meta-sub">Version:</span> <strong>{pVersion}</strong></div>}
                  </div>
                </div>
                <div className="card-bottom-footer">
                  <div className="owner-cluster">
                    {ownerInitials && <span className="owner-avatar-pill">{ownerInitials}</span>}
                    <span className="owner-name-label">{pOwner}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {projectToDelete && (
        <div className="wbs-modal-backdrop" onClick={() => !isDeleting && setProjectToDelete(null)}>
          <div className="wbs-modal-box" style={{ maxWidth: '420px' }} onClick={(e) => e.stopPropagation()}>
            <div className="wbs-modal-header">
              <h3 className="wbs-modal-title wbs-modal-title-destructive">Delete Project?</h3>
              <button type="button" className="wbs-modal-close-btn" disabled={isDeleting} onClick={() => setProjectToDelete(null)}>
                <X size={16} />
              </button>
            </div>
            <p className="wbs-modal-delete-confirm-text">
              Are you sure you want to delete project <strong>"{projectToDelete.name}"</strong>?
            </p>
            <div className="wbs-modal-footer">
              <button type="button" disabled={isDeleting} onClick={() => setProjectToDelete(null)} className="wbs-modal-cancel-btn">Cancel</button>
              <button type="button" disabled={isDeleting} onClick={confirmDeleteProject} className="wbs-modal-submit-btn-danger">
                {isDeleting ? 'Deleting...' : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MyProjectsScreen;