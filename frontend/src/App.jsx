import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import { RequireAuth, useAuth } from './auth.jsx';
import LoginPage from './pages/LoginPage.jsx';
import HomePage from './pages/HomePage.jsx';
import MonitorPage from './pages/MonitorPage.jsx';

function TopBar() {
  const { user, logout } = useAuth();
  const linkCls = ({ isActive }) =>
    `rounded-md px-3 py-1 text-sm ${
      isActive
        ? 'bg-slate-200 text-slate-900'
        : 'text-slate-600 hover:bg-slate-100'
    }`;
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-slate-900">Home</span>
          <nav className="flex gap-1">
            <NavLink to="/" end className={linkCls}>
              Services
            </NavLink>
            {user?.is_admin && (
              <NavLink to="/monitor" className={linkCls}>
                Monitor
              </NavLink>
            )}
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span>{user?.display_name || user?.username}</span>
          <button
            onClick={logout}
            className="rounded-md border border-slate-300 px-3 py-1 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

function Shell({ children }) {
  return (
    <div className="min-h-screen bg-slate-100">
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
