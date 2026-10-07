import './App.css';
import React, { useState } from 'react';
import AppLayout from './components/AppLayout';
import CreateWbsScreen from './views/CreateWbsScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState('create');

  const handleGenerate = (projectDoc, templateDoc) => {
    alert(`Draft WBS Generation initiated for:\n- Project: ${projectDoc.name}\n- Template: ${templateDoc.name}`);
  };

  const handleNavClick = (tabId) => {
    setActiveTab(tabId);
  };

  return (
    <AppLayout activeTab={activeTab} onNavClick={handleNavClick}>
      {activeTab === 'create' && (
        <CreateWbsScreen onGenerateWbs={handleGenerate} />
      )}

      {activeTab === 'projects' && (
        <div style={{ maxWidth: '800px', backgroundColor: '#FFFFFF', padding: '32px', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', marginBottom: '8px' }}>My Projects</h2>
          <p style={{ fontSize: '13px', color: '#64748B' }}>View all ongoing and completed WBS project schedules.</p>
        </div>
      )}

      {activeTab === 'templates' && (
        <div style={{ maxWidth: '800px', backgroundColor: '#FFFFFF', padding: '32px', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', marginBottom: '8px' }}>WBS Templates Library</h2>
          <p style={{ fontSize: '13px', color: '#64748B' }}>Domain templates for Primavera P6 EPC construction, solar, and civil works.</p>
        </div>
      )}

      {activeTab === 'exports' && (
        <div style={{ maxWidth: '800px', backgroundColor: '#FFFFFF', padding: '32px', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', marginBottom: '8px' }}>Export History</h2>
          <p style={{ fontSize: '13px', color: '#64748B' }}>Download previously generated P6 XML, XER, and Excel files.</p>
        </div>
      )}

      {activeTab === 'settings' && (
        <div style={{ maxWidth: '800px', backgroundColor: '#FFFFFF', padding: '32px', borderRadius: '10px', border: '1px solid #E2E8F0' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', marginBottom: '8px' }}>Settings</h2>
          <p style={{ fontSize: '13px', color: '#64748B' }}>Manage your OCI credentials, Primavera P6 endpoints, and LLM preferences.</p>
        </div>
      )}
    </AppLayout>
  );
}