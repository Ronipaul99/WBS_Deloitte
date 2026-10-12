import { useState } from 'react';
import AppLayout from './components/AppLayout';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  const [activeJobId, setActiveJobId] = useState<string>('job_wbs_89412');

  const handleNavClick = (tab: string) => {
    setActiveTab(tab);
  };

  const handleAnalysisComplete = () => {
    console.log('Analysis pipeline complete for job:', activeJobId);
  };

  const handleCancelAnalysis = () => {
    setActiveJobId('');
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
      {activeJobId ? (
        <AnalyzingProjectScreen
          jobId={activeJobId}
          onAnalysisComplete={handleAnalysisComplete}
          onCancel={handleCancelAnalysis}
        />
      ) : (
        <div style={{ padding: '48px', textAlign: 'center', backgroundColor: '#FFFFFF', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
          <h2 style={{ fontSize: '18px', color: '#0F172A', marginBottom: '8px' }}>
            Analysis Cancelled
          </h2>
          <p style={{ fontSize: '13px', color: '#64748B', marginBottom: '20px' }}>
            The active job was cancelled.
          </p>
          <button
            type="button"
            onClick={() => setActiveJobId('job_wbs_89412')}
            style={{
              padding: '8px 16px',
              backgroundColor: '#2563EB',
              color: '#FFFFFF',
              border: 'none',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            Restart Simulation
          </button>
        </div>
      )}
    </AppLayout>
  );
}