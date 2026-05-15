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

  if (services === null) return <p className="text-slate-500">Loading…</p>;

  return (
    <div>
      <h2 className="mb-4 text-lg font-semibold text-slate-900">Services</h2>
      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      {services.length === 0 ? (
        <p className="text-sm text-slate-500">
          No services discovered. Add{' '}
          <code className="rounded bg-slate-200 px-1 py-0.5">homehub.*</code>{' '}
          labels to a container in <code className="rounded bg-slate-200 px-1 py-0.5">docker-compose.yml</code>.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((s) => {
            const st = STATUS[s.status] || { dot: 'bg-slate-400', label: s.status };
            const reachable = s.status === 'running';
            const tile = (
              <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition group-hover:border-slate-400">
                <div className="mb-3 flex items-center justify-between">
                  <ServiceIcon
                    icon={s.icon}
                    name={s.display_name}
                    slug={s.slug}
                  />
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <span className={`h-2 w-2 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>
                <div className="font-medium text-slate-900">{s.display_name}</div>
                {s.description && (
                  <div className="mt-1 text-sm text-slate-500">{s.description}</div>
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
