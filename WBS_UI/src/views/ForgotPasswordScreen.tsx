import { FormEvent, useState } from 'react';
import { ArrowLeft, LoaderCircle, Mail, Sparkles } from 'lucide-react';
import { ApiError, forgotPasswordRequest } from '../services/apiClient';
import './LoginScreen.css';
import './ForgotPasswordScreen.css';

interface ForgotPasswordScreenProps {
  onBackToLogin: () => void;
}

const confirmationMessage =
  'If the account is eligible, password reset instructions will be sent.';

export default function ForgotPasswordScreen({ onBackToLogin }: ForgotPasswordScreenProps) {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await forgotPasswordRequest(email.trim());
      setSubmitted(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 429) {
        setError('Too many requests. Please wait before trying again.');
      } else {
        setError('The request could not be completed. Please try again.');
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

      <section className="login-panel" aria-labelledby="forgot-password-title">
        <div className="login-panel-icon"><Mail size={20} /></div>
        <h2 id="forgot-password-title">Reset your password</h2>
        {submitted ? (
          <div className="recovery-result" role="status">
            <p>{confirmationMessage}</p>
            <button type="button" className="recovery-primary" onClick={onBackToLogin}>
              Back to sign in
            </button>
          </div>
        ) : (
          <>
            <p className="login-panel-subtitle">
              Enter your work email to request a secure reset link.
            </p>
            <form onSubmit={handleSubmit} className="login-form">
              <label htmlFor="recovery-email">Email address</label>
              <input
                id="recovery-email"
                name="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoFocus
                disabled={submitting}
              />
              {error && <p className="login-error" role="alert">{error}</p>}
              <button
                type="submit"
                className="login-submit"
                disabled={submitting || !email.trim()}
              >
                {submitting && <LoaderCircle className="login-spinner" size={17} />}
                {submitting ? 'Sending...' : 'Send reset link'}
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
