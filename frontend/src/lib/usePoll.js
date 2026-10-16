import { useEffect, useRef, useState } from 'react';

/** True while the tab is visible — polling pauses for a backgrounded tab. */
export function usePageVisible() {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);
  return visible;
}

/**
 * Call `fn` every `ms` while `enabled` and the tab is visible, and once more
 * when the tab comes back. Never stacks a call on top of one in flight.
 */
export function usePoll(fn, ms, enabled = true) {
  const visible = usePageVisible();
  const fnRef = useRef(fn);
  const busy = useRef(false);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    if (!enabled || !visible) return undefined;
    const tick = async () => {
      if (busy.current) return;
      busy.current = true;
      try {
        await fnRef.current();
      } finally {
        busy.current = false;
      }
    };
    tick();
    const id = setInterval(tick, ms);
    return () => clearInterval(id);
  }, [ms, enabled, visible]);
}

/** Re-render every `ms`, for "updated 3 s ago" style labels. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
