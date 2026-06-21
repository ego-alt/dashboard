import { useCallback, useEffect, useState } from 'react';
import {
  listUsers,
  createUser,
  setUserPassword,
  setUserAdmin,
  resetUser2fa,
  deleteUser,
} from '../api';
import { useAuth } from '../auth.jsx';

const BLANK = { username: '', display_name: '', password: '', is_admin: false };

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState(BLANK);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await listUsers());
      setError('');
    } catch (err) {
      setError(err.body?.detail || err.message || 'Failed to load users');
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
      setError(err.body?.detail || 'Failed to create user');
    } finally {
      setCreating(false);
    }
  }

  async function resetPassword(u) {
    const pw = window.prompt(`New password for "${u.username}" (min 8 chars):`);
    if (!pw) return;
    try {
      await setUserPassword(u.id, pw);
      setError('');
    } catch (err) {
      setError(err.body?.detail || 'Failed to set password');
    }
  }

  async function toggleAdmin(u) {
    try {
      await setUserAdmin(u.id, !u.is_admin);
      await load();
    } catch (err) {
      setError(err.body?.detail || 'Failed to change role');
    }
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
      setError(err.body?.detail || 'Failed to reset 2FA');
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
      setError(err.body?.detail || 'Failed to delete user');
    }
  }

  if (loading) return <p className="text-slate-500">Loading users…</p>;

  const inputCls =
    'mt-1 rounded-md border border-slate-300 px-2 py-1 text-sm text-slate-900';

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Users</h2>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}

      <form
        onSubmit={onCreate}
        className="mb-6 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <label className="flex flex-col text-xs text-slate-500">
          Username
          <input
            required
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          Display name
          <input
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          Password
          <input
            required
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col text-xs text-slate-500">
          <span aria-hidden="true">&nbsp;</span>
          <span className="mt-1 flex h-[30px] items-center gap-2 text-sm text-slate-700">
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
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {creating ? 'Adding…' : 'Add user'}
        </button>
      </form>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">User</th>
              <th className="px-4 py-2 font-medium">Admin</th>
              <th className="px-4 py-2 font-medium">2FA</th>
              <th className="px-4 py-2 font-medium">Last login</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <div className="font-medium text-slate-900">
                      {u.display_name || u.username}
                    </div>
                    <div className="text-xs text-slate-500">
                      @{u.username}
                      {self && ' · you'}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={u.is_admin}
                      disabled={self}
                      onChange={() => toggleAdmin(u)}
                      aria-label={`${u.username} is an admin`}
                      title={self ? "You can't change your own role" : 'Toggle admin'}
                      className="disabled:opacity-40"
                    />
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {u.totp_enabled ? 'on' : '—'}
                  </td>
                  <td className="px-4 py-2 text-slate-500">
                    {u.last_login_at
                      ? new Date(u.last_login_at).toLocaleString()
                      : '—'}
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    <button
                      onClick={() => resetPassword(u)}
                      className="mr-3 text-xs text-slate-600 hover:text-slate-900"
                    >
                      Password
                    </button>
                    {u.totp_enabled && (
                      <button
                        onClick={() => reset2fa(u)}
                        className="mr-3 text-xs text-slate-600 hover:text-slate-900"
                      >
                        Reset 2FA
                      </button>
                    )}
                    <button
                      onClick={() => remove(u)}
                      disabled={self}
                      className="text-xs text-red-600 hover:text-red-800 disabled:text-slate-300"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                  No users
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
