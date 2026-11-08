/** Small formatting helpers shared by the pages. */

const MIN = 60;
const HOUR = 3600;
const DAY = 86400;

/** "45 s", "12 min", "3 h", "4 d" — a compact age for seconds. */
export function age(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  const s = Math.max(0, seconds);
  if (s < MIN) return `${Math.round(s)} s`;
  if (s < HOUR) return `${Math.round(s / MIN)} min`;
  if (s < DAY) return `${Math.round(s / HOUR)} h`;
  return `${Math.round(s / DAY)} d`;
}

export function secondsSince(iso, now = Date.now()) {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : (now - t) / 1000;
}

/** "just now", "12 min ago", "3 h ago", "4 d ago": how long ago a timestamp was. */
export function ago(iso, now = Date.now()) {
  const s = secondsSince(iso, now);
  if (s == null) return '';
  return s < MIN ? 'just now' : `${age(s)} ago`;
}

// Every date and time on the dashboard is shown through these helpers, in the
// viewing device's time zone. The API sends times with their zone (+00:00).

function toDate(t) {
  if (!t) return null;
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "02:14" ("02:14:05" with seconds). */
export function time(t, { seconds = false } = {}) {
  const d = toDate(t);
  return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(seconds && { second: '2-digit' }) }) : '';
}

/** "14 Oct" ("Tue 14 Oct" with weekday), with the year when it isn't this year's. */
export function day(t, { weekday = false } = {}, now = new Date()) {
  const d = toDate(t);
  if (!d) return '';
  return d.toLocaleDateString([], {
    ...(weekday && { weekday: 'short' }),
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() !== now.getFullYear() && { year: 'numeric' }),
  });
}

/** "02:14" today, "Wed 02:14" within a week, "14 Oct" otherwise. */
export function clock(t, now = new Date()) {
  const d = toDate(t);
  if (!d) return '';
  if (d.toDateString() === now.toDateString()) return time(d);
  if (now - d < 6 * DAY * 1000) return `${d.toLocaleDateString([], { weekday: 'short' })} ${time(d)}`;
  return day(d, {}, now);
}

export function pct(p) {
  if (p == null) return '—';
  if (p >= 99.995) return '100\u00a0%';
  return `${p.toFixed(p >= 99 ? 2 : 1)}\u00a0%`;
}

/** A server message ("can't reach Docker") as a sentence. */
export function sentence(detail, fallback) {
  if (!detail || typeof detail !== 'string') return fallback;
  return detail.charAt(0).toUpperCase() + detail.slice(1) + (/[.!?]$/.test(detail) ? '' : '.');
}

/** "Chrome on Android", "Safari on Mac", … from a user agent. */
export function device(ua) {
  if (!ua) return 'Unknown device';
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /Firefox\//.test(ua)
      ? 'Firefox'
      : /Chrome\//.test(ua)
        ? 'Chrome'
        : /Safari\//.test(ua)
          ? 'Safari'
          : /curl|python|httpx|okhttp/i.test(ua)
            ? 'Script'
            : 'Browser';
  const os = /Android/.test(ua)
    ? 'Android'
    : /iPhone|iPad/.test(ua)
      ? 'iOS'
      : /Mac OS X|Macintosh/.test(ua)
        ? 'Mac'
        : /Windows/.test(ua)
          ? 'Windows'
          : /Linux/.test(ua)
            ? 'Linux'
            : null;
  return os ? `${browser} on ${os}` : browser;
}
