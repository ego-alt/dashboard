import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiJson, backupStatus, containerAction, phoneApps, uptime } from '../api';
import { useAuth } from '../auth.jsx';
import PageHeader from '../components/PageHeader.jsx';
import ServiceIcon from '../components/ServiceIcon.jsx';
import { StateDot, UptimeStrip } from '../components/Status.jsx';
import { age, ago, clock, secondsSince } from '../lib/format';
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
      className={`bp-card bp-ticks relative flex h-full min-h-[var(--tile-h)] flex-col gap-5 px-5 py-5 ${down ? '' : 'bp-card-link'}`}
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
          <ServiceIcon icon={s.icon} iconUrl={s.icon_url} accent={s.accent} name={s.display_name} slug={s.slug} />
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

const isAndroid = /Android/i.test(navigator.userAgent);

function megabytes(bytes) {
  return bytes ? `${(bytes / 1048576).toFixed(1)}\u00a0MB` : '';
}

/** Where a phone app stands for you. The app reports what it has when it
 * checks for updates, so the dashboard knows which to offer. */
function phoneState(a) {
  if (!a.latest) return 'none';
  const have = a.installed?.version_code;
  if (have == null) return 'get';
  return have >= a.latest.version_code ? 'current' : 'update';
}

/** The corner of the icon: a dot for an update, a tick when you're up to date. */
function StateBadge({ state }) {
  if (state === 'update')
    return <span className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-2 border-[var(--color-bg-elevated)] bg-[var(--color-accent)]" />;
  if (state === 'current')
    return (
      <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-[var(--color-bg-elevated)] bg-green-400 text-[var(--color-bg-elevated)]">
        <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" aria-hidden><path d="M2.5 6.2l2.2 2.2 4.8-4.9" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
    );
  return null;
}

const STATE_LABEL = { update: 'update available', current: 'up to date', get: 'not installed', none: 'no release yet' };

/** A compact square: the icon, the name, and the latest version and size. Tap for the rest. */
function PhoneTile({ a, onOpen }) {
  const state = phoneState(a);
  return (
    <button
      type="button"
      onClick={() => onOpen(a)}
      className="bp-card bp-ticks bp-card-link flex h-[var(--tile-h)] flex-col items-center justify-center gap-1.5 px-2 py-3 text-center"
      aria-label={`${a.title}: ${STATE_LABEL[state]}`}
    >
      <span className="relative">
        <ServiceIcon iconUrl={a.icon_url} accent={a.accent} name={a.title} slug={a.name} large />
        <StateBadge state={state} />
      </span>
      <span className="w-full truncate text-sm font-medium text-[var(--color-text-primary)]">{a.title}</span>
      <span className={`text-xs ${state === 'update' ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-muted)]'}`}>
        {a.latest
          ? state === 'update' ? `Update · ${a.latest.version_name}` : [a.latest.version_name, megabytes(a.latest.size)].filter(Boolean).join(' · ')
          : 'No release yet'}
      </span>
    </button>
  );
}

/** Install, Update or Up to date, full width at the foot of the sheet. */
function PhoneAction({ a }) {
  const state = phoneState(a);
  const quiet = 'block w-full rounded border border-[var(--color-border)] py-2.5 text-center text-sm text-[var(--color-text-muted)]';
  if (state === 'none') return <p className={quiet}>No release yet: its CI publishes them</p>;
  if (state === 'current') return <p className={quiet}>Up to date ✓</p>;
  if (!a.ready) return <p className={quiet}>Preparing… the Pi is fetching it</p>;
  return (
    <a href={`/phone-apps/${encodeURIComponent(a.name)}/download`} download className="btn btn-primary w-full justify-center py-2.5">
      {state === 'update' ? `Update to ${a.latest.version_name}` : 'Install'}
    </a>
  );
}

/** A phone app's details: a sheet from the bottom on phones, a panel in the
 * middle on wider screens. Escape, × or a tap outside closes it. */
function PhoneSheet({ a, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  const latest = a.latest;
  const behind = phoneState(a) === 'update';
  return (
    <dialog
      ref={ref}
      className="app-sheet"
      aria-labelledby="app-sheet-title"
      onClose={onClose}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-start gap-4">
          <ServiceIcon iconUrl={a.icon_url} accent={a.accent} name={a.title} slug={a.name} large />
          <div className="min-w-0 flex-1">
            <h2 id="app-sheet-title" className="text-base font-medium text-[var(--color-text-primary)]">{a.title}</h2>
            {a.description && <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">{a.description}</p>}
          </div>
          <button type="button" className="btn btn-ghost -mr-2 -mt-2" onClick={onClose} aria-label="Close">×</button>
        </div>
        {latest && (
          <p className="text-xs text-[var(--color-text-muted)]">
            {[latest.version_name, megabytes(latest.size), ago(latest.published_at)].filter(Boolean).join(' · ')}
            {a.installed && (
              <span className={behind ? 'text-[var(--color-accent)]' : undefined}>
                {' · '}your phone has {a.installed.version_name || a.installed.version_code}
              </span>
            )}
          </p>
        )}
        {latest?.notes && (
          <div>
            <h3 className="mb-1 text-xs font-medium text-[var(--color-text-secondary)]">What’s new</h3>
            <p className="max-h-48 overflow-y-auto whitespace-pre-line text-sm text-[var(--color-text-secondary)]">{latest.notes}</p>
          </div>
        )}
        <PhoneAction a={a} />
        <p className="text-xs text-[var(--color-text-muted)]">
          {isAndroid
            ? 'The first install asks you to allow installs from this browser. After that the app offers its own updates.'
            : 'Open this page on your Android phone to install. After that the app offers its own updates.'}
        </p>
      </div>
    </dialog>
  );
}

/** Android apps from your repos, as a shelf of small tiles: install them here,
 * and they update themselves. */
function PhoneApps({ apps }) {
  const [open, setOpen] = useState(null);
  if (!apps?.length) return null;
  const current = open && apps.find((a) => a.name === open);
  return (
    <section className="mt-10" aria-labelledby="phone-apps">
      <h2 id="phone-apps" className="mb-3 text-sm font-medium text-[var(--color-text-secondary)]">Phone apps</h2>
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {apps.map((a) => <PhoneTile key={a.name} a={a} onOpen={(x) => setOpen(x.name)} />)}
      </div>
      {current && <PhoneSheet a={current} onClose={() => setOpen(null)} />}
    </section>
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
  const [phone, setPhone] = useState(null);

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
    phoneApps().then((r) => setPhone(r.apps)).catch(() => {});
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
      <PhoneApps apps={phone} />
    </div>
  );
}
