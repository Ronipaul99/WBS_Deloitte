import { FormEvent, useState } from 'react';
import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  Sparkles,
} from 'lucide-react';
import { ApiError, resetPasswordRequest } from '../services/apiClient';
import './LoginScreen.css';
import './ForgotPasswordScreen.css';
import './ResetPasswordScreen.css';

interface ResetPasswordScreenProps {
  token: string;
  onResetComplete: () => Promise<void>;
  onBackToLogin: () => void;
}

export default function ResetPasswordScreen({
  token,
  onResetComplete,
  onBackToLogin,
}: ResetPasswordScreenProps) {
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [complete, setComplete] = useState(false);
  const [invalidToken, setInvalidToken] = useState(!token);
  const [error, setError] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (password.length < 12) {
      setError('Password must contain at least 12 characters.');
      return;
    }
    if (new TextEncoder().encode(password).length > 128) {
      setError('Password must not exceed 128 bytes.');
      return;
    }
    if (password !== confirmation) {
      setError('Passwords do not match.');
      return;
    }

    setSubmitting(true);
    try {
      await resetPasswordRequest(token, password);
      await onResetComplete();
      setPassword('');
      setConfirmation('');
      setComplete(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 400) {
        setInvalidToken(true);
      } else if (reason instanceof ApiError && reason.status === 422) {
        setError(reason.message);
      } else {
        setError('The request could not be completed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const title = complete ? 'Password updated' : invalidToken ? 'Reset link unavailable' : 'Choose a new password';

  return (
    <main className="login-shell">
      <section className="login-brand" aria-label="WBS Genie">
        <div className="login-brand-mark"><Sparkles size={24} /></div>
        <div>
          <p className="login-kicker">Project controls workspace</p>
          <h1>WBS Genie</h1>
          <p>Turn project scope into a clear, reviewable work breakdown structure.</p>
        </div>
      </section>

      <section className="login-panel" aria-labelledby="reset-password-title">
        <div className="login-panel-icon">
          {complete ? <CheckCircle2 size={20} /> : <KeyRound size={20} />}
        </div>
        <h2 id="reset-password-title">{title}</h2>

        {complete && (
          <div className="recovery-result reset-result" role="status">
            <p>Your password has been updated. Sign in with your new password.</p>
            <button type="button" className="recovery-primary" onClick={onBackToLogin}>
              Continue to sign in
            </button>
          </div>
        )}

        {!complete && invalidToken && (
          <div className="reset-invalid" role="alert">
            <p>The password reset link is invalid or has expired.</p>
            <button type="button" className="recovery-primary" onClick={onBackToLogin}>
              Back to sign in
            </button>
          </div>
        )}

        {!complete && !invalidToken && (
          <>
            <p className="login-panel-subtitle">Use at least 12 characters.</p>
            <form onSubmit={handleSubmit} className="login-form reset-form">
              <label htmlFor="new-password">New password</label>
              <div className="login-password-field">
                <input
                  id="new-password"
                  name="new-password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={12}
                  autoFocus
                  disabled={submitting}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? 'Hide passwords' : 'Show passwords'}
                  title={showPassword ? 'Hide passwords' : 'Show passwords'}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>

              <label htmlFor="confirm-password">Confirm new password</label>
              <div className="login-password-field">
                <input
                  id="confirm-password"
                  name="confirm-password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  required
                  minLength={12}
                  disabled={submitting}
                />
              </div>

              {error && <p className="login-error" role="alert">{error}</p>}
              <button
                type="submit"
                className="login-submit"
                disabled={submitting || !password || !confirmation}
              >
                {submitting && <LoaderCircle className="login-spinner" size={17} />}
                {submitting ? 'Updating...' : 'Update password'}
              </button>
            </form>
            <button type="button" className="recovery-back" onClick={onBackToLogin}>
              <ArrowLeft size={15} />
              Back to sign in
            </button>
          </>
        )}
      </section>
    </main>
  );
}
