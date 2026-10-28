import type { WorkflowStage } from '../services/workflowTypes';
import { workflowStageLabel, workflowStageTone } from './workflowUi';
import './WorkflowSurfaces.css';

export default function WorkflowStatusBadge({ stage, needsRefresh = false }: {
  stage: WorkflowStage; needsRefresh?: boolean;
}) {
  return <span className={`workflow-badge workflow-badge-${needsRefresh ? 'warning' : workflowStageTone(stage)}`}>
    <span aria-hidden="true" />{needsRefresh ? 'Processing update needed' : workflowStageLabel(stage)}
  </span>;
}
