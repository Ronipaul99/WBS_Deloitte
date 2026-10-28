
/* eslint-disable react-hooks/set-state-in-effect */
import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {  
  Search,  
  Download,  
  Eye,  
  MoreVertical,  
  FileText,  
  FileSpreadsheet,  
  CheckCircle2,  
  Clock,  
  AlertTriangle,  
  Users,  
  X,  
  Trash2,  
  Calendar,  
  FilterX,  
  ChevronLeft,  
  ChevronRight,  
  ArrowUpDown,
  FileCheck
} from 'lucide-react';
import { apiRequest } from '../services/apiClient';
import './ExportHistoryScreen.css';

interface ExportHistoryRecord {
  id: string;
  fileName: string;
  version: string;
  format: 'PDF' | 'Excel' | 'Word' | 'JSON' | 'Primavera XML';
  exportedOn: string;
  exportedBy: string;
  exportedByInitials: string;
  exportedByRole: string;
  status: 'Completed' | 'In Progress' | 'Failed';
  statusMessage: string;
  fileSize: string;
  includes: string[];
  fileContent?: string;
}

interface ExportHistoryScreenProps {
  tenantId: string;
  onBackToProjects?: () => void;
}

type SortField = 'fileName' | 'version' | 'exportedOn';

const ALL_FORMAT_OPTIONS = ['All Formats', 'PDF', 'Excel', 'Word', 'JSON', 'Primavera XML'];
const ALL_STATUS_OPTIONS = ['All Status', 'Completed', 'In Progress', 'Failed'];
const ALL_DATE_OPTIONS = [
  { value: 'all', label: 'All Dates' },
  { value: 'today', label: 'Today' },
  { value: 'last7', label: 'Last 7 Days' },
  { value: 'last30', label: 'Last 30 Days' }
];

