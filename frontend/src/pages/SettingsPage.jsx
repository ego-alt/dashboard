import { useState } from 'react';
import { useAuth } from '../auth.jsx';
import { disableTotp, enableTotp, setupTotp } from '../api';

/**
 * Account settings. Currently: 2FA enrollment / disable.
 *
 * Enrollment flow:
 *   1. Click "Set up 2FA" -> POST /auth/totp/setup -> server returns secret +
 *      provisioning URI + a server-rendered SVG QR code.
 *   2. User scans the QR with an authenticator app, enters the code.
 *   3. POST /auth/totp/enable -> returns the one-time recovery codes, which
 *      we display once and then hide on the next refresh.
 */
export default function SettingsPage() {
  const { user, refresh } = useAuth();
  const [enrollment, setEnrollment] = useState(null); // { secret, uri, qr_svg }
  const [code, setCode] = useState('');
  const [recoveryCodes, setRecoveryCodes] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function onStartSetup() {
    setBusy(true);
    setError('');
    try {
      const body = await setupTotp();
      setEnrollment(body);
    } catch {
      setError('Could not start 2FA setup.');
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmEnable(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const body = await enableTotp(code);
      setRecoveryCodes(body.recovery_codes);
      setEnrollment(null);
      setCode('');
      await refresh();
    } catch (err) {
      setError(err.status === 400 ? 'Wrong code.' : 'Could not enable 2FA.');
    } finally {
      setBusy(false);
    }
  }

  async function onDisable(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await disableTotp(code);
      setCode('');
      await refresh();
    } catch (err) {
      setError(err.status === 400 ? 'Wrong code.' : 'Could not disable 2FA.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-slate-900">Account settings</h2>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-baseline justify-between">
          <h3 className="text-base font-semibold text-slate-900">
            Two-factor authentication
          </h3>
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${
              user?.totp_enabled
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-slate-200 text-slate-600'
            }`}
          >
            {user?.totp_enabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>

        {!user?.totp_enabled && !enrollment && !recoveryCodes && (
          <>
            <p className="mb-4 text-sm text-slate-600">
              Add a second factor (TOTP) on top of your password. Use an
              authenticator app like 1Password, Bitwarden, or Google Authenticator.
            </p>
            <button
              onClick={onStartSetup}
              disabled={busy}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Set up 2FA
            </button>
          </>
        )}

        {enrollment && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Scan the QR code with your authenticator app, then enter the
              6-digit code below to confirm.
            </p>
            <div
              className="mx-auto h-48 w-48 [&_svg]:h-full [&_svg]:w-full"
              dangerouslySetInnerHTML={{ __html: enrollment.qr_svg }}
            />
            <details className="text-sm text-slate-600">
              <summary className="cursor-pointer">Can't scan? Show secret</summary>
              <code className="mt-2 block break-all rounded bg-slate-100 p-2 font-mono text-xs">
                {enrollment.secret}
              </code>
            </details>
            <form onSubmit={onConfirmEnable} className="space-y-3">
              <input
                autoFocus
                autoComplete="one-time-code"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-slate-900 outline-none focus:border-slate-500"
              />
              {error && <p className="text-sm text-red-600">{error}</p>}
              <button
                type="submit"
                disabled={busy || !code}
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {busy ? 'Verifying…' : 'Enable'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setEnrollment(null);
                  setCode('');
                  setError('');
                }}
                className="ml-2 rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
              >
                Cancel
              </button>
            </form>
          </div>
        )}

        {recoveryCodes && (
          <div className="space-y-3">
            <p className="text-sm font-medium text-amber-900">
              Save these recovery codes somewhere safe. They will not be shown
              again — each one works once if you lose access to your
              authenticator.
            </p>
            <ul className="grid grid-cols-2 gap-2 rounded-lg bg-amber-50 p-3 font-mono text-sm text-amber-900">
              {recoveryCodes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <button
              onClick={() => setRecoveryCodes(null)}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              I've saved them
            </button>
          </div>
        )}

        {user?.totp_enabled && !recoveryCodes && (
          <form onSubmit={onDisable} className="space-y-3">
            <p className="text-sm text-slate-600">
              To turn 2FA off, enter a current authenticator code or a recovery code.
            </p>
            <input
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="123456"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-slate-900 outline-none focus:border-slate-500"
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={busy || !code}
              className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-900 hover:bg-rose-100 disabled:opacity-50"
            >
              {busy ? 'Disabling…' : 'Disable 2FA'}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
