import { useCallback, useEffect, useRef, useState } from 'react';
import { containerLogs } from '../api';
import { usePoll } from '../lib/usePoll';

const TAIL = 200;
const FOLLOW_MS = 3000;

// Docker prefixes each line with an RFC 3339 timestamp (timestamps=True).
const TS = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?\s/;

function lineTone(line) {
  if (/\b(ERROR|CRITICAL|FATAL|Traceback|Exception)\b/i.test(line)) return 'text-[var(--color-danger)]';
  if (/\bWARN(ING)?\b/i.test(line)) return 'text-amber-300';
  return 'text-[var(--color-text-secondary)]';
}

function parse(text) {
  return text
    .split('\n')
    .filter(Boolean)
    .map((raw) => {
      const m = raw.match(TS);
      if (!m) return { time: '', text: raw };
      const d = new Date(`${m[1]}${m[3] && m[3] !== 'Z' ? m[3] : 'Z'}`);
      return {
        time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        text: raw.slice(m[0].length),
      };
    });
}

/** The last lines of a container's log in a right-hand drawer, optionally
 * following new lines. Escape or a click outside closes it. */
export default function LogsDrawer({ container, onClose }) {
  const [lines, setLines] = useState(null);
  const [error, setError] = useState('');
  const [follow, setFollow] = useState(false);
  const bodyRef = useRef(null);
  const panelRef = useRef(null);
  const stick = useRef(true);

  const load = useCallback(async () => {
    try {
      const r = await containerLogs(container.id, TAIL);
      setLines(parse(r.logs || ''));
      setError('');
    } catch (e) {
      setError(e.body?.detail || 'Couldn\u2019t load the logs.');
    }
  }, [container.id]);

  useEffect(() => {
    setLines(null);
    stick.current = true;
    load();
  }, [load]);

  usePoll(load, FOLLOW_MS, follow);

  // Keep the newest line in view unless the reader has scrolled up.
  useEffect(() => {
    const el = bodyRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    const onDown = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [onClose]);

  return (
    <aside
      ref={panelRef}
      role="dialog"
      aria-label={`Logs for ${container.name}`}
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[640px] flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-elevated)] shadow-2xl"
    >
      <header className="flex items-center gap-3 border-b border-[var(--color-border)] px-4 py-3">
        <h3 className="font-mono text-sm text-[var(--color-text-primary)]">{container.name}</h3>
        <span className="hidden text-xs text-[var(--color-text-muted)] sm:inline">last {TAIL} lines</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => setFollow((f) => !f)}
            className={`btn text-xs ${follow ? 'border-green-500/40 bg-green-500/10 text-green-300' : 'btn-secondary'}`}
            title={follow ? `Following: new lines every ${FOLLOW_MS / 1000} s` : 'Follow new lines'}
          >
            {follow ? 'Following' : 'Follow'}
          </button>
          <button onClick={load} className="btn btn-secondary text-xs">
            Refresh
          </button>
          <button onClick={onClose} className="btn btn-ghost" aria-label="Close logs" title="Close (Esc)">
            ×
          </button>
        </div>
      </header>
      {error && <p className="px-4 pt-3 text-sm text-[var(--color-danger)]">{error}</p>}
      <div
        ref={bodyRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="flex-1 overflow-auto bg-[var(--color-bg-inset)] px-4 py-3 font-mono text-xs leading-5"
      >
        {lines === null ? (
          <p className="text-[var(--color-text-muted)]">Loading…</p>
        ) : lines.length === 0 ? (
          <p className="text-[var(--color-text-muted)]">No log lines.</p>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="flex gap-3 whitespace-pre-wrap break-all">
              <span className="shrink-0 text-[var(--color-text-muted)]">{l.time}</span>
              <span className={lineTone(l.text)}>{l.text}</span>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
