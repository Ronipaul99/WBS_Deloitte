import React, { useState, useEffect, useCallback } from 'react';
import { 
  Settings as SettingsIcon, 
  Cpu, 
  FileText, 
  Info, 
  Check, 
  RotateCcw, 
  Save 
} from 'lucide-react';
import { 
  AppSettingsPreferences, 
  getAppSettings, 
  saveAppSettings, 
  resetAppSettingsToDefault, 
  getAllTemplates 
} from '../services/wbsService';
import './SettingsScreen.css';

export const SettingsScreen: React.FC = () => {
  const [settings, setSettings] = useState<AppSettingsPreferences | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [saveSuccessNotice, setSaveSuccessNotice] = useState<boolean>(false);
  const [availableTemplates, setAvailableTemplates] = useState<string[]>([]);
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const fetchPreferences = async () => {
      const [prefs, tpls] = await Promise.all([
        getAppSettings(),
        getAllTemplates(),
      ]);

      if (!isMounted) return;

      setSettings(prefs);

      const tplNames = tpls.map((t) => t.name);
      if (!tplNames.includes('Solar EPC Template')) {
        tplNames.unshift('Solar EPC Template');
      }
      if (!tplNames.includes('Infrastructure Template')) {
        tplNames.push('Infrastructure Template');
      }
      setAvailableTemplates(tplNames);
      setLoading(false);
    };

    fetchPreferences().catch(() => {
      if (isMounted) setLoading(false);
    });

    return () => {
      isMounted = false;
    };
  }, []);

  const updatePreference = useCallback((patch: Partial<AppSettingsPreferences>) => {
    setSettings((prev) => {
      if (!prev) return null;
      const updated = { ...prev, ...patch };
      void saveAppSettings(updated);
      return updated;
    });
  }, []);

  const handleExplicitSave = async () => {
    if (!settings) return;
    setSaving(true);
    await saveAppSettings(settings);
    setSaving(false);
    setSaveSuccessNotice(true);
    setTimeout(() => setSaveSuccessNotice(false), 3000);
  };

  const handleReset = async () => {
    const defaults = await resetAppSettingsToDefault();
    setSettings(defaults);
    setSaveSuccessNotice(false);
  };

  const toggleFormat = (format: string) => {
    if (!settings) return;
    const current = [...settings.supportedFormats];
    const exists = current.includes(format);
    const updated = exists 
      ? current.filter((f) => f !== format) 
      : [...current, format];
    
    if (updated.length > 0) {
      updatePreference({ supportedFormats: updated });
    }
  };

  if (loading || !settings) {
    return <div className="settings-loading-state">Loading application preferences...</div>;
  }

  const tooltips: Record<string, string> = {
    wbsLevel: 'Determines the baseline depth level of the generated Work Breakdown Structure breakdown hierarchy.',
    defaultTemplate: 'The standard industry template automatically pre-selected during step 1 file uploads.',
    genModel: 'Large Language Model instance utilized for document decomposition and work package creation.',
    embModel: 'Embedding model used for semantic chunking and RAG similarity retrieval across project documents.',
    chunks: 'Number of top-ranked document semantic text segments retrieved per requirement during generation.',
    sourceEvidence: 'When enabled, preserves verbatim sentence citations and page links inside each generated WBS node.',
    ocr: 'Executes visual OCR on image-only or scanned PDF documents during pre-processing.',
    maxSize: 'The maximum allowed single file size threshold accepted by the upload ingestion parser.',
    formats: 'Permitted document extensions supported during drag-and-drop and manual file uploads.',
  };

  return (
    <div className="settings-page-container" onClick={() => setActiveTooltip(null)}>
      <div className="settings-header">
        <h1 className="settings-page-title">Settings</h1>
        <p className="settings-page-subtitle">
          Configure default preferences for WBS generation and document processing.
        </p>
      </div>

      {saveSuccessNotice && (
        <div className="settings-notification-banner">
          <Check size={16} /> Preferences saved. Settings will be applied to all new WBS generation pipelines.
        </div>
      )}

      <div className="settings-card-panel">
        <div className="settings-card-header">
          <div className="settings-card-icon-wrap blue">
            <SettingsIcon size={18} />
          </div>
          <div className="settings-card-title-group">
            <h2 className="settings-card-title">General Settings</h2>
            <p className="settings-card-desc">Set your default preferences for new projects.</p>
          </div>
        </div>

        <div className="settings-form-row two-col">
          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="wbsLevel">Default WBS Level</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'wbsLevel' ? null : 'wbsLevel'); }}
              >
                <Info size={13} />
                {activeTooltip === 'wbsLevel' && <div className="tooltip-popover">{tooltips.wbsLevel}</div>}
              </div>
            </div>
            <select
              id="wbsLevel"
              className="settings-select-input"
              value={settings.defaultWbsLevel}
              onChange={(e) => updatePreference({ defaultWbsLevel: e.target.value as AppSettingsPreferences['defaultWbsLevel'] })}
            >
              <option value="Level 1">Level 1 (Top Level Phases Only)</option>
              <option value="Level 2">Level 2 (Phases + Work Packages)</option>
              <option value="Level 3">Level 3 (Standard Detailed Tree)</option>
              <option value="Level 4">Level 4 (Granular Tasks)</option>
              <option value="Level 5">Level 5 (Full Deep Decomposition)</option>
            </select>
          </div>

          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="defaultTemplate">Default Template</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'defaultTemplate' ? null : 'defaultTemplate'); }}
              >
                <Info size={13} />
                {activeTooltip === 'defaultTemplate' && <div className="tooltip-popover">{tooltips.defaultTemplate}</div>}
              </div>
            </div>
            <select
              id="defaultTemplate"
              className="settings-select-input"
              value={settings.defaultTemplateId}
              onChange={(e) => updatePreference({ defaultTemplateId: e.target.value })}
            >
              {availableTemplates.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="settings-card-panel">
        <div className="settings-card-header">
          <div className="settings-card-icon-wrap purple">
            <Cpu size={18} />
          </div>
          <div className="settings-card-title-group">
            <h2 className="settings-card-title">AI & RAG Settings</h2>
            <p className="settings-card-desc">Configure AI model and document search settings for WBS generation.</p>
          </div>
        </div>

        <div className="settings-form-row two-col">
          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="genModel">Generation Model</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'genModel' ? null : 'genModel'); }}
              >
                <Info size={13} />
                {activeTooltip === 'genModel' && <div className="tooltip-popover">{tooltips.genModel}</div>}
              </div>
            </div>
            <select
              id="genModel"
              className="settings-select-input"
              value={settings.generationModel}
              onChange={(e) => updatePreference({ generationModel: e.target.value })}
            >
              <option value="Granite 3.3 2B (Local)">Granite 3.3 2B (Local)</option>
              <option value="Granite 3.3 8B (Local)">Granite 3.3 8B (Local)</option>
              <option value="Llama 3 8B Instruct (Local)">Llama 3 8B Instruct (Local)</option>
              <option value="Mistral 7B v0.3 (Local)">Mistral 7B v0.3 (Local)</option>
            </select>
          </div>

          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="embModel">Embedding Model</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'embModel' ? null : 'embModel'); }}
              >
                <Info size={13} />
                {activeTooltip === 'embModel' && <div className="tooltip-popover">{tooltips.embModel}</div>}
              </div>
            </div>
            <select
              id="embModel"
              className="settings-select-input"
              value={settings.embeddingModel}
              onChange={(e) => updatePreference({ embeddingModel: e.target.value })}
            >
              <option value="BGE Small (Local)">BGE Small (Local)</option>
              <option value="all-MiniLM-L6-v2 (Local)">all-MiniLM-L6-v2 (Local)</option>
              <option value="BGE Base EN (Local)">BGE Base EN (Local)</option>
              <option value="Nomic Embed Text (Local)">Nomic Embed Text (Local)</option>
            </select>
          </div>
        </div>

        <div className="settings-form-row two-col" style={{ marginTop: '20px' }}>
          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="chunks">Retrieved Chunks</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'chunks' ? null : 'chunks'); }}
              >
                <Info size={13} />
                {activeTooltip === 'chunks' && <div className="tooltip-popover">{tooltips.chunks}</div>}
              </div>
            </div>
            <input
              id="chunks"
              type="number"
              min={1}
              max={32}
              className="settings-text-input"
              value={settings.retrievedChunks}
              onChange={(e) => updatePreference({ retrievedChunks: parseInt(e.target.value, 10) || 1 })}
            />
          </div>

          <div className="settings-form-field">
            <div className="field-label-row">
              <label>Include Source Evidence in Output</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'sourceEvidence' ? null : 'sourceEvidence'); }}
              >
                <Info size={13} />
                {activeTooltip === 'sourceEvidence' && <div className="tooltip-popover">{tooltips.sourceEvidence}</div>}
              </div>
            </div>
            <div className="toggle-switch-cluster">
              <label className="switch-toggle-widget">
                <input
                  type="checkbox"
                  checked={settings.includeSourceEvidence}
                  onChange={(e) => updatePreference({ includeSourceEvidence: e.target.checked })}
                />
                <span className="slider-round" />
              </label>
              <span className="toggle-sub-label">Show document references for generated WBS items</span>
            </div>
          </div>
        </div>
      </div>

      <div className="settings-card-panel">
        <div className="settings-card-header">
          <div className="settings-card-icon-wrap green">
            <FileText size={18} />
          </div>
          <div className="settings-card-title-group">
            <h2 className="settings-card-title">Document Processing</h2>
            <p className="settings-card-desc">Set preferences for file upload and document parsing.</p>
          </div>
        </div>

        <div className="settings-form-row two-col">
          <div className="settings-form-field">
            <div className="field-label-row">
              <label>OCR for Scanned PDFs</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'ocr' ? null : 'ocr'); }}
              >
                <Info size={13} />
                {activeTooltip === 'ocr' && <div className="tooltip-popover">{tooltips.ocr}</div>}
              </div>
            </div>
            <div className="toggle-switch-cluster">
              <label className="switch-toggle-widget">
                <input
                  type="checkbox"
                  checked={settings.enableOcr}
                  onChange={(e) => updatePreference({ enableOcr: e.target.checked })}
                />
                <span className="slider-round" />
              </label>
              <span className="toggle-sub-label">Enable OCR to read scanned documents</span>
            </div>
          </div>

          <div className="settings-form-field">
            <div className="field-label-row">
              <label htmlFor="maxSize">Maximum File Size</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'maxSize' ? null : 'maxSize'); }}
              >
                <Info size={13} />
                {activeTooltip === 'maxSize' && <div className="tooltip-popover">{tooltips.maxSize}</div>}
              </div>
            </div>
            <select
              id="maxSize"
              className="settings-select-input"
              value={settings.maxFileSizeMb}
              onChange={(e) => updatePreference({ maxFileSizeMb: parseInt(e.target.value, 10) })}
            >
              <option value={10}>10 MB</option>
              <option value={25}>25 MB</option>
              <option value={50}>50 MB</option>
              <option value={100}>100 MB</option>
            </select>
          </div>
        </div>

        <div className="settings-form-row" style={{ marginTop: '20px' }}>
          <div className="settings-form-field">
            <div className="field-label-row">
              <label>Supported File Formats</label>
              <div 
                className="info-tooltip-btn" 
                onClick={(e) => { e.stopPropagation(); setActiveTooltip(activeTooltip === 'formats' ? null : 'formats'); }}
              >
                <Info size={13} />
                {activeTooltip === 'formats' && <div className="tooltip-popover">{tooltips.formats}</div>}
              </div>
            </div>
            <div className="format-tags-row">
              {['PDF', 'DOCX', 'XLSX'].map((fmt) => {
                const isActive = settings.supportedFormats.includes(fmt);
                return (
                  <button
                    key={fmt}
                    type="button"
                    className={`format-toggle-tag ${fmt.toLowerCase()} ${isActive ? 'selected' : 'disabled'}`}
                    onClick={() => toggleFormat(fmt)}
                  >
                    {fmt}
                  </button>
                );
              })}
              <span className="format-summary-sub">
                {settings.supportedFormats.join(', ')}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="settings-bottom-actions-row">
        <button
          type="button"
          className="btn-settings-reset"
          onClick={handleReset}
        >
          <RotateCcw size={14} /> Reset to Default
        </button>
        <button
          type="button"
          className="btn-settings-save"
          onClick={handleExplicitSave}
          disabled={saving}
        >
          <Save size={14} /> {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
};

export default SettingsScreen;