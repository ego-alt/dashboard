import { useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { login, verifyTotp } from '../api';
import { useAuth } from '../auth.jsx';
import { passkeysSupported, signInWithPasskey } from '../webauthn';

export default function LoginPage() {
  const { user, refresh } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [stage, setStage] = useState('credentials'); // 'credentials' | 'totp'
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const next = params.get('next') || '/';

  if (user) {
    return <Navigate to={next} replace />;
  }

  async function onCredentialsSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const result = await login(username, password);
      if (result.needs_2fa) {
        setStage('totp');
        setBusy(false);
        return;
      }
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setError(
        err.status === 401
          ? 'Invalid username or password.'
          : err.status === 429
            ? 'Too many attempts. Try again in a minute.'
            : 'Something went wrong. Try again.',
      );
      setBusy(false);
    }
  }

  async function onPasskeySignIn() {
    setBusy(true);
    setError('');
    try {
      await signInWithPasskey();
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      // NotAllowedError is the browser saying "user cancelled" — quiet.
      if (err?.name !== 'NotAllowedError') {
        setError('Passkey sign-in failed. Try again or use your password.');
      }
      setBusy(false);
    }
  }

  async function onTotpSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await verifyTotp(code);
      await refresh();
      navigate(next, { replace: true });
    } catch (err) {
      setError(
        err.status === 401
          ? 'Wrong code. Try again, or use a recovery code.'
          : 'Something went wrong. Try again.',
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg-inset)] px-4">
      <div className="w-full max-w-sm bp-card p-8">
        <h1 className="mb-1 text-xl font-semibold text-[var(--color-text-primary)]">Home</h1>
        <p className="mb-6 text-sm text-[var(--color-text-muted)]">
          {stage === 'credentials'
            ? 'Sign in to continue.'
            : 'Enter the 6-digit code from your authenticator app, or a recovery code.'}
        </p>

        {stage === 'credentials' && (
          <form onSubmit={onCredentialsSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">
                Username
              </label>
              <input
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">
                Password
              </label>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input"
              />
            </div>
            {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
            <button
              type="submit"
              disabled={busy || !username || !password}
              className="btn btn-primary w-full"
            >
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
            {passkeysSupported() && (
              <>
                <div className="my-2 flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
                  <span className="h-px flex-1 bg-[var(--color-bg-inset)]" />
                  or
                  <span className="h-px flex-1 bg-[var(--color-bg-inset)]" />
                </div>
                <button
                  type="button"
                  onClick={onPasskeySignIn}
                  disabled={busy}
                  className="btn btn-secondary w-full"
                >
                  Sign in with passkey
                </button>
              </>
            )}
          </form>
        )}

        {stage === 'totp' && (
          <form onSubmit={onTotpSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-[var(--color-text-secondary)]">
                Code
              </label>
              <input
                autoFocus
                autoComplete="one-time-code"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="input font-mono"
                placeholder="123456"
              />
            </div>
            {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
            <button
              type="submit"
              disabled={busy || !code}
              className="btn btn-primary w-full"
            >
              {busy ? 'Verifying…' : 'Verify'}
            </button>
            <button
              type="button"
              onClick={() => {
                setStage('credentials');
                setCode('');
                setError('');
              }}
              className="btn btn-secondary w-full text-sm"
            >
              Use a different account
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