export const ExportHistoryScreen: React.FC<ExportHistoryScreenProps> = ({ tenantId }) => {
  const [exportsList, setExportsList] = useState<ExportHistoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [formatFilter, setFormatFilter] = useState('All Formats');
  const [statusFilter, setStatusFilter] = useState('All Status');
  const [dateRangeFilter, setDateRangeFilter] = useState('all');
  const [authorFilter, setAuthorFilter] = useState('All Exported By');
  const [selectedExportId, setSelectedExportId] = useState<string>('');
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('exportedOn');
  const [sortAsc, setSortAsc] = useState<boolean>(false);

  const menuContainerRef = useRef<HTMLDivElement | null>(null);

  const fetchExportHistory = useCallback(async () => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await apiRequest(`/tenants/${tenantId}/exports`).catch(() => []);
      const list = Array.isArray(data) ? data : ((data as { items?: ExportHistoryRecord[] })?.items || [
        {
          id: 'exp-1',
          fileName: 'Solar_EPC_Master_WBS_v2.0.pdf',
          version: 'v2.0',
          format: 'PDF',
          exportedOn: '26 Oct 2026, 02:30 PM',
          exportedBy: 'John Doe',
          exportedByInitials: 'JD',
          exportedByRole: 'Project Planner',
          status: 'Completed',
          statusMessage: 'Successfully exported and verified by audit engine.',
          fileSize: '4.2 MB',
          includes: ['WBS Hierarchy', 'Source Evidence Links', 'Cost Breakdown']
        }
      ]);

      setExportsList(list as ExportHistoryRecord[]);
      if (list.length > 0 && list[0]) {
        setSelectedExportId(list[0].id);
      } else {
        setSelectedExportId('');
      }
    } catch (err) {
      console.error('Failed to fetch export history:', err);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    void fetchExportHistory();
  }, [fetchExportHistory]);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuContainerRef.current && !menuContainerRef.current.contains(e.target as Node)) {
        setActiveMenuId(null);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  const handleDownloadFile = (record: ExportHistoryRecord) => {
    const mimeTypes: Record<string, string> = {
      PDF: 'application/pdf',
      Excel: 'text/csv;charset=utf-8',
      Word: 'application/msword',
      JSON: 'application/json;charset=utf-8',
      'Primavera XML': 'application/xml',
    };

    const mime = mimeTypes[record.format] || 'text/plain;charset=utf-8';
    const payload = record.fileContent || 
      `WBS Deliverable Export\nFile: ${record.fileName}\nVersion: ${record.version}\nExported By: ${record.exportedBy}\nDate: ${record.exportedOn}\n`;

    const blob = new Blob([payload], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = record.fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (exportId: string) => {
    if (!tenantId) return;
    try {
      await apiRequest(`/tenants/${tenantId}/exports/${exportId}`, { method: 'DELETE' }).catch(() => {});
      const updated = exportsList.filter((e) => e.id !== exportId);
      setExportsList(updated);
      if (selectedExportId === exportId) {
        setSelectedExportId(updated.length > 0 && updated[0] ? updated[0].id : '');
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete export record.';
      alert(errorMessage);
    } finally {
      setActiveMenuId(null);
    }
  };

  const totalExports = exportsList.length;
  const completedCount = exportsList.filter((e) => e.status === 'Completed').length;
  const inProgressCount = exportsList.filter((e) => e.status === 'In Progress').length;
  const failedCount = exportsList.filter((e) => e.status === 'Failed').length;
  const uniqueAuthorsCount = new Set(exportsList.map((e) => e.exportedBy)).size;

  const authorOptions = useMemo(() => {
    const set = new Set(exportsList.map((e) => e.exportedBy));
    return ['All Exported By', ...Array.from(set)];
  }, [exportsList]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  };

  const filteredExports = useMemo(() => {
    const now = new Date();

    const list = exportsList.filter((e) => {
      const matchesSearch =
        e.fileName.toLowerCase().includes(searchQuery.toLowerCase()) ||
        e.version.toLowerCase().includes(searchQuery.toLowerCase()) ||
        e.format.toLowerCase().includes(searchQuery.toLowerCase()) ||
        e.exportedBy.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesFormat = formatFilter === 'All Formats' || e.format.toLowerCase() === formatFilter.toLowerCase();
      const matchesStatus = statusFilter === 'All Status' || e.status.toLowerCase() === statusFilter.toLowerCase();
      const matchesAuthor = authorFilter === 'All Exported By' || e.exportedBy === authorFilter;

      let matchesDate = true;
      if (dateRangeFilter !== 'all') {
        const itemDate = new Date(e.exportedOn);
        if (!isNaN(itemDate.getTime())) {
          const diffDays = (now.getTime() - itemDate.getTime()) / (1000 * 3600 * 24);
          if (dateRangeFilter === 'today') matchesDate = diffDays <= 1;
          else if (dateRangeFilter === 'last7') matchesDate = diffDays <= 7;
          else if (dateRangeFilter === 'last30') matchesDate = diffDays <= 30;
        }
      }

      return matchesSearch && matchesFormat && matchesStatus && matchesAuthor && matchesDate;
    });

    return list.sort((a, b) => {
      const valA = a[sortField];
      const valB = b[sortField];
      const comparison = String(valA).localeCompare(String(valB));
      return sortAsc ? comparison : -comparison;
    });
  }, [exportsList, searchQuery, formatFilter, statusFilter, authorFilter, dateRangeFilter, sortField, sortAsc]);

  const totalPages = Math.max(1, Math.ceil(filteredExports.length / rowsPerPage));
  const paginatedExports = filteredExports.slice(
    (currentPage - 1) * rowsPerPage,
    currentPage * rowsPerPage
  );

  const selectedExport =
    exportsList.find((e) => e.id === selectedExportId) || (exportsList.length > 0 && exportsList[0] ? exportsList[0] : null);

  const renderFileIcon = (format: ExportHistoryRecord['format'], large: boolean = false) => {
    const cls = large ? 'file-type-icon large' : 'file-type-icon';
    if (format === 'PDF') return <span className={`${cls} red`}>pdf</span>;
    if (format === 'Excel') return <span className={`${cls} green`}><FileSpreadsheet size={large ? 18 : 13} /></span>;
    if (format === 'Word') return <span className={`${cls} blue`}><FileText size={large ? 18 : 13} /></span>;
    if (format === 'JSON') return <span className={`${cls} orange`}>json</span>;
    return <span className={`${cls} purple`}>xml</span>;
  };

  const renderFormatBadge = (fmt: ExportHistoryRecord['format']) => {
    if (fmt === 'PDF') return <span className="format-pill pdf">PDF</span>;
    if (fmt === 'Excel') return <span className="format-pill excel">Excel</span>;
    if (fmt === 'Word') return <span className="format-pill word">Word</span>;
    if (fmt === 'JSON') return <span className="format-pill json">JSON</span>;
    return <span className="format-pill xml">XML</span>;
  };

  const renderStatusBadge = (status: ExportHistoryRecord['status']) => {
    if (status === 'Completed') {
      return <span className="export-status-badge completed">Completed</span>;
    }
    if (status === 'In Progress') {
      return <span className="export-status-badge in-progress"><Clock size={11} /> In Progress</span>;
    }
    return <span className="export-status-badge failed">● Failed</span>;
  };

  return (
    <div className="export-history-page">
      <div className="export-page-title-row">
        <div>
          <h1 className="export-page-title">Export History</h1>
          <p className="export-page-subtitle">
            View, download and manage all exported WBS files from this project.
          </p>
        </div>
      </div>

      <div className="export-metrics-grid">
        <div className="export-metric-card">
          <div className="export-card-icon blue"><FileText size={20} /></div>
          <div className="export-card-info">
            <span className="export-card-number">{totalExports}</span>
            <span className="export-card-label">Total Exports</span>
          </div>
        </div>

        <div className="export-metric-card">
          <div className="export-card-icon green"><CheckCircle2 size={20} /></div>
          <div className="export-card-info">
            <span className="export-card-number">{completedCount}</span>
            <span className="export-card-label">Completed</span>
          </div>
        </div>

        <div className="export-metric-card">
          <div className="export-card-icon amber"><Clock size={20} /></div>
          <div className="export-card-info">
            <span className="export-card-number">{inProgressCount}</span>
            <span className="export-card-label">In Progress</span>
          </div>
        </div>

        <div className="export-metric-card">
          <div className="export-card-icon red"><AlertTriangle size={20} /></div>
          <div className="export-card-info">
            <span className="export-card-number">{failedCount}</span>
            <span className="export-card-label">Failed</span>
          </div>
        </div>

        <div className="export-metric-card">
          <div className="export-card-icon purple"><Users size={20} /></div>
          <div className="export-card-info">
            <span className="export-card-number">{uniqueAuthorsCount}</span>
            <span className="export-card-label">Exported By</span>
          </div>
        </div>
      </div>

      <div className="export-controls-bar">
        <div className="export-search-box">
          <Search size={15} color="#94A3B8" />
          <input
            type="text"
            placeholder="Search by file name, version, format or exported by..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setCurrentPage(1);
            }}
          />
        </div>

        <div className="export-filter-dropdowns">
          <div className="select-container">
            <select value={formatFilter} onChange={(e) => { setFormatFilter(e.target.value); setCurrentPage(1); }}>
              {ALL_FORMAT_OPTIONS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>

          <div className="select-container">
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }}>
              {ALL_STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div className="select-container">
            <select value={authorFilter} onChange={(e) => { setAuthorFilter(e.target.value); setCurrentPage(1); }}>
              {authorOptions.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>

          <div className="select-container date-range">
            <Calendar size={13} color="#64748B" />
            <select value={dateRangeFilter} onChange={(e) => { setDateRangeFilter(e.target.value); setCurrentPage(1); }}>
              {ALL_DATE_OPTIONS.map((d) => (
                <option key={d.value} value={d.value}>{d.label}</option>
              ))}
            </select>
          </div>

          {(searchQuery || formatFilter !== 'All Formats' || statusFilter !== 'All Status' || authorFilter !== 'All Exported By' || dateRangeFilter !== 'all') && (
            <button
              type="button"
              className="btn-clear-filters"
              onClick={() => {
                setSearchQuery('');
                setFormatFilter('All Formats');
                setStatusFilter('All Status');
                setAuthorFilter('All Exported By');
                setDateRangeFilter('all');
                setCurrentPage(1);
              }}
            >
              <FilterX size={14} /> Clear Filters
            </button>
          )}
        </div>
      </div>

      <div className="export-content-layout">
        <div className="export-table-container">
          <table className="export-data-table">
            <thead>
              <tr>
                <th onClick={() => handleSort('fileName')} className="sortable-th">
                  <div className="th-content">
                    File Name <ArrowUpDown size={12} />
                  </div>
                </th>
                <th onClick={() => handleSort('version')} className="sortable-th">
                  <div className="th-content">
                    Version <ArrowUpDown size={12} />
                  </div>
                </th>
                <th>Format</th>
                <th onClick={() => handleSort('exportedOn')} className="sortable-th">
                  <div className="th-content">
                    Exported On ↑↓
                  </div>
                </th>
                <th>Exported By</th>
                <th>Status</th>
                <th className="align-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="td-empty-notice">
                    Loading export transactions...
                  </td>
                </tr>
              ) : paginatedExports.length === 0 ? (
                <tr>
                  <td colSpan={7} className="td-empty-table-body">
                    <div className="empty-table-cluster">
                      <div className="empty-icon-round"><Download size={26} /></div>
                      <h4>No Export Records Found</h4>
                      <p>Export activities generated for this project will appear right here.</p>
                    </div>
                  </td>
                </tr>
              ) : (
                paginatedExports.map((item) => {
                  const isSelected = selectedExport?.id === item.id;
                  const isMenuOpen = activeMenuId === item.id;
                  return (
                    <tr
                      key={item.id}
                      className={`export-table-row ${isSelected ? 'row-selected' : ''}`}
                      onClick={() => setSelectedExportId(item.id)}
                    >
                      <td>
                        <div className="file-name-cell">
                          {renderFileIcon(item.format)}
                          <div>
                            <strong className="file-title">{item.fileName}</strong>
                            <div className="file-size-sub">{item.fileSize}</div>
                          </div>
                        </div>
                      </td>
                      <td><span className="version-pill">{item.version}</span></td>
                      <td>{renderFormatBadge(item.format)}</td>
                      <td><span className="export-date-cell">{item.exportedOn}</span></td>
                      <td>
                        <div className="author-cell">
                          <span className="author-avatar">{item.exportedByInitials}</span>
                          <div>
                            <div className="author-name">{item.exportedBy}</div>
                            <div className="author-role">{item.exportedByRole}</div>
                          </div>
                        </div>
                      </td>
                      <td>{renderStatusBadge(item.status)}</td>
                      <td className="align-right" onClick={(e) => e.stopPropagation()}>
                        <div className="actions-cluster" ref={isMenuOpen ? menuContainerRef : null}>
                          <button
                            type="button"
                            className="btn-table-action"
                            title="Download file"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDownloadFile(item);
                            }}
                          >
                            <Download size={14} />
                          </button>

                          <button
                            type="button"
                            className="btn-table-action"
                            title="Inspect details"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedExportId(item.id);
                            }}
                          >
                            <Eye size={14} />
                          </button>

                          <div className="relative-menu-wrap">
                            <button
                              type="button"
                              className="btn-table-action"
                              title="More options"
                              onClick={(e) => {
                                e.stopPropagation();
                                setActiveMenuId(isMenuOpen ? null : item.id);
                              }}
                            >
                              <MoreVertical size={14} />
                            </button>
                            {isMenuOpen && (
                              <div className="table-row-dropdown" onClick={(e) => e.stopPropagation()}>
                                <button 
                                  type="button" 
                                  className="dropdown-menu-opt"
                                  onClick={() => {
                                    handleDownloadFile(item);
                                    setActiveMenuId(null);
                                  }}
                                >
                                  <Download size={13} color="#059669" /> Download File
                                </button>
                                <hr className="dropdown-divider-line" />
                                <button 
                                  type="button" 
                                  className="dropdown-menu-opt delete"
                                  onClick={() => void handleDelete(item.id)}
                                >
                                  <Trash2 size={13} color="#DC2626" /> Delete Record
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

          <div className="export-pagination-footer">
            <span className="pagination-info">
              {filteredExports.length > 0 
                ? `Showing ${(currentPage - 1) * rowsPerPage + 1} to ${Math.min(currentPage * rowsPerPage, filteredExports.length)} of ${filteredExports.length} exports`
                : 'Showing 0 exports'}
            </span>

            <div className="pagination-nav-group">
              <button
                type="button"
                className="btn-page-nav"
                disabled={currentPage === 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              >
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

              <button
                type="button"
                className="btn-page-nav"
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              >
                <ChevronRight size={15} />
              </button>

              <div className="rows-per-page-wrap">
                <span>Rows per page</span>
                <select
                  value={rowsPerPage}
                  onChange={(e) => {
                    setRowsPerPage(Number(e.target.value));
                    setCurrentPage(1);
                  }}
                >
                  <option value={10}>10</option>
                  <option value={20}>20</option>
                  <option value={50}>50</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <div className="export-inspector-panel">
          {selectedExport ? (
            <>
              <div className="inspector-header">
                <div className="inspector-file-cluster">
                  {renderFileIcon(selectedExport.format, true)}
                  <div>
                    <h3 className="inspector-filename">{selectedExport.fileName}</h3>
                    <span className="inspector-filesize">{selectedExport.fileSize}</span>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn-close-inspector"
                  onClick={() => setSelectedExportId('')}
                >
                  <X size={15} />
                </button>
              </div>

              <div className="inspector-body">
                <div className="inspector-status-banner">
                  <span className="status-label-badge">{selectedExport.status}</span>
                  <p className="status-desc">{selectedExport.statusMessage}</p>
                </div>

                <div className="meta-keyvalue-list">
                  <div className="keyvalue-row">
                    <span>Version</span>
                    <strong>{selectedExport.version}</strong>
                  </div>
                  <div className="keyvalue-row">
                    <span>Exported On</span>
                    <strong>{selectedExport.exportedOn}</strong>
                  </div>
                  <div className="keyvalue-row">
                    <span>Exported By</span>
                    <div className="author-cluster-small">
                      <span className="author-avatar small">{selectedExport.exportedByInitials}</span>
                      <div>
                        <div className="author-name">{selectedExport.exportedBy}</div>
                        <div className="author-role">{selectedExport.exportedByRole}</div>
                      </div>
                    </div>
                  </div>
                  <div className="keyvalue-row">
                    <span>Format</span>
                    <strong>{selectedExport.format}</strong>
                  </div>
                  <div className="keyvalue-row">
                    <span>File Size</span>
                    <strong>{selectedExport.fileSize}</strong>
                  </div>
                </div>

                <div className="includes-section">
                  <label className="section-title">Includes</label>
                  <div className="includes-checklist">
                    {(selectedExport.includes || []).map((inc) => (
                      <div key={inc} className="include-item">
                        <CheckCircle2 size={13} color="#10B981" />
                        <span>{inc}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="inspector-action-buttons">
                  <button
                    type="button"
                    className="btn-primary-action w-full"
                    onClick={() => handleDownloadFile(selectedExport)}
                  >
                    <Download size={15} /> Download File
                  </button>
                  <button
                    type="button"
                    className="btn-delete-export w-full"
                    onClick={() => void handleDelete(selectedExport.id)}
                  >
                    <Trash2 size={14} /> Delete Export
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="inspector-unselected-placeholder">
              <FileCheck size={36} color="#94A3B8" />
              <h4>No Export Selected</h4>
              <p>Select any item from the table to inspect details and download records.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ExportHistoryScreen;