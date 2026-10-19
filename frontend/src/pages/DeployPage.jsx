import { useCallback, useEffect, useRef, useState } from 'react';
import { addApp, checkRepo, deployApps, deployLatest, deployLog, deployNow, deployRepos, removeApp } from '../api';
import LogsDrawer from '../components/LogsDrawer.jsx';
import PageHeader from '../components/PageHeader.jsx';
import Panel from '../components/Panel.jsx';
import { usePoll } from '../lib/usePoll';

const short = (sha) => (sha ? sha.slice(0, 7) : '');

function ago(iso) {
  if (!iso) return '';
  const mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

const RESULT = {
  deployed: { text: 'Deployed', tone: 'text-[var(--color-text-secondary)]' },
  'rolled-back': { text: 'Rolled back', tone: 'text-amber-300' },
  'ci-failed': { text: 'CI failed', tone: 'text-[var(--color-danger)]' },
  failed: { text: 'Didn’t start', tone: 'text-[var(--color-danger)]' },
  'rollback-failed': { text: 'Rollback failed', tone: 'text-[var(--color-danger)]' },
};

/** One line saying where an app stands: what the Pi runs against what's on GitHub. */
function standing(a, checking) {
  if (a.queued) return { text: 'Queued: the Pi is on it', tone: 'text-[var(--color-accent)]' };
  const deployed = a.deployed?.sha;
  const latest = a.latest?.sha;
  if (!a.latest) {
    return { text: checking ? 'Checking GitHub…' : 'GitHub not reachable', tone: 'text-[var(--color-text-muted)]' };
  }
  if (!a.container && a.kind === 'app') return { text: 'Waiting for its first deploy', tone: 'text-[var(--color-accent)]' };
  if (latest && deployed && latest !== deployed) {
    if (a.latest.ci === 'running') return { text: 'New commit: CI running', tone: 'text-[var(--color-text-secondary)]' };
    if (a.latest.ci === 'failed') return { text: 'New commit failed CI', tone: 'text-[var(--color-danger)]' };
    if (a.latest.ci === 'passed') return { text: 'New commit: deploying within 5 min', tone: 'text-[var(--color-accent)]' };
    return { text: 'New commit: no CI run', tone: 'text-amber-300' };
  }
  const r = RESULT[a.deployed?.result];
  if (r && a.deployed.result !== 'deployed') return r;
  return { text: 'Up to date', tone: 'text-[var(--color-text-muted)]' };
}

function CommitCell({ commit, ci }) {
  if (!commit) return <span className="text-[var(--color-text-muted)]">—</span>;
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <span className="font-mono text-xs text-[var(--color-text-primary)]">{short(commit.sha)}</span>
      {ci && (
        <span
          className={`text-xs ${ci === 'passed' ? 'text-green-400' : ci === 'failed' ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'}`}
          title={`CI ${ci}`}
        >
          {ci === 'passed' ? '✓' : ci === 'failed' ? '✕' : ci === 'running' ? '…' : '–'}
        </span>
      )}
      <span className="text-xs text-[var(--color-text-muted)]">{ago(commit.at)}</span>
    </span>
  );
}

/** The same three actions on every row, so the table reads the same throughout. */
function Actions({ a, busy, onDeploy, onLog, onRemove }) {
  const core = a.kind !== 'app';
  return (
    <span className="flex items-center justify-end gap-3">
      <button className="btn-link text-xs" onClick={() => onLog(a)} title="What the Pi did on its last deploys">Log</button>
      <button className="btn-link text-xs" disabled={busy || a.queued} onClick={() => onDeploy(a)}
        title={a.part_of
          ? `Deploys ${a.part_of}, which ${a.name} ships with (it still has to pass CI)`
          : 'Deploy the latest commit now (it still has to pass CI)'}>
        Deploy now
      </button>
      <button className="btn-link btn-link-danger text-xs"
        disabled={busy || core} onClick={() => onRemove(a)}
        title={core ? 'Part of the stack itself: it can’t be removed here' : 'Stop it and take it off the stack'}>
        Remove
      </button>
    </span>
  );
}

