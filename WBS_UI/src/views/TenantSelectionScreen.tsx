import { Building2, ChevronRight, Sparkles } from 'lucide-react';
import type { TenantMembership } from '../auth/authContext';
import './TenantSelectionScreen.css';

interface TenantSelectionScreenProps {
  tenants: TenantMembership[];
  onSelect: (tenant: TenantMembership) => void;
  onSignOut: () => Promise<void>;
}

export default function TenantSelectionScreen({
  tenants,
  onSelect,
  onSignOut,
}: TenantSelectionScreenProps) {
  return (
    <main className="tenant-shell">
      <header className="tenant-header">
        <div className="tenant-brand"><Sparkles size={18} /> WBS Genie</div>
        <button type="button" onClick={() => void onSignOut()}>Sign out</button>
      </header>
      <section className="tenant-content">
        <h1>{tenants.length ? 'Choose a workspace' : 'No workspace access'}</h1>
        <p>
          {tenants.length
            ? 'Select the organization you want to work in.'
            : 'Ask an administrator to add your account to a workspace.'}
        </p>
        <div className="tenant-list">
          {tenants.map((tenant) => (
            <button key={tenant.id} type="button" onClick={() => onSelect(tenant)}>
              <span className="tenant-icon"><Building2 size={19} /></span>
              <span className="tenant-copy">
                <strong>{tenant.name}</strong>
                <small>{tenant.role?.toLowerCase() ?? 'member'}</small>
              </span>
              <ChevronRight size={18} />
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}
