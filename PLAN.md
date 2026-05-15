# Dashboard — unified auth + home-services hub

Evolve `dashboard` (currently a FastAPI + React Docker-monitor) into the gated
entrypoint for the home stack: single login, service registry, container health
in one place. Library and calendar stay Flask + SQLite (right tool for content
apps), keep running standalone in dev, and pick up trust-header auth via one
env var when running behind the dashboard's nginx.

This is a plan, not a spec — fixed decisions are flagged; open ones live in §12.

**Status (2026-05-15)** — Steps 1–7 of §8 complete: dashboard auth + nginx
compose; library and calendar wired at `/library/` and `/calendar/` with
`auth_request` + `AUTH_PROXY_HEADER` proxy auth. §3.4/§3.5 also done: the
service-registry hub (`/services` + `register-service` CLI + tile home),
admin-gated monitor, and a protected-container guard against self-lockout.
Up next: §8.8–9 tighten / multi-user smoke test; future: unify per-app
SQLite users tables via SQL.

---

## 1. Goal

- One login for the household (you + family eventually).
- Each app retains its own per-user data (books, mood entries, events) keyed off
  a shared canonical `username`.
- Apps stay independently runnable for development; auth mode is a config flag,
  never a code fork.
- Dashboard owns the only `users` table that matters, plus session issuance,
  plus a unified view of running services that reuses its existing Docker
  monitor as the substrate.

---

## 2. Architecture overview

```
                  ┌──────────────┐
   browser  ───>  │    nginx     │  ──>  dashboard  (FastAPI: login + /auth/verify + service API)
                  │  (TLS, only  │  ──>  library    (Flask, bind 127.0.0.1, trust X-Forwarded-User)
                  │   entrypoint)│  ──>  calendar   (Flask, bind 127.0.0.1, trust X-Forwarded-User)
                  └──────────────┘
```

- **nginx** terminates TLS and is the only network-reachable surface. Backends
  bind to `127.0.0.1` so they cannot be hit directly on the LAN.
- For every backend request, nginx calls `dashboard:/auth/verify` via the
  `auth_request` directive. On 200, nginx proxies through with
  `X-Forwarded-User: <username>` injected; on 401, nginx redirects the browser
  to `dashboard:/login?next=<original-url>`.
- **dashboard** owns: the `users` and `sessions` tables, login UI, session
  cookie (scoped to the parent domain), `/auth/verify`, the service-registry
  API, and a React UI that fans out into both auth admin and container/service
  monitoring.
- **library / calendar** drop their login flows in proxy mode. They look up the
  user via the `X-Forwarded-User` header and auto-create local FK rows on first
  sight of a new username.

This is the standard "trusted-header auth" pattern, identical to what
oauth2-proxy / Authelia / Authentik emit — meaning a future swap to a real SSO
product is a config change, not a rewrite.

**Stack pragmatism**: the dashboard's job (live admin/monitor surface, JSON API
consumed by an SPA) is what FastAPI + React are *good* at, so it stays. The
content apps' job (server-rendered pages, forms, lots of HTML) is what Flask is
good at, so they stay too. Two stacks, but each is on its home turf and the
contract between them (`X-Forwarded-User`) is language-agnostic.

---

## 3. Dashboard — new responsibilities

The existing FastAPI app at `app/main.py` already exposes container
lifecycle + system-stats endpoints. The work below *adds* an auth surface and a
service-registry concept on top of that — no rewrites of the Docker monitor.

### 3.1 Schema

Two new tables (auth) plus one bookkeeping table (services). SQLite is fine at
this scale; pick SQLAlchemy 2.0 to stay congruent with library / calendar.

```sql
CREATE TABLE users (
  id            INTEGER PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,    -- value emitted as X-Forwarded-User
  display_name  TEXT,
  password_hash TEXT NOT NULL,           -- argon2id
  is_admin      INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE sessions (
  token       TEXT PRIMARY KEY,          -- random 256-bit, base64url
  user_id     INTEGER NOT NULL REFERENCES users(id),
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  ip          TEXT,
  user_agent  TEXT
);

-- The "human-facing slice" that maps logical services to running containers.
-- Container metadata (status, CPU, etc.) comes from the live Docker API, NOT
-- from this table.
CREATE TABLE services (
  id            INTEGER PRIMARY KEY,
  slug          TEXT UNIQUE NOT NULL,    -- 'library', 'calendar', …
  display_name  TEXT NOT NULL,
  container_name TEXT NOT NULL,          -- docker container name to bind to
  route_prefix  TEXT NOT NULL,           -- '/library/', '/calendar/'
  icon          TEXT,                    -- emoji or asset path
  description   TEXT,
  is_enabled    INTEGER NOT NULL DEFAULT 1
);
```

