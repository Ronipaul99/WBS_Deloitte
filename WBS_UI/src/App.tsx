import { useState } from 'react';
import AppLayout from './components/AppLayout';
import WbsValidationScreen from './views/WbsValidationScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');

  const handleNavClick = (tab: string) => {
    setActiveTab(tab);
  };

  const handleBackToResults = () => {
    console.log('Back to WBS Structure clicked');
  };

  const handleViewUnmapped = () => {
    console.log('View All Unmapped clicked');
  };

  const handleCreateNew = () => {
    console.log('Create New WBS clicked');
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
      <WbsValidationScreen
        jobId="job_wbs_89412"
        onBackToResults={handleBackToResults}
        onViewUnmapped={handleViewUnmapped}
        onCreateNew={handleCreateNew}
      />
    </AppLayout>
  );
}