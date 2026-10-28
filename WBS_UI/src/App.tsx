import { useState, useEffect, useRef } from 'react';
import { AlertTriangle, ArrowLeft, LoaderCircle, RefreshCw } from 'lucide-react';
import { useAuth } from './auth/authContext';
import type { CurrentUser, TenantMembership } from './auth/authContext';
import { PERMISSIONS } from './auth/permissions';
import type { Permission } from './auth/permissions';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import ProcessingProjectDocumentScreen from './views/ProcessingProjectDocumentScreen';
import ReviewProjectSummaryScreen from './views/ReviewProjectSummaryScreen';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';
import WbsResultScreen from './views/WbsResultScreen';
import WbsValidationScreen from './views/WbsValidationScreen';
import LoginScreen from './views/LoginScreen';
import ForgotPasswordScreen from './views/ForgotPasswordScreen';
import ResetPasswordScreen from './views/ResetPasswordScreen';
import InvitationAcceptanceScreen from './views/InvitationAcceptanceScreen';
import SsoCompletionScreen from './views/SsoCompletionScreen';
import AccountSettingsScreen from './views/AccountSettingsScreen';
import HomeScreen from './views/HomeScreen';
import {
  CreateProjectScreen,
  ProjectsScreen,
  ProjectWorkspaceScreen,
} from './views/ProjectScreens';
import type { AccountSettingsSection } from './views/AccountSettingsScreen';
import TenantSelectionScreen from './views/TenantSelectionScreen';
import { acceptTenantInvitation } from './services/memberAdministration';
import { enterpriseSignInUrl } from './services/apiClient';
import { ApiError } from './services/apiClient';
import { startGeneration } from './services/generationsApi';
import { startValidation } from './services/validationsApi';
import { restoreWorkflow, resumeWorkflow } from './services/workflowApi';
import WorkflowCheckpointScreen from './views/WorkflowCheckpointScreen';
import {
  clearWorkflowContext,
  readWorkflowContext,
  saveWorkflowContext,
} from './services/workflowSessionStorage';
import type { ProjectResponse, WorkflowSession } from './services/workflowTypes';
import './App.css';

type PublicAuthRoute =
  | { screen: 'login' | 'forgot'; token: '' }
  | { screen: 'reset' | 'invitation'; token: string }
  | { screen: 'sso'; token: ''; error: string };

const passwordRecoveryEnabled = import.meta.env.VITE_PASSWORD_RECOVERY_ENABLED === 'true';
const authMode = import.meta.env.VITE_AUTH_MODE ?? 'local';
const ssoEnabled = import.meta.env.VITE_SSO_ENABLED === 'true'
  && (authMode === 'oidc' || authMode === 'hybrid');
const localAuthEnabled = authMode === 'local' || authMode === 'hybrid';
const ssoProviderLabel = import.meta.env.VITE_SSO_PROVIDER_LABEL?.trim() || 'Enterprise SSO';
let initialPublicAuthRoute: PublicAuthRoute | undefined;

function readPublicAuthRoute(): PublicAuthRoute {
  const url = new URL(window.location.href);
  if (url.pathname === '/sso/callback') {
    const error = url.searchParams.get('error') ?? '';
    window.history.replaceState(window.history.state, '', '/sso/callback');
    return { screen: 'sso', token: '', error };
  }
  if (url.pathname === '/accept-invitation') {
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const token = fragment.get('token') ?? url.searchParams.get('token') ?? '';
    if (url.search || url.hash) {
      window.history.replaceState(window.history.state, '', '/accept-invitation');
    }
    return { screen: 'invitation', token };
  }
  if (url.pathname === '/reset-password') {
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const token = fragment.get('token') ?? url.searchParams.get('token') ?? '';
    if (url.search || url.hash) {
      window.history.replaceState(window.history.state, '', '/reset-password');
    }
    return { screen: 'reset', token };
  }
  if (url.pathname === '/forgot-password') return { screen: 'forgot', token: '' };
  return { screen: 'login', token: '' };
}

function getInitialPublicAuthRoute(): PublicAuthRoute {
  initialPublicAuthRoute ??= readPublicAuthRoute();
  return initialPublicAuthRoute;
}

export type ScreenType =
  | 'create'
  | 'checkpoint'
  | 'doc_processing'
  | 'doc_summary'
  | 'analyzing'
  | 'results'
  | 'validation';