Sessions stay server-side (a row per session, not JWTs) so revocation is one
SQL DELETE.

### 3.2 Auth module (FastAPI)

```python
# app/auth.py
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response
from .db import get_db   # your SQLAlchemy session factory
from .models import User, Session

SESSION_COOKIE = "session"
SESSION_TTL    = timedelta(days=14)

def _now() -> datetime:
    return datetime.now(timezone.utc)

def mint_session(db, user: User, *, ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(
        token=token, user_id=user.id,
        created_at=_now(), expires_at=_now() + SESSION_TTL,
        ip=ip, user_agent=user_agent[:255],
    ))
    db.commit()
    return token

def lookup_session(db, token: str) -> Optional[Session]:
    s = db.query(Session).filter(Session.token == token).one_or_none()
    if s is None or s.expires_at <= _now():
        return None
    return s

def current_user_optional(request: Request, db = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = lookup_session(db, token)
    return s.user if s else None

def current_user(user = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user

def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user
```

Every protected endpoint becomes `Depends(current_user)` — typed, no ambient
state. Admin endpoints become `Depends(current_admin)`.

### 3.3 Routes added to `app/main.py`

```python
from fastapi import APIRouter, Form, Response
from passlib.hash import argon2

auth_router = APIRouter()

@auth_router.post("/login")
def login(request: Request, response: Response,
          username: str = Form(...), password: str = Form(...),
          db = Depends(get_db)):
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None or not argon2.verify(password, user.password_hash):
        raise HTTPException(status_code=401, detail="bad credentials")
    token = mint_session(
        db, user,
        ip=request.client.host or "",
        user_agent=request.headers.get("user-agent", ""),
    )
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True, secure=True, samesite="lax",
    )
    user.last_login_at = _now()
    db.commit()
    return {"ok": True}

@auth_router.post("/logout")
def logout(request: Request, response: Response, db = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(Session).filter(Session.token == token).delete()
        db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}

@auth_router.get("/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "display_name": user.display_name,
            "is_admin": bool(user.is_admin)}

@auth_router.get("/auth/verify")
def auth_verify(user = Depends(current_user_optional)):
    """Called by nginx auth_request. Cheap: one indexed SELECT."""
    if user is None:
        return Response(status_code=401)
    return Response(status_code=200, headers={"X-User": user.username})

app.include_router(auth_router)
```

The existing `/containers`, `/stats/system`, etc. endpoints gain a
`Depends(current_user)` (or `current_admin` for container start/stop/restart —
those are destructive). The hot-path `/auth/verify` cost is one indexed select;
cache the result per-token in-process for ~5s if the per-request load gets
noisy.

### 3.4 Service registry — built on top of Docker, not parallel to it

Reframe "service" so the live source of truth stays the Docker daemon. The
`services` table is **just metadata** — slug, display name, route prefix, icon,
which container name to associate with. Status / CPU / memory / uptime always
come from the live Docker API the dashboard already wraps.

```python
@app.get("/services")
def list_services(_: User = Depends(current_user), db = Depends(get_db)):
    rows = db.query(Service).filter(Service.is_enabled == 1).all()
    # join against live container state — by container_name, not id (id changes
    # on rebuild, name is stable).
    containers_by_name = {c["name"]: c for c in get_containers()}
    out = []
    for r in rows:
        c = containers_by_name.get(r.container_name)
        out.append({
            "slug": r.slug,
            "display_name": r.display_name,
            "route_prefix": r.route_prefix,
            "icon": r.icon,
            "description": r.description,
            "container": c,    # None if not currently running
        })
    return out
```

Honest signal: if a service has no matching live container, `container` is
`None` and the UI shows it as down. No synthetic healthchecks, no fake metrics.

### 3.5 React frontend changes

The existing `App.jsx` becomes one route in a small SPA. Suggested routes:

