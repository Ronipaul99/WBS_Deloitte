import { useState } from 'react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import { Loader2, ArrowRight } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  const [activeJobId, setActiveJobId] = useState<string>('');

  const handleGenerateWbs = (newJobId: string) => {
    setActiveJobId(newJobId);
  };

  const handleNavClick = (tab: string) => {
    setActiveTab(tab);
  };

  const renderContent = () => {
    if (activeTab === 'create') {
      if (activeJobId) {
        return (
          <div
            style={{
              padding: '48px 32px',
              textAlign: 'center',
              backgroundColor: '#FFFFFF',
              borderRadius: '12px',
              border: '1px solid #E2E8F0',
              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)',
              maxWidth: '600px',
              margin: '20px auto',
            }}
          >
            <div
              style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                backgroundColor: '#EFF6FF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px auto',
              }}
            >
              <Loader2 size={24} color="#2563EB" style={{ animation: 'spin 1s linear infinite' }} />
            </div>

            <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', margin: '0 0 8px 0' }}>
              Project Intake Accepted & Verified
            </h2>

            <p style={{ fontSize: '13px', color: '#64748B', lineHeight: '1.6', margin: '0 0 16px 0' }}>
              Both scope and baseline template documents passed validation gates. Analysis pipeline initialized with ID:
            </p>

            <div
              style={{
                display: 'inline-block',
                padding: '6px 14px',
                backgroundColor: '#F1F5F9',
                borderRadius: '6px',
                fontFamily: 'monospace',
                fontSize: '13px',
                fontWeight: 600,
                color: '#1E293B',
                marginBottom: '24px',
              }}
            >
              {activeJobId}
            </div>

            <p style={{ fontSize: '12px', color: '#94A3B8', margin: '0 0 24px 0' }}>
              (Screen 2 Pipeline Visualizer connects here on <code>feature/screen-2-analysis</code>)
            </p>

            <button
              type="button"
              onClick={() => setActiveJobId('')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 18px',
                backgroundColor: '#F8FAFC',
                border: '1px solid #CBD5E1',
                color: '#334155',
                borderRadius: '6px',
                fontSize: '13px',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              <span>Upload New Documents</span>
              <ArrowRight size={14} />
            </button>
          </div>
        );
      }

      return <CreateWbsScreen onGenerateWbs={handleGenerateWbs} />;
    }

    return (
      <div style={{ padding: '48px', textAlign: 'center', color: '#64748B' }}>
        <h2 style={{ fontSize: '20px', color: '#0F172A', marginBottom: '8px' }}>
          Section Under Development
        </h2>
        <p style={{ fontSize: '14px', margin: 0 }}>
          This section is currently being configured and will be available soon.
        </p>
      </div>
    );
  };

  return (
    <AppLayout 
      activeTab={activeTab} 
      onNavClick={handleNavClick}
      currentUser={{
        name: 'John Doe',
        role: 'Lead Planner',
        initials: 'JD'
      }}
    >
      {renderContent()}
    </AppLayout>
  );
}