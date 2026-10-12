import { useState } from 'react';
import AppLayout from './components/AppLayout';
import WbsResultScreen from './views/WbsResultScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('create');

  const handleNavClick = (tab: string) => {
    setActiveTab(tab);
  };

  const handleRegenerate = () => {
    console.log('Regenerate WBS clicked');
  };

  const handleNavigateToValidation = () => {
    console.log('Navigate to Validation Screen clicked');
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
      <WbsResultScreen
        jobId="job_wbs_89412"
        initialTab="structure"
        onRegenerate={handleRegenerate}
        onNavigateToValidation={handleNavigateToValidation}
      />
    </AppLayout>
  );
}