| Path             | What it shows                                                              |
| ---------------- | -------------------------------------------------------------------------- |
| `/`              | Home — service tiles (from `/services`), each click-through to its route. |
| `/login`         | Login form (POST to `/login`). Public; no auth required.                  |
| `/containers`    | Existing Docker monitor table (current `App.jsx` content).                |
| `/admin/users`   | Admin-only: list / create / disable / reset.                              |

Bootstrap auth state on app mount:

```jsx
// frontend/src/auth.jsx
import { createContext, useContext, useEffect, useState } from "react";
const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined);   // undefined = loading
  useEffect(() => {
    fetch("/me", { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(setUser)
      .catch(() => setUser(null));
  }, []);
  return <AuthCtx.Provider value={{ user, setUser }}>{children}</AuthCtx.Provider>;
}
export const useAuth = () => useContext(AuthCtx);
```

A `<RequireAuth>` wrapper redirects to `/login` if `useAuth().user === null`,
shows a spinner if `=== undefined`, renders children if a user object.

Add `react-router-dom` (currently absent — only one screen exists) when this
lands. Tailwind v4 already configured.

Note: `app/main.py` currently hardcodes
`allow_origins=["http://localhost:5173"]`. In production-behind-nginx the
frontend is served same-origin as the API, so CORS isn't needed — but keep the
dev allowlist for `npm run dev`. Make it env-driven:
`CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")`.

### 3.6 Things to fix in the current code while we're here

- `docker.from_env()` is called at module import time in `app/docker_control.py`
  and `app/system_stats.py`. If the Docker daemon isn't reachable, FastAPI
  crashes on boot. Wrap in a lazy `_get_client()` so the API can serve `/login`
  and `/me` even when Docker is unavailable.
- `app/__init__.py` is empty. Fine, leave it.
- No tests yet. The auth module deserves a pytest file the moment it lands —
  login / bad password / expired session / verify endpoint shape.

---

## 4. Reverse proxy (nginx)

Backend-language-agnostic; works whether dashboard is Flask, FastAPI, or
anything else that serves HTTP.

```nginx
# /etc/nginx/sites-available/home

server {
    listen 443 ssl http2;
    server_name home.local;

    ssl_certificate     /etc/ssl/...;
    ssl_certificate_key /etc/ssl/...;

    # ---- subrequest auth ----
    location = /auth/verify {
        internal;
        proxy_pass         http://127.0.0.1:8000/auth/verify;
        proxy_pass_request_body off;
        proxy_set_header   Content-Length "";
        proxy_set_header   X-Original-URI $request_uri;
        proxy_set_header   Cookie $http_cookie;
    }

    error_page 401 = @login_redirect;
    location @login_redirect {
        return 302 /login?next=$request_uri;
    }

    # ---- dashboard (auth provider + home page) ----
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # Login / static assets must NOT require auth.
    location = /login   { proxy_pass http://127.0.0.1:8000; }
    location = /logout  { proxy_pass http://127.0.0.1:8000; }
    location /assets/   { proxy_pass http://127.0.0.1:8000; }   # vite output

    # ---- library ----
    location /library/ {
        auth_request /auth/verify;
        auth_request_set $user $upstream_http_x_user;
        proxy_set_header X-Forwarded-User $user;
        # Strip any client-supplied header (defense in depth).
        proxy_set_header X-Forwarded-User-Original "";

        proxy_pass http://127.0.0.1:5001/;
        proxy_set_header Host $host;
    }

    # ---- calendar ----
    location /calendar/ {
        auth_request /auth/verify;
        auth_request_set $user $upstream_http_x_user;
        proxy_set_header X-Forwarded-User $user;
        proxy_set_header X-Forwarded-User-Original "";

        proxy_pass http://127.0.0.1:5002/;
        proxy_set_header Host $host;
    }
}
```

Critical points:
- Backends listen on `127.0.0.1` only. Verify: `ss -tlnp | grep -E '5001|5002|8000'`.
- nginx is the *only* source of `X-Forwarded-User` upstream. The
  `X-Forwarded-User-Original ""` line covers the rename-attack edge case.

---

## 5. Library — modifications

Library stays Flask + SQLite. The change is auth-only.

### 5.1 Auth abstraction

