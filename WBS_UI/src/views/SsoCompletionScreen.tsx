import { useEffect } from 'react';
import { AlertTriangle, LoaderCircle, LockKeyhole } from 'lucide-react';
import type { AuthStatus } from '../auth/authContext';
import './LoginScreen.css';

interface SsoCompletionScreenProps {
  status: AuthStatus;
  error: string;
  onComplete: () => void;
  onBackToLogin: () => void;
}

const errorMessages: Record<string, string> = {
  access_denied: 'Your account does not have access yet. Ask a workspace administrator for an invitation.',
  identity_conflict: 'This work identity could not be linked automatically. Contact your administrator.',
  invalid_state: 'This sign-in request expired or was already used. Start a new sign-in.',
  invalid_response: 'The identity provider response could not be verified. Start a new sign-in.',
  provider_denied: 'Enterprise sign-in was cancelled or denied.',
  provider_unavailable: 'Enterprise sign-in is temporarily unavailable. Try again later.',
  sso_failed: 'Enterprise sign-in could not be completed. Try again.',
};

export default function SsoCompletionScreen({
  status,
  error,
  onComplete,
  onBackToLogin,
}: SsoCompletionScreenProps) {
  useEffect(() => {
    if (!error && status === 'authenticated') onComplete();
  }, [error, onComplete, status]);

  const message = error
    ? (errorMessages[error] ?? errorMessages.sso_failed)
    : status === 'unauthenticated'
      ? errorMessages.sso_failed
      : '';

  return (
    <main className="login-shell">
      <section className="login-brand" aria-label="WBS Genie">
        <div className="login-brand-mark"><LockKeyhole size={24} /></div>
        <div>
          <p className="login-kicker">Secure workspace access</p>
          <h1>WBS Genie</h1>
        </div>
      </section>
      <section className="login-panel" aria-live="polite">
        {message ? <AlertTriangle size={22} /> : <LoaderCircle className="login-spinner" size={22} />}
        <h2>{message ? 'Sign-in not completed' : 'Completing sign-in'}</h2>
        <p className={message ? 'login-error' : 'login-panel-subtitle'}>
          {message || 'Verifying your WBS Genie session...'}
        </p>
        {message && (
          <button type="button" className="login-submit" onClick={onBackToLogin}>
            Back to sign in
          </button>
        )}
      </section>
    </main>
  );
}
