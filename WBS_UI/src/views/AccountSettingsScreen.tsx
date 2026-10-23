import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Laptop,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Mail,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserRound,
  UsersRound,
  X,
} from 'lucide-react';
import type { CurrentUser, TenantMembership } from '../auth/authContext';
import { PERMISSIONS } from '../auth/permissions';
import type { Permission } from '../auth/permissions';
import { ApiError } from '../services/apiClient';
import {
  getSessions,
  revokeSession,
} from '../services/accountSecurity';
import type { AccountSession } from '../services/accountSecurity';
import TenantMemberAdministration from './TenantMemberAdministration';
import './AccountSettingsScreen.css';

export type AccountSettingsSection = 'profile' | 'security' | 'members';

interface AccountSettingsScreenProps {
  user: CurrentUser;
  activeTenant: TenantMembership;
  activeSection: AccountSettingsSection;
  onSectionChange: (section: AccountSettingsSection) => void;
  onChangePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  onLogoutAll: () => Promise<void>;
  can: (permission: Permission) => boolean;
  onCurrentMembershipChanged: () => Promise<void>;
}

interface ConfirmationDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmationDialog({
  title,
  message,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: ConfirmationDialogProps) {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [busy, onCancel]);

  return (
    <div
      className="account-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        className="account-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-dialog-title"
        aria-describedby="account-dialog-description"
      >
        <div className="account-dialog-heading">
          <span className="account-dialog-icon"><AlertTriangle size={18} /></span>
          <div>
            <h3 id="account-dialog-title">{title}</h3>
            <p id="account-dialog-description">{message}</p>
          </div>
          <button
            type="button"
            className="account-icon-button"
            aria-label="Close confirmation"
            title="Close"
            onClick={onCancel}
            disabled={busy}
          >
            <X size={17} />
          </button>
        </div>
        <div className="account-dialog-actions">
          <button
            ref={cancelButtonRef}
            type="button"
            className="account-secondary-button"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="account-danger-button"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy && <LoaderCircle className="account-spinner" size={16} />}
            {busy ? 'Working...' : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}

function identityLabel(providers: string[]): string {
  const hasLocal = providers.includes('local');
  const hasEnterprise = providers.some((provider) => provider !== 'local');
  if (hasLocal && hasEnterprise) return 'WBS Genie password and enterprise SSO';
  if (hasLocal) return 'WBS Genie password';
  if (hasEnterprise) return 'Enterprise SSO';
  return 'Provider information unavailable';
}

function ProfileSettings({
  user,
  activeTenant,
}: Pick<AccountSettingsScreenProps, 'user' | 'activeTenant'>) {
  return (
    <section className="account-section" aria-labelledby="profile-settings-title">
      <div className="account-section-heading">
        <UserRound size={19} />
        <div>
          <h2 id="profile-settings-title">Profile details</h2>
          <p>Your account identity and current workspace.</p>
        </div>
      </div>

      <dl className="account-detail-list">
        <div>
          <dt><UserRound size={15} /> Display name</dt>
          <dd>{user.display_name}</dd>
        </div>
        <div>
          <dt><Mail size={15} /> Email address</dt>
          <dd>{user.email}</dd>
        </div>
        <div>
          <dt><Building2 size={15} /> Workspace</dt>
          <dd>{activeTenant.name}</dd>
        </div>
        <div>
          <dt><ShieldCheck size={15} /> Workspace role</dt>
          <dd>{activeTenant.role?.toLowerCase() ?? 'member'}</dd>
        </div>
        <div>
          <dt><LockKeyhole size={15} /> Sign-in method</dt>
          <dd>{identityLabel(user.identity_providers)}</dd>
        </div>
      </dl>

      <p className="account-readonly-note">
        Display name and email are managed by your organization.
      </p>
    </section>
  );
}

interface ChangePasswordFormProps {
  onChangePassword: AccountSettingsScreenProps['onChangePassword'];
}

function ChangePasswordForm({ onChangePassword }: ChangePasswordFormProps) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (newPassword.length < 12) {
      setError('New password must contain at least 12 characters.');
      return;
    }
    if (new TextEncoder().encode(newPassword).length > 128) {
      setError('New password must not exceed 128 bytes.');
      return;
    }
    if (newPassword !== confirmation) {
      setError('New passwords do not match.');
      return;
    }
    if (currentPassword === newPassword) {
      setError('New password must be different from the current password.');
      return;
    }

    setSubmitting(true);
    try {
      await onChangePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmation('');
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 400) {
        setError('Current password is incorrect.');
      } else if (reason instanceof ApiError && reason.status === 422) {
        setError(reason.message);
      } else if (!(reason instanceof ApiError && reason.status === 401)) {
        setError('Password could not be changed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="account-password-form" onSubmit={handleSubmit}>
      <div className="account-password-heading">
        <div>
          <h3>Change password</h3>
          <p>Changing your password signs out every active session.</p>
        </div>
        <button
          type="button"
          className="account-icon-button"
          onClick={() => setShowPasswords((value) => !value)}
          aria-label={showPasswords ? 'Hide passwords' : 'Show passwords'}
          title={showPasswords ? 'Hide passwords' : 'Show passwords'}
        >
          {showPasswords ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>

      <div className="account-form-grid">
        <label htmlFor="current-account-password">
          Current password
          <input
            id="current-account-password"
            type={showPasswords ? 'text' : 'password'}
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={submitting}
            required
          />
        </label>
        <label htmlFor="new-account-password">
          New password
          <input
            id="new-account-password"
            type={showPasswords ? 'text' : 'password'}
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={submitting}
            minLength={12}
            required
          />
        </label>
        <label htmlFor="confirm-account-password">
          Confirm new password
          <input
            id="confirm-account-password"
            type={showPasswords ? 'text' : 'password'}
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            disabled={submitting}
            minLength={12}
            required
          />
        </label>
      </div>

      {error && <p className="account-inline-error" role="alert">{error}</p>}
      <button
        type="submit"
        className="account-primary-button"
        disabled={submitting || !currentPassword || !newPassword || !confirmation}
      >
        {submitting && <LoaderCircle className="account-spinner" size={16} />}
        {submitting ? 'Updating...' : 'Update password'}
      </button>
    </form>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) return 'Not used yet';
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return 'Unavailable';
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(timestamp);
}

interface SecuritySettingsProps {
  user: CurrentUser;
  onChangePassword: AccountSettingsScreenProps['onChangePassword'];
  onLogoutAll: AccountSettingsScreenProps['onLogoutAll'];
}

function SecuritySettings({ user, onChangePassword, onLogoutAll }: SecuritySettingsProps) {
  const [sessions, setSessions] = useState<AccountSession[]>([]);
  const [sessionState, setSessionState] = useState<'loading' | 'ready' | 'error'>(
    user.can_manage_sessions ? 'loading' : 'ready',
  );
  const [sessionError, setSessionError] = useState('');
  const [sessionToRevoke, setSessionToRevoke] = useState<AccountSession | null>(null);
  const [confirmLogoutAll, setConfirmLogoutAll] = useState(false);
  const [destructiveBusy, setDestructiveBusy] = useState(false);

  const loadSessions = useCallback(async () => {
    if (!user.can_manage_sessions) return;
    setSessionState('loading');
    setSessionError('');
    try {
      setSessions(await getSessions());
      setSessionState('ready');
    } catch (reason) {
      if (!(reason instanceof ApiError && reason.status === 401)) {
        setSessionError('Active sessions could not be loaded.');
        setSessionState('error');
      }
    }
  }, [user.can_manage_sessions]);

  useEffect(() => {
    if (!user.can_manage_sessions) return;
    let active = true;
    void getSessions()
      .then((items) => {
        if (!active) return;
        setSessions(items);
        setSessionState('ready');
      })
      .catch((reason: unknown) => {
        if (!active || (reason instanceof ApiError && reason.status === 401)) return;
        setSessionError('Active sessions could not be loaded.');
        setSessionState('error');
      });
    return () => {
      active = false;
    };
  }, [user.can_manage_sessions]);

  const sortedSessions = useMemo(() => [...sessions].sort((left, right) => {
    if (left.current !== right.current) return left.current ? -1 : 1;
    const leftTime = Date.parse(left.last_used_at ?? left.created_at);
    const rightTime = Date.parse(right.last_used_at ?? right.created_at);
    return rightTime - leftTime;
  }), [sessions]);

  const revokeSelectedSession = async () => {
    if (!sessionToRevoke || sessionToRevoke.current) return;
    setDestructiveBusy(true);
    setSessionError('');
    try {
      await revokeSession(sessionToRevoke.id);
      setSessions((current) => current.filter((item) => item.id !== sessionToRevoke.id));
      setSessionToRevoke(null);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) {
        setSessionToRevoke(null);
        await loadSessions();
      } else if (!(reason instanceof ApiError && reason.status === 401)) {
        setSessionError('The session could not be revoked. Please retry.');
        setSessionToRevoke(null);
      }
    } finally {
      setDestructiveBusy(false);
    }
  };

  const signOutEverywhere = async () => {
    setDestructiveBusy(true);
    try {
      await onLogoutAll();
    } catch (reason) {
      if (!(reason instanceof ApiError && reason.status === 401)) {
        setSessionError('Could not sign out every session. Please retry.');
        setConfirmLogoutAll(false);
      }
    } finally {
      setDestructiveBusy(false);
    }
  };

  return (
    <section className="account-section" aria-labelledby="security-settings-title">
      <div className="account-section-heading">
        <ShieldCheck size={19} />
        <div>
          <h2 id="security-settings-title">Security</h2>
          <p>Password and session controls for this account.</p>
        </div>
      </div>

      <div className="account-security-block">
        {user.can_change_password ? (
          <ChangePasswordForm onChangePassword={onChangePassword} />
        ) : (
          <div className="account-managed-message">
            <KeyRound size={19} />
            <div>
              <h3>Password managed by enterprise SSO</h3>
              <p>Use your organization identity provider to update your password.</p>
            </div>
          </div>
        )}
      </div>

      <div className="account-security-block account-session-block">
        <div className="account-block-heading">
          <div>
            <h3>Active sessions</h3>
            <p>Review signed-in sessions and revoke access you no longer recognize.</p>
          </div>
          {user.can_manage_sessions && sessionState === 'ready' && (
            <button
              type="button"
              className="account-icon-button"
              onClick={() => void loadSessions()}
              aria-label="Refresh active sessions"
              title="Refresh active sessions"
            >
              <RefreshCw size={17} />
            </button>
          )}
        </div>

        {!user.can_manage_sessions && (
          <div className="account-managed-message account-managed-message--sessions">
            <Laptop size={19} />
            <div>
              <h3>Sessions managed by enterprise SSO</h3>
              <p>Review or end sessions through your organization identity provider.</p>
            </div>
          </div>
        )}

        {user.can_manage_sessions && sessionState === 'loading' && (
          <div className="account-session-loading" role="status">
            <LoaderCircle className="account-spinner" size={18} />
            Loading active sessions...
          </div>
        )}

        {user.can_manage_sessions && sessionState === 'error' && (
          <div className="account-session-error" role="alert">
            <span>{sessionError}</span>
            <button type="button" onClick={() => void loadSessions()}>
              Retry
            </button>
          </div>
        )}

        {user.can_manage_sessions && sessionState === 'ready' && (
          <>
            {sortedSessions.length === 0 ? (
              <div className="account-session-empty">No active sessions were returned.</div>
            ) : (
              <ul className="account-session-list">
                {sortedSessions.map((session) => (
                  <li key={session.id}>
                    <span className="account-session-icon"><Laptop size={18} /></span>
                    <div className="account-session-copy">
                      <div>
                        <strong>{session.current ? 'Current session' : 'Other active session'}</strong>
                        {session.current && <span className="account-current-badge">This device</span>}
                      </div>
                      <p>Last active: {formatTimestamp(session.last_used_at ?? session.created_at)}</p>
                      <small>Expires: {formatTimestamp(session.expires_at)}</small>
                    </div>
                    {!session.current && (
                      <button
                        type="button"
                        className="account-icon-button account-revoke-button"
                        onClick={() => setSessionToRevoke(session)}
                        aria-label="Revoke other active session"
                        title="Revoke session"
                      >
                        <Trash2 size={17} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {sortedSessions.length > 0 && !sortedSessions.some((session) => !session.current) && (
              <p className="account-other-empty">
                <CheckCircle2 size={15} /> No other active sessions.
              </p>
            )}
          </>
        )}

        {sessionError && sessionState === 'ready' && (
          <p className="account-inline-error" role="alert">{sessionError}</p>
        )}
      </div>

      {user.can_manage_sessions && (
        <div className="account-security-block account-danger-zone">
          <div>
            <h3>Sign out everywhere</h3>
            <p>End every session, including this one, and return to sign in.</p>
          </div>
          <button
            type="button"
            className="account-danger-outline-button"
            onClick={() => setConfirmLogoutAll(true)}
          >
            <LogOut size={16} /> Sign out everywhere
          </button>
        </div>
      )}

      {sessionToRevoke && (
        <ConfirmationDialog
          title="Revoke this session?"
          message="That session will lose access and must sign in again."
          confirmLabel="Revoke session"
          busy={destructiveBusy}
          onCancel={() => setSessionToRevoke(null)}
          onConfirm={() => void revokeSelectedSession()}
        />
      )}

      {confirmLogoutAll && (
        <ConfirmationDialog
          title="Sign out everywhere?"
          message="Every active session will be revoked, including this one."
          confirmLabel="Sign out everywhere"
          busy={destructiveBusy}
          onCancel={() => setConfirmLogoutAll(false)}
          onConfirm={() => void signOutEverywhere()}
        />
      )}
    </section>
  );
}

export default function AccountSettingsScreen({
  user,
  activeTenant,
  activeSection,
  onSectionChange,
  onChangePassword,
  onLogoutAll,
  can,
  onCurrentMembershipChanged,
}: AccountSettingsScreenProps) {
  const isWorkspaceAdministration = activeSection === 'members';
  return (
    <div className="account-settings-page">
      <header className="account-page-heading">
        <p>{isWorkspaceAdministration ? 'Workspace administration' : 'Personal account'}</p>
        <h1>{isWorkspaceAdministration ? 'Workspace settings' : 'Account settings'}</h1>
        <span>
          {isWorkspaceAdministration
            ? 'Manage membership and workspace access.'
            : 'Review your profile, password, and active sessions.'}
        </span>
      </header>

      <div className="account-settings-frame">
        <div className="account-tabs" role="tablist" aria-label="Account settings">
          <button
            type="button"
            role="tab"
            aria-selected={activeSection === 'profile'}
            aria-controls="account-settings-panel"
            onClick={() => onSectionChange('profile')}
          >
            <UserRound size={16} /> Profile
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeSection === 'security'}
            aria-controls="account-settings-panel"
            onClick={() => onSectionChange('security')}
          >
            <ShieldCheck size={16} /> Security
          </button>
          {can(PERMISSIONS.MEMBER_READ) && (
            <button
              type="button"
              role="tab"
              aria-selected={activeSection === 'members'}
              aria-controls="account-settings-panel"
              onClick={() => onSectionChange('members')}
            >
              <UsersRound size={16} /> Members
            </button>
          )}
        </div>

        <div id="account-settings-panel" role="tabpanel">
          {activeSection === 'profile' ? (
            <ProfileSettings user={user} activeTenant={activeTenant} />
          ) : activeSection === 'security' ? (
            <SecuritySettings
              user={user}
              onChangePassword={onChangePassword}
              onLogoutAll={onLogoutAll}
            />
          ) : (
            <TenantMemberAdministration
              key={activeTenant.id}
              tenantId={activeTenant.id}
              tenantName={activeTenant.name}
              currentUserId={user.id}
              canInvite={can(PERMISSIONS.MEMBER_INVITE)}
              canUpdate={can(PERMISSIONS.MEMBER_UPDATE)}
              canRemove={can(PERMISSIONS.MEMBER_REMOVE)}
              onCurrentMembershipChanged={onCurrentMembershipChanged}
            />
          )}
        </div>
      </div>
    </div>
  );
}
