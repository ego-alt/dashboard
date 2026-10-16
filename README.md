# Dashboard

Home-services hub for a Pi-hosted stack: FastAPI auth provider (passwords,
passkeys, TOTP 2FA), server-side sessions, Docker container monitor, and a React
frontend. Nginx terminates TLS in front; other services (library, calendar,
tapes) trust an `X-Forwarded-User` header that nginx injects after an
`auth_request` to dashboard's `/auth/verify`.

The architecture rationale lives in [`PLAN.md`](PLAN.md).

## Pages

- **Services** (`/`): a tile per app with its state (up, degraded, down) and a 30-day uptime strip, plus one status line: all services up, or what's wrong, with the last backup and the fullest disk for admins. Admins can start a down service or open its logs from the tile.
- **Monitor** (`/admin/monitor`, admins): host CPU, memory, disk and temperature; every container with its uptime, restarts, a 24-hour uptime strip, CPU, memory and network; Start, Stop, Restart and a logs drawer (`?logs=<name>` opens one); the last backup. It says when its data is stale.
- **Users** (`/admin/users`, admins): add users, set passwords (which signs the user out everywhere), change roles with Undo, reset 2FA, delete.
- **Settings** (`/settings`): change your password, 2FA with recovery codes, passkeys, where you're signed in (sign out other devices, recent sign-ins), API tokens.

Uptime comes from a sampler thread in the dashboard: once a minute it records each container's state (Docker's `running`, plus its healthcheck when it has one) into hourly rows in `uptime_hours`, kept for 90 days. Minutes when the dashboard itself was down count as no data.

## Stack

