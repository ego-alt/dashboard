import { useCallback, useEffect, useRef, useState } from 'react';
import { apiJson, backupStatus } from '../api';
import { useAuth } from '../auth.jsx';

const POLL_MS = 5000;
// On first load, take a second sample this soon after the first so CPU% and
// rates (which need a delta between two reads) populate immediately instead of
// waiting a full poll interval.
const WARM_MS = 1000;

// Mirrors the backend PROTECTED_CONTAINERS default — controls are hidden for
// these even for admins; the server is the real backstop (returns 409).
const PROTECTED = new Set(['dashboard', 'home-nginx']);

const CARD = 'rounded-xl border border-slate-200 bg-white shadow-sm';

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

function fmtRate(kbs) {
  if (kbs == null) return '—';
  if (kbs >= 1024) return `${(kbs / 1024).toFixed(1)} MB/s`;
  return `${kbs.toFixed(kbs < 10 ? 1 : 0)} KB/s`;
}

function fmtMem(c) {
  if (c.mem_used_mb == null) return '—';
  const used =
    c.mem_used_mb >= 1024
      ? `${(c.mem_used_mb / 1024).toFixed(1)} GB`
      : `${Math.round(c.mem_used_mb)} MB`;
  return c.mem_percent != null ? `${used} (${c.mem_percent.toFixed(0)}%)` : used;
}

// Usage bars go amber past 75% and red past 90% so a filling disk reads at a
// glance. CPU temp is colored against the Pi's throttle points (~80/85°C).
function pctTone(p) {
  if (p == null) return 'slate';
  if (p >= 90) return 'red';
  if (p >= 75) return 'amber';
  return 'slate';
}

function tempTone(t) {
  if (t == null) return 'slate';
  if (t >= 80) return 'red';
  if (t >= 70) return 'amber';
  return 'slate';
}

const BAR_FILL = { slate: 'bg-slate-400', amber: 'bg-amber-500', red: 'bg-red-500' };

function Metric({ label, value, percent, tone = 'slate' }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <dt className="text-xs text-slate-500">{label}</dt>
        <dd className="font-mono text-sm text-slate-900">{value}</dd>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full ${BAR_FILL[tone]}`}
          style={{ width: `${Math.min(100, Math.max(0, percent || 0))}%` }}
        />
      </div>
    </div>
  );
}

function HostSection({ live, hidden }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');
  const inFlight = useRef(false);

  const fetchStats = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setS(await apiJson('/stats/system'));
      setErr('');
    } catch (e) {
      setErr(e.body?.detail || 'Failed to load host stats');
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    if (!live || hidden) return undefined;
    const id = setInterval(fetchStats, POLL_MS);
    return () => clearInterval(id);
  }, [live, hidden, fetchStats]);

  const heading = (
    <h3 className="mb-3 text-base font-semibold text-slate-900">Host</h3>
  );

  if (err)
    return (
      <section className={`${CARD} mb-6 p-4`}>
        {heading}
        <p className="text-sm text-red-600">{err}</p>
      </section>
    );
  if (!s)
    return (
      <section className={`${CARD} mb-6 p-4`}>
        {heading}
        <p className="text-sm text-slate-500">Loading…</p>
      </section>
    );

  const memPct = s.memory_percent;
  return (
    <section className={`${CARD} mb-6 p-4`}>
      {heading}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Metric
          label="CPU"
          value={`${Math.round(s.cpu_percent)}%`}
          percent={s.cpu_percent}
          tone={pctTone(s.cpu_percent)}
        />
        <Metric
          label="Memory"
          value={`${(s.memory_used / 1024).toFixed(1)}/${(s.memory_total / 1024).toFixed(1)} GB`}
          percent={memPct}
          tone={pctTone(memPct)}
        />
        <Metric
          label="Disk /"
          value={
            s.disk_percent != null
              ? `${s.disk_used}/${s.disk_total} GB`
              : '—'
          }
          percent={s.disk_percent}
          tone={pctTone(s.disk_percent)}
        />
        {s.cpu_temp_c != null && (
          <Metric
            label="CPU temp"
            value={`${s.cpu_temp_c.toFixed(1)} °C`}
            percent={(s.cpu_temp_c / 85) * 100}
            tone={tempTone(s.cpu_temp_c)}
          />
        )}
        {s.data_mount && (
          <Metric
            label={`Data ${s.data_mount}`}
            value={`${s.data_disk_used}/${s.data_disk_total} GB`}
            percent={s.data_disk_percent}
            tone={pctTone(s.data_disk_percent)}
          />
        )}
      </dl>
    </section>
  );
}

function BackupsSection() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    backupStatus()
      .then(setS)
      .catch((e) => setErr(e.body?.detail || 'Failed to load backup status'));
  }, []);

  const heading = (extra) => (
    <div className="mb-3 flex items-center gap-3">
      <h3 className="text-base font-semibold text-slate-900">Backups</h3>
      {extra}
    </div>
  );

  if (err)
    return (
      <section className={`mt-6 ${CARD} p-4`}>
        {heading()}
        <p className="text-sm text-red-600">{err}</p>
      </section>
    );
  if (!s)
    return (
      <section className={`mt-6 ${CARD} p-4`}>
        {heading()}
        <p className="text-sm text-slate-500">Loading…</p>
      </section>
    );
  if (!s.available)
    return (
      <section className={`mt-6 ${CARD} p-4`}>
        {heading()}
        <p className="text-sm text-slate-500">No backup has run yet.</p>
      </section>
    );

  const healthy = s.ok && !s.stale;
  const label = !s.ok ? 'failed' : s.stale ? 'stale' : 'healthy';
  const pill = healthy ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800';

  return (
    <section className={`mt-6 ${CARD} p-4`}>
      {heading(
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pill}`}>
          {label}
        </span>,
      )}
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
    </section>
  );
}

