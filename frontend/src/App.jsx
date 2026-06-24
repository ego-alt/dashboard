import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { RequireAuth, useAuth } from './auth.jsx';
import LoginPage from './pages/LoginPage.jsx';
import HomePage from './pages/HomePage.jsx';
import MonitorPage from './pages/MonitorPage.jsx';
import UsersPage from './pages/UsersPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';

// Closed-door "sign out" glyph — matches the door icon the calendar/library apps use.
function DoorIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
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

function TopBar() {
  const { user, logout } = useAuth();
  const linkCls = ({ isActive }) =>
    `bp-nav-link${isActive ? ' bp-nav-link-active' : ''}`;
  return (
    <header className="bp-topbar">
      {/* Mobile: brand + account on row 1, nav drops to its own full-width row
          below (order-last + w-full). Desktop: all inline on one row. */}
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <span className="bp-brand">Home</span>
        <nav className="order-last flex w-full flex-wrap gap-1 sm:order-none sm:w-auto">
          <NavLink to="/" end className={linkCls}>
            Services
          </NavLink>
          {user?.is_admin && (
            <NavLink to="/monitor" className={linkCls}>
              Monitor
            </NavLink>
          )}
          {user?.is_admin && (
            <NavLink to="/users" className={linkCls}>
              Users
            </NavLink>
          )}
          <NavLink to="/settings" className={linkCls}>
            Settings
          </NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="bp-label text-xs text-[var(--color-text-muted)]">
            {user?.display_name || user?.username}
          </span>
          <button
            onClick={logout}
            className="btn btn-ghost"
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

function Shell({ children }) {
  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
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
      <Route
        path="/monitor"
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
        path="/users"
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
