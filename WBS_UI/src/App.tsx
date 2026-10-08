import { useState } from 'react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';
import WbsResultScreen from './views/WbsResultScreen';
import WbsValidationScreen from './views/WbsValidationScreen';
import { resetJobStatusSimulation } from './services/wbsService';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  const [currentScreen, setCurrentScreen] = useState<'create' | 'analyzing' | 'results' | 'validation'>('create');
  const [activeJobId, setActiveJobId] = useState<string>('job_wbs_89412');
  
  // Controls which sub-tab opens when switching to Screen 3
  const [targetResultTab, setTargetResultTab] = useState<'structure' | 'coverage' | 'insights' | 'unmapped'>('structure');

  const handleGenerateWbs = () => {
    resetJobStatusSimulation();
    setActiveJobId('job_wbs_89412');
    setTargetResultTab('structure');
    setCurrentScreen('analyzing');
  };

  const handleAnalysisComplete = () => {
    setTimeout(() => {
      setTargetResultTab('structure');
      setCurrentScreen('results');
    }, 1000);
  };

  const handleRegenerate = () => {
    resetJobStatusSimulation();
    setCurrentScreen('analyzing');
  };

  const handleNavClick = (tab: string) => {
    setActiveTab(tab);
    if (tab === 'create' && currentScreen === 'results') {
      setCurrentScreen('create');
    }
  };

  // Navigates directly from Screen 4 to the Unmapped Requirements tab in Screen 3
  const handleViewAllUnmapped = () => {
    setTargetResultTab('unmapped');
    setCurrentScreen('results');
  };

  const renderContent = () => {
    if (activeTab === 'create') {
      if (currentScreen === 'create') {
        return <CreateWbsScreen onGenerateWbs={handleGenerateWbs} />;
      }
      if (currentScreen === 'analyzing') {
        return <AnalyzingProjectScreen jobId={activeJobId} onAnalysisComplete={handleAnalysisComplete} />;
      }
      if (currentScreen === 'validation') {
        return (
          <WbsValidationScreen
            jobId={activeJobId}
            onBackToResults={() => {
              setTargetResultTab('structure');
              setCurrentScreen('results');
            }}
            onViewUnmapped={handleViewAllUnmapped}
          />
        );
      }
      return (
        <WbsResultScreen
          jobId={activeJobId}
          initialTab={targetResultTab}
          onRegenerate={handleRegenerate}
          onNavigateToValidation={() => setCurrentScreen('validation')}
        />
      );
    }

    const titles: Record<string, string> = {
      projects: 'My Projects',
      templates: 'Templates',
      exports: 'Exports',
      settings: 'Settings',
    };

    return (
      <div style={{ padding: '48px', textAlign: 'center', color: '#64748B' }}>
        <h2 style={{ fontSize: '20px', color: '#0F172A', marginBottom: '8px' }}>
          {titles[activeTab] || 'Section Under Development'}
        </h2>
        <p style={{ fontSize: '14px', margin: 0 }}>
          This section is currently being configured and will be available soon.
        </p>
      </div>
    );
  };

  return (
    <AppLayout activeTab={activeTab} onNavClick={handleNavClick}>
      {renderContent()}
    </AppLayout>
  );
}