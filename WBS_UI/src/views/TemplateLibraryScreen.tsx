/* eslint-disable react-hooks/set-state-in-effect */
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {  
  Search,  
  Plus,  
  FileSpreadsheet,  
  MoreVertical,  
  ChevronRight,  
  ChevronDown,  
  X,  
  Eye,  
  ArrowRight,    
  FilterX  
} from 'lucide-react';
import { apiRequest } from '../services/apiClient';
import './TemplateLibraryScreen.css';

interface DynamicTemplateRecord {
  id: string;
  name: string;
  description: string;
  categories: string[];
  usageCount: number;
  lastUpdated: string;
  updatedBy: string;
  structure: Array<{
    phaseNumber: number;
    phaseName: string;
    itemCount: number;
    subItems: string[];
  }>;
}

interface TemplateLibraryScreenProps {
  tenantId: string;
  onUseTemplate: (template: DynamicTemplateRecord) => void;
  onNavigateToUpload: () => void;
}

export const TemplateLibraryScreen: React.FC<TemplateLibraryScreenProps> = ({
  tenantId,
  onUseTemplate,
  onNavigateToUpload,
}) => {
  const [templates, setTemplates] = useState<DynamicTemplateRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All Categories');
  const [sortBy, setSortBy] = useState<'Most Used' | 'Name' | 'Recently Updated'>('Most Used');
  const [previewTemplate, setPreviewTemplate] = useState<DynamicTemplateRecord | null>(null);
  const [expandedPhases, setExpandedPhases] = useState<Record<number, boolean>>({ 1: true });

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTemplateName, setNewTemplateName] = useState('');
  const [newTemplateCategory, setNewTemplateCategory] = useState('');
  const [newTemplateDesc, setNewTemplateDesc] = useState('');
  const [phaseInputs, setPhaseInputs] = useState(['Project Management', 'Engineering & Design']);

  const fetchTemplates = useCallback(async () => {
    if (!tenantId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await apiRequest(`/tenants/${tenantId}/templates`).catch(() => []);
      const templateList = Array.isArray(data) ? data : ((data as { items?: DynamicTemplateRecord[] })?.items || [
        {
          id: '1',
          name: 'Solar EPC Project',
          description: 'Standard WBS template for Solar EPC projects including design, procurement, construction and commissioning.',
          categories: ['Energy & Utilities', 'EPC'],
          usageCount: 128,
          lastUpdated: '15 Oct 2026',
          updatedBy: 'John Doe',
          structure: [
            { phaseNumber: 1, phaseName: 'Project Management', itemCount: 6, subItems: ['Project Initiation', 'Planning & Scheduling', 'Risk Management'] },
            { phaseNumber: 2, phaseName: 'Engineering & Design', itemCount: 8, subItems: ['Site Survey', 'Civil Engineering', 'Electrical Schematics'] },
            { phaseNumber: 3, phaseName: 'Procurement', itemCount: 7, subItems: ['PV Modules', 'Inverters', 'BESS Infrastructure'] }
          ]
        },
        {
          id: '2',
          name: 'Infrastructure Project',
          description: 'WBS template for road, bridge and infrastructure development projects.',
          categories: ['Infrastructure', 'Construction'],
          usageCount: 96,
          lastUpdated: '10 Oct 2026',
          updatedBy: 'Sarah Mitchell',
          structure: [
            { phaseNumber: 1, phaseName: 'Site Preparation', itemCount: 4, subItems: ['Clearing', 'Grading', 'Access Roads'] }
          ]
        }
      ]);

      setTemplates(templateList as DynamicTemplateRecord[]);
      if (templateList.length > 0 && templateList[0]) {
        setPreviewTemplate(templateList[0]);
      }
    } catch (err) {
      console.error('Failed to load templates:', err);
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchTemplates();
  }, [fetchTemplates]);

  const allCategories = useMemo(() => {
    const catSet = new Set<string>();
    templates.forEach((t) => (t.categories || []).forEach((c) => catSet.add(c)));
    return ['All Categories', ...Array.from(catSet)];
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    return templates
      .filter((t) => {
        const matchesSearch =
          t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
          (t.categories || []).some((c) => c.toLowerCase().includes(searchQuery.toLowerCase()));

        const matchesCat =
          selectedCategory === 'All Categories' || (t.categories || []).includes(selectedCategory);

        return matchesSearch && matchesCat;
      })
      .sort((a, b) => {
        if (sortBy === 'Most Used') return (b.usageCount || 0) - (a.usageCount || 0);
        if (sortBy === 'Name') return (a.name || '').localeCompare(b.name || '');
        return new Date(b.lastUpdated || 0).getTime() - new Date(a.lastUpdated || 0).getTime();
      });
  }, [templates, searchQuery, selectedCategory, sortBy]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTemplateName.trim() || !newTemplateCategory.trim() || !tenantId) return;

    try {
      await apiRequest(`/tenants/${tenantId}/templates`, {
        method: 'POST',
        body: JSON.stringify({
          name: newTemplateName.trim(),
          category: newTemplateCategory.trim(),
          description: newTemplateDesc.trim(),
          phases: phaseInputs.filter((p) => p.trim().length > 0)
        })
      });

      setNewTemplateName('');
      setNewTemplateCategory('');
      setNewTemplateDesc('');
      setShowCreateModal(false);
      await fetchTemplates();
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create template.';
      alert(errorMessage);
    }
  };

  const togglePhase = (phaseNumber: number) => {
    setExpandedPhases((prev) => ({ ...prev, [phaseNumber]: !prev[phaseNumber] }));
  };

  return (
    <div className="template-library-page">
      <div className="template-library-topbar">
        <div>
          <h1 className="template-page-title">Template Library</h1>
          <p className="template-page-subtitle">
            Use ready-made templates to quickly generate a WBS for your project.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary-action"
          onClick={() => setShowCreateModal(true)}
        >
          <Plus size={16} /> Create Custom Template
        </button>
      </div>

      <div className="template-controls-bar">
        <div className="template-search-box">
          <Search size={15} color="#94A3B8" />
          <input
            type="text"
            placeholder="Search templates by name, industry or keyword..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="template-filter-dropdowns">
          <div className="select-container">
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
            >
              {allCategories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          <div className="select-container">
            <span className="select-prefix-label">Sort by</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'Most Used' | 'Name' | 'Recently Updated')}
            >
              <option value="Most Used">Most Used</option>
              <option value="Name">Name</option>
              <option value="Recently Updated">Recently Updated</option>
            </select>
          </div>

          {(searchQuery || selectedCategory !== 'All Categories') && (
            <button
              type="button"
              className="btn-clear-filters"
              onClick={() => {
                setSearchQuery('');
                setSelectedCategory('All Categories');
              }}
            >
              <FilterX size={14} /> Clear
            </button>
          )}
        </div>
      </div>

      <div className="template-workspace-grid">
        <div className="template-table-container">
          {loading ? (
            <div className="template-empty-box">Loading template library...</div>
          ) : filteredTemplates.length === 0 ? (
            <div className="template-empty-box">
              <div className="empty-icon-circle"><FileSpreadsheet size={32} /></div>
              <h3>No Templates in Library</h3>
              <p>
                Upload domain reference files when creating a WBS or define a custom template to populate this library.
              </p>
              <div className="empty-action-buttons">
                <button
                  type="button"
                  className="btn-primary-action"
                  onClick={() => setShowCreateModal(true)}
                >
                  <Plus size={16} /> Create Custom Template
                </button>
                <button
                  type="button"
                  className="btn-secondary-action"
                  onClick={onNavigateToUpload}
                >
                  Generate WBS with Scope File
                </button>
              </div>
            </div>
          ) : (
            <table className="template-data-table">
              <thead>
                <tr>
                  <th>Template Name ↑↓</th>
                  <th>Category</th>
                  <th>Description</th>
                  <th>Used</th>
                  <th>Last Updated</th>
                  <th className="align-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredTemplates.map((item) => {
                  const isSelected = previewTemplate?.id === item.id;
                  return (
                    <tr
                      key={item.id}
                      className={`template-row ${isSelected ? 'row-active' : ''}`}
                      onClick={() => setPreviewTemplate(item)}
                    >
                      <td>
                        <div className="template-name-cluster">
                          <div className="template-icon-circle">
                            <FileSpreadsheet size={16} color="#2563EB" />
                          </div>
                          <strong>{item.name}</strong>
                        </div>
                      </td>
                      <td>
                        <div className="template-categories-stack">
                          {(item.categories || []).map((c) => (
                            <span key={c} className="category-pill-tag">{c}</span>
                          ))}
                        </div>
                      </td>
                      <td>
                        <p className="template-desc-cell">{item.description}</p>
                      </td>
                      <td>
                        <span className="template-used-number">{item.usageCount || 0}</span>
                      </td>
                      <td>
                        <div className="template-updated-cluster">
                          <span>{item.lastUpdated || 'Recently'}</span>
                          <small>{item.updatedBy || 'System'}</small>
                        </div>
                      </td>
                      <td className="align-right" onClick={(e) => e.stopPropagation()}>
                        <div className="template-action-row">
                          <button
                            type="button"
                            className="btn-use-template"
                            onClick={() => onUseTemplate(item)}
                          >
                            Use
                          </button>
                          <button type="button" className="btn-icon-subtle">
                            <MoreVertical size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {previewTemplate && (
          <div className="template-preview-drawer">
            <div className="preview-drawer-header">
              <div className="drawer-title-cluster">
                <div className="template-icon-circle large">
                  <FileSpreadsheet size={20} color="#2563EB" />
                </div>
                <div>
                  <h3 className="drawer-title">{previewTemplate.name}</h3>
                  <div className="drawer-categories-row">
                    {(previewTemplate.categories || []).map((c) => (
                      <span key={c} className="category-pill-tag">{c}</span>
                    ))}
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="btn-close-drawer"
                onClick={() => setPreviewTemplate(null)}
              >
                <X size={16} />
              </button>
            </div>

            <div className="preview-drawer-body">
              <div className="preview-section">
                <label className="drawer-section-label">Description</label>
                <p className="drawer-description-text">{previewTemplate.description}</p>
              </div>

              <div className="preview-section">
                <label className="drawer-section-label">Template Structure (Preview)</label>
                <div className="structure-phases-accordion">
                  {(previewTemplate.structure || []).map((phase) => {
                    const isExpanded = expandedPhases[phase.phaseNumber];
                    return (
                      <div key={phase.phaseNumber} className="phase-accordion-card">
                        <div
                          className="phase-accordion-header"
                          onClick={() => togglePhase(phase.phaseNumber)}
                        >
                          <div className="phase-title-row">
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                            <span className="phase-num-badge">{phase.phaseNumber}</span>
                            <strong>{phase.phaseName}</strong>
                          </div>
                          <span className="phase-count-sub">{phase.itemCount || phase.subItems?.length || 0} items</span>
                        </div>

                        {isExpanded && (
                          <div className="phase-accordion-content">
                            {(phase.subItems || []).map((sub, idx) => (
                              <div key={sub} className="phase-subitem-row">
                                <span className="subitem-code">{phase.phaseNumber}.{idx + 1}</span>
                                <span className="subitem-text">{sub}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="preview-drawer-footer">
              <button
                type="button"
                className="btn-preview-structure"
                onClick={() => onUseTemplate(previewTemplate)}
              >
                <Eye size={15} /> Preview Template
              </button>
              <button
                type="button"
                className="btn-primary-action flex-grow"
                onClick={() => onUseTemplate(previewTemplate)}
              >
                Use This Template <ArrowRight size={15} />
              </button>
            </div>
          </div>
        )}
      </div>

      {showCreateModal && (
        <div className="modal-backdrop">
          <div className="modal-dialog">
            <div className="modal-header">
              <h3 className="modal-title">Create Custom Template</h3>
              <button
                type="button"
                className="btn-close-drawer"
                onClick={() => setShowCreateModal(false)}
              >
                <X size={16} />
              </button>
            </div>
            <form onSubmit={(e) => void handleCreateSubmit(e)}>
              <div className="modal-field">
                <label>Template Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g., Renewable EPC Standard"
                  value={newTemplateName}
                  onChange={(e) => setNewTemplateName(e.target.value)}
                />
              </div>

              <div className="modal-field">
                <label>Industry / Category</label>
                <input
                  type="text"
                  required
                  placeholder="e.g., Energy & Utilities"
                  value={newTemplateCategory}
                  onChange={(e) => setNewTemplateCategory(e.target.value)}
                />
              </div>

              <div className="modal-field">
                <label>Description</label>
                <textarea
                  rows={3}
                  placeholder="Describe the scope structure and phases covered by this template..."
                  value={newTemplateDesc}
                  onChange={(e) => setNewTemplateDesc(e.target.value)}
                />
              </div>

              <div className="modal-field">
                <label>Default Top-Level Phases</label>
                {phaseInputs.map((val, idx) => (
                  <input
                    key={idx}
                    type="text"
                    value={val}
                    onChange={(e) => {
                      const updated = [...phaseInputs];
                      updated[idx] = e.target.value;
                      setPhaseInputs(updated);
                    }}
                    style={{ marginBottom: '6px' }}
                  />
                ))}
                <button
                  type="button"
                  className="btn-add-phase"
                  onClick={() => setPhaseInputs([...phaseInputs, `Phase ${phaseInputs.length + 1}`])}
                >
                  + Add Phase
                </button>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary-action">
                  Save Template
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default TemplateLibraryScreen;