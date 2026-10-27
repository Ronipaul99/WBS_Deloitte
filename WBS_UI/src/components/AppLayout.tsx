import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { 
  Sparkles,
  House,
  FolderKanban, 
  FileSpreadsheet, 
  DownloadCloud, 
  Settings, 
  HelpCircle, 
  ChevronDown,
  User,
  Building2,
  LogOut,
  X
} from 'lucide-react';
import './AppLayout.css';
import { PERMISSIONS } from '../auth/permissions';
import type { Permission } from '../auth/permissions';

export interface UserProfile {
  name: string;
  role: string;
  initials: string;
}

interface AppLayoutProps {
  children: ReactNode;
  activeTab?: string;
  onNavClick?: (tab: string) => void;
  appTitle?: string;
  currentUser?: UserProfile;
  onSignOut?: () => void;
  onProfileDetails?: () => void;
  canSwitchWorkspace?: boolean;
  onSwitchWorkspace?: () => void;
  can?: (permission: Permission) => boolean;
}

export default function AppLayout({
  children,
  activeTab = 'home',
  onNavClick,
  appTitle = 'WBS Genie',
  currentUser = {
    name: 'John Doe',
    role: 'Lead Planner',
    initials: 'JD',
  },
  onSignOut,
  onProfileDetails,
  canSwitchWorkspace = false,
  onSwitchWorkspace,
  can = () => false,
}: AppLayoutProps) {
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const profileControlRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const firstProfileItemRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!showProfileMenu) return;

    const focusTimer = window.setTimeout(() => firstProfileItemRef.current?.focus(), 0);
    const handlePointerDown = (event: MouseEvent) => {
      if (!profileControlRef.current?.contains(event.target as Node)) {
        setShowProfileMenu(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setShowProfileMenu(false);
        profileButtonRef.current?.focus();
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [showProfileMenu]);

  const sidebarLinks = [
    { id: 'home', label: 'Home', icon: House, permission: PERMISSIONS.PROJECT_READ },
    { id: 'projects', label: 'My Projects', icon: FolderKanban, permission: PERMISSIONS.PROJECT_READ },
    { id: 'templates', label: 'Templates', icon: FileSpreadsheet, permission: PERMISSIONS.TEMPLATE_READ },
    { id: 'exports', label: 'Exports', icon: DownloadCloud, permission: PERMISSIONS.EXPORT_READ },
    { id: 'settings', label: 'Settings', icon: Settings, permission: PERMISSIONS.MEMBER_READ },
    { id: 'ai-models', label: 'AI Models', icon: Sparkles, permission: PERMISSIONS.LLM_MANAGE },
  ].filter((item) => can(item.permission));

  return (
    <div className="app-layout-shell">
      {/* 52px Header */}
      <header className="app-header">
        {/* Brandmark + Title */}
        <div className="app-brand-wrapper">
          <div className="app-brand-icon-box">
            <Sparkles size={16} color="#FFFFFF" strokeWidth={2.4} />
          </div>

          <span className="app-brand-title">
            {appTitle}
          </span>
        </div>

        {/* Right Navigation */}
        <div className="app-header-right">
          <button 
            type="button"
            title="Help & Documentation"
            aria-label="Open Help Documentation"
            onClick={() => setShowHelpModal(true)}
            className="app-help-btn"
          >
            <HelpCircle size={17} />
          </button>

          <div className="app-profile-control" ref={profileControlRef}>
            <button
              ref={profileButtonRef}
              type="button"
              onClick={() => setShowProfileMenu((prev) => !prev)}
              className="app-profile-pill"
              aria-expanded={showProfileMenu}
              aria-haspopup="menu"
              aria-label="Open profile menu"
            >
              <span className="app-profile-avatar">
                {currentUser.initials}
              </span>
              <span className="app-profile-name">{currentUser.name}</span>
              <ChevronDown size={12} color="#94A3B8" />
            </button>

            {showProfileMenu && (
              <div className="app-profile-dropdown" role="menu" aria-label="Profile menu">
                <div className="app-profile-info-header">
                  <p className="app-profile-info-name">{currentUser.name}</p>
                  <p className="app-profile-info-role">{currentUser.role}</p>
                </div>
                <button
                  ref={firstProfileItemRef}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowProfileMenu(false);
                    onProfileDetails?.();
                  }}
                  className="app-profile-item-btn"
                >
                  <User size={13} color="#64748B" /> Profile Details
                </button>
                {canSwitchWorkspace && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setShowProfileMenu(false);
                      onSwitchWorkspace?.();
                    }}
                    className="app-profile-item-btn"
                  >
                    <Building2 size={13} color="#64748B" /> Switch workspace
                  </button>
                )}
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setShowProfileMenu(false);
                    onSignOut?.();
                  }}
                  className="app-profile-signout-btn"
                >
                  <LogOut size={13} color="#DC2626" /> Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <div className="app-body-container">
        <aside className="app-sidebar">
          <nav className="app-sidebar-nav">
            {sidebarLinks.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => {
                    setShowProfileMenu(false);
                    onNavClick?.(item.id);
                  }}
                  className={`app-nav-button ${
                    isActive ? 'app-nav-button-active' : 'app-nav-button-inactive'
                  }`}
                >
                  <Icon size={15} color={isActive ? '#2563EB' : '#94A3B8'} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>

        <main className="app-main-content">
          <div className="app-content-wrapper">
            {children}
          </div>
        </main>
      </div>

      {/* Help Modal */}
      {showHelpModal && (
        <div className="app-help-backdrop">
          <div className="app-help-dialog">
            <div className="app-help-dialog-header">
              <h3 className="app-help-dialog-title">Help & Documentation</h3>
              <button 
                type="button" 
                aria-label="Close help modal" 
                onClick={() => setShowHelpModal(false)}
                className="app-help-dialog-close"
              >
                <X size={15} />
              </button>
            </div>
            <p className="app-help-dialog-body">
              Upload your Project Scope Document in Step 1. You can optionally add a domain WBS template in Step 2, or let the pipeline synthesize the project hierarchy directly from the project scope.
            </p>
            <div className="app-help-dialog-footer">
              <button 
                type="button" 
                onClick={() => setShowHelpModal(false)} 
                className="app-help-close-btn"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
