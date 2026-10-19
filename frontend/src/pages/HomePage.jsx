import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiJson, backupStatus, containerAction, uptime } from '../api';
import { useAuth } from '../auth.jsx';
import PageHeader from '../components/PageHeader.jsx';
import ServiceIcon from '../components/ServiceIcon.jsx';
import { StateDot, UptimeStrip } from '../components/Status.jsx';
import { age, clock, secondsSince } from '../lib/format';
import { STATE, shownState } from '../lib/state';
import { usePoll } from '../lib/usePoll';

const SERVICES_POLL_MS = 30_000;
const UPTIME_POLL_MS = 5 * 60_000;
const UPTIME_DAYS = 30;

function sinceText(s) {
  const label = STATE[shownState(s)]?.label ?? s.state;
  if (!s.since) return label;
  if (s.state === 'up') return `up ${age(secondsSince(s.since))}`;
  return `${label} since ${clock(s.since)}`;
}

/** One line under the heading: everything fine, or what needs you. Admins
 * also see the last backup and the fullest disk. */
function StatusLine({ services, dockerDown, host, backup }) {
  const problems = services.filter((s) => s.state === 'down' || s.state === 'degraded');
  const parts = [];
  let bad = dockerDown || problems.length > 0;

  if (dockerDown) parts.push('can’t reach Docker on the Pi; service links still work');
  else if (problems.length === 0) parts.push(`all ${services.length} services up`);
  else
    for (const s of problems)
      parts.push(`${s.display_name} ${shownState(s)}${s.since ? ` since ${clock(s.since)}` : ''}`);

  if (backup) {
    if (!backup.available) parts.push('no backup yet');
    else if (!backup.ok) {
      parts.push('last backup failed');
      bad = true;
    } else if (backup.stale) {
      parts.push(`backup stale (${age(backup.age_seconds)} ago)`);
      bad = true;
    } else parts.push(`backup ${age(backup.age_seconds)} ago`);
  }
  if (host) {
    const disks = [host.disk_percent, host.data_disk_percent].filter((p) => p != null);
    if (disks.length) {
      const fullest = Math.max(...disks);
      if (fullest >= 90) bad = true;
      parts.push(`disk ${Math.round(fullest)}\u00a0%`);
    }
  }

  return (
    <p
      className={`flex items-center gap-2 text-sm ${
        bad ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'
      }`}
      aria-live="polite"
    >
      <StateDot state={bad ? 'down' : 'up'} />
      <span>{parts.join(' · ')}</span>
    </p>
  );
}

function Tile({ s, uptime30, isAdmin, onStart, busy }) {
  const st = STATE[shownState(s)] || STATE.unknown;
  const down = s.state === 'down';
  const problem = down || s.state === 'degraded';
  const actions = isAdmin && problem && s.state !== 'unknown';
  return (
    <div
      className={`bp-card bp-ticks relative flex h-full flex-col gap-5 px-5 py-5 ${down ? '' : 'bp-card-link'}`}
      title={down ? `${s.display_name} is down` : undefined}
    >
      {/* The whole tile opens the app in a new tab, unless the app is down. */}
      {!down && (
        <a
          href={s.route_prefix}
          target="_blank"
          rel="noopener"
          className="absolute inset-0 z-0"
          aria-label={`Open ${s.display_name} in a new tab`}
        />
      )}
      <div className="flex items-start gap-3">
        <span className={down ? 'opacity-60' : ''}>
          <ServiceIcon icon={s.icon} iconUrl={s.icon_url} name={s.display_name} slug={s.slug} />
        </span>
        <div className={`min-w-0 flex-1 ${down ? 'opacity-60' : ''}`}>
          <div className="font-medium text-[var(--color-text-primary)]">{s.display_name}</div>
          {s.description && (
            <div className="mt-0.5 truncate text-sm text-[var(--color-text-muted)]" title={s.description}>
              {s.description}
            </div>
          )}
        </div>
        <span
          className={`flex shrink-0 items-center gap-1.5 self-start text-xs ${
            problem ? st.text : 'text-[var(--color-text-muted)]'
          }`}
        >
          <StateDot state={s.state} />
          {sinceText(s)}
        </span>
      </div>
      {/* Strip, with admin actions in place of the % when something's wrong. */}
      <div className="flex items-center gap-3">
        <UptimeStrip
          data={uptime30}
          name={s.container_name}
          showPct={!actions}
          className="flex-1"
        />
        {actions && (
          <span className="relative z-10 flex shrink-0 items-center gap-3 text-xs">
            {down && (
              <button onClick={() => onStart(s)} disabled={busy} className="btn-link text-xs">
                {busy ? 'Starting…' : 'Start'}
              </button>
            )}
            <Link
              to={`/admin/monitor?logs=${encodeURIComponent(s.container_name)}`}
              className="btn-link text-xs"
            >
              Logs
            </Link>
          </span>
        )}
      </div>
    </div>
  );
}

export default function HomePage() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;
  const [services, setServices] = useState(null); // null = loading
  const [dockerDown, setDockerDown] = useState(false);
  const [error, setError] = useState('');
  const [uptime30, setUptime30] = useState(null);
  const [host, setHost] = useState(null);
  const [backup, setBackup] = useState(null);
  const [starting, setStarting] = useState(null);

  const loadServices = useCallback(async () => {
    try {
      setServices(await apiJson('/services'));
      setDockerDown(false);
      setError('');
    } catch (e) {
      if (e.status === 503 && Array.isArray(e.body?.services)) {
        // Docker is unreachable: keep the last known tiles so links still work.
        setDockerDown(true);
        setServices((cur) => (e.body.services.length ? e.body.services : (cur ?? [])));
      } else {
        setError(e.body?.detail || 'Couldn’t load services.');
        setServices((cur) => cur ?? []);
      }
    }
    if (isAdmin) {
      apiJson('/stats/system').then(setHost).catch(() => {});
      backupStatus().then(setBackup).catch(() => {});
    }
  }, [isAdmin]);

  usePoll(loadServices, SERVICES_POLL_MS);
  usePoll(
    () => uptime(UPTIME_DAYS).then(setUptime30).catch(() => {}),
    UPTIME_POLL_MS,
  );

  async function start(s) {
    setStarting(s.slug);
    try {
      await containerAction(s.container_name, 'start');
      setError('');
    } catch (e) {
      setError(`Couldn’t start ${s.display_name}: ${e.body?.detail || 'no response'}`);
    } finally {
      await loadServices();
      setStarting(null);
    }
  }

  if (services === null)
    return <p className="text-sm text-[var(--color-text-muted)]">Loading…</p>;

  return (
    <div>
      <PageHeader title="Services">
        {(services.length > 0 || dockerDown) && (
          <StatusLine services={services} dockerDown={dockerDown} host={host} backup={backup} />
        )}
      </PageHeader>
      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}
      {services.length === 0 ? (
        !dockerDown && (
          <p className="text-sm text-[var(--color-text-muted)]">
            No services discovered. Add <code className="bp-code">homehub.*</code>{' '}
            labels to a container in <code className="bp-code">docker-compose.yml</code>.
          </p>
        )
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((s) => (
            <Tile
              key={s.slug}
              s={s}
              uptime30={uptime30}
              isAdmin={isAdmin}
              onStart={start}
              busy={starting === s.slug}
            />
          ))}
        </div>
      )}
    </div>
  );
}
