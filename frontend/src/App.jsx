import { Routes, Route } from 'react-router-dom';
import { RequireAuth, useAuth } from './auth.jsx';
import LoginPage from './pages/LoginPage.jsx';
import MonitorPage from './pages/MonitorPage.jsx';

function TopBar() {
  const { user, logout } = useAuth();
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <span className="font-semibold text-slate-900">Home</span>
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

function Dashboard() {
  return (
    <div className="min-h-screen bg-slate-100">
      <TopBar />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <MonitorPage />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
