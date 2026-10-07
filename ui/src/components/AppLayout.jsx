import React, { useState } from 'react';
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

export default function AppLayout({ children, activeTab = 'create', onNavClick }) {
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
            <svg 
              width="102" 
              height="14" 
              viewBox="0 0 1000 134" 
              fill="#FFFFFF" 
              xmlns="http://www.w3.org/2000/svg"
              style={{ display: 'block', shapeRendering: 'geometricPrecision' }}
            >
              {/* O */}
              <path d="M117.8 0C52.7 0 0 30 0 67s52.7 67 117.8 67 117.8-30 117.8-67S182.9 0 117.8 0zm0 106.8c-39.7 0-71.9-17.8-71.9-39.8s32.2-39.8 71.9-39.8 71.9 17.8 71.9 39.8-32.2 39.8-71.9 39.8z"/>
              {/* R */}
              <path d="M256.3 5v124h38.6V83.6h32.8l37 45.4h44.8l-43.5-51.8c23.9-5.6 39-21.1 39-39.2 0-22.6-21.2-33-53.2-33H256.3zm38.6 26h23.8c12.8 0 21.3 3.7 21.3 13.3 0 9.1-8.5 13.5-21.3 13.5h-23.8V31z"/>
              {/* A */}
              <path d="M500.5 5L441 129h40.2l11-23.8h57.1l11 23.8h40.2L541 5h-40.5zm4.7 33.8l19.3 41.3h-38.5l19.2-41.3z"/>
              {/* C */}
              <path d="M703.1 0c-59 0-106.8 30-106.8 67s47.8 67 106.8 67c43.5 0 80.7-16.2 96.4-40.5l-33.6-14.7c-11.1 15.3-35.7 26.6-62.8 26.6-37.6 0-68-17.8-68-39.8s30.4-39.8 68-39.8c27.1 0 51.7 11.3 62.8 26.6l33.6-14.7C783.8 16.2 746.6 0 703.1 0z"/>
              {/* L */}
              <path d="M822.4 5v124h84.5V99.7H861V5h-38.6z"/>
              {/* E */}
              <path d="M915.5 5v124H1000V99.7h-45.9V74.4h39.8V49.6h-39.8V29.8H1000V5h-84.5z"/>
            </svg>
          </div>

          {/* Thin vertical divider */}
          <span style={{
            display: 'inline-block',
            width: '1px',
            height: '14px',
            backgroundColor: 'rgba(255, 255, 255, 0.28)',
            margin: '0 16px'
          }} />

          {/* Clean title without subpixel fringing */}
          <span style={{ 
            fontWeight: 600, 
            fontSize: '13px', 
            color: '#FFFFFF', 
            letterSpacing: '-0.1px',
            lineHeight: 1,
            userSelect: 'none'
          }}>
            AI WBS Builder
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