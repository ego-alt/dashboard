import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiJson, backupStatus, containerAction, uptime } from '../api';
import { useAuth } from '../auth.jsx';
import LogsDrawer from '../components/LogsDrawer.jsx';
import Panel from '../components/Panel.jsx';
import { StateDot, UptimeStrip } from '../components/Status.jsx';
import { PROBLEM_RANK, STATE, shownState } from '../lib/state';
import { age, secondsSince, sentence } from '../lib/format';
import { useNow, usePoll } from '../lib/usePoll';

const POLL_MS = 5000;
// On first load, take a second sample this soon after the first so CPU% and
// rates (which need a delta between two reads) populate immediately instead of
// waiting a full poll interval.
const WARM_MS = 1000;
// Data older than this many poll intervals is shown as stale.
const STALE_AFTER = 3;
const UPTIME_POLL_MS = 60_000;

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

const BAR_FILL = { slate: 'bg-[var(--color-text-muted)]', amber: 'bg-amber-500', red: 'bg-red-500' };

function Metric({ label, value, percent, tone = 'slate' }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <dt className="text-xs text-[var(--color-text-muted)]">{label}</dt>
        <dd className="whitespace-nowrap font-mono text-sm text-[var(--color-text-primary)]">{value}</dd>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-bg-inset)]">
        <div
          className={`h-full rounded-full ${BAR_FILL[tone]}`}
          style={{ width: `${Math.min(100, Math.max(0, percent || 0))}%` }}
        />
      </div>
    </div>
  );
}

function HostSection({ live, stale }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');

  const fetchStats = useCallback(async () => {
    try {
      setS(await apiJson('/stats/system'));
      setErr('');
    } catch (e) {
      setErr(e.body?.detail || 'Couldn\u2019t load host stats.');
    }
  }, []);

  usePoll(fetchStats, POLL_MS, live);

  if (!s)
    return (
      <Panel title="Host" className="mb-6">
        <p className={`text-sm ${err ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'}`}>
          {err || 'Loading…'}
        </p>
      </Panel>
    );

  const memPct = s.memory_percent;
  return (
    <Panel title="Host" className={`mb-6 transition-opacity ${stale || err ? 'opacity-50' : ''}`}>
      {/* Four across when the card is wide enough, else two (phones, or beside the logs pane). */}
      <div className="@container">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 @2xl:grid-cols-4">
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
      </div>
    </Panel>
  );
}

