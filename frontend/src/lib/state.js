/** Service/container states, as the API reports them (see container_state). */

export const STATE = {
  up: { dot: 'bg-green-500', text: 'text-green-300', label: 'up' },
  degraded: { dot: 'bg-amber-500', text: 'text-amber-300', label: 'degraded' },
  starting: { dot: 'bg-amber-500', text: 'text-amber-300', label: 'starting' },
  down: { dot: 'bg-red-500', text: 'text-red-300', label: 'down' },
  unknown: { dot: 'bg-slate-400', text: 'text-[var(--color-text-muted)]', label: 'unknown' },
};

export const PROBLEM_RANK = { down: 0, degraded: 1, starting: 2, unknown: 2, up: 3 };