function AddApp({ onAdded, onClose }) {
  const [repos, setRepos] = useState(null);
  const [owner, setOwner] = useState('');
  const [privateHidden, setPrivateHidden] = useState(false);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState(null);
  const [check, setCheck] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    deployRepos()
      .then((r) => { setRepos(r.repos); setOwner(r.owner); setPrivateHidden(r.private_hidden); })
      .catch((e) => setError(e.body?.detail || 'Couldn’t list your GitHub repos.'));
  }, []);

  async function pick(name) {
    setPicked(name);
    setCheck(null);
    setError('');
    try {
      setCheck(await checkRepo(name));
    } catch (e) {
      setError(e.body?.detail || 'Couldn’t check that repo.');
    }
  }

  async function deploy() {
    setBusy(true);
    setError('');
    try {
      await addApp(picked);
      onAdded(picked);
    } catch (e) {
      setError(e.body?.detail || 'Couldn’t add it.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title="Add an app"
      description={`Any repo under ${owner || 'your account'} with a Dockerfile, a homestack.toml and a CI workflow. It's served at /<repo name>/ behind your sign-in.`}
      aside={<button className="btn btn-ghost" onClick={onClose} aria-label="Close" title="Close">×</button>}
      className="mb-6"
    >
      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}
      {repos === null ? (
        <p className="text-sm text-[var(--color-text-muted)]">{error ? '' : 'Loading your repos…'}</p>
      ) : repos.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">Every repo is already on the stack.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-border)] rounded border border-[var(--color-border)]">
          {repos.map((r) => (
            <li key={r.repo}>
              <button
                className={`flex w-full items-baseline gap-3 px-3 py-2 text-left hover:bg-[var(--color-highlight-soft)] ${picked === r.name ? 'bg-[var(--color-highlight-soft)]' : ''}`}
                onClick={() => pick(r.name)}
              >
                <span className="font-mono text-sm text-[var(--color-text-primary)]">{r.name}</span>
                <span className="truncate text-xs text-[var(--color-text-muted)]">{r.description}</span>
                <span className="ml-auto shrink-0 text-xs text-[var(--color-text-muted)]">
                  {r.private ? 'private · ' : ''}{ago(r.pushed_at)}
                </span>
              </button>
              {picked === r.name && (
                <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-inset)] px-3 py-3">
                  {!check ? (
                    <p className="text-sm text-[var(--color-text-muted)]">Checking…</p>
                  ) : (
                    <>
                      <ul className="space-y-1 text-sm">
                        {check.checks.map((c) => (
                          <li key={c.label} className="flex gap-2">
                            <span className={c.ok ? 'text-green-400' : 'text-[var(--color-danger)]'}>{c.ok ? '✓' : '✕'}</span>
                            <span className="text-[var(--color-text-primary)]">{c.label}</span>
                            {c.detail && <span className="text-[var(--color-text-muted)]">{c.detail}</span>}
                          </li>
                        ))}
                      </ul>
                      {check.manifest && (
                        <p className="mt-2 text-xs text-[var(--color-text-muted)]">
                          “{check.manifest.title}” on port {check.manifest.port}, health {check.manifest.health}
                          {check.manifest.data ? `, keeps ${check.manifest.data}` : ''}
                        </p>
                      )}
                      <div className="mt-3 flex items-center gap-3">
                        <button className="btn btn-primary" disabled={!check.ok || busy} onClick={deploy}>
                          {busy ? 'Adding…' : `Deploy ${check.name}`}
                        </button>
                        <button className="btn btn-secondary" onClick={() => pick(r.name)}>Check again</button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {privateHidden && (
        <p className="mt-3 text-xs text-[var(--color-text-muted)]">
          Private repos show here once the dashboard has a <span className="font-mono">DEPLOY_GITHUB_TOKEN</span> (see docs/DEPLOY.md).
        </p>
      )}
    </Panel>
  );
}

export default function DeployPage() {
  const [apps, setApps] = useState(null);
  const [githubProblem, setGithubProblem] = useState('');
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState({});
  const [logFor, setLogFor] = useState(null);

  const [latest, setLatest] = useState({});        // name → latest commit, from GitHub
  const [checking, setChecking] = useState(false);
  const asking = useRef(false);

  // The Pi's side first (instant), then GitHub's (seconds when not cached).
  const load = useCallback(async () => {
    let r;
    try {
      r = await deployApps();
      setApps(r.apps);
      setGithubProblem(r.github_problem || '');
      setError('');
    } catch (e) {
      setError(e.body?.detail || 'Couldn’t load the deploy status.');
      return;
    }
    if (r.apps.every((a) => a.latest) || asking.current) return;
    asking.current = true;
    setChecking(true);
    try {
      const l = await deployLatest();
      setLatest(l.latest || {});
      setGithubProblem(l.github_problem || '');
    } catch {
      setGithubProblem('GitHub isn’t answering.');
    } finally {
      asking.current = false;
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);
  // Faster while something is on its way out.
  const active = (apps || []).some((a) => a.queued || (a.kind === 'app' && !a.container));
  usePoll(load, active ? 5000 : 30000);

  async function run(a, fn, message) {
    setBusy((b) => ({ ...b, [a.name]: true }));
    try {
      await fn(a.name);
      setNotice(message);
      await load();
    } catch (e) {
      setNotice(e.body?.detail || 'That didn’t work.');
    } finally {
      setBusy((b) => ({ ...b, [a.name]: false }));
    }
  }

  const fetchLog = useCallback(async () => (await deployLog(logFor, 300)).lines.join('\n'), [logFor]);

  const row = (app) => {
    const a = { ...app, latest: app.latest || latest[app.name] || null };   // GitHub's answer, when it's in
    const s = standing(a, checking);
    return { a, s, props: {
      a, busy: !!busy[a.name],
      onDeploy: (x) => run(x, deployNow, `Asked the Pi to deploy ${x.name}.`),
      onLog: (x) => setLogFor(x.name),
      onRemove: (x) => window.confirm(`Remove ${x.name} from the stack? Its container stops; its repo and data stay on the Pi.`)
        && run(x, removeApp, `Removing ${x.name}.`),
    } };
  };

  return (
    <div>
      <PageHeader
        title="Deploy"
        aside={
          <>
            <button className="btn btn-secondary" onClick={load}>Refresh</button>
            {!adding && <button className="btn btn-primary" onClick={() => setAdding(true)}>Add an app</button>}
          </>
        }
      />

      {adding && (
        <AddApp
          onClose={() => setAdding(false)}
          onAdded={(name) => { setAdding(false); setNotice(`Added ${name}. The Pi is cloning and building it.`); load(); }}
        />
      )}

      <Panel
        flush
        title="On the Pi"
        description="Commits that pass CI deploy on their own within 5 minutes; a deploy that doesn't come up healthy is rolled back."
        aside={notice && <span className="text-xs text-[var(--color-text-secondary)]">{notice}</span>}
      >
        {error && <p className="px-4 pt-3 text-sm text-[var(--color-danger)]">{error}</p>}
        {githubProblem && <p className="px-4 pt-3 text-sm text-amber-300">{githubProblem}</p>}
        {apps === null ? (
          <p className="px-4 py-6 text-[var(--color-text-muted)]">{error ? '' : 'Loading…'}</p>
        ) : (
          <div className="@container">
            <table className="hidden min-w-full text-sm @3xl:table">
              <thead className="bg-[var(--color-bg-inset)] text-left text-[var(--color-text-muted)]">
                <tr>
                  <th className="px-4 py-2 font-medium">App</th>
                  <th className="px-3 py-2 font-medium">Running</th>
                  <th className="px-3 py-2 font-medium">Latest on GitHub</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {apps.map(row).map(({ a, s, props }) => (
                  <tr key={a.name} className="hover:bg-[var(--color-highlight-soft)]">
                    <td className="whitespace-nowrap px-4 py-2">
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-[var(--color-text-primary)]">{a.name}</span>
                        {a.part_of && <span className="text-xs text-[var(--color-text-muted)]">with {a.part_of}</span>}
                      </span>
                    </td>
                    <td className="px-3 py-2"><CommitCell commit={a.deployed ? { sha: a.deployed.sha, at: a.deployed.at } : null} /></td>
                    <td className="px-3 py-2" title={a.latest?.message}><CommitCell commit={a.latest} ci={a.latest?.ci} /></td>
                    <td className={`px-3 py-2 text-xs ${s.tone}`}>{s.text}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right"><Actions {...props} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="divide-y divide-[var(--color-border)] @3xl:hidden">
              {apps.map(row).map(({ a, s, props }) => (
                <li key={a.name} className="space-y-1.5 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-[var(--color-text-primary)]">{a.name}</span>
                    <span className={`ml-auto text-xs ${s.tone}`}>{s.text}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-[var(--color-text-muted)]">
                    <span>running <span className="font-mono">{short(a.deployed?.sha) || '—'}</span></span>
                    <span>latest <span className="font-mono">{short(a.latest?.sha) || '—'}</span></span>
                    <span className="ml-auto"><Actions {...props} /></span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Panel>

      {logFor && (
        <LogsDrawer title={`deploy · ${logFor}`} fetchText={fetchLog} onClose={() => setLogFor(null)} />
      )}
    </div>
  );
}
