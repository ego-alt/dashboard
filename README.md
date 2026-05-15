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
docker compose exec dashboard python -m app.cli create-admin <username>
uv run python scripts/sync_household_users.py                # mirror users → library + calendar
open https://localhost                                     # hub: a tile per labeled service
open https://localhost/library/                            # EPUB library (dashboard login required)
open https://localhost/calendar/                           # calendar (dashboard login required)
```

The hub auto-discovers services from Docker labels — no registration step.
Any container with `homehub.enable=true` + `homehub.route` (see the
`labels:` blocks on `library`/`calendar` in `docker-compose.yml`) appears as
a tile. Add a service = add labels where you already define the container.

Set `LIBRARY_BOOK_DIR` in `.env` to your existing books path (e.g.
`/mnt/backup/books`). The compose file mounts `../library/instance` for the
SQLite DB — point that at your existing `instance/` if migrating a live deploy.

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `dev-certs.sh` | TLS certs for nginx (`./tls/home.crt` + `.key`) |
| `sync_household_users.py` | Copy dashboard roster → library/calendar shadow `users` |

Dashboard DB is bind-mounted like library/calendar: **`./data/dashboard.db`** →
`/data/dashboard.db` in the container (same file on host and in Docker).

The container runs as uid **10001**. If you create users or touch the DB on the
host with `uv run python -m app.cli …`, fix ownership before logging in via
compose: `sudo chown -R 10001:10001 data/` then `docker compose restart dashboard`.

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for notes on the one-time May 2026
consolidation (already applied on this Pi).

**After adding a dashboard user** (`python -m app.cli create-admin …`):

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
| `/services`                          | GET    | user     | Hub tiles discovered from `homehub.*` Docker labels + status (running/stopped) |
| `/containers`                        | GET    | user     | List containers + live stats |
| `/containers/{id}/start\|stop\|restart` | POST | admin   | Container lifecycle (refuses protected gateway containers, 409) |
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

Service tiles aren't a CLI concern — they're discovered from Docker
`homehub.*` labels (see Quickstart).

Inside compose: `docker compose exec dashboard python -m app.cli <cmd>`.

## Environment

Copy [`.env.example`](.env.example) to `.env` and edit. Compose reads `.env`
automatically; for `uv run`-based dev, `export` the vars or use `direnv`.
Notable knobs: `SESSION_COOKIE_SECURE`, `DOCKER_GID`,
`PROTECTED_CONTAINERS` (gateway containers the monitor refuses to
stop/restart — default `dashboard,home-nginx`), and `DASHBOARD_API_TARGET`
(Vite dev-proxy upstream).

## Tests

```sh
uv run pytest
```

34 tests cover the auth surface (login lifecycle, session expiry, cookie
attributes, authorization gates), label-based service discovery (filtering,
status, daemon-down resilience, sort order), the protected-container
anti-lockout guard, and a mocked-daemon layer for `app/docker_control.py`.

## Layout

```
app/                FastAPI application
  auth.py           argon2id hashing, sessions, FastAPI deps
  db.py             SQLAlchemy engine, get_db, session_scope
  models.py         User, UserSession, Service ORM
  docker_control.py docker-py wrappers, parallelized stats
  services.py       service discovery from Docker homehub.* labels
  system_stats.py   psutil-only host stats
  main.py           routes + lifespan + protected-container guard
  cli.py            operator CLI (users, sessions)
frontend/           React 19 + Vite SPA: login, service-tile home, admin monitor
nginx/conf.d/       Reverse-proxy + auth_request config
scripts/            dev-certs.sh, sync_household_users.py
docs/               MIGRATION.md (one-time stack consolidation notes)
tests/              pytest
Dockerfile          Multi-stage (Vite build + uv) for the FastAPI service
docker-compose.yml  nginx + dashboard + library + calendar
PLAN.md             Full design rationale + migration roadmap
```