```python
# library/auth.py
from flask import request, session, current_app
from .models import User, db

def current_user():
    """Resolve user. Proxy-mode trusts a header; otherwise reads session."""
    proxy_header = current_app.config.get("AUTH_PROXY_HEADER")
    if proxy_header:
        username = request.headers.get(proxy_header)
        return _get_or_create_proxy_user(username) if username else None
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

def _get_or_create_proxy_user(username: str) -> User:
    """Auto-provision on first sight. Dashboard is the source of truth."""
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, password_hash=None, source="proxy")
        db.session.add(user)
        db.session.commit()
    return user
```

### 5.2 Login route guard

```python
@auth_bp.route("/login")
def login():
    if current_app.config.get("AUTH_PROXY_HEADER"):
        return redirect("/", code=302)   # auth happens upstream
    # ... existing standalone login form ...
```

### 5.3 Config

```python
# library/config.py
AUTH_PROXY_HEADER = os.environ.get("AUTH_PROXY_HEADER")  # e.g. "X-Forwarded-User"
```

Standalone: unset → existing flow. Deployed: `X-Forwarded-User` → trust-header.

### 5.4 Bind safely

```
gunicorn -b 127.0.0.1:5001 'library:create_app()'
```

For paranoia, in proxy mode add a `before_request` that 403s any non-loopback
`request.remote_addr`.

### 5.5 Existing-user migration

One-off SQL after the proxy goes live:

```sql
UPDATE users SET username = 'ellery' WHERE username = '<your old account>';
DELETE FROM users WHERE username NOT IN ('ellery', 'family-member-1');
```

Book / bookmark FKs already point at `user_id`, so they survive the rename.

---

## 6. Calendar — modifications

Identical shape to library (smaller diff because the auth surface is smaller).

- Copy `auth.py` from library, swap the model import.
- Same config flag (`AUTH_PROXY_HEADER`).
- Same login-route guard.
- **Subevent ownership**: keep things simple — children inherit `user_id` from
  the root event. Only revisit if shared/collaborative events become a real
  feature.

---

## 7. Containerize library and calendar

Required so they appear in the dashboard's existing Docker monitor coherently.
Both repos already have Docker configuration; this is a cleanup-and-commit, not
new infrastructure.

Each app needs:

- A working `Dockerfile` (likely present; audit it: pinned base image,
  non-root user, exposed port matches what nginx upstream expects).
- A `/healthz` route returning 200 with no auth — used by Docker `HEALTHCHECK`
  and by curious humans.
- An entrypoint that respects `AUTH_PROXY_HEADER` from env.
- Bind to `0.0.0.0` inside the container; nginx targets the docker network. The
  "only reachable from nginx" property comes from docker-compose network
  isolation, not from binding to 127.0.0.1 inside the container.

Container-naming convention:
- `library` (not `library_app_1` or whatever compose auto-names) so the
  `services.container_name` join in §3.4 is stable. Use
  `container_name: library` in compose.

---

## 8. Migration plan (rollout order)

Independently revertible at every step.

1. **Dashboard: add auth tables + module + endpoints.** No nginx yet, no proxy
   enforcement. Browser-test `/login` → set cookie → `/me` returns user.
2. **Dashboard: containerize itself.** Write a Dockerfile if missing. Confirm
   it still works.
3. **Stand up nginx in front of dashboard only.** TLS via mkcert for now.
   Browser-test that login through nginx works, cookies persist.
4. **Wire library into nginx, `AUTH_PROXY_HEADER` UNSET.** Library still
   serves its own login. End-to-end test `/library/` routing.
5. **Flip library into proxy mode.** Set `AUTH_PROXY_HEADER=X-Forwarded-User`
   in its compose env. Browser-test: hit `/library/` while logged into
   dashboard → no prompt, header-derived user is recognized.
6. **Auto-provision check.** Admin-create a new user in dashboard. Have them
   log in, navigate to `/library/`. Confirm library auto-creates the FK row.
7. **Repeat steps 4–6 for calendar.**
8. **Tighten.** Hide the now-dead login templates in library/calendar (gated by
   `AUTH_PROXY_HEADER` so standalone dev still shows them).
9. **Multi-user smoke test.** Add a family-member account; confirm strict
   per-user isolation in library and calendar.

---

## 9. Security checklist