- **Backend**: FastAPI + uvicorn (Python 3.11+, managed by `uv`)
- **DB**: SQLAlchemy 2.0 over SQLite (drop-in to Postgres later)
- **Auth**: argon2id passwords (breach-checked vs HaveIBeenPwned at set time),
  server-side `user_sessions` (HttpOnly cookies), TOTP 2FA with recovery codes,
  WebAuthn passkeys
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
open https://localhost/music/                              # tapes music streamer (dashboard login required)
```

The hub auto-discovers services from Docker labels — no registration step.
Any container with `homehub.enable=true` + `homehub.route` (see the
`labels:` blocks on `library`/`calendar`/`music` in `docker-compose.yml`) appears as
a tile. Add a service = add labels where you already define the container.

Set `LIBRARY_BOOK_DIR` in `.env` to your existing books path (e.g.
`/mnt/backup/books`). The compose file mounts `../library/instance` for the
SQLite DB — point that at your existing `instance/` if migrating a live deploy.
Likewise set `MUSIC_HOST_DIR` to your music library (e.g. `/mnt/backup/tapes`);
it's mounted into both nginx (so it can serve audio bytes via `X-Accel`) and the
tapes service.

### Scripts (`scripts/`)

| Script | Purpose |
|--------|---------|
| `dev-certs.sh` | TLS certs for nginx (`./tls/home.crt` + `.key`) |
| `sync_household_users.py` | Copy dashboard roster → library/calendar shadow `users` |
| `restic-backup.sh` | Nightly off-site backup to GCS (see [Backups](#backups)) |
| `restic-restore.sh` | Restore wrapper around `restic restore` |
| `deploy.sh` | Auto-deploy: ships new commits that passed CI (see [Deploying](#deploying)) |
| `install-deploy-timer.sh` | One-time install of the 5-minute deploy timer on the Pi |

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

## Deploying

All four repos (dashboard, library, calendar, tapes) sit side by side on the Pi,
and each runs **CI on GitHub** (`.github/workflows/ci.yml`: tests, the frontend
build here, and advisory lint) on every push and pull request.

The Pi **pulls** its deploys; nothing pushes to it. A systemd timer runs
`scripts/deploy.sh` every 5 minutes. For each repo it:

1. fetches the deploy branch (`main` for tapes, `master` for the rest);
2. stops unless there's a new commit **and** that commit's CI run passed;
3. fast-forwards, rebuilds and restarts only that service. A dashboard change
   also re-applies `docker-compose.yml` to the other services, reloads nginx,
   and rebuilds the `mcp` container. That last step is best-effort: a broken
   `mcp` shows as `"mcp": "failed"` in the status file and never rolls the
   dashboard back;
4. waits for the container's health check. If it doesn't come up healthy, it
   rolls back to the previous commit, rebuilds that, and won't retry the bad
   commit until a newer one lands.

It skips any repo with local edits or a branch that has diverged from GitHub,
so hand-made changes on the Pi are never overwritten. Database migrations run
when containers start (library and calendar run `flask db upgrade`).

**Install once on the Pi** (from the dashboard folder):

```sh
sudo scripts/install-deploy-timer.sh
```

It runs deploys as the user who owns the repos (who must be in the `docker`
group). Then:

```sh
journalctl -u home-stack-deploy -f              # watch deploys
cat /var/lib/home-stack-deploy/status.json      # last outcome per repo
sudo systemctl start home-stack-deploy          # check right now
systemctl list-timers home-stack-deploy.timer   # next run
```

To pause auto-deploys: `sudo systemctl stop home-stack-deploy.timer`
(`start` to resume). To deploy by hand, run the same steps yourself:
`git pull` in the repo, then `docker compose build <service> && docker compose up -d <service>`.

**Why pull, not a GitHub runner on the Pi?** The repos are public, and GitHub
advises against self-hosted runners on public repos: a pull request from anyone
could run code on the Pi. Polling needs no inbound access and only reads
public CI results. (Optional: set `DEPLOY_GITHUB_TOKEN` in the service for a
higher API limit; the default 60 requests/hour is plenty at this rate.)

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
| `/me`                                | GET    | user     | Current-user info (id, role, 2FA, recovery codes left) |
| `/me/password`                       | POST   | user     | Change your password (`current_password`, `new_password`, `sign_out_others`) |
| `/auth/sessions`                     | GET    | user     | Your sessions (public ids, device, last seen; never the cookie) |
| `/auth/sessions/{id}`                | DELETE | user     | Sign out one of your other sessions |
| `/auth/sessions/revoke-others`       | POST   | user     | Sign out everywhere else |
| `/auth/login-events`                 | GET    | user     | Your recent sign-ins, including failed attempts |
| `/auth/verify`                       | GET    | internal | nginx `auth_request`; session cookie **or** `Authorization: Bearer <api-token>`; returns `X-User` on 200 |
| `/auth/totp/{setup,enable,disable}`  | POST   | user     | Enroll / manage TOTP 2FA (`enable` returns recovery codes) |
| `/auth/totp/recovery-codes`          | POST   | user     | New recovery codes (needs a current authenticator code) |
| `/auth/totp/verify`                  | POST   | pending  | Second-factor step during login |
| `/auth/webauthn/register/*`, `/credentials` | varies | user | Register, list, remove passkeys |
| `/auth/webauthn/login/{begin,finish}`| POST   | public   | Passkey login |
| `/auth/tokens`                       | GET    | user     | List the caller's API tokens (no raw values) |
| `/auth/tokens`                       | POST   | user     | Mint an API token (`name`); returns the raw token **once** |
| `/auth/tokens/{id}`                  | DELETE | user     | Revoke an API token |
| `/users`                             | GET/POST | admin  | List / create users (a browser visit redirects to the page) |
| `/users/{id}/{password,admin,reset-2fa}` | POST | admin   | Set password (ends the user's sessions), toggle admin, clear a user's 2FA |
| `/users/{id}`                        | DELETE | admin    | Delete a user (purges their sessions, tokens, passkeys) |
| `/services`                          | GET    | user     | Hub tiles discovered from `homehub.*` Docker labels, with state (up/degraded/down) and since when; 503 with the last known tiles when Docker is unreachable |
| `/containers`                        | GET    | user     | List containers with state, health, start time and restart count (`?stats=1` adds live CPU/memory/network) |
| `/uptime`                            | GET    | user     | Uptime strips: `days=1` → 24 hourly buckets, else daily; `tz` = viewer's UTC offset in minutes |
| `/containers/{id}/start\|stop\|restart` | POST | admin   | Container lifecycle (refuses protected gateway containers, 409) |
| `/containers/{id}/logs`              | GET    | user     | Recent logs |
| `/stats/system`                      | GET    | user     | psutil CPU / mem / disk |
| `/stats/containers/{id}`             | GET    | user     | Per-container CPU / network |
| `/backups/status`                    | GET    | admin    | Last backup run (reads the status file; powers the Monitor "Backups" card) |

`/auth/verify` is marked `internal` in nginx — external clients hit 404. Only
nginx-internal subrequests can reach it.

### API tokens (for native apps)

Native clients (e.g. the document scanner uploading to the calendar) can't hold
a session cookie, so they authenticate with a long-lived **API token**. Generate
one in the frontend at **Settings → API tokens** (shown once; only its SHA-256
hash is stored). The client sends `Authorization: Bearer <token>`; nginx forwards
it on the `auth_request` to `/auth/verify`, which resolves it to the owning user
and returns `X-User` — so the token works for the proxied apps exactly like a
browser session. A token authorizes downstream apps **only**; dashboard-native
endpoints (`/containers`, `/me`, token management) stay cookie-only. Revoke
anytime from the same screen.

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
stop/restart — default `dashboard,home-nginx`), `DASHBOARD_API_TARGET`
(Vite dev-proxy upstream), and `UPTIME_SAMPLER=0` to turn the uptime sampler off.

## AI assistants (MCP)

[`mcp/`](mcp/) is a Model Context Protocol server, the `mcp` container, that lets
any MCP client (Claude, ChatGPT, Gemini, Cursor, local models) use the calendar,
music and library as the signed-in user. Remote clients connect to
`https://home.local/mcp` and sign in through the dashboard login with OAuth.
Desktop clients can instead run it locally over stdio with an API token from
Settings. Connected apps and their activity are listed at `/oauth/connections`.
Setup: [`mcp/README.md`](mcp/README.md). Design: [`docs/mcp-plan.md`](docs/mcp-plan.md).
Open findings: [`mcp/AUDIT.md`](mcp/AUDIT.md).

## Backups

Nightly off-site backup of the whole stack to Google Cloud Storage via
[restic](https://restic.net) — encrypted and deduplicated client-side. One
snapshot covers the four SQLite DBs (snapshotted consistently and
integrity-checked first), each app's `.env`, calendar attachments, books, and
music. A systemd timer runs it at 03:30 with missed-run catch-up. Each run
writes a small status file the **Monitor → Backups** card reads, so a stale or
failed backup is visible in the UI (the dashboard never holds restic creds).

```sh
systemctl status restic-backup.timer        # next run
journalctl -u restic-backup.service -n 50   # last run's log
sudo systemctl start restic-backup.service  # run now
sudo scripts/restic-restore.sh --list       # browse snapshots to restore
```

Full setup (GCS bucket + service account, repo init, install the timer) and
restore / disaster-recovery steps: [`docs/BACKUPS.md`](docs/BACKUPS.md).

## Tests

```sh
uv run pytest
```

The tests cover the auth surface (login lifecycle, session expiry, TOTP 2FA, recovery codes, WebAuthn passkeys, API tokens, HaveIBeenPwned checks, admin user management, your own password and sessions, authorization gates), label-based service discovery (filtering, state, Docker-down handling, sort order), container state and the uptime sampler, the protected-container anti-lockout guard, the backup-status endpoint (freshness/staleness), and a mocked-daemon layer for `app/docker_control.py`.

## Layout

```
app/                FastAPI application
  auth.py           argon2id hashing, sessions, FastAPI deps
  totp.py           TOTP 2FA + recovery codes
  webauthn_helpers.py  passkey registration / assertion
  hibp.py           HaveIBeenPwned k-anonymity password check
  db.py             SQLAlchemy engine, get_db, session_scope
  models.py         User, UserSession, ApiToken, WebauthnCredential, LoginEvent, UptimeHour ORM
  docker_control.py docker-py wrappers, container state, parallelized stats
  services.py       service discovery from Docker homehub.* labels
  system_stats.py   psutil-only host stats
  uptime.py         per-minute uptime sampler + the strips /uptime returns
  main.py           routes + lifespan + protected-container guard
  cli.py            operator CLI (users, sessions)
frontend/           React 19 + Vite SPA: login, services, monitor, users, settings
mcp/                MCP server for AI assistants (own package + container; see mcp/README.md)
nginx/conf.d/       Reverse-proxy + auth_request config
scripts/            dev-certs.sh, sync_household_users.py, restic-backup.sh
  systemd/          restic-backup.{service,timer} for the nightly backup
docs/               MIGRATION.md, BACKUPS.md (restic → GCS runbook), mcp-plan.md (MCP design)
tests/              pytest
Dockerfile          Multi-stage (Vite build + uv) for the FastAPI service
docker-compose.yml  nginx + dashboard + library + calendar + music (tapes) + mcp
PLAN.md             Full design rationale + migration roadmap
```