export default function MonitorPage() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [containers, setContainers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statsPending, setStatsPending] = useState(true);
  const [error, setError] = useState('');
  const [live, setLive] = useState(true);
  const [hidden, setHidden] = useState(false);
  // Previous stats snapshot ({ ts, byId }) — successive reads are diffed into
  // CPU% and network rate (the backend now returns raw cumulative counters).
  const prevRef = useRef(null);
  // Guards against overlapping requests: a slow poll on the Pi must not let the
  // next interval tick stack a second in-flight fetch on top of it.
  const inFlightRef = useRef(false);

  // One stats read → diff against the previous snapshot → update rows.
  const sampleStats = useCallback(async () => {
    const withStats = await apiJson('/containers?stats=1');
    const now = Date.now();
    const prev = prevRef.current;
    const dt = prev ? (now - prev.ts) / 1000 : 0;
    const rows = withStats.map((c) => {
      const p = prev?.byId?.[c.id];
      if (p && dt > 0 && c.cpu_total != null) {
        // CPU% from the delta, mirroring `docker stats`. Guards on positive
        // deltas, so a container restart (counter reset) reads 0, not negative.
        const cpuDelta = c.cpu_total - p.cpu;
        const sysDelta = c.system_cpu - p.sys;
        const cpuPct =
          sysDelta > 0 && cpuDelta > 0
            ? Math.round((cpuDelta / sysDelta) * (c.online_cpus || 1) * 10000) / 100
            : 0;
        return {
          ...c,
          cpu_percent: cpuPct,
          rx_rate_kbs: Math.max(0, (c.network_rx_bytes - p.rx) / 1024 / dt),
          tx_rate_kbs: Math.max(0, (c.network_tx_bytes - p.tx) / 1024 / dt),
        };
      }
      return c;
    });
    prevRef.current = {
      ts: now,
      byId: Object.fromEntries(
        withStats
          .filter((c) => c.cpu_total != null)
          .map((c) => [
            c.id,
            {
              rx: c.network_rx_bytes,
              tx: c.network_tx_bytes,
              cpu: c.cpu_total,
              sys: c.system_cpu,
            },
          ]),
      ),
    };
    setContainers(rows);
    setError('');
  }, []);

  const load = useCallback(
    async (initial = false) => {
      if (inFlightRef.current) return; // in-flight guard
      inFlightRef.current = true;
      try {
        if (initial) {
          // Fast first paint: metadata before the per-container stats.
          setContainers(await apiJson('/containers'));
          setLoading(false);
        }
        await sampleStats();
        if (initial) {
          // Warm second read so CPU%/rates show on first paint, not after 5s.
          await new Promise((r) => setTimeout(r, WARM_MS));
          await sampleStats();
        }
      } catch (err) {
        setError(err.body?.detail || err.message || 'Failed to load containers');
      } finally {
        setLoading(false);
        setStatsPending(false);
        inFlightRef.current = false;
      }
    },
    [sampleStats],
  );

  useEffect(() => {
    load(true);
  }, [load]);

  // Pause polling for a backgrounded tab — no point sampling the daemon for a
  // page nobody's looking at.
  useEffect(() => {
    const onVis = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  useEffect(() => {
    if (!live || hidden) return undefined;
    const id = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(id);
  }, [live, hidden, load]);

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
      await load(true);
    } catch (err) {
      setError(err.body?.detail || `Failed to ${verb} ${c.name}`);
    }
  }

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Monitor</h2>

      <HostSection live={live} hidden={hidden} />

      <section className={`${CARD} overflow-hidden`}>
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-base font-semibold text-slate-900">Containers</h3>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setLive((v) => !v)}
              className={`flex items-center gap-1.5 rounded-md border px-3 py-1 text-sm ${
                live
                  ? 'border-green-300 bg-green-50 text-green-800'
                  : 'border-slate-300 hover:bg-slate-50'
              }`}
              title={live ? `Live — refreshing every ${POLL_MS / 1000}s` : 'Paused'}
            >
              <span
                className={`h-2 w-2 rounded-full ${live ? 'bg-green-500' : 'bg-slate-400'}`}
              />
              {live ? 'Live' : 'Paused'}
            </button>
            <button
              onClick={() => load(true)}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>
        </div>
        {error && <p className="px-4 pt-3 text-sm text-red-600">{error}</p>}
        {loading ? (
          <p className="px-4 py-6 text-slate-500">Loading containers…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">CPU %</th>
                  <th className="px-4 py-2 font-medium">Memory</th>
                  <th className="px-4 py-2 font-medium">RX/s</th>
                  <th className="px-4 py-2 font-medium">TX/s</th>
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
                        {statsPending && c.status === 'running' && c.cpu_percent == null
                          ? '…'
                          : (c.cpu_percent ?? '—')}
                      </td>
                      <td className="px-4 py-2 text-slate-700">
                        {statsPending && c.status === 'running' && c.mem_used_mb == null
                          ? '…'
                          : fmtMem(c)}
                      </td>
                      <td className="px-4 py-2 text-slate-700">
                        {statsPending && c.status === 'running' && c.rx_rate_kbs == null
                          ? '…'
                          : c.status === 'running'
                            ? fmtRate(c.rx_rate_kbs)
                            : '—'}
                      </td>
                      <td className="px-4 py-2 text-slate-700">
                        {statsPending && c.status === 'running' && c.tx_rate_kbs == null
                          ? '…'
                          : c.status === 'running'
                            ? fmtRate(c.tx_rate_kbs)
                            : '—'}
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
      </section>

      <BackupsSection />
    </div>
  );
}