export default function App() {
  const {
    status,
    user,
    activeTenant,
    login,
    logout,
    changePassword,
    logoutAll,
    refreshUser,
    selectTenant,
    can,
  } = useAuth();
  const [publicAuthRoute, setPublicAuthRoute] = useState<PublicAuthRoute>(
    getInitialPublicAuthRoute,
  );

  const navigatePublicAuth = (route: PublicAuthRoute) => {
    const path = route.screen === 'login'
      ? '/'
      : route.screen === 'sso'
        ? '/sso/callback'
      : route.screen === 'invitation'
        ? '/accept-invitation'
        : `/${route.screen}-password`;
    window.history.pushState({}, '', path);
    initialPublicAuthRoute = route;
    setPublicAuthRoute(route);
  };

  useEffect(() => {
    const handlePopState = () => {
      const route = readPublicAuthRoute();
      initialPublicAuthRoute = route;
      setPublicAuthRoute(route);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  if (publicAuthRoute.screen === 'sso') {
    return (
      <SsoCompletionScreen
        status={status}
        error={publicAuthRoute.error}
        onComplete={() => {
          window.history.replaceState({}, '', '/');
          navigatePublicAuth({ screen: 'login', token: '' });
        }}
        onBackToLogin={() => navigatePublicAuth({ screen: 'login', token: '' })}
      />
    );
  }

  if (publicAuthRoute.screen === 'invitation') {
    return (
      <InvitationAcceptanceScreen
        token={publicAuthRoute.token}
        authStatus={status}
        authenticatedEmail={user?.email}
        onAcceptAuthenticated={async (token) => {
          await acceptTenantInvitation(token);
          await refreshUser();
          navigatePublicAuth({ screen: 'login', token: '' });
        }}
        onSignInAndAccept={async (email, password, token) => {
          let signedIn = false;
          try {
            await login(email, password);
            signedIn = true;
            await acceptTenantInvitation(token);
            await refreshUser();
            navigatePublicAuth({ screen: 'login', token: '' });
          } catch (reason) {
            if (signedIn) await logout();
            throw reason;
          }
        }}
        onCreateAccount={(displayName, password, token) => (
          acceptTenantInvitation(token, { displayName, password })
        )}
        localAuthEnabled={localAuthEnabled}
        onEnterpriseLogin={ssoEnabled
          ? () => window.location.assign(enterpriseSignInUrl())
          : undefined}
        enterpriseLabel={ssoProviderLabel}
        onBackToLogin={async () => {
          if (status === 'authenticated') {
            await logout();
          } else {
            navigatePublicAuth({ screen: 'login', token: '' });
          }
        }}
      />
    );
  }

  if (passwordRecoveryEnabled && publicAuthRoute.screen === 'forgot') {
    return (
      <ForgotPasswordScreen
        onBackToLogin={() => navigatePublicAuth({ screen: 'login', token: '' })}
      />
    );
  }
  if (passwordRecoveryEnabled && publicAuthRoute.screen === 'reset') {
    return (
      <ResetPasswordScreen
        token={publicAuthRoute.token}
        onResetComplete={logout}
        onBackToLogin={() => navigatePublicAuth({ screen: 'login', token: '' })}
      />
    );
  }

  if (status === 'loading') {
    return <div className="auth-loading" role="status"><LoaderCircle className="login-spinner" /></div>;
  }
  if (status === 'unauthenticated' || !user) {
    return (
      <LoginScreen
        onLogin={login}
        localAuthEnabled={localAuthEnabled}
        onEnterpriseLogin={ssoEnabled
          ? () => window.location.assign(enterpriseSignInUrl())
          : undefined}
        enterpriseLabel={ssoProviderLabel}
        onForgotPassword={passwordRecoveryEnabled
          && localAuthEnabled
          ? () => navigatePublicAuth({ screen: 'forgot', token: '' })
          : undefined}
      />
    );
  }
  if (!activeTenant) {
    return (
      <TenantSelectionScreen
        tenants={user.tenants}
        onSelect={selectTenant}
        onSignOut={logout}
      />
    );
  }
  return (
    <WorkspaceApp
      key={activeTenant.id}
      user={user}
      activeTenant={activeTenant}
      can={can}
      onSignOut={logout}
      onChangePassword={changePassword}
      onLogoutAll={logoutAll}
      onRefreshUser={refreshUser}
      canSwitchWorkspace={user.tenants.length > 1}
      onSwitchWorkspace={() => selectTenant(null)}
    />
  );
}

interface WorkspaceAppProps {
  user: CurrentUser;
  activeTenant: TenantMembership;
  can: (permission: Permission) => boolean;
  onSignOut: () => Promise<void>;
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  onLogoutAll: () => Promise<void>;
  onRefreshUser: () => Promise<CurrentUser>;
  canSwitchWorkspace: boolean;
  onSwitchWorkspace: () => void;
}

function WorkspaceApp({
  user,
  activeTenant,
  can,
  onSignOut,
  onChangePassword,
  onLogoutAll,
  onRefreshUser,
  canSwitchWorkspace,
  onSwitchWorkspace,
}: WorkspaceAppProps) {
  const directMemberRoute = window.location.pathname === '/settings/members';
  const [activeTab, setActiveTab] = useState<string>(directMemberRoute ? 'settings' : 'home');
  const [projectScreen, setProjectScreen] = useState<
    'list' | 'create' | 'workspace' | 'wbs' | 'result'
  >('list');
  const [selectedProject, setSelectedProject] = useState<ProjectResponse | null>(null);
  const [selectedWbsVersionId, setSelectedWbsVersionId] = useState<string | null>(null);
  const [currentScreen, setCurrentScreen] = useState<ScreenType>('create');
  const [workflow, setWorkflow] = useState<WorkflowSession | null>(null);
  const [settingsSection, setSettingsSection] = useState<AccountSettingsSection>(
    directMemberRoute ? 'members' : 'profile',
  );
  const [targetResultTab, setTargetResultTab] = useState<
    'structure' | 'coverage' | 'insights' | 'unmapped'
  >('structure');
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const restoreController = useRef<AbortController | null>(null);
  const [isRestoringWorkflow, setIsRestoringWorkflow] = useState(
    () => readWorkflowContext(activeTenant.id) !== null,
  );
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const canCreateProject = can(PERMISSIONS.PROJECT_CREATE);
  const canCreateWbs = can(PERMISSIONS.DOCUMENT_UPLOAD) && can(PERMISSIONS.DOCUMENT_PROCESS);

  useEffect(() => {
    const stored = readWorkflowContext(activeTenant.id);
    if (!stored) return;
    const controller = new AbortController();
    restoreController.current = controller;
    restoreWorkflow(activeTenant.id, stored, controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return;
        setSelectedProject(session.project);
        setWorkflow(session);
        setActiveTab('projects');
        setProjectScreen('wbs');
        setCurrentScreen(session.recovery?.resume_screen ?? 'doc_processing');
        saveWorkflowContext(activeTenant.id, session);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        const invalidContext = reason instanceof ApiError
          ? reason.status === 403 || reason.status === 404
          : reason instanceof Error && reason.message.includes('saved document workflow');
        if (invalidContext) clearWorkflowContext(activeTenant.id, stored.projectId);
        setRestoreError(invalidContext
          ? 'The saved document workflow is no longer available in this workspace.'
          : 'The document workflow could not be restored. Check the connection and try again.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsRestoringWorkflow(false);
      });
    return () => controller.abort();
  }, [activeTenant.id, restoreAttempt]);

  const resetWbsFlow = (clearStored = true) => {
    restoreController.current?.abort();
    setIsRestoringWorkflow(false);
    setRestoreError(null);
    if (clearStored) {
      clearWorkflowContext(activeTenant.id, workflow?.project.id ?? selectedProject?.id);
    }
    setWorkflow(null);
    setSelectedWbsVersionId(null);
    setCurrentScreen('create');
    setTargetResultTab('structure');
  };

  const showProjectList = () => {
    resetWbsFlow(false);
    setSelectedProject(null);
    setProjectScreen('list');
    setActiveTab('projects');
  };

  const showCreateProject = () => {
    if (!canCreateProject) return;
    resetWbsFlow(false);
    setSelectedProject(null);
    setProjectScreen('create');
    setActiveTab('projects');
  };

  const openProject = (project: ProjectResponse) => {
    resetWbsFlow(false);
    setSelectedProject(project);
    setActiveTab('projects');
    setProjectScreen('workspace');
  };

  const showWbsUpload = () => {
    if (!selectedProject || !canCreateWbs) return;
    resetWbsFlow(false);
    setProjectScreen('wbs');
  };

  const openExistingWbs = (versionId: string) => {
    if (!selectedProject) return;
    setWorkflow(null);
    setSelectedWbsVersionId(versionId);
    setTargetResultTab('structure');
    setProjectScreen('result');
  };

  // 1. Step 1 (Upload) -> Step 2 (Document Processing Stepper)
  const handleWorkflowStarted = (session: WorkflowSession) => {
    saveWorkflowContext(activeTenant.id, session);
    setSelectedProject(session.project);
    setWorkflow(session);
    setCurrentScreen(session.recovery?.resume_screen ?? 'doc_processing');
  };

  const handleLoadSavedWorkflow = async (workflowId: string, signal?: AbortSignal) => {
    try {
      const session = await resumeWorkflow(activeTenant.id, workflowId, signal);
      if (signal?.aborted) return false;
      handleWorkflowStarted(session);
      setActiveTab('projects');
      setProjectScreen('wbs');
      return true;
    } catch (reason) {
      if (signal?.aborted) return false;
      if (!signal) setRestoreError(reason instanceof Error ? reason.message : 'The saved workflow is unavailable.');
      return false;
    }
  };

  // 3. Step 3 (Review Summary) -> Step 4 (Decomposition Pipeline Analysis)
  const handleProceedToAnalyze = (generationJobId: string, summaryId: string) => {
    setWorkflow((current) => current ? { ...current, generationJobId, summaryId } : current);
    setCurrentScreen('analyzing');
  };

  // 4. Step 4 (Pipeline Analysis Complete) -> Step 5 (WBS Result Screen)
  const handleAnalysisComplete = (wbsVersionId: string) => {
    if (workflow?.workflowId) {
      void handleLoadSavedWorkflow(workflow.workflowId);
      return;
    }
    setWorkflow((current) => current ? { ...current, wbsVersionId } : current);
    setTargetResultTab('structure');
    setCurrentScreen('results');
  };

  const handleBackToUpload = () => {
    setWorkflow(null);
    setCurrentScreen('create');
  };

  const handleBackToProject = () => {
    resetWbsFlow();
    setProjectScreen(selectedProject ? 'workspace' : 'list');
  };

  const handleLeaveProcessing = (completed: boolean) => {
    resetWbsFlow(completed);
    setProjectScreen(selectedProject ? 'workspace' : 'list');
  };

  const handleRegenerate = async () => {
    if (!workflow?.summaryId) throw new Error('The approved summary is no longer available.');
    const job = await startGeneration(activeTenant.id, workflow.project.id, {
      documentId: workflow.document.id,
      summaryId: workflow.summaryId,
      templateId: workflow.template?.id ?? null,
      workflowId: workflow.workflowId,
      regenerate: Boolean(workflow.workflowId),
    });
    if (job.workflow_id) {
      await handleLoadSavedWorkflow(job.workflow_id);
      return;
    }
    setWorkflow((current) => current ? {
      ...current,
      generationJobId: job.id,
      wbsVersionId: null,
      validationId: null,
    } : current);
    setCurrentScreen('analyzing');
  };

  const handleNavigateToValidation = async () => {
    if (!workflow?.wbsVersionId) throw new Error('The WBS version is not available for validation.');
    const validation = await startValidation(activeTenant.id, workflow.wbsVersionId);
    setWorkflow((current) => current ? { ...current, validationId: validation.id } : current);
    setCurrentScreen('validation');
  };

  const handleBackToResults = () => {
    setTargetResultTab('structure');
    setCurrentScreen('results');
  };

  const handleCreateNewWbs = () => {
    resetWbsFlow();
    setProjectScreen('wbs');
  };

  const handleViewAllUnmapped = () => {
    setTargetResultTab('unmapped');
    setCurrentScreen('results');
  };

  const handleNavClick = (tab: string) => {
    const requiredPermissions: Record<string, Permission> = {
      home: PERMISSIONS.PROJECT_READ,
      projects: PERMISSIONS.PROJECT_READ,
      templates: PERMISSIONS.TEMPLATE_READ,
      exports: PERMISSIONS.EXPORT_READ,
      settings: PERMISSIONS.MEMBER_READ,
    };
    if (!requiredPermissions[tab] || !can(requiredPermissions[tab])) return;
    if (tab === 'projects') {
      showProjectList();
    } else {
      setActiveTab(tab);
      resetWbsFlow(false);
      setSelectedProject(null);
      setProjectScreen('list');
    }
    if (tab === 'settings') {
      setSettingsSection('members');
      window.history.pushState({}, '', '/settings/members');
    } else if (window.location.pathname.startsWith('/settings/')) {
      window.history.pushState({}, '', '/');
    }
  };

  const handleProfileDetails = () => {
    resetWbsFlow(false);
    setSelectedProject(null);
    setProjectScreen('list');
    setSettingsSection('profile');
    setActiveTab('settings');
    window.history.pushState({}, '', '/settings/profile');
  };

  const handleSettingsSectionChange = (section: AccountSettingsSection) => {
    setSettingsSection(section);
    window.history.pushState({}, '', `/settings/${section}`);
  };

  const renderMissingJobIdError = () => (
    <div className="app-missing-job-card">
      <div className="app-missing-job-icon-box">
        <AlertTriangle size={24} />
      </div>
      <h2 className="app-missing-job-title">Missing Job ID</h2>
      <p className="app-missing-job-desc">
        No active analysis job was found. Return to the project and start the WBS workflow again.
      </p>
      <button
        type="button"
        onClick={handleBackToProject}
        className="app-missing-job-btn"
      >
        <ArrowLeft size={15} />
        Back to Project
      </button>
    </div>
  );

  const renderContent = () => {
    if (isRestoringWorkflow) {
      return (
        <div className="wbs-state-loading" role="status" aria-live="polite">
          <LoaderCircle size={34} className="login-spinner" />
          <span className="wbs-state-loading-text">Restoring document processing...</span>
        </div>
      );
    }

    if (restoreError) {
      return (
        <div className="app-missing-job-card" role="alert">
          <div className="app-missing-job-icon-box"><AlertTriangle size={24} /></div>
          <h2 className="app-missing-job-title">Document workflow unavailable</h2>
          <p className="app-missing-job-desc">{restoreError}</p>
          <div className="app-missing-job-actions">
            <button
              type="button"
              className="app-missing-job-btn"
              onClick={() => {
                setRestoreError(null);
                setIsRestoringWorkflow(true);
                setRestoreAttempt((value) => value + 1);
              }}
            >
              <RefreshCw size={14} /> Check again
            </button>
            <button
              type="button"
              className="project-secondary-button"
              onClick={() => {
                const stored = readWorkflowContext(activeTenant.id);
                clearWorkflowContext(activeTenant.id, stored?.projectId);
                setRestoreError(null);
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      );
    }

    if (activeTab === 'settings') {
      return (
        <AccountSettingsScreen
          user={user}
          activeTenant={activeTenant}
          activeSection={settingsSection}
          onSectionChange={handleSettingsSectionChange}
          onChangePassword={onChangePassword}
          onLogoutAll={onLogoutAll}
          can={can}
          onCurrentMembershipChanged={async () => { await onRefreshUser(); }}
        />
      );
    }

    if (activeTab === 'home') {
      return (
        <HomeScreen
          user={user}
          activeTenant={activeTenant}
          canCreateProject={canCreateProject}
          onCreateProject={showCreateProject}
          onOpenProject={openProject}
          onViewProjects={showProjectList}
        />
      );
    }

    if (activeTab === 'projects') {
      if (projectScreen === 'create') {
        return (
          <CreateProjectScreen
            tenantId={activeTenant.id}
            onCreated={openProject}
            onCancel={showProjectList}
          />
        );
      }

      if (projectScreen === 'workspace' && selectedProject) {
        return (
          <ProjectWorkspaceScreen
            tenantId={activeTenant.id}
            project={selectedProject}
            canCreateWbs={canCreateWbs}
            canDeleteDocument={can(PERMISSIONS.DOCUMENT_UPLOAD)}
            onBack={showProjectList}
            onCreateWbs={showWbsUpload}
            onOpenWbs={openExistingWbs}
            onResumeWorkflow={handleLoadSavedWorkflow}
          />
        );
      }

      if (projectScreen === 'result' && selectedProject && selectedWbsVersionId) {
        return (
          <WbsResultScreen
            tenantId={activeTenant.id}
            project={selectedProject}
            template={null}
            versionId={selectedWbsVersionId}
            initialTab={targetResultTab}
            onBack={handleBackToProject}
          />
        );
      }

      if (projectScreen === 'list') {
        return (
          <ProjectsScreen
            tenantId={activeTenant.id}
            canCreateProject={canCreateProject}
            onCreateProject={showCreateProject}
            onOpenProject={openProject}
          />
        );
      }

      if (!selectedProject) return renderMissingJobIdError();

      if (currentScreen === 'create') {
        return (
          <CreateWbsScreen
            project={selectedProject}
            onWorkflowStarted={handleWorkflowStarted}
            onBack={handleBackToProject}
          />
        );
      }

      if (!workflow) {
        return renderMissingJobIdError();
      }

      if (currentScreen === 'doc_processing') {
        if (!workflow.ingestionJobId || !workflow.processingRunId || !workflow.initialIngestionStatus) {
          return renderMissingJobIdError();
        }
        return (
          <ProcessingProjectDocumentScreen
            tenantId={activeTenant.id}
            jobId={workflow.ingestionJobId}
            processingRunId={workflow.processingRunId}
            document={workflow.document}
            template={workflow.template}
            initialStatus={workflow.initialIngestionStatus}
            onBack={handleLeaveProcessing}
            onContinue={workflow.workflowId ? () => void handleLoadSavedWorkflow(workflow.workflowId!) : undefined}
          />
        );
      }

      if (currentScreen === 'doc_summary') {
        return (
          <ReviewProjectSummaryScreen
            tenantId={activeTenant.id}
            project={workflow.project}
            document={workflow.document}
            template={workflow.template}
            workflowId={workflow.workflowId}
            onProceedToAnalyze={handleProceedToAnalyze}
            onDiscard={handleBackToUpload}
          />
        );
      }

      if (currentScreen === 'checkpoint' && workflow.recovery) {
        return <WorkflowCheckpointScreen tenantId={activeTenant.id} state={workflow.recovery}
          onResumed={handleWorkflowStarted} onBack={handleBackToProject}
          onViewWbs={() => setCurrentScreen('results')} />;
      }

      if (currentScreen === 'analyzing') {
        if (!workflow.generationJobId) return renderMissingJobIdError();
        return (
          <AnalyzingProjectScreen
            tenantId={activeTenant.id}
            jobId={workflow.generationJobId}
            projectName={workflow.project.name}
            onAnalysisComplete={handleAnalysisComplete}
            onCancel={handleBackToUpload}
          />
        );
      }

      if (currentScreen === 'validation') {
        if (!workflow.validationId) return renderMissingJobIdError();
        return (
          <WbsValidationScreen
            tenantId={activeTenant.id}
            validationId={workflow.validationId}
            project={workflow.project}
            template={workflow.template}
            onBackToResults={handleBackToResults}
            onViewUnmapped={handleViewAllUnmapped}
            onCreateNew={handleCreateNewWbs}
          />
        );
      }

      return (
        <WbsResultScreen
          tenantId={activeTenant.id}
          project={workflow.project}
          template={workflow.template}
          versionId={workflow.wbsVersionId ?? undefined}
          historicalOutput={Boolean(workflow.recovery && workflow.recovery.input_compatibility !== 'CURRENT')}
          initialTab={targetResultTab}
          onBack={handleBackToProject}
          onRegenerate={handleRegenerate}
          onNavigateToValidation={handleNavigateToValidation}
        />
      );
    }

    const placeholderTitles: Record<string, string> = {
      templates: 'Templates',
      exports: 'Exports',
    };

    return (
      <div className="app-placeholder-box">
        <h2 className="app-placeholder-title">
          {placeholderTitles[activeTab] || 'Section Under Development'}
        </h2>
        <p className="app-placeholder-desc">
          This section is currently being configured and will be available soon.
        </p>
      </div>
    );
  };

  return (
    <AppLayout
      activeTab={activeTab}
      onNavClick={handleNavClick}
      can={can}
      currentUser={{
        name: user.display_name,
        role: `${activeTenant.name} - ${activeTenant.role?.toLowerCase() ?? 'member'}`,
        initials: user.display_name
          .split(/\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((part) => part[0].toUpperCase())
          .join('') || 'U',
      }}
      onSignOut={() => {
        clearWorkflowContext(activeTenant.id, workflow?.project.id ?? selectedProject?.id);
        void onSignOut();
      }}
      onProfileDetails={handleProfileDetails}
      canSwitchWorkspace={canSwitchWorkspace}
      onSwitchWorkspace={() => {
        clearWorkflowContext(activeTenant.id, workflow?.project.id ?? selectedProject?.id);
        onSwitchWorkspace();
      }}
    >
      {renderContent()}
    </AppLayout>
  );
}
