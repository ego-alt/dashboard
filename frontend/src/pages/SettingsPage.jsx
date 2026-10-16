import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../auth.jsx';
import Panel from '../components/Panel.jsx';
import { age, clock, device, secondsSince } from '../lib/format';
import {
  changePassword,
  createApiToken,
  deleteApiToken,
  deletePasskey,
  disableTotp,
  enableTotp,
  listApiTokens,
  listPasskeys,
  listSessions,
  loginEvents,
  regenerateRecoveryCodes,
  revokeOtherSessions,
  revokeSession,
  setupTotp,
} from '../api';
import { passkeysSupported, registerPasskey } from '../webauthn';

function RecoveryCodes({ codes, onDone }) {
  const [copied, setCopied] = useState(false);
  const text = codes.join('\n');
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([`Home recovery codes (each works once)\n\n${text}\n`], { type: 'text/plain' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'home-recovery-codes.txt';
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-amber-300">
        Save these recovery codes somewhere safe. They won't be shown again. Each one
        signs you in once if you lose your authenticator.
      </p>
      <ul className="grid grid-cols-2 gap-2 rounded-lg bg-amber-500/15 p-3 font-mono text-sm text-amber-300">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button onClick={copy} className="btn btn-secondary text-sm">
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button onClick={download} className="btn btn-secondary text-sm">
          Download .txt
        </button>
        <button onClick={onDone} className="btn btn-primary text-sm">
          I've saved them
        </button>
      </div>
    </div>
  );
}

/**
 * Account settings: password, 2FA, passkeys, where you're signed in, and API
 * tokens.
 *
 * 2FA enrollment:
 *   1. "Set up 2FA" -> POST /auth/totp/setup -> secret + provisioning URI +
 *      a server-rendered SVG QR code.
 *   2. The user scans the QR with an authenticator app and enters the code.
 *   3. POST /auth/totp/enable -> the one-time recovery codes, shown until the
 *      user says they've saved them.
 */
export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Settings</h2>
      <PasswordSection />
      <TwoFactorSection />
      <PasskeysSection />
      <SessionsSection />
      <ApiTokensSection />
    </div>
  );
}

