# Dashboard

Home-services hub for a Pi-hosted stack: FastAPI auth provider, server-side
sessions, Docker container monitor, and a React frontend. Nginx terminates TLS
in front; other services (library, calendar) trust an `X-Forwarded-User` header
that nginx injects after an `auth_request` to dashboard's `/auth/verify`.

The architecture rationale lives in [`PLAN.md`](PLAN.md).

## Stack

- **Backend**: FastAPI + uvicorn (Python 3.11+, managed by `uv`)
- **DB**: SQLAlchemy 2.0 over SQLite (drop-in to Postgres later)
- **Auth**: argon2id hashing, server-side `user_sessions` table, HttpOnly cookies
- **Frontend**: React 19 + Vite + Tailwind v4
- **Container view**: docker-py + psutil
- **Reverse proxy**: nginx (TLS termination + `auth_request`)

## Quickstart — full stack via compose

```sh
scripts/dev-certs.sh                                       # one-time TLS for home.local + localhost
docker compose up -d --build
uv run python scripts/household_sql_pass.py                # once (or after adding users)
docker compose up -d --build
open https://localhost                                     # accept self-signed if no mkcert
open https://localhost/library/                            # EPUB library (dashboard login required)
open https://localhost/calendar/                           # calendar (dashboard login required)
```

Set `LIBRARY_BOOK_DIR` in `.env` to your existing books path (e.g.
`/mnt/backup/books`). The compose file mounts `../library/instance` for the
SQLite DB — point that at your existing `instance/` if migrating a live deploy.

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `dev-certs.sh` | TLS certs for nginx (`./tls/home.crt` + `.key`) |
| `household_sql_pass.py` | One-time bootstrap: backups, dashboard users, sync |
| `sync_household_users.py` | **Ongoing:** copy dashboard roster → library/calendar shadow `users` |

Dashboard DB is bind-mounted like library/calendar: **`./data/dashboard.db`** →
`/data/dashboard.db` in the container (same file on host and in Docker).

**First-time / reset:**

```sh
uv run python scripts/household_sql_pass.py
```

Creates `data/dashboard.db`, household users `admin` + `natalieha`, syncs library
and calendar. Passwords go to `.bootstrap-credentials` unless
`DASHBOARD_ADMIN_PASSWORD` / `DASHBOARD_NATALIE_PASSWORD` are set.

**After adding a dashboard user** (`python -m app.cli create-user …`):

```sh
uv run python scripts/sync_household_users.py
```

**Sync does not:** copy passwords, merge bookmarks/events, or change numeric
`user_id`s. It only ensures each dashboard username exists in the app DBs
(`password_hash` NULL for proxy mode). First HTTP visit also auto-creates missing
rows; the script avoids surprises before someone opens an app.

Optional: `sync_household_users.py --prune-library` drops library users absent
from dashboard with no bookmarks/tags.

If your host's `docker.sock` has a non-default GID, set `DOCKER_GID` before
`compose up`. Pi/Debian is usually `999`, macOS + colima is often `991` — check
with `stat -c '%g' /var/run/docker.sock`.

## Quickstart — backend dev (no Docker)

```sh
uv sync
uv run uvicorn app.main:app --reload                       # http://127.0.0.1:8000
uv run python -m app.cli create-admin <username>
```

## Quickstart — frontend dev

```sh
cd frontend
npm install
npm run dev                                                # vite on http://localhost:5173
                                                           # talks to backend on :8000 via CORS
```

## Endpoints

| Route                                | Method | Auth     | Purpose |
| ------------------------------------ | ------ | -------- | --- |
| `/ping`                              | GET    | public   | Healthcheck (Docker `HEALTHCHECK` target) |
| `/login`                             | POST   | public   | Username + password → session cookie |
| `/logout`                            | POST   | public   | Revoke current session |
| `/me`                                | GET    | user     | Current-user info |
| `/auth/verify`                       | GET    | internal | nginx `auth_request`; returns `X-User` on 200 |
| `/containers`                        | GET    | user     | List containers + live stats |
| `/containers/{id}/start\|stop\|restart` | POST | admin   | Container lifecycle |
| `/containers/{id}/logs`              | GET    | user     | Recent logs |
| `/stats/system`                      | GET    | user     | psutil CPU / mem / disk |
| `/stats/containers/{id}`             | GET    | user     | Per-container CPU / network |

`/auth/verify` is marked `internal` in nginx — external clients hit 404. Only
nginx-internal subrequests can reach it.

## CLI

```sh
uv run python -m app.cli create-admin <user> [--display-name "Name"]
uv run python -m app.cli passwd        <user>
uv run python -m app.cli list-users
uv run python -m app.cli purge-sessions
```

Inside compose: `docker compose exec dashboard python -m app.cli <cmd>`.

## Environment

Copy [`.env.example`](.env.example) to `.env` and edit. Compose reads `.env`
automatically; for `uv run`-based dev, `export` the vars or use `direnv`.

## Tests

```sh
uv run pytest
```

23 tests cover the auth surface (login lifecycle, session expiry, cookie
attributes, authorization gates) and a mocked-daemon layer for
`app/docker_control.py`.

## Layout

```
app/                FastAPI application
  auth.py           argon2id hashing, sessions, FastAPI deps
  db.py             SQLAlchemy engine, get_db, session_scope
  models.py         User, UserSession, Service ORM
  docker_control.py docker-py wrappers, parallelized stats
  system_stats.py   psutil-only host stats
  main.py           routes + lifespan
  cli.py            operator CLI
frontend/           React 19 + Vite SPA (login + dashboard shell + router)
nginx/conf.d/       Reverse-proxy + auth_request config
scripts/            dev-certs.sh, household_sql_pass.py, sync_household_users.py
tests/              pytest
Dockerfile          Multi-stage (Vite build + uv) for the FastAPI service
docker-compose.yml  nginx + dashboard + library + calendar
PLAN.md             Full design rationale + migration roadmap
```