function BackupsSection() {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');

  // Backups run nightly, so this isn't on the 5s poll — fetched on mount and
  // on demand via the Refresh button (the only card that still needs one).
  const load = useCallback(() => {
    backupStatus()
      .then((data) => {
        setS(data);
        setErr('');
      })
      .catch((e) => setErr(e.body?.detail || 'Couldn’t load the backup status.'));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const card = (body, badge = null) => (
    <Panel
      title="Backups"
      className="mt-6"
      aside={
        <>
          {badge}
          <button onClick={load} className="btn-link text-xs">
            Refresh
          </button>
        </>
      }
    >
      {body}
    </Panel>
  );

  if (err)
    return card(<p className="text-sm text-[var(--color-danger)]">{err}</p>);
  if (!s)
    return card(<p className="text-sm text-[var(--color-text-muted)]">Loading…</p>);
  if (!s.available)
    return card(<p className="text-sm text-[var(--color-text-muted)]">No backup has run yet.</p>);

  const healthy = s.ok && !s.stale;
  const label = !s.ok ? 'failed' : s.stale ? 'stale' : 'healthy';
  const pill = healthy ? 'bg-green-500/15 text-green-300' : 'bg-red-500/15 text-red-300';

  return (
    card(
      <>
        {Array.isArray(s.databases) && s.databases.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {s.databases.map((d) => (
              <span
                key={d.app}
                className={`rounded-full px-2 py-0.5 text-xs ${
                  d.ok ? 'bg-[var(--color-bg-inset)] text-[var(--color-text-secondary)]' : 'bg-red-500/15 text-red-300'
                }`}
              >
                {d.app} {d.ok ? '✓' : '✗'}
              </span>
            ))}
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-[var(--color-text-muted)]">Last run</dt>
            <dd className="text-[var(--color-text-primary)]">{fmtAge(s.age_seconds)}</dd>
          </div>
          <div>
            <dt className="text-[var(--color-text-muted)]">Duration</dt>
            <dd className="text-[var(--color-text-primary)]">
              {s.duration_seconds != null ? `${s.duration_seconds}s` : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--color-text-muted)]">Snapshots</dt>
            <dd className="text-[var(--color-text-primary)]">{s.snapshot_count ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-[var(--color-text-muted)]">Repo size</dt>
            <dd className="text-[var(--color-text-primary)]">{fmtBytes(s.repo_bytes)}</dd>
          </div>
        </dl>
        {!healthy && (
          <p className="mt-3 text-sm text-[var(--color-danger)]">
            {s.error || 'Last backup is stale — check the timer on the Pi.'}
          </p>
        )}
      </>,
      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pill}`}>{label}</span>,
    )
  );
}

const VERBS = {
  start: { pending: 'starting…', done: 'started' },
  stop: { pending: 'stopping…', done: 'stopped' },
  restart: { pending: 'restarting…', done: 'restarted' },
};

const CONFIRM = {
  stop: (n) => `Stop ${n}? Anyone using it will be cut off until it's started again.`,
  restart: (n) => `Restart ${n}? It will be unavailable for a few seconds.`,
};

/** Problems first, then the hub's services, then infrastructure. */
function sortContainers(rows) {
  return [...rows].sort(
    (a, b) =>
      (PROBLEM_RANK[a.state] ?? 2) - (PROBLEM_RANK[b.state] ?? 2) ||
      (b.hub ? 1 : 0) - (a.hub ? 1 : 0) ||
      a.name.localeCompare(b.name),
  );
}

function uptimeText(c, now) {
  if (c.state === 'down') {
    const s = secondsSince(c.finished_at, now);
    return s == null ? 'down' : `down ${age(s)}`;
  }
  const s = secondsSince(c.started_at, now);
  return s == null ? '' : `up ${age(s)}`;
}

function cpuText(c) {
  if (c.cpu_percent == null) return '—';
  if (c.cpu_percent > 0 && c.cpu_percent < 0.1) return '<0.1 %';
  return `${c.cpu_percent.toFixed(1)} %`;
}

function netText(c) {
  if (c.state === 'down' || c.rx_rate_kbs == null) return '—';
  return `↓ ${fmtRate(c.rx_rate_kbs)}  ↑ ${fmtRate(c.tx_rate_kbs)}`;
}

function StateCell({ c, pending }) {
  if (pending)
    return <span className="text-xs text-[var(--color-text-secondary)]">{VERBS[pending].pending}</span>;
  const s = STATE[shownState(c)] || STATE.unknown;
  return (
    <span className={`flex items-center gap-1.5 text-xs ${s.text}`} title={c.health ? `health: ${c.health} · docker: ${c.status}` : `docker: ${c.status}`}>
      <StateDot state={c.state} />
      {s.label}
    </span>
  );
}

function Actions({ c, isAdmin, pending, onAction, onLogs }) {
  const logs = (
    <button onClick={() => onLogs(c)} className="btn-link text-xs">
      Logs
    </button>
  );
  if (!isAdmin) return logs;
  if (PROTECTED.has(c.name))
    return (
      <span className="flex items-center justify-end gap-3">
        {logs}
        <span className="text-xs text-[var(--color-text-muted)]" title="Stopping this would cut off the dashboard itself">
          protected
        </span>
      </span>
    );
  const busy = !!pending;
  const btn = (verb, label) => (
    <button onClick={() => onAction(c, verb)} disabled={busy} className="btn-link text-xs">
      {label}
    </button>
  );
  return (
    <span className="flex items-center justify-end gap-3">
      {logs}
      {c.status === 'running' ? (
        <>
          {btn('stop', 'Stop')}
          {btn('restart', 'Restart')}
        </>
      ) : (
        btn('start', 'Start')
      )}
    </span>
  );
}

export default function MonitorPage() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [params, setParams] = useSearchParams();
  const [containers, setContainers] = useState(null);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);
  const [live, setLive] = useState(true);
  const [pending, setPending] = useState({}); // id → verb in flight
  const [notice, setNotice] = useState('');
  const [uptime24, setUptime24] = useState(null);
  const now = useNow(1000);
  // Previous stats snapshot ({ ts, byId }) — successive reads are diffed into
  // CPU% and network rate (the backend returns raw cumulative counters).
  const prevRef = useRef(null);

  // One stats read → diff against the previous snapshot → update rows.
  const sampleStats = useCallback(async () => {
    try {
      const withStats = await apiJson('/containers?stats=1');
      const ts = Date.now();
      const prev = prevRef.current;
      const dt = prev ? (ts - prev.ts) / 1000 : 0;
      const rows = withStats.map((c) => {
        const p = prev?.byId?.[c.id];
        if (p && dt > 0 && c.cpu_total != null) {
          // CPU% from the delta, mirroring `docker stats`. Guards on positive
          // deltas, so a container restart (counter reset) reads 0, not negative.
          const cpuDelta = c.cpu_total - p.cpu;
          const sysDelta = c.system_cpu - p.sys;
          const cpuPct =
            sysDelta > 0 && cpuDelta > 0 ? (cpuDelta / sysDelta) * (c.online_cpus || 1) * 100 : 0;
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
        ts,
        byId: Object.fromEntries(
          withStats
            .filter((c) => c.cpu_total != null)
            .map((c) => [
              c.id,
              { rx: c.network_rx_bytes, tx: c.network_tx_bytes, cpu: c.cpu_total, sys: c.system_cpu },
            ]),
        ),
      };
      setContainers(rows);
      setUpdatedAt(ts);
      setError('');
    } catch (err) {
      setError(sentence(err.body?.detail, 'Couldn’t reach the dashboard.'));
    }
  }, []);

  // Fast first paint: metadata before the per-container stats, then a warm
  // second read so CPU% and rates show within a second, not after 5 s.
  useEffect(() => {
    apiJson('/containers')
      .then((rows) => setContainers((cur) => cur ?? rows))
      .catch(() => {});
    const id = setTimeout(sampleStats, WARM_MS);
    return () => clearTimeout(id);
  }, [sampleStats]);

  usePoll(sampleStats, POLL_MS, live);
  usePoll(
    () => uptime(1).then(setUptime24).catch(() => {}),
    UPTIME_POLL_MS,
    true,
  );

  const sorted = useMemo(() => (containers ? sortContainers(containers) : []), [containers]);

  // ?logs=<name> (from a Services tile) opens that container's logs.
  const logsName = params.get('logs');
  const logsFor = logsName ? sorted.find((c) => c.name === logsName) : null;
  const openLogs = useCallback(
    (c) => setParams((p) => ({ ...Object.fromEntries(p), logs: c.name }), { replace: true }),
    [setParams],
  );
  const closeLogs = useCallback(
    () =>
      setParams(
        (p) => {
          const next = Object.fromEntries(p);
          delete next.logs;
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  useEffect(() => {
    if (!notice) return undefined;
    const id = setTimeout(() => setNotice(''), 6000);
    return () => clearTimeout(id);
  }, [notice]);

  async function action(c, verb) {
    if (CONFIRM[verb] && !window.confirm(CONFIRM[verb](c.name))) return;
    setPending((p) => ({ ...p, [c.id]: verb }));
    setNotice('');
    try {
      await containerAction(c.id, verb);
      setNotice(`${c.name} ${VERBS[verb].done}.`);
      setError('');
    } catch (err) {
      setError(`Couldn’t ${verb} ${c.name}: ${err.body?.detail || 'no response'}`);
    } finally {
      await sampleStats();
      setPending((p) => {
        const next = { ...p };
        delete next[c.id];
        return next;
      });
    }
  }

  const ageS = updatedAt ? (now - updatedAt) / 1000 : null;
  const stale = !!error || (live && ageS != null && ageS > (STALE_AFTER * POLL_MS) / 1000);
  const freshness =
    updatedAt == null
      ? ''
      : stale
        ? `stale · last update ${age(ageS)} ago`
        : live
          ? `updated ${age(ageS)} ago`
          : `paused · last update ${age(ageS)} ago`;

  const rowProps = (c) => ({
    c,
    isAdmin,
    pending: pending[c.id],
    onAction: action,
    onLogs: openLogs,
  });

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Monitor</h2>
        <span
          className={`ml-auto text-xs ${stale ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'}`}
          aria-live="polite"
        >
          {freshness}
        </span>
        <button
          onClick={() => setLive((v) => !v)}
          className={`btn text-sm ${
            stale
              ? 'border-red-500/40 bg-red-500/10 text-red-300'
              : live
                ? 'border-green-500/40 bg-green-500/10 text-green-300'
                : 'btn-secondary'
          }`}
          title={live ? `Live: refreshing every ${POLL_MS / 1000} s. Click to pause.` : 'Paused. Click to resume.'}
        >
          <span
            className={`h-2 w-2 rounded-full ${
              stale ? 'bg-red-500' : live ? 'bg-green-500' : 'bg-[var(--color-text-muted)]'
            }`}
          />
          {stale ? 'Stale' : live ? 'Live' : 'Paused'}
        </button>
      </div>

      <HostSection live={live} stale={stale} />

      <Panel
        flush
        title="Containers"
        aside={notice && <span className="text-xs text-[var(--color-text-secondary)]">{notice}</span>}
      >
        {error && <p className="px-4 pt-3 text-sm text-[var(--color-danger)]">{error}</p>}
        {containers === null ? (
          <p className="px-4 py-6 text-[var(--color-text-muted)]">{error ? '' : 'Loading containers…'}</p>
        ) : sorted.length === 0 ? (
          <p className="px-4 py-6 text-center text-[var(--color-text-muted)]">No containers</p>
        ) : (
          <div className={`@container transition-opacity ${stale ? 'opacity-50' : ''}`}>
            {/* Wide card: one table row per container. Chosen by the card's
                width, not the screen's, so it also switches when the logs
                pane takes room. */}
            <table className="hidden min-w-full text-sm @4xl:table">
              <thead className="bg-[var(--color-bg-inset)] text-left text-[var(--color-text-muted)]">
                <tr>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">State</th>
                  <th className="px-3 py-2 font-medium">Uptime</th>
                  <th className="w-44 px-3 py-2 font-medium">Last 24 h</th>
                  <th className="px-3 py-2 text-right font-medium">CPU</th>
                  <th className="px-3 py-2 text-right font-medium">Memory</th>
                  <th className="hidden px-3 py-2 text-right font-medium @5xl:table-cell">Network</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {sorted.map((c) => (
                  <tr key={c.id} className="hover:bg-[var(--color-highlight-soft)]">
                    <td className="whitespace-nowrap px-4 py-2">
                      <button
                        onClick={() => openLogs(c)}
                        className="font-mono text-[var(--color-text-primary)] hover:underline"
                        title="Show logs"
                      >
                        {c.name}
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <StateCell c={c} pending={pending[c.id]} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-[var(--color-text-secondary)]">
                      {uptimeText(c, now)}
                      {c.restart_count > 0 && (
                        <span className="ml-2 text-xs text-[var(--color-text-muted)]" title={`Restarted ${c.restart_count} times by Docker`}>
                          ↻{c.restart_count}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <UptimeStrip data={uptime24} name={c.name} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)]">
                      {c.state === 'down' ? '—' : cpuText(c)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)]">
                      {c.state === 'down' ? '—' : fmtMem(c)}
                    </td>
                    <td className="hidden whitespace-pre px-3 py-2 text-right font-mono text-xs text-[var(--color-text-secondary)] @5xl:table-cell">
                      {netText(c)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-right">
                      <Actions {...rowProps(c)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Narrow card (phones, or beside the logs pane): one compact card per container. */}
            <ul className="divide-y divide-[var(--color-border)] @4xl:hidden">
              {sorted.map((c) => (
                <li key={c.id} className="space-y-2 px-4 py-3">
                  <div className="flex items-center gap-3">
                    <button onClick={() => openLogs(c)} className="font-mono text-sm text-[var(--color-text-primary)]">
                      {c.name}
                    </button>
                    <StateCell c={c} pending={pending[c.id]} />
                    <span className="ml-auto text-xs text-[var(--color-text-muted)]">
                      {uptimeText(c, now)}
                      {c.restart_count > 0 && ` · ↻${c.restart_count}`}
                    </span>
                  </div>
                  <UptimeStrip data={uptime24} name={c.name} />
                  <div className="flex items-center gap-3 font-mono text-xs text-[var(--color-text-secondary)]">
                    {c.state !== 'down' && (
                      <span>
                        {cpuText(c)} · {fmtMem(c)}
                      </span>
                    )}
                    <span className="ml-auto font-sans">
                      <Actions {...rowProps(c)} />
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Panel>

      <BackupsSection />

      {logsFor && <LogsDrawer container={logsFor} onClose={closeLogs} />}
    </div>
  );
}
