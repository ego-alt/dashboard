import { useCallback, useEffect, useState } from 'react';
import { apiJson } from '../api';

export default function MonitorPage() {
  const [containers, setContainers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setContainers(await apiJson('/containers'));
      setError('');
    } catch (err) {
      setError(err.body?.detail || err.message || 'Failed to load containers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function action(id, verb) {
    try {
      await apiJson(`/containers/${id}/${verb}`, { method: 'POST' });
      await load();
    } catch (err) {
      setError(err.body?.detail || `Failed to ${verb} container`);
    }
  }

  if (loading) return <p className="text-slate-500">Loading containers…</p>;

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
            {containers.map((c) => (
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
                <td className="px-4 py-2 text-slate-700">{c.cpu_percent ?? '—'}</td>
                <td className="px-4 py-2 text-slate-700">{c.network_rx_kb ?? '—'}</td>
                <td className="px-4 py-2 text-slate-700">{c.network_tx_kb ?? '—'}</td>
                <td className="px-4 py-2 text-slate-700">{c.runtime_seconds ?? '—'}</td>
                <td className="px-4 py-2 text-right whitespace-nowrap">
                  <button
                    onClick={() => action(c.id, 'stop')}
                    className="mr-3 text-xs text-slate-600 hover:text-slate-900"
                  >
                    Stop
                  </button>
                  <button
                    onClick={() => action(c.id, 'restart')}
                    className="text-xs text-slate-600 hover:text-slate-900"
                  >
                    Restart
                  </button>
                </td>
              </tr>
            ))}
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
    </div>
  );
}
