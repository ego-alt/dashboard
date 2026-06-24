import { useEffect, useState } from 'react';
import { useAuth } from '../auth.jsx';
import {
  createApiToken,
  deleteApiToken,
  deletePasskey,
  disableTotp,
  enableTotp,
  listApiTokens,
  listPasskeys,
  setupTotp,
} from '../api';
import { passkeysSupported, registerPasskey } from '../webauthn';

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
      <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Account settings</h2>

      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-6 shadow-sm">
        <div className="mb-4 flex items-baseline justify-between">
          <h3 className="text-base font-semibold text-[var(--color-text-primary)]">
            Two-factor authentication
          </h3>
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${
              user?.totp_enabled
                ? 'bg-emerald-500/15 text-emerald-300'
                : 'bg-[var(--color-bg-inset)] text-[var(--color-text-secondary)]'
            }`}
          >
            {user?.totp_enabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>

        {!user?.totp_enabled && !enrollment && !recoveryCodes && (
          <>
            <p className="mb-4 text-sm text-[var(--color-text-secondary)]">
              Add a second factor (TOTP) on top of your password. Use an
              authenticator app like 1Password, Bitwarden, or Google Authenticator.
            </p>
            <button
              onClick={onStartSetup}
              disabled={busy}
              className="btn btn-primary text-sm"
            >
              Set up 2FA
            </button>
          </>
        )}

        {enrollment && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--color-text-secondary)]">
              Scan the QR code with your authenticator app, then enter the
              6-digit code below to confirm.
            </p>
            <div
              className="mx-auto h-48 w-48 [&_svg]:h-full [&_svg]:w-full"
              dangerouslySetInnerHTML={{ __html: enrollment.qr_svg }}
            />
            <details className="text-sm text-[var(--color-text-secondary)]">
              <summary className="cursor-pointer">Can't scan? Show secret</summary>
              <code className="mt-2 block break-all rounded bg-[var(--color-bg-inset)] p-2 font-mono text-xs">
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
                className="input font-mono"
              />
              {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
              <button
                type="submit"
                disabled={busy || !code}
                className="btn btn-primary text-sm"
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
                className="btn btn-secondary text-sm ml-2"
              >
                Cancel
              </button>
            </form>
          </div>
        )}

        {recoveryCodes && (
          <div className="space-y-3">
            <p className="text-sm font-medium text-amber-300">
              Save these recovery codes somewhere safe. They will not be shown
              again — each one works once if you lose access to your
              authenticator.
            </p>
            <ul className="grid grid-cols-2 gap-2 rounded-lg bg-amber-500/15 p-3 font-mono text-sm text-amber-300">
              {recoveryCodes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <button
              onClick={() => setRecoveryCodes(null)}
              className="btn btn-secondary text-sm"
            >
              I've saved them
            </button>
          </div>
        )}

        {user?.totp_enabled && !recoveryCodes && (
          <form onSubmit={onDisable} className="space-y-3">
            <p className="text-sm text-[var(--color-text-secondary)]">
              To turn 2FA off, enter a current authenticator code or a recovery code.
            </p>
            <input
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="123456"
              className="input font-mono"
            />
            {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
            <button
              type="submit"
              disabled={busy || !code}
              className="btn btn-danger text-sm"
            >
              {busy ? 'Disabling…' : 'Disable 2FA'}
            </button>
          </form>
        )}
      </section>

      <PasskeysSection />

      <ApiTokensSection />
    </div>
  );
}

/**
 * API tokens for native apps (e.g. the document scanner, which uploads scans to
 * the calendar). The raw token is shown once at creation — only its hash is
 * stored server-side — so we surface a copy button and a "save it now" warning.
 */
function ApiTokensSection() {
  const [tokens, setTokens] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newName, setNewName] = useState('');
  const [freshToken, setFreshToken] = useState(null); // shown once after creation
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    listApiTokens()
      .then(setTokens)
      .catch(() => setTokens([]));
  }, []);

  async function onCreate(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { token } = await createApiToken(newName || 'API token');
      setFreshToken(token);
      setCopied(false);
      setNewName('');
      const fresh = await listApiTokens();
      setTokens(fresh);
    } catch {
      setError('Could not create token.');
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id) {
    if (!confirm('Revoke this token? Apps using it will stop working.')) return;
    setBusy(true);
    setError('');
    try {
      await deleteApiToken(id);
      const fresh = await listApiTokens();
      setTokens(fresh);
    } catch {
      setError('Could not revoke token.');
    } finally {
      setBusy(false);
    }
  }

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(freshToken);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-6 shadow-sm">
      <h3 className="mb-1 text-base font-semibold text-[var(--color-text-primary)]">
        API tokens
      </h3>
      <p className="mb-4 text-sm text-[var(--color-text-secondary)]">
        Let an app authenticate to your home stack without your password — for
        example, the document scanner uploading a scan to your calendar. Paste
        the token into the app once; revoke it here to cut access.
      </p>

      {freshToken && (
        <div className="mb-4 space-y-2 rounded-lg bg-amber-500/15 p-3">
          <p className="text-sm font-medium text-amber-300">
            Copy this token now — it won't be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-[var(--color-bg-elevated)] p-2 font-mono text-xs text-[var(--color-text-primary)]">
              {freshToken}
            </code>
            <button onClick={onCopy} className="btn btn-secondary text-xs">
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <button
            onClick={() => setFreshToken(null)}
            className="btn btn-secondary text-xs"
          >
            Done
          </button>
        </div>
      )}

      {tokens === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
      ) : tokens.length === 0 ? (
        <p className="mb-4 text-sm text-[var(--color-text-muted)]">No tokens yet.</p>
      ) : (
        <ul className="mb-4 divide-y divide-[var(--color-border)]">
          {tokens.map((t) => (
            <li
              key={t.id}
              className="flex items-center justify-between py-2 text-sm"
            >
              <div>
                <div className="font-medium text-[var(--color-text-primary)]">
                  {t.name}{' '}
                  <span className="font-mono text-xs text-[var(--color-text-muted)]">
                    {t.prefix}…
                  </span>
                </div>
                <div className="text-xs text-[var(--color-text-muted)]">
                  added {new Date(t.created_at).toLocaleDateString()}
                  {t.last_used_at ? (
                    <> · last used {new Date(t.last_used_at).toLocaleDateString()}</>
                  ) : (
                    <> · never used</>
                  )}
                </div>
              </div>
              <button
                onClick={() => onDelete(t.id)}
                disabled={busy}
                className="text-xs text-[var(--color-danger)] hover:underline disabled:opacity-50"
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={onCreate} className="flex items-end gap-2">
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
            Name for this app
          </label>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Document scanner, …"
            className="input text-sm"
          />
        </div>
        <button type="submit" disabled={busy} className="btn btn-primary text-sm">
          Generate token
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-[var(--color-danger)]">{error}</p>}
    </section>
  );
}

function PasskeysSection() {
  const [passkeys, setPasskeys] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newName, setNewName] = useState('');

  useEffect(() => {
    listPasskeys()
      .then(setPasskeys)
      .catch(() => setPasskeys([]));
  }, []);

  async function onAdd(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await registerPasskey(newName || 'Passkey');
      const fresh = await listPasskeys();
      setPasskeys(fresh);
      setNewName('');
    } catch (err) {
      if (err?.name !== 'NotAllowedError') {
        setError('Could not register passkey.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id) {
    if (!confirm('Remove this passkey?')) return;
    setBusy(true);
    setError('');
    try {
      await deletePasskey(id);
      const fresh = await listPasskeys();
      setPasskeys(fresh);
    } catch {
      setError('Could not remove passkey.');
    } finally {
      setBusy(false);
    }
  }

  if (!passkeysSupported()) {
    return (
      <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-6 shadow-sm">
        <h3 className="mb-2 text-base font-semibold text-[var(--color-text-primary)]">Passkeys</h3>
        <p className="text-sm text-[var(--color-text-secondary)]">
          This browser doesn't support WebAuthn. Open the dashboard in a recent
          browser to enroll a passkey.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-elevated)] p-6 shadow-sm">
      <h3 className="mb-1 text-base font-semibold text-[var(--color-text-primary)]">Passkeys</h3>
      <p className="mb-4 text-sm text-[var(--color-text-secondary)]">
        Sign in without a password using your device's built-in authenticator
        (Touch ID, Windows Hello, security key, etc.). A passkey alone is a
        strong factor — 2FA isn't asked for again on top of it.
      </p>

      {passkeys === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
      ) : passkeys.length === 0 ? (
        <p className="mb-4 text-sm text-[var(--color-text-muted)]">No passkeys yet.</p>
      ) : (
        <ul className="mb-4 divide-y divide-[var(--color-border)]">
          {passkeys.map((k) => (
            <li
              key={k.id}
              className="flex items-center justify-between py-2 text-sm"
            >
              <div>
                <div className="font-medium text-[var(--color-text-primary)]">{k.name}</div>
                <div className="text-xs text-[var(--color-text-muted)]">
                  added {new Date(k.created_at).toLocaleDateString()}
                  {k.last_used_at && (
                    <>
                      {' '}
                      · last used {new Date(k.last_used_at).toLocaleDateString()}
                    </>
                  )}
                </div>
              </div>
              <button
                onClick={() => onDelete(k.id)}
                disabled={busy}
                className="text-xs text-[var(--color-danger)] hover:underline disabled:opacity-50"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={onAdd} className="flex items-end gap-2">
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium text-[var(--color-text-secondary)]">
            Nickname for this device
          </label>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="iPhone, Yubikey, …"
            className="input text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="btn btn-primary text-sm"
        >
          Add passkey
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-[var(--color-danger)]">{error}</p>}
    </section>
  );
}
