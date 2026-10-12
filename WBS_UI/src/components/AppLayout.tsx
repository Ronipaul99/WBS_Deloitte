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
    <div style={{ 
      minHeight: '100vh', 
      display: 'flex', 
      flexDirection: 'column', 
      backgroundColor: '#F8FAFC',
      fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      width: '100%',
      boxSizing: 'border-box'
    }}>
      
      {/* 52px Header */}
      <header style={{
        backgroundColor: '#0F172A',
        height: '52px',
        padding: '0 22px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
        boxShadow: '0 2px 10px rgba(0, 0, 0, 0.25)',
        flexShrink: 0,
        boxSizing: 'border-box',
        width: '100%',
        zIndex: 50
      }}>
        {/* Brandmark + Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '11px', userSelect: 'none' }}>
          <div style={{
            width: '30px',
            height: '30px',
            borderRadius: '8px',
            background: 'linear-gradient(135deg, #3B82F6 0%, #8B5CF6 50%, #EC4899 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 14px rgba(139, 92, 246, 0.55)',
            flexShrink: 0
          }}>
            <Sparkles size={16} color="#FFFFFF" strokeWidth={2.4} />
          </div>

          <span style={{ 
            fontWeight: 800, 
            fontSize: '17px', 
            letterSpacing: '-0.3px',
            background: 'linear-gradient(90deg, #FFFFFF 0%, #E2E8F0 50%, #93C5FD 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            textShadow: '0 2px 8px rgba(0, 0, 0, 0.4)',
            display: 'inline-block',
            lineHeight: 1
          }}>
            {appTitle}
          </span>
        </div>

        {/* Right Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', position: 'relative' }}>
          <button 
            type="button"
            title="Help & Documentation"
            aria-label="Open Help Documentation"
            onClick={() => setShowHelpModal(true)}
            style={{
              background: 'none',
              border: 'none',
              color: '#94A3B8',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '5px',
              borderRadius: '6px',
              transition: 'all 0.15s ease'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#FFFFFF';
              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = '#94A3B8';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <HelpCircle size={17} />
          </button>

          {/* Profile Pill */}
          <div 
            onClick={() => setShowProfileMenu((prev) => !prev)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              padding: '3px 10px 3px 4px',
              borderRadius: '9999px',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              cursor: 'pointer',
              transition: 'background-color 0.15s ease'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.12)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)')}
          >
            <div style={{
              width: '22px',
              height: '22px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #2563EB, #1D4ED8)',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: '10px'
            }}>
              {currentUser.initials}
            </div>
            <span style={{ color: '#F1F5F9', fontSize: '11.5px', fontWeight: 500 }}>{currentUser.name}</span>
            <ChevronDown size={12} color="#94A3B8" />
          </div>

          {showProfileMenu && (
            <div style={{
              position: 'absolute',
              top: '44px',
              right: '0',
              width: '185px',
              backgroundColor: '#FFFFFF',
              borderRadius: '8px',
              boxShadow: '0 10px 30px rgba(0,0,0,0.15)',
              border: '1px solid #E2E8F0',
              padding: '4px 0',
              zIndex: 100
            }}>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #F1F5F9' }}>
                <p style={{ fontSize: '12px', fontWeight: 600, color: '#0F172A', margin: 0 }}>{currentUser.name}</p>
                <p style={{ fontSize: '10.5px', color: '#64748B', margin: 0 }}>{currentUser.role}</p>
              </div>
              <button 
                type="button"
                onClick={() => setShowProfileMenu(false)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', background: 'none', border: 'none', fontSize: '11.5px', color: '#334155', cursor: 'pointer', textAlign: 'left' }}
              >
                <User size={13} color="#64748B" /> Profile Details
              </button>
              <button 
                type="button"
                onClick={() => setShowProfileMenu(false)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', background: 'none', border: 'none', fontSize: '11.5px', color: '#DC2626', cursor: 'pointer', textAlign: 'left', borderTop: '1px solid #F1F5F9' }}
              >
                <LogOut size={13} color="#DC2626" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main Container */}
      <div 
        className="app-body-container"
        style={{ 
          display: 'flex', 
          flex: 1, 
          minHeight: 'calc(100vh - 52px)',
          width: '100%',
          boxSizing: 'border-box'
        }}
      >
        <aside 
          className="app-sidebar"
          style={{
            width: '210px',
            backgroundColor: '#FFFFFF',
            borderRight: '1px solid #E2E8F0',
            padding: '16px 12px',
            display: 'flex',
            flexDirection: 'column',
            flexShrink: 0,
            boxSizing: 'border-box'
          }}
        >
          <nav style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {sidebarLinks.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => onNavClick && onNavClick(item.id)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    fontSize: '12px',
                    fontWeight: isActive ? 600 : 500,
                    border: 'none',
                    cursor: 'pointer',
                    backgroundColor: isActive ? '#EFF6FF' : 'transparent',
                    color: isActive ? '#1D4ED8' : '#64748B',
                    textAlign: 'left',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <Icon size={15} color={isActive ? '#2563EB' : '#94A3B8'} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>

        <main 
          style={{ 
            flex: 1, 
            padding: '24px clamp(16px, 3vw, 36px)', 
            overflowY: 'auto',
            display: 'flex', 
            justifyContent: 'center',
            boxSizing: 'border-box',
            maxWidth: '100%',
            overflowX: 'hidden'
          }}
        >
          <div style={{ width: '100%', maxWidth: '980px', boxSizing: 'border-box' }}>
            {children}
          </div>
        </main>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .app-body-container {
            flex-direction: column !important;
          }
          .app-sidebar {
            width: 100% !important;
            border-right: none !important;
            border-bottom: 1px solid #E2E8F0 !important;
            padding: 8px 12px !important;
          }
          .app-sidebar nav {
            flex-direction: row !important;
            overflow-x: auto !important;
          }
          .app-sidebar nav button {
            white-space: nowrap !important;
          }
        }
      `}</style>

      {/* Help Modal */}
      {showHelpModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(15, 23, 42, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200, padding: '16px', boxSizing: 'border-box' }}>
          <div style={{ backgroundColor: '#FFFFFF', borderRadius: '8px', width: '100%', maxWidth: '390px', padding: '20px', boxShadow: '0 12px 30px rgba(0,0,0,0.15)', border: '1px solid #E2E8F0', boxSizing: 'border-box' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <h3 style={{ fontSize: '13.5px', fontWeight: 700, color: '#0F172A', margin: 0 }}>Help & Documentation</h3>
              <button type="button" aria-label="Close help modal" onClick={() => setShowHelpModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748B' }}>
                <X size={15} />
              </button>
            </div>
            <p style={{ fontSize: '11.5px', color: '#64748B', lineHeight: '1.6', marginBottom: '16px' }}>
              Upload your Project Scope Document in Step 1 and your domain WBS template in Step 2. The pipeline will dynamically synthesize the project hierarchy and derive Primavera P6 work breakdown structures.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button 
                type="button"
                onClick={() => setShowHelpModal(false)} 
                style={{ 
                  padding: '6px 14px', 
                  backgroundColor: '#2563EB', 
                  color: '#FFFFFF', 
                  border: 'none', 
                  borderRadius: '4px', 
                  fontSize: '11.5px', 
                  fontWeight: 600, 
                  cursor: 'pointer' 
                }}
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