import { pct } from '../lib/format';
import { STATE } from '../lib/state';

export function StateDot({ state, className = '' }) {
  const s = STATE[state] || STATE.unknown;
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${s.dot} ${className}`} />;
}

function bucketTone(b) {
  if (!b) return null;
  const [, degraded, down] = b;
  if (down > 0) return 'bg-red-500';
  if (degraded > 0) return 'bg-amber-500';
  return 'bg-[var(--color-text-muted)]';
}

function bucketTitle(b, label) {
  if (!b) return `${label}: no data`;
  const [up, degraded, down] = b;
  const parts = [`${up} min up`];
  if (degraded) parts.push(`${degraded} min degraded`);
  if (down) parts.push(`${down} min down`);
  return `${label}: ${parts.join(', ')}`;
}

function bucketLabel(start, kind, i) {
  const t = new Date(Date.parse(start) + i * (kind === 'hour' ? 3600e3 : 86400e3));
  return kind === 'hour'
    ? t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : t.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

/**
 * A row of thin ticks, one per hour or day, oldest on the left: filled when up,
 * amber for any degraded minutes, red for any downtime, hollow with no data.
 */
export function UptimeStrip({ data, name, showPct = true, className = '' }) {
  const entry = data?.services?.[name];
  const n = data?.bucket === 'hour' ? 24 : (entry?.buckets.length ?? 30);
  const buckets = entry?.buckets ?? Array(n).fill(null);
  const span = data?.bucket === 'hour' ? '24 h' : `${buckets.length} d`;
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="flex h-3 flex-1 items-stretch gap-px" aria-label={`Uptime over ${span}: ${pct(entry?.pct)}`}>
        {buckets.map((b, i) => {
          const tone = bucketTone(b);
          return (
            <span
              key={i}
              title={data ? bucketTitle(b, bucketLabel(data.start, data.bucket, i)) : undefined}
              className={`min-w-[2px] flex-1 rounded-[1px] ${
                tone ?? 'border border-[var(--color-border)]'
              } ${tone && tone.includes('muted') ? 'opacity-60' : ''}`}
            />
          );
        })}
      </div>
      {showPct && (
        <span className="w-16 shrink-0 text-right font-mono text-xs text-[var(--color-text-muted)]">
          {pct(entry?.pct)}
        </span>
      )}
    </div>
  );
}
