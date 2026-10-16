import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { AUTH_EXPIRED, apiJson, logout as apiLogout } from './api';

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  // undefined = not yet resolved, null = anonymous, object = logged in.
  const [user, setUser] = useState(undefined);

  // Re-reads /me while keeping the current user on screen: only the very
  // first load shows "Loading…". (Blanking the user here used to unmount the
  // whole page, which threw away the 2FA recovery codes before they showed.)
  const refresh = useCallback(
    () =>
      apiJson('/me')
        .then(setUser)
        .catch(() => setUser(null)),
    [],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onExpired = () => setUser((u) => (u ? null : u));
    window.addEventListener(AUTH_EXPIRED, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED, onExpired);
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  return (
    <AuthCtx.Provider value={{ user, setUser, refresh, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

function Centered({ children }) {
  return (
    <div className="flex min-h-screen items-center justify-center text-[var(--color-text-muted)]">
      {children}
    </div>
  );
}

export function RequireAuth({ children }) {
  const { user } = useAuth();
  const location = useLocation();

  if (user === undefined) {
    return <Centered>Loading…</Centered>;
  }

  if (user === null) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return children;
}
