import { useCallback, useEffect, useState } from 'react';
import { clock, sentence } from '../lib/format';
import {
  listUsers,
  createUser,
  setUserPassword,
  setUserAdmin,
  resetUser2fa,
  deleteUser,
} from '../api';
import { useAuth } from '../auth.jsx';
import PageHeader from '../components/PageHeader.jsx';
import Panel from '../components/Panel.jsx';

const BLANK = { username: '', display_name: '', password: '', is_admin: false };

// 18 characters from an unambiguous alphabet (~100 bits), for "Generate".
const ALPHABET = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
function generatePassword(n = 18) {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join('');
}

/** Inline "set a new password" form for one user. */
function PasswordForm({ user, onDone, onCancel }) {
  const [pw, setPw] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const name = user.display_name || user.username;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await setUserPassword(user.id, pw);
      const ended = r?.sessions_ended || 0;
      onDone(
        `${name}'s password is set${
          ended ? `, and ${ended} ${ended === 1 ? 'session was' : 'sessions were'} signed out` : ''
        }. ${show ? '' : 'Share it with them privately.'}`.trim(),
      );
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t set the password.'));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
      <span className="text-xs text-[var(--color-text-muted)]">New password for {name}</span>
      <input
        autoFocus
        type={show ? 'text' : 'password'}
        autoComplete="new-password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        placeholder="8+ characters"
        className="input font-mono sm:w-56"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setPw(generatePassword());
            setShow(true);
          }}
          className="btn btn-secondary text-xs"
        >
          Generate
        </button>
        <label className="flex items-center gap-1 text-xs text-[var(--color-text-secondary)]">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
          Show
        </label>
        <button type="submit" disabled={busy || pw.length < 8} className="btn btn-primary text-xs">
          {busy ? 'Saving…' : 'Set password'}
        </button>
        <button type="button" onClick={onCancel} className="btn btn-secondary text-xs">
          Cancel
        </button>
      </div>
      {error && <p className="w-full text-sm text-[var(--color-danger)]">{error}</p>}
      <p className="w-full text-xs text-[var(--color-text-muted)]">
        Setting a password signs {name} out everywhere.
      </p>
    </form>
  );
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState(BLANK);
  const [creating, setCreating] = useState(false);
  const [editingPw, setEditingPw] = useState(null); // user id
  const [notice, setNotice] = useState(null); // { text, undo? }

  const load = useCallback(async () => {
    try {
      setUsers(await listUsers());
      setError('');
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t load users.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onCreate(e) {
    e.preventDefault();
    setCreating(true);
    setError('');
    try {
      await createUser(form);
      setForm(BLANK);
      await load();
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t add the user.'));
    } finally {
      setCreating(false);
    }
  }

  async function setRole(u, isAdmin, { undoable = true } = {}) {
    const name = u.display_name || u.username;
    try {
      await setUserAdmin(u.id, isAdmin);
      setError('');
      await load();
      setNotice(
        undoable
          ? {
              text: isAdmin ? `${name} is now an admin.` : `${name} is no longer an admin.`,
              undo: () => setRole(u, !isAdmin, { undoable: false }),
            }
          : { text: `Undone: ${name} is ${isAdmin ? 'an admin again' : 'no longer an admin'}.` },
      );
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t change the role.'));
    }
  }

  function toggleAdmin(u) {
    const name = u.display_name || u.username;
    if (
      !u.is_admin &&
      !window.confirm(
        `Make ${name} an admin? They'll be able to stop containers, read logs and manage users.`,
      )
    )
      return;
    setRole(u, !u.is_admin);
  }

  async function reset2fa(u) {
    if (
      !window.confirm(
        `Reset 2FA for "${u.username}"? They'll sign in with their password ` +
          `alone until they re-enroll.`,
      )
    ) {
      return;
    }
    try {
      await resetUser2fa(u.id);
      await load();
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t reset 2FA.'));
    }
  }

  async function remove(u) {
    if (
      !window.confirm(
        `Delete "${u.username}"? Removes their account, sessions, API tokens ` +
          `and passkeys. This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await deleteUser(u.id);
      await load();
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn\u2019t delete the user.'));
    }
  }

  if (loading) return <p className="text-[var(--color-text-muted)]">Loading users…</p>;

  const rowProps = {
    me,
    editingPw,
    setEditingPw,
    setNotice,
    toggleAdmin,
    reset2fa,
    remove,
  };

  const inputCls = 'input mt-1';
  // Text fields share the row's spare width; the checkbox and button don't grow.
  const fieldCls = 'flex w-full min-w-0 flex-col text-xs text-[var(--color-text-muted)] sm:flex-1';

  return (
    <div>
      <PageHeader title="Users" />
      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}

      <Panel
        as="form"
        onSubmit={onCreate}
        className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end"
      >
        <label className={fieldCls}>
          Username
          <input
            required
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className={fieldCls}>
          Display name
          <input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className={fieldCls}>
          Password
          <input
            required
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col text-xs text-[var(--color-text-muted)]">
          <span aria-hidden="true" className="hidden sm:block">&nbsp;</span>
          <span className="mt-1 flex h-[30px] items-center gap-2 text-sm text-[var(--color-text-secondary)]">
            <input
              type="checkbox"
              checked={form.is_admin}
              onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
            />
            Admin
          </span>
        </label>
        <button
          type="submit"
          disabled={creating}
          className="btn btn-primary w-full text-sm sm:w-auto"
        >
          {creating ? 'Adding…' : 'Add user'}
        </button>
      </Panel>

      {notice && (
        <p className="mb-3 flex items-center gap-3 text-sm text-[var(--color-text-secondary)]">
          {notice.text}
          {notice.undo && (
            <button
              onClick={() => {
                const undo = notice.undo;
                setNotice(null);
                undo();
              }}
              className="btn-link text-sm underline"
            >
              Undo
            </button>
          )}
          <button onClick={() => setNotice(null)} className="btn-link ml-auto text-xs" aria-label="Dismiss">
            ×
          </button>
        </p>
      )}

      <Panel flush>
        {/* Desktop table. */}
        <table className="hidden min-w-full text-sm sm:table">
          <thead className="bg-[var(--color-bg-inset)] text-left text-[var(--color-text-muted)]">
            <tr>
              <th className="px-4 py-2 font-medium">Username</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Admin</th>
              <th className="px-4 py-2 font-medium">2FA</th>
              <th className="px-4 py-2 font-medium">Last sign-in</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-border)]">
            {users.map((u) => (
              <UserRow key={u.id} u={u} {...rowProps} />
            ))}
          </tbody>
        </table>

        {/* Phone cards. */}
        <ul className="divide-y divide-[var(--color-border)] sm:hidden">
          {users.map((u) => {
            const self = u.id === me?.id;
            return (
              <li key={u.id} className="space-y-2 px-4 py-3 text-sm">
                <div className="flex items-baseline gap-2">
                  <span className="font-medium text-[var(--color-text-primary)]">
                    {u.display_name || u.username}
                  </span>
                  <span className="text-xs text-[var(--color-text-muted)]">
                    @{u.username}
                    {self && ' · you'}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-muted)]">
                  <AdminToggle u={u} self={self} onToggle={toggleAdmin} label />
                  <span>2FA {u.totp_enabled ? 'on' : 'off'}</span>
                  <span>last sign-in {u.last_login_at ? clock(u.last_login_at) : 'never'}</span>
                </div>
                {editingPw === u.id ? (
                  <PasswordForm
                    user={u}
                    onDone={(text) => {
                      setEditingPw(null);
                      setNotice({ text });
                    }}
                    onCancel={() => setEditingPw(null)}
                  />
                ) : (
                  <RowActions u={u} self={self} {...rowProps} />
                )}
              </li>
            );
          })}
        </ul>

        {users.length === 0 && (
          <p className="px-4 py-6 text-center text-[var(--color-text-muted)]">No users</p>
        )}
      </Panel>
    </div>
  );
}

function AdminToggle({ u, self, onToggle, label = false }) {
  return (
    <label className="flex items-center gap-1.5">
      <input
        type="checkbox"
        checked={u.is_admin}
        disabled={self}
        onChange={() => onToggle(u)}
        aria-label={`${u.username} is an admin`}
        title={self ? "You can't change your own role" : u.is_admin ? 'Remove admin' : 'Make admin'}
        className="disabled:opacity-40"
      />
      {label && 'admin'}
    </label>
  );
}

function RowActions({ u, self, setEditingPw, reset2fa, remove }) {
  return (
    <span className="flex items-center gap-3 sm:justify-end">
      <button onClick={() => setEditingPw(u.id)} className="btn-link text-xs">
        Password
      </button>
      {u.totp_enabled && (
        <button onClick={() => reset2fa(u)} className="btn-link text-xs">
          Reset 2FA
        </button>
      )}
      {!self && (
        <button onClick={() => remove(u)} className="btn-link btn-link-danger text-xs">
          Delete
        </button>
      )}
    </span>
  );
}

function UserRow({ u, me, editingPw, setEditingPw, setNotice, toggleAdmin, reset2fa, remove }) {
  const self = u.id === me?.id;
  return (
    <>
      <tr className="hover:bg-[var(--color-highlight-soft)]">
        <td className="px-4 py-2 text-[var(--color-text-secondary)]">
          @{u.username}
          {self && <span className="text-xs text-[var(--color-text-muted)]"> · you</span>}
        </td>
        <td className="px-4 py-2 text-[var(--color-text-primary)]">
          {u.display_name || <span className="text-[var(--color-text-muted)]">—</span>}
        </td>
        <td className="px-4 py-2">
          <AdminToggle u={u} self={self} onToggle={toggleAdmin} />
        </td>
        <td className="px-4 py-2 text-[var(--color-text-secondary)]">{u.totp_enabled ? 'on' : '—'}</td>
        <td className="px-4 py-2 text-[var(--color-text-muted)]">
          {u.last_login_at ? clock(u.last_login_at) : '—'}
        </td>
        <td className="whitespace-nowrap px-4 py-2 text-right">
          <RowActions u={u} self={self} setEditingPw={setEditingPw} reset2fa={reset2fa} remove={remove} />
        </td>
      </tr>
      {editingPw === u.id && (
        <tr className="bg-[var(--color-bg-inset)]">
          <td colSpan={6} className="px-4 py-3">
            <PasswordForm
              user={u}
              onDone={(text) => {
                setEditingPw(null);
                setNotice({ text });
              }}
              onCancel={() => setEditingPw(null)}
            />
          </td>
        </tr>
      )}
    </>
  );
}
