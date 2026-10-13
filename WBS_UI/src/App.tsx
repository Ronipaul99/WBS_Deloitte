import { useState, useRef } from 'react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';
import WbsResultScreen from './views/WbsResultScreen';
import WbsValidationScreen from './views/WbsValidationScreen';
import { resetJobStatusSimulation } from './services/wbsService';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  
  const [currentScreen, setCurrentScreen] = useState<'create' | 'analyzing' | 'results' | 'validation'>('validation');
  const [activeJobId, setActiveJobId] = useState<string>('');
  
  const [targetResultTab, setTargetResultTab] = useState<'structure' | 'coverage' | 'insights' | 'unmapped'>('structure');

  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPendingNavigation = () => {
    if (advanceTimerRef.current) {
      clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }
  };

  const handleGenerateWbs = (newJobId: string) => {
    clearPendingNavigation();
    setActiveJobId(newJobId);
    resetJobStatusSimulation(newJobId);
    setTargetResultTab('structure');
    setCurrentScreen('analyzing');
  };

  const handleAnalysisComplete = () => {
    clearPendingNavigation();
    advanceTimerRef.current = setTimeout(() => {
      setTargetResultTab('structure');
      setCurrentScreen('results');
      advanceTimerRef.current = null;
    }, 800);
  };

  const handleCancelAnalysis = () => {
    clearPendingNavigation();
    setCurrentScreen('create');
  };

  const handleRegenerate = () => {
    clearPendingNavigation();
    if (activeJobId) {
      resetJobStatusSimulation(activeJobId);
      setCurrentScreen('analyzing');
    } else {
      setCurrentScreen('create');
    }
  };

  const handleNavigateToValidation = () => {
    clearPendingNavigation();
    setCurrentScreen('validation');
  };

  const handleBackToResults = () => {
    clearPendingNavigation();
    setTargetResultTab('structure');
    setCurrentScreen('results');
  };

  const handleCreateNewWbs = () => {
    clearPendingNavigation();
    resetJobStatusSimulation();
    setActiveJobId('');
    setCurrentScreen('create');
  };

  const handleViewAllUnmapped = () => {
    clearPendingNavigation();
    setTargetResultTab('unmapped');
    setCurrentScreen('results');
  };

  const handleNavClick = (tab: string) => {
    clearPendingNavigation();
    setActiveTab(tab);
    if (tab === 'create') {
      setCurrentScreen('create');
    }
  };

  const renderContent = () => {
    if (activeTab === 'create') {
      if (currentScreen === 'create') {
        return <CreateWbsScreen onGenerateWbs={handleGenerateWbs} />;
      }

      if (currentScreen === 'analyzing') {
        return (
          <AnalyzingProjectScreen
            jobId={activeJobId}
            onAnalysisComplete={handleAnalysisComplete}
            onCancel={handleCancelAnalysis}
          />
        );
      }

      if (currentScreen === 'validation') {
        return (
          <WbsValidationScreen
            jobId={activeJobId}
            onBackToResults={handleBackToResults}
            onViewUnmapped={handleViewAllUnmapped}
            onCreateNew={handleCreateNewWbs}
          />
        );
      }

      return (
        <WbsResultScreen
          jobId={activeJobId}
          initialTab={targetResultTab}
          onRegenerate={handleRegenerate}
          onNavigateToValidation={handleNavigateToValidation}
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