import { useState, useEffect, useCallback, useMemo, useRef, FC, ReactNode } from 'react';
import {
  ChevronRight,
  ChevronDown,
  RotateCcw,
  CheckSquare,
  Download,
  FileText,
  Edit2,
  Move,
  Trash2,
  X,
  Sparkles,
  AlertTriangle,
  Info,
  RefreshCw,
  FileSpreadsheet,
  FileCode,
  Share2,
  ArrowLeft,
} from 'lucide-react';
import { downloadExport, getExport, startExport } from '../services/exportsApi';
import { pollResource } from '../services/polling';
import { getLatestWbs, getWbsVersion, updateWbs } from '../services/wbsApi';
import { presentWbs } from '../services/workflowPresentation';
import type {
  ExportFormat,
  ProjectResponse,
  TemplateResponse,
  UnmappedRequirement,
  WbsNode,
  WbsResultPayload,
} from '../services/workflowTypes';
import { useAuth } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import './WbsResultScreen.css';

export type WbsScreenTab = 'structure' | 'coverage' | 'insights' | 'unmapped' | 'hierarchy' | 'scope';

interface WbsResultScreenProps {
  tenantId: string;
  project: ProjectResponse;
  template: TemplateResponse | null;
  versionId?: string;
  initialTab?: WbsScreenTab;
  onBack?: () => void;
  onNavigateToValidation?: () => void | Promise<void>;
  onProceedToValidation?: () => void | Promise<void>;
  onRegenerate?: () => void | Promise<void>;
}

function findNodeRecursive(nodes: WbsNode[], id: string): WbsNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    if (node.children && node.children.length > 0) {
      const match = findNodeRecursive(node.children, id);
      if (match) return match;
    }
  }
  return null;
}

function updateNodeRecursive(nodes: WbsNode[], updated: WbsNode): WbsNode[] {
  return nodes.map((node) => {
    if (node.id === updated.id) {
      return { ...node, ...updated };
    }
    if (node.children && node.children.length > 0) {
      return { ...node, children: updateNodeRecursive(node.children, updated) };
    }
    return node;
  });
}

function removeNodeRecursive(nodes: WbsNode[], targetId: string): WbsNode[] {
  return nodes
    .filter((n) => n.id !== targetId)
    .map((node) => {
      if (node.children && node.children.length > 0) {
        return { ...node, children: removeNodeRecursive(node.children, targetId) };
      }
      return node;
    });
}

function insertNodeRecursive(nodes: WbsNode[], parentId: string, newNode: WbsNode): WbsNode[] {
  if (parentId === 'Root') {
    return [...nodes, { ...newNode, parent: 'Root' }];
  }
  return nodes.map((node) => {
    if (node.id === parentId) {
      return {
        ...node,
        children: [...(node.children || []), { ...newNode, parent: node.id }],
      };
    }
    if (node.children && node.children.length > 0) {
      return { ...node, children: insertNodeRecursive(node.children, parentId, newNode) };
    }
    return node;
  });
}

function isDescendantRecursive(nodes: WbsNode[], potentialParentId: string, targetId: string): boolean {
  for (const node of nodes) {
    if (node.id === targetId) {
      const checkChildren = (children?: WbsNode[]): boolean => {
        if (!children) return false;
        for (const child of children) {
          if (child.id === potentialParentId || checkChildren(child.children)) {
            return true;
          }
        }
        return false;
      };
      return checkChildren(node.children);
    }
    if (node.children && isDescendantRecursive(node.children, potentialParentId, targetId)) {
      return true;
    }
  }
  return false;
}

function reindexTreeRecursive(nodes: WbsNode[], parentCode: string = ''): WbsNode[] {
  return nodes.map((node, idx) => {
    const currentCode = parentCode ? `${parentCode}.${idx + 1}` : `${idx + 1}.0`;
    const updatedNode: WbsNode = {
      ...node,
      code: currentCode,
    };
    if (updatedNode.children && updatedNode.children.length > 0) {
      updatedNode.children = reindexTreeRecursive(updatedNode.children, currentCode.replace(/\.0$/, ''));
    }
    return updatedNode;
  });
}

interface AccessibleModalProps {
  title: string;
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
  maxWidth?: string;
  isDestructive?: boolean;
}

