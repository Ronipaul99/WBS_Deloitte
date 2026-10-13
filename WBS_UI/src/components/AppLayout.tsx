import { useState, ReactNode } from 'react';
import { 
  Sparkles,
  Layers, 
  FolderKanban, 
  FileSpreadsheet, 
  DownloadCloud, 
  Settings, 
  HelpCircle, 
  ChevronDown,
  User,
  LogOut,
  X
} from 'lucide-react';
import './AppLayout.css';

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
}

export default function AppLayout({
  children,
  activeTab = 'create',
  onNavClick,
  appTitle = 'WBS Genie',
  currentUser = {
    name: 'John Doe',
    role: 'Lead Planner',
    initials: 'JD',
  },
}: AppLayoutProps) {
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [showHelpModal, setShowHelpModal] = useState(false);

  const sidebarLinks = [
    { id: 'create', label: 'Create WBS', icon: Layers },
    { id: 'projects', label: 'My Projects', icon: FolderKanban },
    { id: 'templates', label: 'Templates', icon: FileSpreadsheet },
    { id: 'exports', label: 'Exports', icon: DownloadCloud },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

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

          {/* Profile Pill */}
          <div 
            onClick={() => setShowProfileMenu((prev) => !prev)}
            className="app-profile-pill"
          >
            <div className="app-profile-avatar">
              {currentUser.initials}
            </div>
            <span className="app-profile-name">{currentUser.name}</span>
            <ChevronDown size={12} color="#94A3B8" />
          </div>

          {showProfileMenu && (
            <div className="app-profile-dropdown">
              <div className="app-profile-info-header">
                <p className="app-profile-info-name">{currentUser.name}</p>
                <p className="app-profile-info-role">{currentUser.role}</p>
              </div>
              <button 
                type="button"
                onClick={() => setShowProfileMenu(false)}
                className="app-profile-item-btn"
              >
                <User size={13} color="#64748B" /> Profile Details
              </button>
              <button 
                type="button"
                onClick={() => setShowProfileMenu(false)}
                className="app-profile-signout-btn"
              >
                <LogOut size={13} color="#DC2626" /> Sign Out
              </button>
            </div>
          )}
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
                  onClick={() => onNavClick && onNavClick(item.id)}
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
              Upload your Project Scope Document in Step 1 and your domain WBS template in Step 2. The pipeline will dynamically synthesize the project hierarchy and derive Primavera P6 work breakdown structures.
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