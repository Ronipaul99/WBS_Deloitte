import { useState, useRef } from 'react';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';
import WbsResultScreen from './views/WbsResultScreen';
import WbsValidationScreen from './views/WbsValidationScreen';
import { resetJobStatusSimulation } from './services/wbsService';
import './App.css';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  
  const [currentScreen, setCurrentScreen] = useState<'create' | 'analyzing' | 'results' | 'validation'>('create');
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
    if (activeJobId && activeJobId.trim().length > 0) {
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

  const renderMissingJobIdError = () => (
    <div className="app-missing-job-card">
      <div className="app-missing-job-icon-box">
        <AlertTriangle size={24} />
      </div>
      <h2 className="app-missing-job-title">
        Missing Job ID
      </h2>
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
    if (activeTab === 'create') {
      if (currentScreen === 'create') {
        return <CreateWbsScreen onGenerateWbs={handleGenerateWbs} />;
      }

      const hasValidJobId = Boolean(activeJobId && activeJobId.trim().length > 0);
      if (!hasValidJobId) {
        return renderMissingJobIdError();
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
      <div className="app-placeholder-box">
        <h2 className="app-placeholder-title">
          {titles[activeTab] || 'Section Under Development'}
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