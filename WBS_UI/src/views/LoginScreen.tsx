import { FormEvent, useState } from 'react';
import { Building2, Eye, EyeOff, LoaderCircle, LockKeyhole, Sparkles } from 'lucide-react';
import { ApiError } from '../services/apiClient';
import './LoginScreen.css';

interface LoginScreenProps {
  onLogin: (email: string, password: string) => Promise<void>;
  onForgotPassword?: () => void;
  localAuthEnabled?: boolean;
  onEnterpriseLogin?: () => void;
  enterpriseLabel?: string;
}

export default function LoginScreen({
  onLogin,
  onForgotPassword,
  localAuthEnabled = true,
  onEnterpriseLogin,
  enterpriseLabel = 'Enterprise SSO',
}: LoginScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [ssoSubmitting, setSsoSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await onLogin(email.trim(), password);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 429) {
        setError('Too many attempts. Please wait before trying again.');
      } else {
        setError('The email or password is incorrect.');
      }
    } finally {
      setSubmitting(false);
    }
  };

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

      <section className="login-panel">
        <div className="login-panel-icon"><LockKeyhole size={20} /></div>
        <h2>Sign in</h2>
        <p className="login-panel-subtitle">Use your work account to continue.</p>

        {onEnterpriseLogin && (
          <button
            type="button"
            className="login-enterprise"
            disabled={ssoSubmitting || submitting}
            onClick={() => {
              setSsoSubmitting(true);
              onEnterpriseLogin();
            }}
          >
            {ssoSubmitting
              ? <LoaderCircle className="login-spinner" size={17} />
              : <Building2 size={17} />}
            {ssoSubmitting ? 'Redirecting...' : `Continue with ${enterpriseLabel}`}
          </button>
        )}

        {onEnterpriseLogin && localAuthEnabled && (
          <div className="login-divider"><span>or</span></div>
        )}

        {localAuthEnabled && <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="login-email">Email address</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            disabled={submitting}
          />

          <label htmlFor="login-password">Password</label>
          <div className="login-password-field">
            <input
              id="login-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              disabled={submitting}
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              title={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>

          {onForgotPassword && (
            <button
              type="button"
              className="login-forgot-link"
              onClick={onForgotPassword}
              disabled={submitting}
            >
              Forgot password?
            </button>
          )}

          {error && <p className="login-error" role="alert">{error}</p>}

          <button
            type="submit"
            className="login-submit"
            disabled={submitting || !email.trim() || !password}
          >
            {submitting && <LoaderCircle className="login-spinner" size={17} />}
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>}
      </section>
    </main>
  );
}
