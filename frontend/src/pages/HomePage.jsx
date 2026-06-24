import { useEffect, useState } from 'react';
import { apiJson } from '../api';
import ServiceIcon from '../components/ServiceIcon.jsx';

const STATUS = {
  running: { dot: 'bg-green-500', label: 'running' },
  stopped: { dot: 'bg-amber-500', label: 'stopped' },
};

export default function HomePage() {
  const [services, setServices] = useState(null); // null = loading
  const [error, setError] = useState('');

  useEffect(() => {
    apiJson('/services')
      .then(setServices)
      .catch((e) => {
        setError(e.body?.detail || e.message || 'Failed to load services');
        setServices([]);
      });
  }, []);

  if (services === null)
    return <p className="bp-label text-sm text-[var(--color-text-muted)]">Loading…</p>;

  return (
    <div>
      <h2 className="bp-heading mb-5">Services</h2>
      {error && <p className="mb-3 text-sm text-[var(--color-danger)]">{error}</p>}
      {services.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">
          No services discovered. Add <code className="bp-code">homehub.*</code>{' '}
          labels to a container in <code className="bp-code">docker-compose.yml</code>.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((s) => {
            const st = STATUS[s.status] || { dot: 'bg-slate-400', label: s.status };
            const reachable = s.status === 'running';
            const tile = (
              <div className={`bp-card bp-ticks flex h-full flex-col p-5 ${reachable ? 'bp-card-link' : ''}`}>
                <div className="mb-3 flex items-center justify-between">
                  <ServiceIcon
                    icon={s.icon}
                    name={s.display_name}
                    slug={s.slug}
                  />
                  <span className="bp-label flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
                    <span className={`h-2 w-2 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>
                <div className="font-medium text-[var(--color-text-primary)]">{s.display_name}</div>
                {s.description && (
                  <div className="mt-1 text-sm text-[var(--color-text-muted)]">{s.description}</div>
                )}
              </div>
            );
            return reachable ? (
              <a key={s.slug} href={s.route_prefix} className="group block">
                {tile}
              </a>
            ) : (
              <div
                key={s.slug}
                className="cursor-not-allowed opacity-60"
                title={`${s.display_name} is ${st.label}`}
              >
                {tile}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
