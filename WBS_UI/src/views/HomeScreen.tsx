import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  CircleDot,
  FolderKanban,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react';
import type { CurrentUser, TenantMembership } from '../auth/authContext';
import { listProjects } from '../services/projectsApi';
import type { ProjectResponse } from '../services/workflowTypes';
import './HomeScreen.css';

interface HomeScreenProps {
  user: CurrentUser;
  activeTenant: TenantMembership;
  canCreateProject: boolean;
  onCreateProject: () => void;
  onOpenProject: (project: ProjectResponse) => void;
  onViewProjects: () => void;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date);
}

export default function HomeScreen({
  user,
  activeTenant,
  canCreateProject,
  onCreateProject,
  onOpenProject,
  onViewProjects,
}: HomeScreenProps) {
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listProjects(activeTenant.id, controller.signal)
      .then(setProjects)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : 'Projects could not be loaded.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [activeTenant.id, reloadKey]);

  const recentProjects = useMemo(() => projects.slice(0, 5), [projects]);
  const firstName = user.display_name.trim().split(/\s+/)[0] || 'there';
  const retryLoad = () => {
    setLoading(true);
    setError(null);
    setReloadKey((value) => value + 1);
  };

  return (
    <div className="home-screen">
      <header className="home-welcome">
        <div className="home-welcome-copy">
          <p className="home-workspace-label">
            <CircleDot size={13} aria-hidden="true" />
            {activeTenant.name}
          </p>
          <h1>Welcome back, {firstName}</h1>
          <p>Move from project scope to a validated, planner-ready work breakdown structure.</p>
        </div>
        {canCreateProject && (
          <button type="button" className="home-primary-action" onClick={onCreateProject}>
            <FolderKanban size={17} aria-hidden="true" />
            Create project
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        )}
      </header>

      <section className="home-overview" aria-label="Workspace overview">
        <div className="home-overview-item">
          <span className="home-overview-icon home-overview-icon-blue">
            <FolderKanban size={18} aria-hidden="true" />
          </span>
          <span className="home-overview-copy">
            <small>Active projects</small>
            <strong>{loading ? '...' : projects.length}</strong>
          </span>
        </div>
      </section>

      <div className="home-content-grid">
        <section className="home-projects" aria-labelledby="home-projects-title">
          <div className="home-section-heading">
            <div>
              <p className="home-section-kicker">Workspace activity</p>
              <h2 id="home-projects-title">Recent projects</h2>
            </div>
            {!loading && !error && projects.length > 0 && (
              <button type="button" className="home-view-projects" onClick={onViewProjects}>
                View all <ArrowRight size={13} aria-hidden="true" />
              </button>
            )}
          </div>

          {loading ? (
            <div className="home-project-state" role="status">
              <LoaderCircle className="home-spinner" size={22} />
              <span>Loading projects...</span>
            </div>
          ) : error ? (
            <div className="home-project-state home-project-error" role="alert">
              <span>{error}</span>
              <button type="button" onClick={retryLoad}>
                <RefreshCw size={14} aria-hidden="true" />
                Retry
              </button>
            </div>
          ) : recentProjects.length === 0 ? (
            <div className="home-empty-state">
              <span className="home-empty-icon"><FolderKanban size={23} aria-hidden="true" /></span>
              <div>
                <h3>No projects yet</h3>
                <p>Create a project first, then add its scope document and generate the WBS.</p>
              </div>
              {canCreateProject && (
                <button type="button" onClick={onCreateProject}>
                  Create first project
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              )}
            </div>
          ) : (
            <div className="home-project-list">
              {recentProjects.map((project) => (
                <button
                  type="button"
                  className="home-project-row"
                  key={project.id}
                  onClick={() => onOpenProject(project)}
                  aria-label={`Open ${project.name}`}
                >
                  <span className="home-project-mark" aria-hidden="true">
                    {project.name.trim().charAt(0).toUpperCase() || 'P'}
                  </span>
                  <span className="home-project-details">
                    <strong>{project.name}</strong>
                    <small>{project.description || 'Project scope workspace'}</small>
                  </span>
                  <span className="home-project-meta">
                    <span>{project.status}</span>
                    <time dateTime={project.updated_at}>{formatDate(project.updated_at)}</time>
                  </span>
                  <ArrowRight className="home-project-arrow" size={15} aria-hidden="true" />
                </button>
              ))}
            </div>
          )}
        </section>

      </div>
    </div>
  );
}
