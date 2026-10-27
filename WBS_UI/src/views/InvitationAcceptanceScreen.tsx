import { FormEvent, useState } from 'react';
import {
  ArrowLeft,
  Building2,
  CheckCircle2,
  LoaderCircle,
  LockKeyhole,
  Mail,
  Sparkles,
  UserRound,
} from 'lucide-react';
import type { AuthStatus } from '../auth/authContext';
import { ApiError } from '../services/apiClient';
import type { InvitationAcceptanceResponse } from '../services/memberAdministration';
import './InvitationAcceptanceScreen.css';

interface InvitationAcceptanceScreenProps {
  token: string;
  authStatus: AuthStatus;
  authenticatedEmail?: string;
  onAcceptAuthenticated: (token: string) => Promise<void>;
  onSignInAndAccept: (email: string, password: string, token: string) => Promise<void>;
  onCreateAccount: (
    displayName: string,
    password: string,
    token: string,
  ) => Promise<InvitationAcceptanceResponse>;
  onBackToLogin: () => void | Promise<void>;
  localAuthEnabled?: boolean;
  onEnterpriseLogin?: () => void;
  enterpriseLabel?: string;
}

type AcceptanceMode = 'new' | 'existing';

function safeError(reason: unknown): string {
  if (reason instanceof ApiError && reason.status === 400) {
    return 'This invitation is unavailable or has expired.';
  }
  if (reason instanceof ApiError && reason.status === 401) {
    return 'This email already has an account. Sign in to continue.';
  }
  if (reason instanceof ApiError && reason.status === 422) return reason.message;
  return 'The invitation could not be accepted. Please try again.';
}

export default function InvitationAcceptanceScreen({
  token,
  authStatus,
  authenticatedEmail,
  onAcceptAuthenticated,
  onSignInAndAccept,
  onCreateAccount,
  onBackToLogin,
  localAuthEnabled = true,
  onEnterpriseLogin,
  enterpriseLabel = 'Enterprise SSO',
}: InvitationAcceptanceScreenProps) {
  const [mode, setMode] = useState<AcceptanceMode>('new');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [accepted, setAccepted] = useState<InvitationAcceptanceResponse | null>(null);

  const validatePassword = (): boolean => {
    if (password.length < 12) {
      setError('Password must contain at least 12 characters.');
      return false;
    }
    if (new TextEncoder().encode(password).length > 128) {
      setError('Password must not exceed 128 bytes.');
      return false;
    }
    if (mode === 'new' && password !== confirmation) {
      setError('Passwords do not match.');
      return false;
    }
    return true;
  };

  const submitPublicFlow = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (!validatePassword()) return;
    setPending(true);
    try {
      if (mode === 'existing') {
        await onSignInAndAccept(email.trim(), password, token);
      } else {
        setAccepted(await onCreateAccount(displayName.trim(), password, token));
        setDisplayName('');
        setPassword('');
        setConfirmation('');
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401 && mode === 'new') {
        setMode('existing');
      }
      setError(safeError(reason));
    } finally {
      setPending(false);
    }
  };

  const acceptForAuthenticatedUser = async () => {
    setPending(true);
    setError('');
    try {
      await onAcceptAuthenticated(token);
    } catch (reason) {
      setError(safeError(reason));
      setPending(false);
    }
  };

  return (
    <main className="invite-acceptance-shell">
      <header className="invite-acceptance-header">
        <div><Sparkles size={18} /> WBS Genie</div>
        <button type="button" onClick={() => void onBackToLogin()}>
          <ArrowLeft size={16} />
          {authStatus === 'authenticated' ? 'Use another account' : 'Sign in'}
        </button>
      </header>

      <section className="invite-acceptance-content">
        <div className="invite-acceptance-mark"><Building2 size={24} /></div>
        <p className="invite-acceptance-eyebrow">Workspace invitation</p>

        {!token ? (
          <div className="invite-acceptance-state" role="alert">
            <h1>Invitation unavailable</h1>
            <p>The invitation link is invalid or no longer available.</p>
            <button type="button" onClick={() => void onBackToLogin()}>Return to sign in</button>
          </div>
        ) : authStatus === 'loading' ? (
          <div className="invite-acceptance-state" role="status">
            <LoaderCircle className="invite-acceptance-spinner" size={22} />
            <h1>Checking your account</h1>
          </div>
        ) : accepted ? (
          <div className="invite-acceptance-state" role="status">
            <CheckCircle2 className="invite-acceptance-success" size={30} />
            <h1>Welcome to {accepted.tenant_name}</h1>
            <p>Your account is ready with the {accepted.role.toLowerCase()} role.</p>
            <button type="button" onClick={() => void onBackToLogin()}>Continue to sign in</button>
          </div>
        ) : authStatus === 'authenticated' && authenticatedEmail ? (
          <div className="invite-acceptance-state">
            <h1>Join the workspace</h1>
            <p>The invitation will be matched to {authenticatedEmail}.</p>
            {error && <p className="invite-acceptance-error" role="alert">{error}</p>}
            <button type="button" disabled={pending} onClick={() => void acceptForAuthenticatedUser()}>
              {pending && <LoaderCircle className="invite-acceptance-spinner" size={16} />}
              {pending ? 'Accepting...' : 'Accept invitation'}
            </button>
          </div>
        ) : (
          <>
            <h1>Join your workspace</h1>
            <p className="invite-acceptance-intro">
              Continue with the work identity that received this invitation.
            </p>
            {onEnterpriseLogin && (
              <button
                type="button"
                className="invite-acceptance-enterprise"
                disabled={pending}
                onClick={() => {
                  setPending(true);
                  onEnterpriseLogin();
                }}
              >
                <Building2 size={16} />
                Continue with {enterpriseLabel}
              </button>
            )}
            {localAuthEnabled && <div className="invite-acceptance-modes" role="tablist" aria-label="Account choice">
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'new'}
                onClick={() => { setMode('new'); setError(''); }}
              >
                New account
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'existing'}
                onClick={() => { setMode('existing'); setError(''); }}
              >
                Existing account
              </button>
            </div>}

            {localAuthEnabled && <form className="invite-acceptance-form" onSubmit={submitPublicFlow}>
              {mode === 'new' ? (
                <label htmlFor="invitation-display-name">
                  Display name
                  <span><UserRound size={16} /><input id="invitation-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" disabled={pending} required /></span>
                </label>
              ) : (
                <label htmlFor="invitation-email">
                  Email address
                  <span><Mail size={16} /><input id="invitation-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" disabled={pending} required /></span>
                </label>
              )}
              <label htmlFor="invitation-password">
                Password
                <span><LockKeyhole size={16} /><input id="invitation-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'new' ? 'new-password' : 'current-password'} disabled={pending} minLength={12} required /></span>
              </label>
              {mode === 'new' && (
                <label htmlFor="invitation-password-confirmation">
                  Confirm password
                  <span><LockKeyhole size={16} /><input id="invitation-password-confirmation" type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" disabled={pending} minLength={12} required /></span>
                </label>
              )}
              {error && <p className="invite-acceptance-error" role="alert">{error}</p>}
              <button type="submit" disabled={pending || !password || (mode === 'new' ? !displayName.trim() || !confirmation : !email.trim())}>
                {pending && <LoaderCircle className="invite-acceptance-spinner" size={16} />}
                {pending ? 'Working...' : mode === 'new' ? 'Create account and join' : 'Sign in and join'}
              </button>
            </form>}
          </>
        )}
      </section>
    </main>
  );
}
