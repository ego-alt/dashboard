import { useCallback, useEffect, useState } from 'react';
import { apiJson, backupStatus } from '../api';
import { useAuth } from '../auth.jsx';

// Mirrors the backend PROTECTED_CONTAINERS default — controls are hidden for
// these even for admins; the server is the real backstop (returns 409).
const PROTECTED = new Set(['dashboard', 'home-nginx']);

function fmtAge(s) {
  if (s == null) return '—';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function fmtBytes(b) {
  if (b == null) return '—';
  return b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(0)} MB`;
}

function BackupsCard() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    backupStatus()
      .then(setS)
      .catch((e) => setErr(e.body?.detail || 'Failed to load backup status'));
  }, []);

  const wrap = 'mt-6 rounded-lg border border-slate-200 bg-white p-4';
  if (err)
    return (
      <div className={wrap}>
        <p className="text-sm text-red-600">{err}</p>
      </div>
    );
  if (!s)
    return (
      <div className={wrap}>
        <p className="text-sm text-slate-500">Loading backups…</p>
      </div>
    );
  if (!s.available)
    return (
      <div className={wrap}>
        <h2 className="text-lg font-semibold text-slate-900">Backups</h2>
        <p className="mt-1 text-sm text-slate-500">No backup has run yet.</p>
      </div>
    );

  const healthy = s.ok && !s.stale;
  const label = !s.ok ? 'failed' : s.stale ? 'stale' : 'healthy';
  const pill = healthy ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';

  return (
    <div className={wrap}>
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Backups</h2>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pill}`}>
          {label}
        </span>
      </div>
      {Array.isArray(s.databases) && s.databases.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {s.databases.map((d) => (
            <span
              key={d.app}
              className={`rounded-full px-2 py-0.5 text-xs ${
                d.ok ? 'bg-slate-100 text-slate-700' : 'bg-red-100 text-red-800'
              }`}
            >
              {d.app} {d.ok ? '✓' : '✗'}
            </span>
          ))}
        </div>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-slate-500">Last run</dt>
          <dd className="text-slate-900">{fmtAge(s.age_seconds)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Duration</dt>
          <dd className="text-slate-900">
            {s.duration_seconds != null ? `${s.duration_seconds}s` : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Snapshots</dt>
          <dd className="text-slate-900">{s.snapshot_count ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Repo size</dt>
          <dd className="text-slate-900">{fmtBytes(s.repo_bytes)}</dd>
        </div>
      </dl>
      {!healthy && (
        <p className="mt-3 text-sm text-red-600">
          {s.error || 'Last backup is stale — check the timer on the Pi.'}
        </p>
      )}
    </div>
  );
}

export default function MonitorPage() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [containers, setContainers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setStatsLoading(true);
    try {
      const rows = await apiJson('/containers');
      setContainers(rows);
      setError('');
      setLoading(false);

      const withStats = await apiJson('/containers?stats=1');
      setContainers(withStats);
    } catch (err) {
      setError(err.body?.detail || err.message || 'Failed to load containers');
    } finally {
      setLoading(false);
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function action(c, verb) {
    if (
      !window.confirm(
        `${verb} container "${c.name}"? This affects the running service.`,
      )
    ) {
      return;
    }
    try {
      await apiJson(`/containers/${c.id}/${verb}`, { method: 'POST' });
      await load();
    } catch (err) {
      setError(err.body?.detail || `Failed to ${verb} ${c.name}`);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">Containers</h2>
        <button
          onClick={load}
          className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Loading containers…</p>
      ) : (
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">CPU %</th>
              <th className="px-4 py-2 font-medium">RX KB</th>
              <th className="px-4 py-2 font-medium">TX KB</th>
              <th className="px-4 py-2 font-medium">Runtime s</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {containers.map((c) => {
              const protectedC = PROTECTED.has(c.name);
              return (
                <tr key={c.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-slate-800">{c.name}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        c.status === 'running'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-slate-200 text-slate-700'
                      }`}
                    >
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {statsLoading && c.status === 'running' && c.cpu_percent == null
                      ? '…'
                      : (c.cpu_percent ?? '—')}
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {statsLoading && c.status === 'running' && c.network_rx_kb == null
                      ? '…'
                      : (c.network_rx_kb ?? '—')}
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {statsLoading && c.status === 'running' && c.network_tx_kb == null
                      ? '…'
                      : (c.network_tx_kb ?? '—')}
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {statsLoading && c.status === 'running' && c.runtime_seconds == null
                      ? '…'
                      : (c.runtime_seconds ?? '—')}
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {!isAdmin ? null : protectedC ? (
                      <span className="text-xs text-slate-400">protected</span>
                    ) : (
                      <>
                        <button
                          onClick={() => action(c, 'stop')}
                          className="mr-3 text-xs text-slate-600 hover:text-slate-900"
                        >
                          Stop
                        </button>
                        <button
                          onClick={() => action(c, 'restart')}
                          className="text-xs text-slate-600 hover:text-slate-900"
                        >
                          Restart
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
            {containers.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                  No containers
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      )}
      <BackupsCard />
    </div>
  );
}
