import { useState } from 'react'
import AppLayout from './components/AppLayout'
import CreateWbsScreen from './views/CreateWbsScreen'

export default function App() {
  const [activeTab, setActiveTab] = useState('create')

  const handleGenerateWbs = () => {
    alert('Generating WBS from uploaded documents...')
  }

  return (
    <AppLayout activeTab={activeTab} onNavClick={(tab: string) => setActiveTab(tab)}>
      {activeTab === 'create' ? (
        <CreateWbsScreen onGenerateWbs={handleGenerateWbs} />
      ) : (
        <div style={{ padding: '32px', textAlign: 'center', color: '#64748B' }}>
          <h3>Section under development</h3>
          <p>This tab will be available in future releases.</p>
        </div>
      )}
    </AppLayout>
  )
}