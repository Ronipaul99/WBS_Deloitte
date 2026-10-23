import { useState, useEffect } from 'react';
import { AlertTriangle, ArrowLeft, LoaderCircle } from 'lucide-react';
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
import type { AccountSettingsSection } from './views/AccountSettingsScreen';
import TenantSelectionScreen from './views/TenantSelectionScreen';
import { acceptTenantInvitation } from './services/memberAdministration';
import { enterpriseSignInUrl } from './services/apiClient';
import { startGeneration } from './services/generationsApi';
import { startValidation } from './services/validationsApi';
import type { WorkflowSession } from './services/workflowTypes';
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
  const defaultTab = can(PERMISSIONS.PROJECT_CREATE) ? 'create' : 'projects';
  const directMemberRoute = window.location.pathname === '/settings/members';
  const [activeTab, setActiveTab] = useState<string>(directMemberRoute ? 'settings' : defaultTab);
  const [currentScreen, setCurrentScreen] = useState<ScreenType>('create');
  const [workflow, setWorkflow] = useState<WorkflowSession | null>(null);
  const [settingsSection, setSettingsSection] = useState<AccountSettingsSection>(
    directMemberRoute ? 'members' : 'profile',
  );
  const [targetResultTab, setTargetResultTab] = useState<
    'structure' | 'coverage' | 'insights' | 'unmapped'
  >('structure');

  // 1. Step 1 (Upload) -> Step 2 (Document Processing Stepper)
  const handleWorkflowStarted = (session: WorkflowSession) => {
    setWorkflow(session);
    setCurrentScreen('doc_processing');
  };

  // 2. Step 2 (Document Processing) -> Step 3 (Review Summary)
  const handleDocProcessingComplete = () => {
    setCurrentScreen('doc_summary');
  };

  // 3. Step 3 (Review Summary) -> Step 4 (Decomposition Pipeline Analysis)
  const handleProceedToAnalyze = (generationJobId: string, summaryId: string) => {
    setWorkflow((current) => current ? { ...current, generationJobId, summaryId } : current);
    setCurrentScreen('analyzing');
  };

  // 4. Step 4 (Pipeline Analysis Complete) -> Step 5 (WBS Result Screen)
  const handleAnalysisComplete = (wbsVersionId: string) => {
    setWorkflow((current) => current ? { ...current, wbsVersionId } : current);
    setTargetResultTab('structure');
    setCurrentScreen('results');
  };

  // Navigation handlers
  const handleBackToCreate = () => {
    setWorkflow(null);
    setCurrentScreen('create');
  };

  const handleRegenerate = async () => {
    if (!workflow?.summaryId) throw new Error('The approved summary is no longer available.');
    const job = await startGeneration(activeTenant.id, workflow.project.id, {
      documentId: workflow.document.id,
      summaryId: workflow.summaryId,
      templateId: workflow.template?.id ?? null,
    });
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
    setWorkflow(null);
    setCurrentScreen('create');
  };

  const handleViewAllUnmapped = () => {
    setTargetResultTab('unmapped');
    setCurrentScreen('results');
  };

  const handleNavClick = (tab: string) => {
    const requiredPermissions: Record<string, Permission> = {
      create: PERMISSIONS.PROJECT_CREATE,
      projects: PERMISSIONS.PROJECT_READ,
      templates: PERMISSIONS.TEMPLATE_READ,
      exports: PERMISSIONS.EXPORT_READ,
      settings: PERMISSIONS.MEMBER_READ,
    };
    if (!requiredPermissions[tab] || !can(requiredPermissions[tab])) return;
    setActiveTab(tab);
    if (tab === 'settings') {
      setSettingsSection('members');
      window.history.pushState({}, '', '/settings/members');
    } else if (window.location.pathname.startsWith('/settings/')) {
      window.history.pushState({}, '', '/');
    }
    if (tab === 'create') {
      setWorkflow(null);
      setCurrentScreen('create');
    }
  };

  const handleProfileDetails = () => {
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
        No active analysis job ID was provided for this page. Please start from Step 1 and upload your project files.
      </p>
      <button
        type="button"
        onClick={handleCreateNewWbs}
        className="app-missing-job-btn"
      >
        <ArrowLeft size={15} />
        Back to Document Upload
      </button>
    </div>
  );

  const renderContent = () => {
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

    if (activeTab === 'create') {
      if (currentScreen === 'create') {
        return <CreateWbsScreen onWorkflowStarted={handleWorkflowStarted} />;
      }

      if (!workflow) {
        return renderMissingJobIdError();
      }

      if (currentScreen === 'doc_processing') {
        return (
          <ProcessingProjectDocumentScreen
            tenantId={activeTenant.id}
            jobId={workflow.summaryJobId}
            document={workflow.document}
            template={workflow.template}
            onProcessingComplete={handleDocProcessingComplete}
            onBack={handleBackToCreate}
            onCancel={handleBackToCreate}
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
            onProceedToAnalyze={handleProceedToAnalyze}
            onDiscard={handleBackToCreate}
          />
        );
      }

      if (currentScreen === 'analyzing') {
        if (!workflow.generationJobId) return renderMissingJobIdError();
        return (
          <AnalyzingProjectScreen
            tenantId={activeTenant.id}
            jobId={workflow.generationJobId}
            projectName={workflow.project.name}
            onAnalysisComplete={handleAnalysisComplete}
            onCancel={handleBackToCreate}
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
          initialTab={targetResultTab}
          onRegenerate={handleRegenerate}
          onNavigateToValidation={handleNavigateToValidation}
        />
      );
    }

    const placeholderTitles: Record<string, string> = {
      projects: 'My Projects',
      templates: 'Templates',
      exports: 'Exports',
      settings: 'Settings',
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
      onSignOut={() => void onSignOut()}
      onProfileDetails={handleProfileDetails}
      canSwitchWorkspace={canSwitchWorkspace}
      onSwitchWorkspace={onSwitchWorkspace}
    >
      {renderContent()}
    </AppLayout>
  );
}