- [ ] Backend containers bind inside docker network only; nginx is the only
      port-mapped service on the host.
- [ ] nginx strips inbound `X-Forwarded-User` and similar header names before
      setting its own.
- [ ] Sessions stored server-side, hard expiry + idle timeout.
- [ ] Cookie attributes: `HttpOnly`, `Secure`, `SameSite=Lax`.
- [ ] Passwords hashed with **argon2id**.
- [ ] Rate limit `/login` (`limit_req_zone` in nginx).
- [ ] CSRF tokens on dashboard login form. FastAPI: use a double-submit cookie
      or a per-session CSRF token returned by `/me`.
- [ ] `/auth/verify` marked `internal` in nginx; clients can't call directly.
- [ ] HTTPS only (mkcert on LAN; Let's Encrypt via DNS challenge if exposing
      publicly; or Tailscale Funnel certs).
- [ ] Health endpoints (`/healthz`, `/library/healthz`, `/calendar/healthz`)
      configured with `auth_request off` so the dashboard can poll without
      bouncing through auth.

---

## 10. Future migration path

The trusted-header pattern is forward-compatible with:

- **[Authelia](https://www.authelia.com/)** — self-hosted SSO; emits the same
  `Remote-User` / `X-Forwarded-User` header convention. Dashboard would shrink
  to "service registry + Docker monitor."
- **[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/)** — sits in
  front of nginx, integrates with Google / GitHub / etc.
- **[Authentik](https://goauthentik.io/)** — heavier, full IdP with admin UI.

Backends don't change for any of these — that's the *point* of standardising
on the trusted-header pattern from day one.

---

## 11. docker-compose layout (Pi)

A single compose file at the home-services root brings up the whole stack.
Approximate shape:

```yaml
# ~/home/docker-compose.yml
version: "3.9"

services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./tls:/etc/ssl/home:ro
    depends_on: [dashboard, library, calendar]

  dashboard:
    build: ./dashboard
    container_name: dashboard
    environment:
      - DATABASE_URL=sqlite:////data/dashboard.db
      - SESSION_COOKIE_DOMAIN=home.local
    volumes:
      - dashboard_data:/data
      - /var/run/docker.sock:/var/run/docker.sock   # needs root or 'docker' group
    expose: ["8000"]

  library:
    build: ./library
    container_name: library
    environment:
      - AUTH_PROXY_HEADER=X-Forwarded-User
      - BOOK_DIR=/data/books
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    volumes:
      - library_data:/data
    expose: ["5001"]

  calendar:
    build: ./calendar
    container_name: calendar
    environment:
      - AUTH_PROXY_HEADER=X-Forwarded-User
    volumes:
      - calendar_data:/data
    expose: ["5002"]

volumes:
  dashboard_data:
  library_data:
  calendar_data:
```

The `docker.sock` bind-mount is what gives dashboard its container view. It's
a real privilege (effectively root on the host) — that's an accepted tradeoff
of a single-trusted-operator home setup. If you ever invite less-trusted users
to administer, swap to a read-only Docker socket proxy (e.g.
`tecnativa/docker-socket-proxy`).

`expose` (not `ports`) keeps each backend reachable only inside the docker
network — nginx is the sole `ports`-mapped service.

---

## 12. Open decisions

- **Domain.** Pick a stable hostname for the Pi: `home.local`,
  `house.lan`, or a Tailscale-magic-DNS name. All cookies + same-origin
  assumptions key off it.
- **TLS source.** mkcert (LAN), Let's Encrypt via DNS challenge (if public
  DNS points into the LAN), or Tailscale Funnel automatic certs.
- **Family onboarding.** Admin-only create from dashboard, vs. self-service
  with admin approval. Recommend admin-only at this scale.
- **CSRF mechanism.** Double-submit cookie is simplest with FastAPI + an SPA.
  Per-session token returned by `/me` is slightly more secure. Decide before
  shipping.
- **Frontend routing.** `react-router-dom` (default), TanStack Router, or
  Wouter. Default is fine.
- **Container restart policy.** `restart: unless-stopped` is the right
  default; just confirm.
- **Dashboard observability scope.** What does "stats" mean once auth lands?
  Live Docker stats are honest. Synthetic user-engagement metrics are
  theatre — skip those until they earn their place.