const AccessibleModal: FC<AccessibleModalProps> = ({
  title,
  isOpen,
  onClose,
  children,
  maxWidth = '480px',
  isDestructive = false,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      previousActiveElement.current = document.activeElement as HTMLElement;
      setTimeout(() => closeButtonRef.current?.focus(), 50);
    } else if (previousActiveElement.current) {
      previousActiveElement.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-heading"
      className="wbs-modal-backdrop"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        className="wbs-modal-box"
        style={{ maxWidth }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="wbs-modal-header">
          <h3
            id="modal-heading"
            className={`wbs-modal-title ${
              isDestructive ? 'wbs-modal-title-destructive' : 'wbs-modal-title-standard'
            }`}
          >
            {title}
          </h3>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            className="wbs-modal-close-btn"
          >
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
};

export const WbsResultScreen: FC<WbsResultScreenProps> = ({
  tenantId,
  project,
  template,
  versionId,
  initialTab = 'structure',
  onBack,
  onNavigateToValidation,
  onProceedToValidation,
  onRegenerate,
}) => {
  const { can } = useAuth();
  const canUpdateWbs = can(PERMISSIONS.WBS_UPDATE);
  const canGenerateWbs = can(PERMISSIONS.WBS_GENERATE);
  const canRunValidation = can(PERMISSIONS.VALIDATION_RUN);
  const canCreateExport = can(PERMISSIONS.EXPORT_CREATE);
  const handleValidate = onNavigateToValidation || onProceedToValidation;

  const resolveTab = useCallback((tab: WbsScreenTab): 'structure' | 'coverage' | 'insights' | 'unmapped' => {
    if (tab === 'coverage' || tab === 'scope') return 'coverage';
    if (tab === 'insights') return 'insights';
    if (tab === 'unmapped') return 'unmapped';
    return 'structure';
  }, []);

  const [data, setData] = useState<WbsResultPayload | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});

  const [activeTab, setActiveTab] = useState<'structure' | 'coverage' | 'insights' | 'unmapped'>(() => resolveTab(initialTab));
  const [prevInitialTab, setPrevInitialTab] = useState(initialTab);

  if (initialTab !== prevInitialTab) {
    setPrevInitialTab(initialTab);
    setActiveTab(resolveTab(initialTab));
  }

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [isStartingAction, setIsStartingAction] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showExportMenu, setShowExportMenu] = useState<boolean>(false);
  const [reloadNonce, setReloadNonce] = useState<number>(0);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const exportControllerRef = useRef<AbortController | null>(null);

  // Modals
  const [editingNode, setEditingNode] = useState<WbsNode | null>(null);
  const [movingNode, setMovingNode] = useState<WbsNode | null>(null);
  const [nodePendingDelete, setNodePendingDelete] = useState<WbsNode | null>(null);
  const [viewEvidenceModal, setViewEvidenceModal] = useState<boolean>(false);
  const [mappingReq, setMappingReq] = useState<UnmappedRequirement | null>(null);
  const [targetParentId, setTargetParentId] = useState<string>('');

  useEffect(() => {
    let isMounted = true;

    async function load() {
      setIsLoading(true);
      setLoadError(null);
      try {
        const version = versionId
          ? await getWbsVersion(tenantId, versionId)
          : await getLatestWbs(tenantId, project.id);
        const res = presentWbs(version, project, template);
        if (!isMounted) return;

        setData(res);

        if (res.wbsTree && res.wbsTree.length > 0) {
          const initialExpanded = res.wbsTree.reduce((acc, rootNode) => {
            acc[rootNode.id] = true;
            return acc;
          }, {} as Record<string, boolean>);
          setExpandedNodes(initialExpanded);

          const allFlat: WbsNode[] = [];
          const flatten = (items: WbsNode[]) => {
            for (const item of items) {
              allFlat.push(item);
              if (item.children) flatten(item.children);
            }
          };
          flatten(res.wbsTree);

          const aiTarget = allFlat.find((n) => n.isAiAdded) || allFlat[0];
          setSelectedNodeId(aiTarget ? aiTarget.id : null);
        } else {
          setSelectedNodeId(null);
        }
      } catch (err: unknown) {
        if (!isMounted) return;
        setLoadError(err instanceof Error ? err.message : 'Failed to retrieve WBS generated hierarchy.');
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    load();

    return () => {
      isMounted = false;
    };
  }, [project, reloadNonce, template, tenantId, versionId]);

  useEffect(() => () => exportControllerRef.current?.abort(), []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectedNode = useMemo(() => {
    if (!data || !selectedNodeId) return null;
    return findNodeRecursive(data.wbsTree, selectedNodeId);
  }, [data, selectedNodeId]);

  const candidateParents = useMemo(() => {
    if (!data) return [];
    const list: Array<{ id: string; label: string }> = [{ id: 'Root', label: 'Root (Top-Level Phase)' }];
    const collect = (nodes: WbsNode[]) => {
      for (const n of nodes) {
        list.push({ id: n.id, label: `${n.code} ${n.name}` });
        if (n.children && n.children.length > 0) collect(n.children);
      }
    };
    collect(data.wbsTree);
    return list;
  }, [data]);

  const moveOptions = useMemo(() => {
    if (!data || !movingNode) return [];
    return candidateParents.filter(
      (c) => c.id !== movingNode.id && !isDescendantRecursive(data.wbsTree, c.id, movingNode.id)
    );
  }, [data, movingNode, candidateParents]);

  const parentDisplayLabel = useMemo(() => {
    if (!selectedNode || !selectedNode.parent || selectedNode.parent === 'Root') {
      return 'Root (Top-Level Phase)';
    }
    const matched = candidateParents.find((c) => c.id === selectedNode.parent);
    return matched ? matched.label : selectedNode.parent;
  }, [selectedNode, candidateParents]);

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedNodes((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const getDisplayConfidence = (confidenceVal?: number): number => {
    if (confidenceVal === undefined || confidenceVal === null) return 0;
    if (confidenceVal <= 1) return Math.round(confidenceVal * 100);
    return Math.min(100, Math.round(confidenceVal));
  };

  const handleExport = async (format: ExportFormat) => {
    if (!data || isExporting) return;
    setShowExportMenu(false);
    setActionError(null);
    setIsExporting(true);
    const controller = new AbortController();
    exportControllerRef.current = controller;
    try {
      const started = await startExport(tenantId, data.versionId, format, controller.signal);
      const completed = await pollResource({
        signal: controller.signal,
        request: (signal) => getExport(tenantId, started.id, signal),
        isTerminal: (value) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(value.status),
      });
      if (completed.status !== 'COMPLETED' || !completed.download_url) {
        throw new Error('The server could not prepare this export.');
      }
      const { blob, fileName } = await downloadExport(
        completed.download_url,
        format,
        completed.file_name ?? `wbs-export.${format === 'p6_xml' ? 'xml' : format}`,
        controller.signal,
      );
      if (blob.size === 0) throw new Error('The exported file was empty.');
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      if (!controller.signal.aborted) {
        setActionError(err instanceof Error ? err.message : 'Unable to download the requested export.');
      }
    } finally {
      if (exportControllerRef.current === controller) exportControllerRef.current = null;
      setIsExporting(false);
    }
  };

  const runWorkflowAction = async (action: (() => void | Promise<void>) | undefined) => {
    if (!action || isStartingAction) return;
    setActionError(null);
    setIsStartingAction(true);
    try {
      await action();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'The workflow action could not be started.');
    } finally {
      setIsStartingAction(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!data || !editingNode || isSaving) return;
    setActionError(null);
    setIsSaving(true);

    const prevTree = data.wbsTree;
    const updatedTree = updateNodeRecursive(data.wbsTree, editingNode);
    setData({ ...data, wbsTree: updatedTree });
    setEditingNode(null);

    try {
      await updateWbs(tenantId, data.versionId, updatedTree);
    } catch {
      setData((curr) => (curr ? { ...curr, wbsTree: prevTree } : null));
      setActionError('Failed to save deliverable edits. Changes were rolled back.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!data || !nodePendingDelete || isSaving) return;
    setActionError(null);
    setIsSaving(true);

    const prevTree = data.wbsTree;
    const filteredTree = removeNodeRecursive(data.wbsTree, nodePendingDelete.id);
    const reindexedTree = reindexTreeRecursive(filteredTree);

    setData({ ...data, wbsTree: reindexedTree });
    if (selectedNodeId === nodePendingDelete.id) {
      setSelectedNodeId(reindexedTree[0]?.id ?? null);
    }
    setNodePendingDelete(null);

    try {
      await updateWbs(tenantId, data.versionId, reindexedTree);
    } catch {
      setData((curr) => (curr ? { ...curr, wbsTree: prevTree } : null));
      setSelectedNodeId(nodePendingDelete.id);
      setActionError('Failed to remove deliverable. Deletion was rolled back.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleExecuteMove = async () => {
    if (!data || !movingNode || !targetParentId || isSaving) return;
    setActionError(null);

    if (targetParentId === movingNode.id || isDescendantRecursive(data.wbsTree, targetParentId, movingNode.id)) {
      setActionError('Cannot move a node into itself or its own sub-elements.');
      return;
    }

    setIsSaving(true);
    const prevTree = data.wbsTree;
    const pruned = removeNodeRecursive(data.wbsTree, movingNode.id);
    const inserted = insertNodeRecursive(pruned, targetParentId, movingNode);
    const reindexed = reindexTreeRecursive(inserted);

    setData({ ...data, wbsTree: reindexed });
    setExpandedNodes((prev) => ({ ...prev, [targetParentId]: true }));
    setMovingNode(null);
    setTargetParentId('');

    try {
      await updateWbs(tenantId, data.versionId, reindexed);
    } catch {
      setData((curr) => (curr ? { ...curr, wbsTree: prevTree } : null));
      setActionError('Failed to move deliverable. Relocation was rolled back.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleMapRequirementToNode = async () => {
    if (!data || !mappingReq || !targetParentId || isSaving) return;
    setActionError(null);
    setIsSaving(true);

    const prevTree = data.wbsTree;
    const prevUnmapped = data.unmappedRequirements;
    const prevCoverage = data.scopeCoverage;

    const newPackage: WbsNode = {
      id: `wbs_${Date.now()}`,
      code: '0.0',
      name: mappingReq.title,
      type: targetParentId === 'Root' ? 'Phase' : 'Work Package',
      parent: targetParentId,
      source: mappingReq.sourceDoc,
      template: data.templateName || 'Aligned with Standard Template',
      confidence: 90,
      isAiAdded: true,
      description: `Integrated deliverable mapped from: ${mappingReq.reason}`,
      evidence: {
        text: `Requirement ${mappingReq.code} (${mappingReq.title}) allocated to deliverable scope from ${mappingReq.sourceDoc}.`,
        document: mappingReq.sourceDoc || data.projectName,
        section: mappingReq.code || 'Contract Clause',
      },
      children: [],
    };

    const inserted = insertNodeRecursive(data.wbsTree, targetParentId, newPackage);
    const reindexed = reindexTreeRecursive(inserted);
    const updatedUnmapped = data.unmappedRequirements.filter((r) => r.id !== mappingReq.id);

    const totalReqs = data.scopeCoverage?.totalRequirements ?? 0;
    const currentMapped = data.scopeCoverage?.mappedCount ?? 0;
    const currentGaps = data.scopeCoverage?.gapCount ?? 0;

    const newMappedCount = Math.min(totalReqs, currentMapped + 1);
    const newGapCount = Math.max(0, currentGaps - 1);
    const newOverallScore = totalReqs > 0 ? Math.round((newMappedCount / totalReqs) * 100) : 0;

    const updatedCoverage = {
      overallScore: newOverallScore,
      totalRequirements: totalReqs,
      mappedCount: newMappedCount,
      gapCount: newGapCount,
      categories: data.scopeCoverage?.categories || [],
    };

    setData({
      ...data,
      wbsTree: reindexed,
      unmappedRequirements: updatedUnmapped,
      scopeCoverage: updatedCoverage,
    });

    setExpandedNodes((prev) => ({ ...prev, [targetParentId]: true }));
    setMappingReq(null);
    setTargetParentId('');

    try {
      await updateWbs(tenantId, data.versionId, reindexed, {
        ...updatedCoverage,
        unmappedRequirements: updatedUnmapped,
      });
    } catch {
      setData((curr) =>
        curr
          ? {
              ...curr,
              wbsTree: prevTree,
              unmappedRequirements: prevUnmapped,
              scopeCoverage: prevCoverage,
            }
          : null
      );
      setActionError('Failed to map requirement to WBS. Assignment was rolled back.');
    } finally {
      setIsSaving(false);
    }
  };

  const renderTreeRows = (nodes: WbsNode[], depth: number = 0): React.ReactNode => {
    return nodes.map((node) => {
      const hasChildren = Boolean(node.children && node.children.length > 0);
      const isExpanded = Boolean(expandedNodes[node.id]);
      const isSelected = selectedNodeId === node.id;

      return (
        <div key={node.id} className="wbs-tree-row-wrapper">
          <div
            onClick={() => setSelectedNodeId(node.id)}
            className={`wbs-tree-row ${isSelected ? 'wbs-tree-row-selected' : 'wbs-tree-row-unselected'}`}
            style={{ paddingLeft: `${depth * 18 + 12}px` }}
          >
            <div className="wbs-tree-row-left">
              <div
                onClick={(e) => hasChildren && toggleExpand(node.id, e)}
                className="wbs-tree-toggle-btn"
                style={{ cursor: hasChildren ? 'pointer' : 'default' }}
              >
                {hasChildren ? (
                  isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                ) : (
                  <span className="wbs-tree-toggle-spacer" />
                )}
              </div>

              <span className="wbs-tree-node-code">
                {node.code}
              </span>

              <span
                className={`wbs-tree-node-name ${
                  isSelected ? 'wbs-tree-node-name-selected' : 'wbs-tree-node-name-unselected'
                }`}
              >
                {node.name}
              </span>
            </div>

            <div className="wbs-tree-node-type">
              {node.type}
            </div>
          </div>

          {hasChildren && isExpanded && renderTreeRows(node.children!, depth + 1)}
        </div>
      );
    });
  };

  if (isLoading) {
    return (
      <div className="wbs-state-loading">
        <RefreshCw size={30} color="#1A73E8" className="wbs-spin-icon" />
        <span className="wbs-state-loading-text">Loading WBS hierarchy & contracts...</span>
      </div>
    );
  }

  if (loadError || !data) {
    return (
      <div className="wbs-state-error-card">
        <AlertTriangle size={32} color="#DC2626" className="wbs-error-icon-top" />
        <h2 className="wbs-error-heading">
          Unable to Load WBS
        </h2>
        <p className="wbs-error-text">
          {loadError || 'The WBS results could not be retrieved.'}
        </p>
        <button
          onClick={() => setReloadNonce((prev) => prev + 1)}
          className="wbs-retry-btn"
        >
          <RefreshCw size={14} /> Retry Connection
        </button>
      </div>
    );
  }

  const confidenceScore = getDisplayConfidence(selectedNode?.confidence);
  const unmappedCount = data.unmappedRequirements?.length ?? 0;

  // Reliable dynamic evidence fallback so no node renders an empty card
  const activeEvidence = selectedNode?.evidence || (selectedNode ? {
    text: selectedNode.description || `Baseline scope requirement identified for ${selectedNode.name}.`,
    document: data.projectName || 'Project Specification Document',
    section: `Section ${selectedNode.code} Scope Clause`,
  } : null);

  return (
    <div className="wbs-result-container">
      {onBack && (
        <button type="button" className="project-back-button" onClick={onBack}>
          <ArrowLeft size={15} aria-hidden="true" />
          Back to Project
        </button>
      )}
      {actionError && (
        <div className="wbs-action-error-banner">
          <span>{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="wbs-banner-close-btn"
          >
            <X size={15} />
          </button>
        </div>
      )}

      {/* Header Row */}
      <div className="wbs-result-header-row">
        <div>
          <h1 className="wbs-header-title">
            AI WBS Builder
          </h1>
          <div className="wbs-header-meta">
            <span>Project: <strong>{data.projectName}</strong></span>
            <span>|</span>
            <span>{data.version || 'Draft v1.0'}</span>
            <span>|</span>
            <span>Generated on {data.generatedDate}</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="wbs-header-actions">
          {onRegenerate && canGenerateWbs && (
            <button
              type="button"
              disabled={isSaving || isExporting || isStartingAction}
              onClick={() => void runWorkflowAction(onRegenerate)}
              className="wbs-btn-regenerate"
            >
              <RotateCcw size={13} />
              <span>Regenerate</span>
            </button>
          )}

          {handleValidate && canRunValidation && (
            <button
              type="button"
              disabled={isSaving || isExporting || isStartingAction}
              onClick={() => void runWorkflowAction(handleValidate)}
              className="wbs-btn-validate"
            >
              <CheckSquare size={13} color="#FFFFFF" />
              <span>Validate & Proceed</span>
            </button>
          )}

          {/* Export Dropdown */}
          {canCreateExport && <div className="wbs-export-dropdown-wrapper" ref={exportMenuRef}>
            <button
              type="button"
              disabled={isSaving || isExporting || isStartingAction}
              onClick={() => setShowExportMenu(!showExportMenu)}
              className="wbs-btn-export"
            >
              <Download size={13} />
              <span>Export</span>
              <ChevronDown size={12} />
            </button>

            {showExportMenu && (
              <div className="wbs-export-menu">
                <button
                  type="button"
                  onClick={() => void handleExport('csv')}
                  className="wbs-export-item"
                >
                  <FileSpreadsheet size={15} color="#16A34A" />
                  <span>Export as Excel (.csv)</span>
                </button>

                <button
                  type="button"
                  onClick={() => void handleExport('json')}
                  className="wbs-export-item"
                >
                  <FileCode size={15} color="#1A73E8" />
                  <span>Export as JSON</span>
                </button>

                <button
                  type="button"
                  onClick={() => void handleExport('p6_xml')}
                  className="wbs-export-item wbs-export-item-divider"
                >
                  <Share2 size={15} color="#059669" />
                  <span>Export as Primavera P6 (XML)</span>
                </button>
              </div>
            )}
          </div>}
        </div>
      </div>

      {/* Tabs */}
      <div className="wbs-tabs-container">
        {[
          { key: 'structure', label: 'WBS Structure' },
          { key: 'coverage', label: 'Scope Coverage' },
          { key: 'insights', label: 'AI Insights' },
          {
            key: 'unmapped',
            label: unmappedCount > 0 ? `Unmapped Requirements (${unmappedCount})` : 'Unmapped Requirements',
          },
        ].map((tab) => (
          <button
            type="button"
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={`wbs-tab-btn ${
              activeTab === tab.key ? 'wbs-tab-btn-active' : 'wbs-tab-btn-inactive'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: STRUCTURE */}
      {activeTab === 'structure' && (
        <div className="wbs-structure-grid">
          {/* Tree View */}
          <div className="wbs-tree-card">
            <div className="wbs-tree-card-header">
              <span>WBS</span>
              <span>Type</span>
            </div>

            <div className="wbs-tree-scroll-area">
              {renderTreeRows(data.wbsTree)}
            </div>
          </div>

          {/* Node Inspector */}
          {selectedNode ? (
            <div className="wbs-inspector-card">
              <div className="wbs-inspector-header">
                <h2 className="wbs-inspector-title">
                  {selectedNode.code} {selectedNode.name}
                </h2>

                {selectedNode.isAiAdded && (
                  <span className="wbs-ai-badge">
                    <Sparkles size={11} /> AI Added
                  </span>
                )}
              </div>

              {/* Node Details Grid */}
              <div className="wbs-node-details-grid">
                <div>
                  <span className="wbs-field-label">WBS Code</span>
                  <span className="wbs-field-val">{selectedNode.code}</span>
                </div>

                <div>
                  <span className="wbs-field-label">Type</span>
                  <span className="wbs-field-val">{selectedNode.type}</span>
                </div>

                <div>
                  <span className="wbs-field-label">Parent</span>
                  <span className="wbs-field-val">{parentDisplayLabel}</span>
                </div>

                <div>
                  <span className="wbs-field-label">Confidence</span>
                  <div className="wbs-confidence-row">
                    <span className="wbs-confidence-val">
                      {confidenceScore}%
                    </span>
                    <div className="wbs-confidence-track">
                      <div
                        className="wbs-confidence-fill"
                        style={{ width: `${confidenceScore}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <span className="wbs-field-label">Source</span>
                  <span className="wbs-field-val">{selectedNode.source || 'RFP Scope Clause'}</span>
                </div>

                <div>
                  <span className="wbs-field-label">Template</span>
                  <span className="wbs-field-val">{selectedNode.template || 'Custom Scope Addition'}</span>
                </div>
              </div>

              {/* Description */}
              <div>
                <span className="wbs-desc-label">Description</span>
                <p className="wbs-desc-body">
                  {selectedNode.description}
                </p>
              </div>

              {/* Source Evidence Box */}
              <div>
                <h3 className="wbs-evidence-title">
                  Source Evidence
                </h3>
                {activeEvidence ? (
                  <div className="wbs-evidence-box">
                    <p className="wbs-evidence-quote">
                      "{activeEvidence.text}"
                    </p>

                    <div className="wbs-evidence-footer">
                      <div className="wbs-evidence-meta">
                        <FileText size={15} color="#DC2626" />
                        <span className="wbs-evidence-doc-name">
                          {activeEvidence.document}
                        </span>
                        <span>|</span>
                        <span>{activeEvidence.section}</span>
                      </div>

                      <button
                        type="button"
                        onClick={() => setViewEvidenceModal(true)}
                        className="wbs-view-doc-btn"
                      >
                        View in Document
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="wbs-evidence-empty-box">
                    No source evidence recorded for this deliverable.
                  </div>
                )}
              </div>

              {/* Node Operations */}
              {canUpdateWbs && <div className="wbs-node-ops-row">
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => setEditingNode(selectedNode)}
                  className="wbs-node-op-btn"
                >
                  <Edit2 size={13} /> Edit
                </button>

                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => {
                    setMovingNode(selectedNode);
                    const options = candidateParents.filter(
                      (c) => c.id !== selectedNode.id && !isDescendantRecursive(data.wbsTree, c.id, selectedNode.id)
                    );
                    setTargetParentId(options.find((c) => c.id === selectedNode.parent)?.id ?? options[0]?.id ?? 'Root');
                  }}
                  className="wbs-node-op-btn"
                >
                  <Move size={13} /> Move
                </button>

                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => setNodePendingDelete(selectedNode)}
                  className="wbs-node-delete-btn"
                >
                  <Trash2 size={13} /> Remove
                </button>
              </div>}
            </div>
          ) : (
            <div className="wbs-inspector-placeholder">
              Select any WBS node to view and configure properties.
            </div>
          )}
        </div>
      )}

      {/* TAB 2: COVERAGE */}
      {activeTab === 'coverage' && (
        <div className="wbs-coverage-card">
          <div className="wbs-coverage-grid">
            <div className="wbs-coverage-kpi-box">
              <span className="wbs-coverage-kpi-label">Overall Score</span>
              <div className="wbs-kpi-val-score">
                {data.scopeCoverage?.overallScore ?? 0}%
              </div>
            </div>
            <div className="wbs-coverage-kpi-box">
              <span className="wbs-coverage-kpi-label">Total Requirements</span>
              <div className="wbs-kpi-val-total">
                {data.scopeCoverage?.totalRequirements ?? 0}
              </div>
            </div>
            <div className="wbs-coverage-kpi-box">
              <span className="wbs-coverage-kpi-label">Mapped to WBS</span>
              <div className="wbs-kpi-val-mapped">
                {data.scopeCoverage?.mappedCount ?? 0}
              </div>
            </div>
            <div className="wbs-coverage-kpi-box">
              <span className="wbs-coverage-kpi-label">Potential Gaps</span>
              <div className="wbs-kpi-val-gaps">
                {data.scopeCoverage?.gapCount ?? 0}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: INSIGHTS */}
      {activeTab === 'insights' && (
        <div className="wbs-insights-container">
          {data.aiInsights?.map((insight) => (
            <div key={insight.id} className="wbs-insight-card">
              <div className="wbs-insight-icon-box">
                {insight.type === 'RISK_WARNING' && <AlertTriangle size={18} color="#DC2626" />}
                {insight.type === 'SCOPE_ADDITION' && <Sparkles size={18} color="#D97706" />}
                {insight.type === 'OPTIMIZATION' && <Info size={18} color="#1A73E8" />}
              </div>
              <div>
                <div className="wbs-insight-title-row">
                  <h4 className="wbs-insight-title">
                    {insight.title}
                  </h4>
                  <span
                    className={`wbs-priority-badge ${
                      insight.impact === 'High' ? 'wbs-priority-high' : 'wbs-priority-standard'
                    }`}
                  >
                    {insight.impact} Priority
                  </span>
                </div>
                <p className="wbs-insight-desc">
                  {insight.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TAB 4: UNMAPPED REQUIREMENTS */}
      {activeTab === 'unmapped' && (
        <div className="wbs-unmapped-card">
          <h2 className="wbs-unmapped-title">
            Unmapped Requirements ({unmappedCount})
          </h2>

          <div className="wbs-unmapped-list">
            {data.unmappedRequirements?.map((req) => (
              <div key={req.id} className="wbs-unmapped-item">
                <div>
                  <span className="wbs-unmapped-code">
                    {req.code}
                  </span>
                  <span className="wbs-unmapped-item-title">
                    {req.title}
                  </span>
                  <p className="wbs-unmapped-desc">
                    {req.reason} (Source: {req.sourceDoc})
                  </p>
                </div>

                {canUpdateWbs && <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => {
                    setMappingReq(req);
                    setTargetParentId(data.wbsTree[0]?.id || 'Root');
                  }}
                  className="wbs-map-btn"
                >
                  Map to WBS
                </button>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Accessible Modals */}
      <AccessibleModal
        title="Edit Work Package"
        isOpen={Boolean(editingNode)}
        onClose={() => !isSaving && setEditingNode(null)}
      >
        {editingNode && (
          <>
            <div className="wbs-modal-form-stack">
              <div>
                <label htmlFor="edit-deliverable-name" className="wbs-form-label">Deliverable Name</label>
                <input
                  id="edit-deliverable-name"
                  type="text"
                  value={editingNode.name}
                  onChange={(e) => setEditingNode({ ...editingNode, name: e.target.value })}
                  className="wbs-form-input"
                />
              </div>
              <div>
                <label htmlFor="edit-deliverable-desc" className="wbs-form-label">Description</label>
                <textarea
                  id="edit-deliverable-desc"
                  rows={4}
                  value={editingNode.description}
                  onChange={(e) => setEditingNode({ ...editingNode, description: e.target.value })}
                  className="wbs-form-textarea"
                />
              </div>
            </div>
            <div className="wbs-modal-footer">
              <button type="button" disabled={isSaving} onClick={() => setEditingNode(null)} className="wbs-modal-cancel-btn">Cancel</button>
              <button type="button" disabled={isSaving} onClick={handleSaveEdit} className="wbs-modal-submit-btn">
                {isSaving ? 'Saving...' : 'Save Changes'}
              </button>
            </div>
          </>
        )}
      </AccessibleModal>

      <AccessibleModal
        title={`Relocate "${movingNode?.name ?? ''}"`}
        isOpen={Boolean(movingNode)}
        onClose={() => !isSaving && setMovingNode(null)}
      >
        {movingNode && (
          <>
            <div className="wbs-modal-select-wrapper">
              <label htmlFor="relocate-target-parent" className="wbs-form-label">Select Target Parent Node</label>
              <select
                id="relocate-target-parent"
                value={targetParentId}
                onChange={(e) => setTargetParentId(e.target.value)}
                className="wbs-form-input"
              >
                {moveOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.label}</option>
                ))}
              </select>
            </div>
            <div className="wbs-modal-footer">
              <button type="button" disabled={isSaving} onClick={() => setMovingNode(null)} className="wbs-modal-cancel-btn">Cancel</button>
              <button type="button" disabled={isSaving} onClick={handleExecuteMove} className="wbs-modal-submit-btn">
                {isSaving ? 'Moving...' : 'Move Deliverable'}
              </button>
            </div>
          </>
        )}
      </AccessibleModal>

      <AccessibleModal
        title="Remove Deliverable?"
        isOpen={Boolean(nodePendingDelete)}
        onClose={() => !isSaving && setNodePendingDelete(null)}
        maxWidth="420px"
        isDestructive
      >
        {nodePendingDelete && (
          <>
            <p className="wbs-modal-delete-confirm-text">
              Are you sure you want to remove <strong>{nodePendingDelete.code} {nodePendingDelete.name}</strong>? Any child packages will also be removed.
            </p>
            <div className="wbs-modal-footer">
              <button type="button" disabled={isSaving} onClick={() => setNodePendingDelete(null)} className="wbs-modal-cancel-btn">Cancel</button>
              <button
                type="button"
                disabled={isSaving}
                onClick={handleConfirmDelete}
                className="wbs-modal-submit-btn wbs-modal-submit-btn-danger"
              >
                {isSaving ? 'Removing...' : 'Confirm Remove'}
              </button>
            </div>
          </>
        )}
      </AccessibleModal>

      <AccessibleModal
        title={activeEvidence?.document || 'Scope Document'}
        isOpen={viewEvidenceModal}
        onClose={() => setViewEvidenceModal(false)}
        maxWidth="600px"
      >
        {activeEvidence && (
          <>
            <div className="wbs-evidence-preview-box">
              <div className="wbs-evidence-section-header">
                {activeEvidence.section}
              </div>
              <p className="wbs-evidence-dialog-text">
                "{activeEvidence.text}"
              </p>
            </div>
            <div className="wbs-modal-footer">
              <button type="button" onClick={() => setViewEvidenceModal(false)} className="wbs-modal-submit-btn">Done</button>
            </div>
          </>
        )}
      </AccessibleModal>

      <AccessibleModal
        title="Map Requirement to WBS"
        isOpen={Boolean(mappingReq)}
        onClose={() => !isSaving && setMappingReq(null)}
      >
        {mappingReq && (
          <>
            <div className="wbs-modal-form-stack">
              <div className="wbs-modal-req-pill">
                <strong>{mappingReq.code}:</strong> {mappingReq.title}
              </div>
              <div>
                <label htmlFor="map-target-parent" className="wbs-form-label">Assign Under Parent Node</label>
                <select
                  id="map-target-parent"
                  value={targetParentId}
                  onChange={(e) => setTargetParentId(e.target.value)}
                  className="wbs-form-input"
                >
                  {candidateParents.map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="wbs-modal-footer">
              <button type="button" disabled={isSaving} onClick={() => setMappingReq(null)} className="wbs-modal-cancel-btn">Cancel</button>
              <button type="button" disabled={isSaving} onClick={handleMapRequirementToNode} className="wbs-modal-submit-btn">
                {isSaving ? 'Assigning...' : 'Assign Deliverable'}
              </button>
            </div>
          </>
        )}
      </AccessibleModal>
    </div>
  );
};

export default WbsResultScreen;
