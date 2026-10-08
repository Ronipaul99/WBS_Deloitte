import { useState, useEffect, useCallback, useMemo, useRef, FC } from 'react';
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
} from 'lucide-react';
import {
  getWbsResult,
  updateWbsTree,
  WbsResultPayload,
  WbsNode,
  UnmappedRequirement,
} from '../services/wbsService';

export type WbsScreenTab = 'structure' | 'coverage' | 'insights' | 'unmapped' | 'hierarchy' | 'scope';

interface WbsResultScreenProps {
  jobId: string;
  initialTab?: WbsScreenTab;
  onNavigateToValidation?: () => void;
  onProceedToValidation?: () => void;
  onBack?: () => void;
  onRegenerate?: () => void;
}

/* ==========================================================================
   Recursive Multi-Level Tree Helpers
   ========================================================================== */

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
  return nodes.map((node) => {
    if (node.id === parentId) {
      return {
        ...node,
        children: [...(node.children || []), newNode],
      };
    }
    if (node.children && node.children.length > 0) {
      return { ...node, children: insertNodeRecursive(node.children, parentId, newNode) };
    }
    return node;
  });
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

/* ==========================================================================
   Screen 3: AI WBS Builder
   ========================================================================== */

export const WbsResultScreen: FC<WbsResultScreenProps> = ({
  jobId,
  initialTab = 'structure',
  onNavigateToValidation,
  onProceedToValidation,
  onBack,
  onRegenerate,
}) => {
  const handleValidate = onNavigateToValidation || onProceedToValidation;

  const resolveTab = (tab: WbsScreenTab): 'structure' | 'coverage' | 'insights' | 'unmapped' => {
    if (tab === 'coverage' || tab === 'scope') return 'coverage';
    if (tab === 'insights') return 'insights';
    if (tab === 'unmapped') return 'unmapped';
    return 'structure';
  };

  const [data, setData] = useState<WbsResultPayload | null>(null);
  const [selectedNode, setSelectedNode] = useState<WbsNode | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});
  const [activeTab, setActiveTab] = useState<'structure' | 'coverage' | 'insights' | 'unmapped'>(resolveTab(initialTab));

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showExportMenu, setShowExportMenu] = useState<boolean>(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  // Modals
  const [editingNode, setEditingNode] = useState<WbsNode | null>(null);
  const [movingNode, setMovingNode] = useState<WbsNode | null>(null);
  const [nodePendingDelete, setNodePendingDelete] = useState<WbsNode | null>(null);
  const [viewEvidenceModal, setViewEvidenceModal] = useState<boolean>(false);
  const [mappingReq, setMappingReq] = useState<UnmappedRequirement | null>(null);
  const [targetParentId, setTargetParentId] = useState<string>('');

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const res = await getWbsResult(jobId);
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
        setSelectedNode(aiTarget || null);
      } else {
        setSelectedNode(null);
      }
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : 'Failed to retrieve WBS generated hierarchy.');
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    setActiveTab(resolveTab(initialTab));
  }, [initialTab]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setEditingNode(null);
        setMovingNode(null);
        setNodePendingDelete(null);
        setViewEvidenceModal(false);
        setMappingReq(null);
        setShowExportMenu(false);
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedNodes((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  /* --------------------------------------------------------------------------
     Export Handlers (Excel, JSON, Primavera P6 XML)
     -------------------------------------------------------------------------- */

  const handleExportJson = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data.wbsTree, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.projectName.replace(/\s+/g, '_')}_WBS.json`;
    a.click();
    URL.revokeObjectURL(url);
    setShowExportMenu(false);
  };

  const handleExportExcel = () => {
    if (!data) return;
    const rows: Array<{ code: string; name: string; type: string; parent: string; confidence: string; description: string }> = [];
    const extract = (nodes: WbsNode[], parent = '') => {
      for (const n of nodes) {
        const conf = n.confidence > 1 ? `${n.confidence}%` : `${Math.round(n.confidence * 100)}%`;
        rows.push({
          code: n.code,
          name: n.name,
          type: n.type,
          parent,
          confidence: conf,
          description: (n.description || '').replace(/"/g, '""'),
        });
        if (n.children) extract(n.children, n.code);
      }
    };
    extract(data.wbsTree);

    const csvContent =
      'WBS Code,Deliverable Name,Type,Parent Node,Confidence Score,Scope Description\n' +
      rows.map((r) => `"${r.code}","${r.name}","${r.type}","${r.parent}","${r.confidence}","${r.description}"`).join('\n');

    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.projectName.replace(/\s+/g, '_')}_WBS_Export.csv`;
    a.click();
    URL.revokeObjectURL(url);
    setShowExportMenu(false);
  };

  const handleExportP6Xml = () => {
    if (!data) return;

    let objectIdCounter = 1000;
    const p6Nodes: string[] = [];

    const generateP6XmlNodes = (nodes: WbsNode[], parentObjectId: string | null = null) => {
      for (const node of nodes) {
        const currentObjectId = String(objectIdCounter++);
        p6Nodes.push(`
      <WBS>
        <ObjectId>${currentObjectId}</ObjectId>
        <ProjectObjectId>1</ProjectObjectId>
        <ParentObjectId>${parentObjectId ?? ''}</ParentObjectId>
        <Code>${node.code}</Code>
        <Name>${node.name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</Name>
        <SequenceNumber>${currentObjectId}</SequenceNumber>
      </WBS>`);

        if (node.children && node.children.length > 0) {
          generateP6XmlNodes(node.children, currentObjectId);
        }
      }
    };

    generateP6XmlNodes(data.wbsTree, null);

    const xmlContent = `<?xml version="1.0" encoding="UTF-8"?>
<APIBusinessObjects xmlns="http://xmlns.oracle.com/Primavera/P6/V22/API/BusinessObjects">
  <Project>
    <ObjectId>1</ObjectId>
    <Id>${data.projectId || 'PRJ-AI-WBS'}</Id>
    <Name>${data.projectName.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</Name>
    <WBSList>${p6Nodes.join('')}
    </WBSList>
  </Project>
</APIBusinessObjects>`;

    const blob = new Blob([xmlContent], { type: 'application/xml;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${data.projectName.replace(/\s+/g, '_')}_Primavera_P6.xml`;
    a.click();
    URL.revokeObjectURL(url);
    setShowExportMenu(false);
  };

  /* --------------------------------------------------------------------------
     Mutation Handlers
     -------------------------------------------------------------------------- */

  const handleSaveEdit = async () => {
    if (!data || !editingNode) return;
    const updatedTree = updateNodeRecursive(data.wbsTree, editingNode);
    setData({ ...data, wbsTree: updatedTree });
    if (selectedNode?.id === editingNode.id) {
      setSelectedNode(editingNode);
    }
    setEditingNode(null);
    await updateWbsTree(jobId, updatedTree);
  };

  const handleConfirmDelete = async () => {
    if (!data || !nodePendingDelete) return;
    const filteredTree = removeNodeRecursive(data.wbsTree, nodePendingDelete.id);
    const reindexedTree = reindexTreeRecursive(filteredTree);

    setData({ ...data, wbsTree: reindexedTree });
    if (selectedNode?.id === nodePendingDelete.id) {
      setSelectedNode(reindexedTree[0] || null);
    }
    setNodePendingDelete(null);
    await updateWbsTree(jobId, reindexedTree);
  };

  const handleExecuteMove = async () => {
    if (!data || !movingNode || !targetParentId) return;
    const pruned = removeNodeRecursive(data.wbsTree, movingNode.id);
    const inserted = insertNodeRecursive(pruned, targetParentId, movingNode);
    const reindexed = reindexTreeRecursive(inserted);

    setData({ ...data, wbsTree: reindexed });
    const freshRef = findNodeRecursive(reindexed, movingNode.id);
    if (freshRef) setSelectedNode(freshRef);

    setExpandedNodes((prev) => ({ ...prev, [targetParentId]: true }));
    setMovingNode(null);
    setTargetParentId('');
    await updateWbsTree(jobId, reindexed);
  };

  const handleMapRequirementToNode = async () => {
    if (!data || !mappingReq || !targetParentId) return;

    const newPackage: WbsNode = {
      id: `wbs_${Date.now()}`,
      code: '0.0',
      name: mappingReq.title,
      type: 'Work Package',
      parent: targetParentId,
      source: mappingReq.sourceDoc,
      template: 'Custom Mapped Scope',
      confidence: 95,
      isAiAdded: true,
      description: `Integrated deliverable mapped from: ${mappingReq.reason}`,
      children: [],
    };

    const inserted = insertNodeRecursive(data.wbsTree, targetParentId, newPackage);
    const reindexed = reindexTreeRecursive(inserted);
    const updatedUnmapped = data.unmappedRequirements.filter((r) => r.id !== mappingReq.id);

    setData({
      ...data,
      wbsTree: reindexed,
      unmappedRequirements: updatedUnmapped,
    });

    setExpandedNodes((prev) => ({ ...prev, [targetParentId]: true }));
    setMappingReq(null);
    setTargetParentId('');
    await updateWbsTree(jobId, reindexed);
  };

  const candidateParents = useMemo(() => {
    if (!data) return [];
    const list: Array<{ id: string; label: string }> = [];
    const collect = (nodes: WbsNode[]) => {
      for (const n of nodes) {
        list.push({ id: n.id, label: `${n.code} ${n.name}` });
        if (n.children && n.children.length > 0) collect(n.children);
      }
    };
    collect(data.wbsTree);
    return list;
  }, [data]);

  // Normalizes percentage properly (prevents 9300%)
  const getDisplayConfidence = (confidenceVal?: number): number => {
    if (confidenceVal === undefined || confidenceVal === null) return 90;
    if (confidenceVal <= 1) return Math.round(confidenceVal * 100);
    return Math.min(100, Math.round(confidenceVal));
  };

  /* --------------------------------------------------------------------------
     Tree Row Renderer (Table Layout)
     -------------------------------------------------------------------------- */

  const renderTreeRows = (nodes: WbsNode[], depth: number = 0): React.ReactNode => {
    return nodes.map((node) => {
      const hasChildren = Boolean(node.children && node.children.length > 0);
      const isExpanded = Boolean(expandedNodes[node.id]);
      const isSelected = selectedNode?.id === node.id;

      return (
        <div key={node.id} style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            onClick={() => setSelectedNode(node)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              paddingLeft: `${depth * 18 + 12}px`,
              borderBottom: '1px solid #F1F5F9',
              backgroundColor: isSelected ? '#EFF6FF' : '#FFFFFF',
              cursor: 'pointer',
              userSelect: 'none',
              transition: 'background 0.1s ease',
            }}
          >
            {/* Left: Expander + Code + Name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
              <div
                onClick={(e) => hasChildren && toggleExpand(node.id, e)}
                style={{
                  width: '16px',
                  height: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: hasChildren ? 'pointer' : 'default',
                  color: '#64748B',
                }}
              >
                {hasChildren ? (
                  isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
                ) : (
                  <span style={{ width: '14px' }} />
                )}
              </div>

              <span style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B', flexShrink: 0 }}>
                {node.code}
              </span>

              <span
                style={{
                  fontSize: '13px',
                  fontWeight: isSelected ? 600 : 400,
                  color: isSelected ? '#1A73E8' : '#334155',
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  overflow: 'hidden',
                }}
              >
                {node.name}
              </span>
            </div>

            {/* Right: Type Column */}
            <div
              style={{
                fontSize: '12px',
                color: '#64748B',
                textAlign: 'right',
                flexShrink: 0,
                paddingLeft: '12px',
              }}
            >
              {node.type}
            </div>
          </div>

          {hasChildren && isExpanded && renderTreeRows(node.children!, depth + 1)}
        </div>
      );
    });
  };

  /* --------------------------------------------------------------------------
     Loading & Error Guards
     -------------------------------------------------------------------------- */

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '460px',
          gap: '12px',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <RefreshCw size={30} color="#1A73E8" style={{ animation: 'spin 1s linear infinite' }} />
        <span style={{ fontSize: '13px', color: '#64748B' }}>Loading WBS hierarchy & contracts...</span>
      </div>
    );
  }

  if (loadError || !data) {
    return (
      <div
        style={{
          maxWidth: '520px',
          margin: '60px auto',
          padding: '32px',
          backgroundColor: '#FFFFFF',
          borderRadius: '8px',
          border: '1px solid #FCA5A5',
          textAlign: 'center',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <AlertTriangle size={32} color="#DC2626" style={{ margin: '0 auto 12px auto' }} />
        <h2 style={{ fontSize: '17px', fontWeight: 600, color: '#0F172A', margin: '0 0 6px 0' }}>
          Unable to Load WBS
        </h2>
        <p style={{ fontSize: '13px', color: '#64748B', margin: '0 0 20px 0' }}>
          {loadError || 'The WBS results could not be retrieved.'}
        </p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '10px' }}>
          {onBack && (
            <button
              onClick={onBack}
              style={{
                padding: '6px 16px',
                fontSize: '12.5px',
                borderRadius: '6px',
                border: '1px solid #CBD5E1',
                backgroundColor: '#FFFFFF',
                color: '#475569',
                cursor: 'pointer',
              }}
            >
              Back
            </button>
          )}
          <button
            onClick={loadData}
            style={{
              padding: '6px 16px',
              fontSize: '12.5px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: '#1A73E8',
              color: '#FFFFFF',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const confidenceScore = getDisplayConfidence(selectedNode?.confidence);
  const unmappedCount = data.unmappedRequirements?.length ?? 0;

  return (
    <div
      style={{
        padding: '24px 32px',
        maxWidth: '1440px',
        margin: '0 auto',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        backgroundColor: '#F8FAFC',
        minHeight: '100%',
      }}
    >
      {/* Header Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '16px',
          marginBottom: '16px',
        }}
      >
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#0F172A', margin: '0 0 4px 0' }}>
            AI WBS Builder
          </h1>
          <div style={{ fontSize: '12.5px', color: '#64748B', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>Project: <strong>{data.projectName}</strong></span>
            <span>|</span>
            <span>{data.version || 'Draft v1.0'}</span>
            <span>|</span>
            <span>Generated on {data.generatedDate}</span>
          </div>
        </div>

        {/* Top Right Action Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {onRegenerate && (
            <button
              onClick={onRegenerate}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '7px 14px',
                fontSize: '12.5px',
                fontWeight: 500,
                color: '#1E293B',
                backgroundColor: '#FFFFFF',
                border: '1px solid #CBD5E1',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              <RotateCcw size={13} />
              <span>Regenerate</span>
            </button>
          )}

          {handleValidate && (
            <button
              onClick={handleValidate}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '7px 14px',
                fontSize: '12.5px',
                fontWeight: 500,
                color: '#1A73E8',
                backgroundColor: '#FFFFFF',
                border: '1px solid #BFDBFE',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              <CheckSquare size={13} color="#1A73E8" />
              <span>Validate</span>
            </button>
          )}

          {/* Export Dropdown */}
          <div style={{ position: 'relative' }} ref={exportMenuRef}>
            <button
              onClick={() => setShowExportMenu(!showExportMenu)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '7px 14px',
                fontSize: '12.5px',
                fontWeight: 500,
                color: '#FFFFFF',
                backgroundColor: '#1E293B',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              <Download size={13} />
              <span>Export</span>
              <ChevronDown size={12} />
            </button>

            {showExportMenu && (
              <div
                style={{
                  position: 'absolute',
                  right: 0,
                  top: '100%',
                  marginTop: '6px',
                  backgroundColor: '#FFFFFF',
                  borderRadius: '6px',
                  border: '1px solid #E2E8F0',
                  boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)',
                  width: '210px',
                  zIndex: 50,
                  overflow: 'hidden',
                }}
              >
                <button
                  onClick={handleExportExcel}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    width: '100%',
                    padding: '10px 14px',
                    fontSize: '12.5px',
                    color: '#1E293B',
                    border: 'none',
                    background: 'none',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAFC')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <FileSpreadsheet size={15} color="#16A34A" />
                  <span>Export as Excel (.csv)</span>
                </button>

                <button
                  onClick={handleExportJson}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    width: '100%',
                    padding: '10px 14px',
                    fontSize: '12.5px',
                    color: '#1E293B',
                    border: 'none',
                    background: 'none',
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAFC')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <FileCode size={15} color="#1A73E8" />
                  <span>Export as JSON</span>
                </button>

                <button
                  onClick={handleExportP6Xml}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    width: '100%',
                    padding: '10px 14px',
                    fontSize: '12.5px',
                    color: '#1E293B',
                    border: 'none',
                    background: 'none',
                    cursor: 'pointer',
                    textAlign: 'left',
                    borderTop: '1px solid #F1F5F9',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAFC')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                >
                  <Share2 size={15} color="#059669" />
                  <span>Export as Primavera P6 (XML)</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Tabs with Dynamic Unmapped Badge (3) */}
      <div style={{ display: 'flex', gap: '28px', borderBottom: '1px solid #E2E8F0', marginBottom: '20px' }}>
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
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            style={{
              background: 'none',
              border: 'none',
              padding: '10px 0',
              fontSize: '13px',
              fontWeight: activeTab === tab.key ? 700 : 500,
              color: activeTab === tab.key ? '#1A73E8' : '#64748B',
              borderBottom: activeTab === tab.key ? '2.5px solid #1A73E8' : '2.5px solid transparent',
              cursor: 'pointer',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: WBS STRUCTURE */}
      {activeTab === 'structure' && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(380px, 1.1fr) minmax(460px, 1.3fr)',
            gap: '20px',
            alignItems: 'start',
          }}
        >
          {/* Left Tree Table */}
          <div
            style={{
              backgroundColor: '#FFFFFF',
              border: '1px solid #E2E8F0',
              borderRadius: '8px',
              overflow: 'hidden',
              boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '10px 16px',
                backgroundColor: '#F8FAFC',
                borderBottom: '1px solid #E2E8F0',
                fontSize: '12px',
                fontWeight: 600,
                color: '#64748B',
              }}
            >
              <span>WBS</span>
              <span>Type</span>
            </div>

            <div style={{ maxHeight: '720px', overflowY: 'auto' }}>
              {renderTreeRows(data.wbsTree)}
            </div>
          </div>

          {/* Right Selected Item Detail Card */}
          {selectedNode ? (
            <div
              style={{
                backgroundColor: '#FFFFFF',
                border: '1px solid #E2E8F0',
                borderRadius: '8px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '20px',
                boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', margin: 0 }}>
                  {selectedNode.code} {selectedNode.name}
                </h2>

                {selectedNode.isAiAdded && (
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      backgroundColor: '#FEF3C7',
                      color: '#B45309',
                      padding: '3px 8px',
                      borderRadius: '12px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Sparkles size={11} /> AI Added
                  </span>
                )}
              </div>

              {/* 2-Column Key Value Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  rowGap: '14px',
                  columnGap: '20px',
                  fontSize: '13px',
                }}
              >
                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    WBS Code
                  </span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>{selectedNode.code}</span>
                </div>

                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    Type
                  </span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>{selectedNode.type}</span>
                </div>

                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    Parent
                  </span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>
                    {selectedNode.parent || 'Root Phase'}
                  </span>
                </div>

                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    Confidence
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontWeight: 600, color: '#059669' }}>
                      {confidenceScore}%
                    </span>
                    <div
                      style={{
                        width: '80px',
                        height: '6px',
                        backgroundColor: '#E2E8F0',
                        borderRadius: '3px',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${confidenceScore}%`,
                          height: '100%',
                          backgroundColor: '#10B981',
                        }}
                      />
                    </div>
                  </div>
                </div>

                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    Source
                  </span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>{selectedNode.source || 'RFP Clause'}</span>
                </div>

                <div>
                  <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '2px' }}>
                    Template
                  </span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>{selectedNode.template || 'No equivalent in template'}</span>
                </div>
              </div>

              {/* Description */}
              <div>
                <span style={{ color: '#64748B', display: 'block', fontSize: '12px', marginBottom: '4px' }}>
                  Description
                </span>
                <p style={{ fontSize: '13px', color: '#334155', lineHeight: '1.5', margin: 0 }}>
                  {selectedNode.description}
                </p>
              </div>

              {/* Source Evidence Box */}
              <div>
                <h3 style={{ fontSize: '13.5px', fontWeight: 600, color: '#0F172A', margin: '0 0 8px 0' }}>
                  Source Evidence
                </h3>
                <div
                  style={{
                    backgroundColor: '#F8FAFC',
                    border: '1px solid #E2E8F0',
                    borderRadius: '6px',
                    padding: '14px 16px',
                  }}
                >
                  <p style={{ fontSize: '12.5px', color: '#334155', fontStyle: 'italic', margin: '0 0 12px 0', lineHeight: '1.5' }}>
                    "{selectedNode.evidence?.text || 'The successful bidder shall design, supply, install and commission deliverables in accordance with scope specifications.'}"
                  </p>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#64748B' }}>
                      <FileText size={15} color="#DC2626" />
                      <span style={{ fontWeight: 500, color: '#1E293B' }}>
                        {selectedNode.evidence?.document || 'RFP_Solar_Plant_Project.pdf'}
                      </span>
                      <span>|</span>
                      <span>{selectedNode.evidence?.section || 'Section 7.3'}</span>
                    </div>

                    <button
                      type="button"
                      onClick={() => setViewEvidenceModal(true)}
                      style={{
                        padding: '4px 10px',
                        fontSize: '11.5px',
                        fontWeight: 600,
                        backgroundColor: '#FFFFFF',
                        border: '1px solid #CBD5E1',
                        borderRadius: '4px',
                        color: '#1E293B',
                        cursor: 'pointer',
                      }}
                    >
                      View in Document
                    </button>
                  </div>
                </div>
              </div>

              {/* Action Buttons: Edit, Move, Remove */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingTop: '8px' }}>
                <button
                  type="button"
                  onClick={() => setEditingNode(selectedNode)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    fontSize: '12.5px',
                    fontWeight: 500,
                    border: '1px solid #CBD5E1',
                    borderRadius: '5px',
                    backgroundColor: '#FFFFFF',
                    color: '#1E293B',
                    cursor: 'pointer',
                  }}
                >
                  <Edit2 size={13} /> Edit
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setMovingNode(selectedNode);
                    setTargetParentId(selectedNode.parent || data.wbsTree[0]?.id || '');
                  }}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    fontSize: '12.5px',
                    fontWeight: 500,
                    border: '1px solid #CBD5E1',
                    borderRadius: '5px',
                    backgroundColor: '#FFFFFF',
                    color: '#1E293B',
                    cursor: 'pointer',
                  }}
                >
                  <Move size={13} /> Move
                </button>

                <button
                  type="button"
                  onClick={() => setNodePendingDelete(selectedNode)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    fontSize: '12.5px',
                    fontWeight: 500,
                    border: '1px solid #FCA5A5',
                    borderRadius: '5px',
                    backgroundColor: '#FEF2F2',
                    color: '#DC2626',
                    cursor: 'pointer',
                  }}
                >
                  <Trash2 size={13} /> Remove
                </button>
              </div>
            </div>
          ) : (
            <div
              style={{
                backgroundColor: '#FFFFFF',
                border: '1px dashed #CBD5E1',
                borderRadius: '8px',
                padding: '40px',
                textAlign: 'center',
                color: '#64748B',
                fontSize: '13px',
              }}
            >
              Select any WBS node to view and configure properties.
            </div>
          )}
        </div>
      )}

      {/* TAB 2: SCOPE COVERAGE */}
      {activeTab === 'coverage' && (
        <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '24px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
            <div style={{ padding: '16px', backgroundColor: '#F8FAFC', borderRadius: '6px' }}>
              <span style={{ fontSize: '12px', color: '#64748B' }}>Overall Score</span>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#16A34A', marginTop: '4px' }}>
                {data.scopeCoverage?.overallScore || 91}%
              </div>
            </div>
            <div style={{ padding: '16px', backgroundColor: '#F8FAFC', borderRadius: '6px' }}>
              <span style={{ fontSize: '12px', color: '#64748B' }}>Total Requirements</span>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#0F172A', marginTop: '4px' }}>
                {data.scopeCoverage?.totalRequirements || 112}
              </div>
            </div>
            <div style={{ padding: '16px', backgroundColor: '#F8FAFC', borderRadius: '6px' }}>
              <span style={{ fontSize: '12px', color: '#64748B' }}>Mapped to WBS</span>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#2563EB', marginTop: '4px' }}>
                {data.scopeCoverage?.mappedCount || 102}
              </div>
            </div>
            <div style={{ padding: '16px', backgroundColor: '#F8FAFC', borderRadius: '6px' }}>
              <span style={{ fontSize: '12px', color: '#64748B' }}>Potential Gaps</span>
              <div style={{ fontSize: '24px', fontWeight: 700, color: '#DC2626', marginTop: '4px' }}>
                {data.scopeCoverage?.gapCount || 2}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: AI INSIGHTS */}
      {activeTab === 'insights' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {data.aiInsights?.map((insight) => (
            <div
              key={insight.id}
              style={{
                backgroundColor: '#FFFFFF',
                border: '1px solid #E2E8F0',
                borderRadius: '8px',
                padding: '16px 20px',
                display: 'flex',
                gap: '12px',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ marginTop: '2px' }}>
                {insight.type === 'RISK_WARNING' && <AlertTriangle size={18} color="#DC2626" />}
                {insight.type === 'SCOPE_ADDITION' && <Sparkles size={18} color="#D97706" />}
                {insight.type === 'OPTIMIZATION' && <Info size={18} color="#1A73E8" />}
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h4 style={{ fontSize: '14px', fontWeight: 600, color: '#0F172A', margin: 0 }}>
                    {insight.title}
                  </h4>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor: insight.impact === 'High' ? '#FEE2E2' : '#EFF6FF',
                      color: insight.impact === 'High' ? '#DC2626' : '#1A73E8',
                    }}
                  >
                    {insight.impact} Priority
                  </span>
                </div>
                <p style={{ fontSize: '13px', color: '#475569', margin: '4px 0 0 0', lineHeight: '1.4' }}>
                  {insight.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TAB 4: UNMAPPED REQUIREMENTS */}
      {activeTab === 'unmapped' && (
        <div style={{ backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '24px' }}>
          <h2 style={{ fontSize: '16px', fontWeight: 600, color: '#0F172A', margin: '0 0 16px 0' }}>
            Unmapped Requirements ({unmappedCount})
          </h2>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {data.unmappedRequirements?.map((req) => (
              <div
                key={req.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '12px 16px',
                  backgroundColor: '#FFFBEB',
                  border: '1px solid #FDE68A',
                  borderRadius: '6px',
                }}
              >
                <div>
                  <span style={{ fontSize: '12px', fontWeight: 700, color: '#92400E', marginRight: '8px' }}>
                    {req.code}
                  </span>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#1E293B' }}>
                    {req.title}
                  </span>
                  <p style={{ fontSize: '12px', color: '#78350F', margin: '2px 0 0 0' }}>
                    {req.reason} (Source: {req.sourceDoc})
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    setMappingReq(req);
                    setTargetParentId(data.wbsTree[0]?.id || '');
                  }}
                  style={{
                    padding: '6px 12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    backgroundColor: '#D97706',
                    color: '#FFFFFF',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Map to WBS
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modals */}
      {editingNode && (
        <div style={modalBackdrop}>
          <div style={modalBox}>
            <div style={modalHeader}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>Edit Work Package</h3>
              <button onClick={() => setEditingNode(null)} style={closeBtn}><X size={16} /></button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '12px' }}>
              <div>
                <label style={labelStyle}>Deliverable Name</label>
                <input
                  type="text"
                  value={editingNode.name}
                  onChange={(e) => setEditingNode({ ...editingNode, name: e.target.value })}
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={labelStyle}>Description</label>
                <textarea
                  rows={4}
                  value={editingNode.description}
                  onChange={(e) => setEditingNode({ ...editingNode, description: e.target.value })}
                  style={{ ...inputStyle, resize: 'vertical' }}
                />
              </div>
            </div>
            <div style={modalFooter}>
              <button onClick={() => setEditingNode(null)} style={cancelBtn}>Cancel</button>
              <button onClick={handleSaveEdit} style={submitBtn}>Save Changes</button>
            </div>
          </div>
        </div>
      )}

      {movingNode && (
        <div style={modalBackdrop}>
          <div style={modalBox}>
            <div style={modalHeader}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>Relocate "{movingNode.name}"</h3>
              <button onClick={() => setMovingNode(null)} style={closeBtn}><X size={16} /></button>
            </div>
            <div style={{ marginTop: '12px' }}>
              <label style={labelStyle}>Select Target Parent Node</label>
              <select
                value={targetParentId}
                onChange={(e) => setTargetParentId(e.target.value)}
                style={inputStyle}
              >
                {candidateParents
                  .filter((c) => c.id !== movingNode.id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
              </select>
            </div>
            <div style={modalFooter}>
              <button onClick={() => setMovingNode(null)} style={cancelBtn}>Cancel</button>
              <button onClick={handleExecuteMove} style={submitBtn}>Move Deliverable</button>
            </div>
          </div>
        </div>
      )}

      {nodePendingDelete && (
        <div style={modalBackdrop}>
          <div style={{ ...modalBox, maxWidth: '420px' }}>
            <div style={modalHeader}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, color: '#DC2626', margin: 0 }}>Remove Deliverable?</h3>
              <button onClick={() => setNodePendingDelete(null)} style={closeBtn}><X size={16} /></button>
            </div>
            <p style={{ fontSize: '13px', color: '#475569', margin: '12px 0 16px 0', lineHeight: '1.5' }}>
              Are you sure you want to remove <strong>{nodePendingDelete.code} {nodePendingDelete.name}</strong>? Any child packages will also be removed.
            </p>
            <div style={modalFooter}>
              <button onClick={() => setNodePendingDelete(null)} style={cancelBtn}>Cancel</button>
              <button onClick={handleConfirmDelete} style={{ ...submitBtn, backgroundColor: '#DC2626' }}>
                Confirm Remove
              </button>
            </div>
          </div>
        </div>
      )}

      {viewEvidenceModal && selectedNode && (
        <div style={modalBackdrop}>
          <div style={{ ...modalBox, maxWidth: '600px' }}>
            <div style={modalHeader}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>
                {selectedNode.evidence?.document || 'Contract Document'}
              </h3>
              <button onClick={() => setViewEvidenceModal(false)} style={closeBtn}><X size={16} /></button>
            </div>
            <div style={{ marginTop: '14px', backgroundColor: '#F8FAFC', padding: '16px', borderRadius: '6px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748B', marginBottom: '4px' }}>
                {selectedNode.evidence?.section || 'Scope Specification Section'}
              </div>
              <p style={{ fontSize: '13px', color: '#1E293B', lineHeight: '1.6', margin: 0 }}>
                "{selectedNode.evidence?.text}"
              </p>
            </div>
            <div style={modalFooter}>
              <button onClick={() => setViewEvidenceModal(false)} style={submitBtn}>Done</button>
            </div>
          </div>
        </div>
      )}

      {mappingReq && (
        <div style={modalBackdrop}>
          <div style={modalBox}>
            <div style={modalHeader}>
              <h3 style={{ fontSize: '15px', fontWeight: 600, margin: 0 }}>Map Requirement to WBS</h3>
              <button onClick={() => setMappingReq(null)} style={closeBtn}><X size={16} /></button>
            </div>
            <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ padding: '8px 12px', backgroundColor: '#F8FAFC', borderRadius: '4px', fontSize: '12px' }}>
                <strong>{mappingReq.code}:</strong> {mappingReq.title}
              </div>
              <div>
                <label style={labelStyle}>Assign Under Parent Node</label>
                <select
                  value={targetParentId}
                  onChange={(e) => setTargetParentId(e.target.value)}
                  style={inputStyle}
                >
                  {candidateParents.map((c) => (
                    <option key={c.id} value={c.id}>{c.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div style={modalFooter}>
              <button onClick={() => setMappingReq(null)} style={cancelBtn}>Cancel</button>
              <button onClick={handleMapRequirementToNode} style={submitBtn}>Assign Deliverable</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default WbsResultScreen;

/* ==========================================================================
   Styles
   ========================================================================== */

const modalBackdrop: React.CSSProperties = {
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  backgroundColor: 'rgba(15, 23, 42, 0.4)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
  padding: '16px',
};

const modalBox: React.CSSProperties = {
  backgroundColor: '#FFFFFF',
  borderRadius: '8px',
  width: '100%',
  maxWidth: '480px',
  padding: '20px',
  boxShadow: '0 10px 25px rgba(0,0,0,0.1)',
  fontFamily: 'system-ui, -apple-system, sans-serif',
};

const modalHeader: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  paddingBottom: '10px',
  borderBottom: '1px solid #E2E8F0',
};

const closeBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#94A3B8',
  cursor: 'pointer',
};

const modalFooter: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  gap: '8px',
  marginTop: '18px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '12px',
  fontWeight: 600,
  color: '#475569',
  marginBottom: '4px',
  display: 'block',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: '5px',
  border: '1px solid #CBD5E1',
  fontSize: '12.5px',
  boxSizing: 'border-box',
};

const submitBtn: React.CSSProperties = {
  padding: '7px 14px',
  fontSize: '12.5px',
  fontWeight: 600,
  backgroundColor: '#1A73E8',
  color: '#FFFFFF',
  border: 'none',
  borderRadius: '5px',
  cursor: 'pointer',
};

const cancelBtn: React.CSSProperties = {
  padding: '7px 14px',
  fontSize: '12.5px',
  fontWeight: 500,
  backgroundColor: '#FFFFFF',
  color: '#475569',
  border: '1px solid #CBD5E1',
  borderRadius: '5px',
  cursor: 'pointer',
};