function PasswordSection() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [show, setShow] = useState(false);
  const [signOutOthers, setSignOutOthers] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setDone('');
    try {
      const r = await changePassword(current, next, signOutOthers);
      setCurrent('');
      setNext('');
      setDone(
        r.sessions_ended
          ? `Password changed. Signed out ${r.sessions_ended} other ${r.sessions_ended === 1 ? 'session' : 'sessions'}.`
          : 'Password changed.',
      );
    } catch (err) {
      const d = err.body?.detail;
      setError(d ? d.charAt(0).toUpperCase() + d.slice(1) + '.' : 'Couldn’t change your password.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Password">
      <form onSubmit={onSubmit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-xs text-[var(--color-text-muted)]">
            Current password
            <input
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className="input mt-1"
            />
          </label>
          <label className="block text-xs text-[var(--color-text-muted)]">
            New password <span className="text-[var(--color-text-muted)]">(8+ characters)</span>
            <input
              type={show ? 'text' : 'password'}
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className="input mt-1"
            />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[var(--color-text-secondary)]">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
            Show
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={signOutOthers}
              onChange={(e) => setSignOutOthers(e.target.checked)}
            />
            Sign out my other devices
          </label>
          <button
            type="submit"
            disabled={busy || !current || next.length < 8}
            className="btn btn-primary text-sm sm:ml-auto"
          >
            {busy ? 'Changing…' : 'Change password'}
          </button>
        </div>
        {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
        {done && <p className="text-sm text-[var(--color-text-secondary)]">{done}</p>}
      </form>
    </Panel>
  );
}

function TwoFactorSection() {
  const { user, refresh } = useAuth();
  const [enrollment, setEnrollment] = useState(null); // { secret, uri, qr_svg }
  const [code, setCode] = useState('');
  const [recoveryCodes, setRecoveryCodes] = useState(null);
  const [mode, setMode] = useState(null); // null | 'regenerate' | 'disable'
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  function reset() {
    setMode(null);
    setCode('');
    setError('');
  }

  async function onStartSetup() {
    setBusy(true);
    setError('');
    try {
      setEnrollment(await setupTotp());
    } catch {
      setError('Couldn’t start 2FA setup.');
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
      setError(err.status === 400 ? 'Wrong code.' : 'Couldn’t turn on 2FA.');
    } finally {
      setBusy(false);
    }
  }

  async function onCodeSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      if (mode === 'regenerate') {
        const body = await regenerateRecoveryCodes(code);
        setRecoveryCodes(body.recovery_codes);
      } else {
        await disableTotp(code);
      }
      reset();
      await refresh();
    } catch (err) {
      setError(err.status === 400 ? 'Wrong code.' : 'Something went wrong. Try again.');
    } finally {
      setBusy(false);
    }
  }

  const left = user?.totp_recovery_left;

  return (
    <Panel
      title="Two-factor authentication"
      aside={
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            user?.totp_enabled
              ? 'bg-green-500/15 text-green-300'
              : 'bg-[var(--color-bg-inset)] text-[var(--color-text-secondary)]'
          }`}
        >
          {user?.totp_enabled ? 'On' : 'Off'}
        </span>
      }
    >

      {recoveryCodes ? (
        <RecoveryCodes codes={recoveryCodes} onDone={() => setRecoveryCodes(null)} />
      ) : !user?.totp_enabled && !enrollment ? (
        <>
          <p className="mb-3 text-sm text-[var(--color-text-secondary)]">
            Add a second factor (TOTP) on top of your password. Use an authenticator app
            like 1Password, Bitwarden, or Google Authenticator.
          </p>
          <button onClick={onStartSetup} disabled={busy} className="btn btn-primary text-sm">
            Set up 2FA
          </button>
          {error && <p className="mt-2 text-sm text-[var(--color-danger)]">{error}</p>}
        </>
      ) : enrollment ? (
        <div className="space-y-4">
          <p className="text-sm text-[var(--color-text-secondary)]">
            Scan the QR code with your authenticator app, then enter the 6-digit code it
            shows.
          </p>
          {/* The SVG is black modules on a transparent background: give it a
              white tile, or it's invisible (and unscannable) on the dark card. */}
          <div
            className="mx-auto h-52 w-52 rounded bg-white p-3 [&_svg]:h-full [&_svg]:w-full"
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
            <button type="submit" disabled={busy || !code} className="btn btn-primary text-sm">
              {busy ? 'Verifying…' : 'Turn on'}
            </button>
            <button
              type="button"
              onClick={() => {
                setEnrollment(null);
                reset();
              }}
              className="btn btn-secondary ml-2 text-sm"
            >
              Cancel
            </button>
          </form>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-[var(--color-text-secondary)]">
            Signing in asks for a code from your authenticator app.{' '}
            {left != null && (
              <span className={left <= 2 ? 'text-amber-300' : ''}>
                {left} recovery {left === 1 ? 'code' : 'codes'} left.
              </span>
            )}
          </p>
          {mode ? (
            <form onSubmit={onCodeSubmit} className="space-y-3">
              <p className="text-sm text-[var(--color-text-secondary)]">
                {mode === 'regenerate'
                  ? 'Enter a code from your authenticator app. Your old recovery codes will stop working.'
                  : 'To turn 2FA off, enter a code from your authenticator app or a recovery code.'}
              </p>
              <input
                autoFocus
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="123456"
                className="input font-mono"
              />
              {error && <p className="text-sm text-[var(--color-danger)]">{error}</p>}
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy || !code}
                  className={`btn text-sm ${mode === 'disable' ? 'btn-danger' : 'btn-primary'}`}
                >
                  {mode === 'disable' ? 'Turn off 2FA' : 'Get new codes'}
                </button>
                <button type="button" onClick={reset} className="btn btn-secondary text-sm">
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="flex items-center gap-4">
              <button onClick={() => setMode('regenerate')} className="btn btn-secondary text-sm">
                New recovery codes
              </button>
              <button onClick={() => setMode('disable')} className="btn-link btn-link-danger text-sm">
                Turn off…
              </button>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

const LOGIN_REASONS = {
  'bad-password': 'wrong password',
  'bad-totp': 'wrong 2FA code',
  'needs-2fa': 'password ok, waiting for 2FA',
  'totp-totp': 'with 2FA',
  'totp-recovery': 'with a recovery code',
  passkey: 'with a passkey',
};

function SessionsSection() {
  const [sessions, setSessions] = useState(null);
  const [events, setEvents] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    listSessions()
      .then(setSessions)
      .catch(() => setSessions([]));
    loginEvents()
      .then(setEvents)
      .catch(() => setEvents([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn) {
    setBusy(true);
    setError('');
    try {
      await fn();
      load();
    } catch {
      setError('Couldn’t sign that session out.');
    } finally {
      setBusy(false);
    }
  }

  const others = (sessions || []).filter((s) => !s.current).length;

  return (
    <Panel
      title="Where you're signed in"
      description="Sign out a device you've lost or don't use any more."
      aside={
        others > 0 && (
          <button
            onClick={() => run(revokeOtherSessions)}
            disabled={busy}
            className="btn-link btn-link-danger text-xs"
          >
            Sign out all other devices
          </button>
        )
      }
    >
      {sessions === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
      ) : (
        <ul className="mb-3 divide-y divide-[var(--color-border)]">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <div>
                <div className="font-medium text-[var(--color-text-primary)]">
                  {device(s.user_agent)}
                  {s.current && (
                    <span className="ml-2 text-xs font-normal text-green-300">this device</span>
                  )}
                </div>
                <div className="text-xs text-[var(--color-text-muted)]">
                  {s.ip || 'unknown address'} · signed in {clock(s.created_at)} · last seen{' '}
                  {age(secondsSince(s.last_seen_at))} ago
                </div>
              </div>
              {!s.current && (
                <button
                  onClick={() => run(() => revokeSession(s.id))}
                  disabled={busy}
                  className="btn-link btn-link-danger text-xs"
                >
                  Sign out
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}
      {events?.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-[var(--color-text-secondary)]">Recent sign-ins</summary>
          <ul className="mt-2 space-y-1 text-xs">
            {events.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className={`w-3 ${e.success ? 'text-green-300' : 'text-[var(--color-danger)]'}`}>
                  {e.success ? '✓' : '✗'}
                </span>
                <span className="w-24 shrink-0 text-[var(--color-text-muted)]">{clock(e.at)}</span>
                <span className="text-[var(--color-text-secondary)]">
                  {device(e.user_agent)} · {e.ip || 'unknown address'}
                  {e.reason && LOGIN_REASONS[e.reason] && ` · ${LOGIN_REASONS[e.reason]}`}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
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
    <Panel
      title="API tokens"
      description="Let an app authenticate to your home stack without your password — for example, the document scanner uploading a scan to your calendar. Paste the token into the app once; revoke it here to cut access."
    >

      {freshToken && (
        <div className="mb-3 space-y-2 rounded-lg bg-amber-500/15 p-3">
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
        <p className="mb-3 text-sm text-[var(--color-text-muted)]">No tokens yet.</p>
      ) : (
        <ul className="mb-3 divide-y divide-[var(--color-border)]">
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
                className="btn-link btn-link-danger text-xs"
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={onCreate} className="flex items-end gap-2">
        <div className="flex-1">
          <label className="mb-1 block text-xs text-[var(--color-text-muted)]">
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
    </Panel>
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
      <Panel
        title="Passkeys"
        description="This browser doesn't support WebAuthn. Open the dashboard in a recent browser to enroll a passkey."
      />
    );
  }

  return (
    <Panel
      title="Passkeys"
      description="Sign in without a password using your device's built-in authenticator (Touch ID, Windows Hello, security key, etc.). A passkey alone is a strong factor — 2FA isn't asked for again on top of it."
    >

      {passkeys === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>
      ) : passkeys.length === 0 ? (
        <p className="mb-3 text-sm text-[var(--color-text-muted)]">No passkeys yet.</p>
      ) : (
        <ul className="mb-3 divide-y divide-[var(--color-border)]">
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
                className="btn-link btn-link-danger text-xs"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={onAdd} className="flex items-end gap-2">
        <div className="flex-1">
          <label className="mb-1 block text-xs text-[var(--color-text-muted)]">
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
    </Panel>
  );
}
