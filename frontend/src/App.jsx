import { useState } from 'react';
import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { apiJson } from './api.js';
import { RequireAuth, useAuth } from './auth.jsx';
import LoginPage from './pages/LoginPage.jsx';
import HomePage from './pages/HomePage.jsx';
import MonitorPage from './pages/MonitorPage.jsx';
import UsersPage from './pages/UsersPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import DeployPage from './pages/DeployPage.jsx';

// Closed-door "sign out" glyph — matches the door icon the calendar/library apps use.
function DoorIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
      <path
        d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M4 21h16"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="15" cy="12.5" r="1.1" fill="currentColor" />
    </svg>
  );
}

// Power glyph, drawn like the door: shuts the Pi down (admins only).
function PowerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden>
      <path
        d="M12 3v8M6.6 6.6a8 8 0 1 0 10.8 0"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Asks first: once it's off, the Pi stays off until it's unplugged and plugged back in.
function PowerButton() {
  const [state, setState] = useState('idle'); // idle | asking | sent | failed
  async function shutDown() {
    if (!window.confirm('Shut down the Pi? Every app stops, and it stays off until you unplug it and plug it back in.')) return;
    setState('asking');
    try {
      await apiJson('/system/shutdown', { method: 'POST' });
      setState('sent');
    } catch {
      setState('failed');
    }
  }
  const label = { idle: 'Shut down the Pi', asking: 'Asking the Pi…', sent: 'Shutting down…', failed: "Couldn't ask the Pi to shut down" }[state];
  return (
    <>
      {(state === 'sent' || state === 'failed') && (
        <span className="text-sm text-[var(--color-text-muted)]">{state === 'sent' ? 'Shutting down…' : "Couldn't shut down"}</span>
      )}
      <button
        onClick={shutDown}
        disabled={state === 'asking' || state === 'sent'}
        className="btn btn-ghost"
        style={{ padding: 6 }}
        title={label}
        aria-label={label}
      >
        <PowerIcon />
      </button>
    </>
  );
}

function navItems(user) {
  return [
    { to: '/', label: 'Services', end: true },
    user?.is_admin && { to: '/admin/monitor', label: 'Monitor' },
    user?.is_admin && { to: '/admin/deploy', label: 'Deploy' },
    user?.is_admin && { to: '/admin/users', label: 'Users' },
    { to: '/settings', label: 'Settings' },
  ].filter(Boolean);
}

function TopBar() {
  const { user, logout } = useAuth();
  const linkCls = ({ isActive }) =>
    `bp-nav-link${isActive ? ' bp-nav-link-active' : ''}`;
  return (
    <header className="bp-topbar">
      {/* One row: tabs at the left edge, account at the right edge. On phones
          the tabs move to the bottom bar. */}
      <div className="flex items-center gap-4 px-4 py-[11.5px] sm:px-6">
        <span className="bp-brand">Home</span>
        <nav className="hidden gap-1 sm:flex">
          {navItems(user).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={linkCls}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-sm text-[var(--color-text-muted)]">
            {user?.display_name || user?.username}
          </span>
          {user?.is_admin && <PowerButton />}
          <button
            onClick={logout}
            className="btn btn-ghost"
            style={{ padding: 6 }}
            title="Sign out"
            aria-label="Sign out"
          >
            <DoorIcon />
          </button>
        </div>
      </div>
    </header>
  );
}

// Phones: the page nav as a bar along the bottom, in thumb reach.
function BottomNav() {
  const { user } = useAuth();
  return (
    <nav
      className="bp-bottombar fixed inset-x-0 bottom-0 z-30 flex sm:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {navItems(user).map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.end}
          className={({ isActive }) =>
            `flex-1 py-3 text-center text-sm ${
              isActive ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-muted)]'
            }`
          }
        >
          {n.label}
        </NavLink>
      ))}
    </nav>
  );
}

function Shell({ children }) {
  return (
    <div className="min-h-screen">
      <TopBar />
      {/* Narrows to make room when a side pane (the logs) is open. */}
      <div className="bp-main-wrap">
        <main className="mx-auto max-w-5xl px-4 pt-6 pb-24 sm:pb-6">{children}</main>
      </div>
      <BottomNav />
    </div>
  );
}

function AdminOnly({ children }) {
  const { user } = useAuth();
  return user?.is_admin ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Shell>
              <HomePage />
            </Shell>
          </RequireAuth>
        }
      />
      {/* Old paths. /users is also an API route, so the server redirects
          browser visits to it (see list_users_endpoint). */}
      <Route path="/monitor" element={<Navigate to="/admin/monitor" replace />} />
      <Route path="/users" element={<Navigate to="/admin/users" replace />} />
      <Route
        path="/admin/deploy"
        element={
          <RequireAuth>
            <AdminOnly>
              <Shell>
                <DeployPage />
              </Shell>
            </AdminOnly>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/monitor"
        element={
          <RequireAuth>
            <AdminOnly>
              <Shell>
                <MonitorPage />
              </Shell>
            </AdminOnly>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/users"
        element={
          <RequireAuth>
            <AdminOnly>
              <Shell>
                <UsersPage />
              </Shell>
            </AdminOnly>
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <Shell>
              <SettingsPage />
            </Shell>
          </RequireAuth>
        }
      />
      <Route
        path="*"
        element={
          <RequireAuth>
            <Shell>
              <HomePage />
            </Shell>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
