import { useState, ReactNode } from 'react';
import { 
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

interface AppLayoutProps {
  children: ReactNode;
  activeTab?: string;
  onNavClick?: (tab: string) => void;
  appTitle?: string;
}

export default function AppLayout({
  children,
  activeTab = 'create',
  onNavClick,
  appTitle = 'AI WBS Builder',
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
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    }}>
      
      {/* 46px Header */}
      <header style={{
        backgroundColor: '#1E2530',
        height: '46px',
        padding: '0 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid #2B3442',
        flexShrink: 0
      }}>
        {/* Canonical Oracle Brandmark Vector + Application Title */}
        <div style={{ display: 'flex', alignItems: 'center', height: '100%' }}>
          
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <img 
              src="https://upload.wikimedia.org/wikipedia/commons/5/50/Oracle_logo.svg" 
              alt="ORACLE" 
              style={{
                height: '14px',
                width: 'auto',
                display: 'block',
                filter: 'brightness(0) invert(1)', // Converts standard red SVG to solid crisp white
                userSelect: 'none',
              }} 
            />
          </div>

          {/* Thin vertical divider */}
          <span style={{
            display: 'inline-block',
            width: '1px',
            height: '14px',
            backgroundColor: 'rgba(255, 255, 255, 0.28)',
            margin: '0 16px'
          }} />

          {/* Application Title */}
          <span style={{ 
            fontWeight: 600, 
            fontSize: '13px', 
            color: '#FFFFFF', 
            letterSpacing: '-0.1px',
            lineHeight: 1,
            userSelect: 'none'
          }}>
            {appTitle}
          </span>
        </div>

        {/* Right Nav */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', position: 'relative' }}>
          <button 
            title="Help & Documentation"
            onClick={() => setShowHelpModal(true)}
            style={{
              background: 'none',
              border: 'none',
              color: '#94A3B8',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: '4px',
              transition: 'color 0.15s ease'
            }}
            onMouseEnter={(e) => e.currentTarget.style.color = '#FFFFFF'}
            onMouseLeave={(e) => e.currentTarget.style.color = '#94A3B8'}
          >
            <HelpCircle size={16} />
          </button>

          {/* John Doe Pill */}
          <div 
            onClick={() => setShowProfileMenu(prev => !prev)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '7px',
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              padding: '3px 10px 3px 4px',
              borderRadius: '9999px',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              cursor: 'pointer'
            }}
          >
            <div style={{
              width: '21px',
              height: '21px',
              borderRadius: '50%',
              backgroundColor: '#1A73E8',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              fontSize: '10px'
            }}>
              JD
            </div>
            <span style={{ color: '#F1F5F9', fontSize: '11.5px', fontWeight: 500 }}>John Doe</span>
            <ChevronDown size={12} color="#94A3B8" />
          </div>

          {showProfileMenu && (
            <div style={{
              position: 'absolute',
              top: '40px',
              right: '0',
              width: '170px',
              backgroundColor: '#FFFFFF',
              borderRadius: '6px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
              border: '1px solid #E2E8F0',
              padding: '4px 0',
              zIndex: 100
            }}>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #F1F5F9' }}>
                <p style={{ fontSize: '12px', fontWeight: 600, color: '#0F172A', margin: 0 }}>John Doe</p>
                <p style={{ fontSize: '10.5px', color: '#64748B', margin: 0 }}>Lead Planner</p>
              </div>
              <button 
                onClick={() => { alert("Profile Settings"); setShowProfileMenu(false); }}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 12px', background: 'none', border: 'none', fontSize: '11.5px', color: '#334155', cursor: 'pointer', textAlign: 'left' }}
              >
                <User size={13} color="#64748B" /> Profile Details
              </button>
              <button 
                onClick={() => { alert("Signed out."); setShowProfileMenu(false); }}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 12px', background: 'none', border: 'none', fontSize: '11.5px', color: '#DC2626', cursor: 'pointer', textAlign: 'left', borderTop: '1px solid #F1F5F9' }}
              >
                <LogOut size={13} color="#DC2626" /> Sign Out
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main Container */}
      <div style={{ display: 'flex', flex: 1, minHeight: 'calc(100vh - 46px)' }}>
        {/* Left Sidebar */}
        <aside style={{
          width: '210px',
          backgroundColor: '#FFFFFF',
          borderRight: '1px solid #E2E8F0',
          padding: '16px 12px',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0
        }}>
          <nav style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            {sidebarLinks.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
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
                    backgroundColor: isActive ? '#E8F1FD' : 'transparent',
                    color: isActive ? '#1A73E8' : '#5F6D7E',
                    textAlign: 'left'
                  }}
                >
                  <Icon size={15} color={isActive ? '#1A73E8' : '#718096'} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Viewport: Centered and responsive */}
        <main style={{ 
          flex: 1, 
          padding: '36px 48px', 
          overflowY: 'auto',
          display: 'flex', 
          justifyContent: 'center' 
        }}>
          <div style={{ width: '100%', maxWidth: '980px' }}>
            {children}
          </div>
        </main>
      </div>

      {/* Help Modal */}
      {showHelpModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(15, 23, 42, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}>
          <div style={{ backgroundColor: '#FFFFFF', borderRadius: '8px', width: '390px', padding: '20px', boxShadow: '0 12px 30px rgba(0,0,0,0.15)', border: '1px solid #E2E8F0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <h3 style={{ fontSize: '13.5px', fontWeight: 700, color: '#0F172A', margin: 0 }}>Help & Documentation</h3>
              <button onClick={() => setShowHelpModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748B' }}>
                <X size={15} />
              </button>
            </div>
            <p style={{ fontSize: '11.5px', color: '#64748B', lineHeight: '1.6', marginBottom: '16px' }}>
              Upload your Project RFP/BOQ in Step 1 and your domain reference WBS template in Step 2. Once both documents are selected, click Generate Draft WBS.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button 
                onClick={() => setShowHelpModal(false)} 
                style={{ 
                  padding: '6px 14px', 
                  backgroundColor: '#1A73E8', 
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