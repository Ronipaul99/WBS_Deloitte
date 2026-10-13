import { useState, useRef, useEffect } from 'react';
import { AlertTriangle, ArrowLeft } from 'lucide-react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';
import ProcessingProjectDocumentScreen from './views/ProcessingProjectDocumentScreen';
import ReviewProjectSummaryScreen from './views/ReviewProjectSummaryScreen';
import AnalyzingProjectScreen from './views/AnalyzingProjectScreen';
import WbsResultScreen from './views/WbsResultScreen';
import WbsValidationScreen from './views/WbsValidationScreen';
import './App.css';

export type ScreenType =
  | 'create'
  | 'doc_processing'
  | 'doc_summary'
  | 'analyzing'
  | 'results'
  | 'validation';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');
  const [currentScreen, setCurrentScreen] = useState<ScreenType>('create');
  const [activeJobId, setActiveJobId] = useState<string>('');
  const [targetResultTab, setTargetResultTab] = useState<
    'structure' | 'coverage' | 'insights' | 'unmapped'
  >('structure');

  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPendingNavigation = () => {
    if (advanceTimerRef.current) {
      clearTimeout(advanceTimerRef.current);
      advanceTimerRef.current = null;
    }
  };

  // Ensure timer teardown if App unmounts
  useEffect(() => {
    return () => {
      clearPendingNavigation();
    };
  }, []);

  // 1. Step 1 (Upload) -> Step 2 (Document Processing Stepper)
  const handleGenerateWbs = (newJobId: string) => {
    clearPendingNavigation();
    setActiveJobId(newJobId);
    setCurrentScreen('doc_processing');
  };

  // 2. Step 2 (Document Processing) -> Step 3 (Review Summary)
  const handleDocProcessingComplete = () => {
    clearPendingNavigation();
    setCurrentScreen('doc_summary');
  };

  // 3. Step 3 (Review Summary) -> Step 4 (Decomposition Pipeline Analysis)
  const handleProceedToAnalyze = () => {
    clearPendingNavigation();
    setCurrentScreen('analyzing');
  };

  // 4. Step 4 (Pipeline Analysis Complete) -> Step 5 (WBS Result Screen)
  const handleAnalysisComplete = () => {
    clearPendingNavigation();
    advanceTimerRef.current = setTimeout(() => {
      setTargetResultTab('structure');
      setCurrentScreen('results');
      advanceTimerRef.current = null;
    }, 600);
  };

  // Navigation handlers
  const handleBackToCreate = () => {
    clearPendingNavigation();
    setCurrentScreen('create');
  };

  const handleRegenerate = () => {
    clearPendingNavigation();
    if (activeJobId && activeJobId.trim().length > 0) {
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
      setActiveJobId('');
      setCurrentScreen('create');
    }
  };

  const renderMissingJobIdError = () => (
    <div className="app-missing-job-card">
      <div className="app-missing-job-icon-box">
        <AlertTriangle size={24} />
      </div>
      <h2 className="app-missing-job-title">Missing Job ID</h2>
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

      if (currentScreen === 'doc_processing') {
        return (
          <ProcessingProjectDocumentScreen
            jobId={activeJobId}
            onProcessingComplete={handleDocProcessingComplete}
            onBack={handleBackToCreate}
            onCancel={handleBackToCreate}
          />
        );
      }

      if (currentScreen === 'doc_summary') {
        return (
          <ReviewProjectSummaryScreen
            jobId={activeJobId}
            onProceedToAnalyze={handleProceedToAnalyze}
            onDiscard={handleBackToCreate}
          />
        );
      }

      if (currentScreen === 'analyzing') {
        return (
          <AnalyzingProjectScreen
            jobId={activeJobId}
            onAnalysisComplete={handleAnalysisComplete}
            onCancel={handleBackToCreate}
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

    const placeholderTitles: Record<string, string> = {
      projects: 'My Projects',
      templates: 'Templates',
      exports: 'Exports',
      settings: 'Settings',
    };

    return (
      <div className="app-placeholder-box">
        <h2 className="app-placeholder-title">
          {placeholderTitles[activeTab] || 'Section Under Development'}
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
        initials: 'JD',
      }}
    >
      {renderContent()}
    </AppLayout>
  );
}