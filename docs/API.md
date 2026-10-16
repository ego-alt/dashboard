# API

Everything the dashboard serves, for the SPA, nginx, native apps and the MCP server. "user" means any signed-in session cookie; "admin" an admin's.

| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/ping` | GET | public | Healthcheck (Docker `HEALTHCHECK` target) |
| `/login` | POST | public | Username + password → session cookie |
| `/logout` | POST | public | Revoke the current session |
| `/me` | GET | user | Current user (id, role, 2FA, recovery codes left) |
| `/me/password` | POST | user | Change your password (`current_password`, `new_password`, `sign_out_others`) |
| `/auth/sessions` | GET | user | Your sessions (public ids, device, last seen; never the cookie) |
| `/auth/sessions/{id}` | DELETE | user | Sign out one of your other sessions |
| `/auth/sessions/revoke-others` | POST | user | Sign out everywhere else |
| `/auth/login-events` | GET | user | Your recent sign-ins, including failed attempts |
| `/auth/verify` | GET | internal | nginx `auth_request`: session cookie **or** `Authorization: Bearer <api-token>`; returns `X-User` on 200 |
| `/auth/totp/{setup,enable,disable}` | POST | user | Enrol and manage TOTP 2FA (`enable` returns recovery codes) |
| `/auth/totp/recovery-codes` | POST | user | New recovery codes (needs a current authenticator code) |
| `/auth/totp/verify` | POST | pending | Second-factor step during login |
| `/auth/webauthn/register/*`, `/credentials` | varies | user | Register, list, remove passkeys |
| `/auth/webauthn/login/{begin,finish}` | POST | public | Passkey login |
| `/auth/tokens` | GET / POST | user | List your API tokens (no raw values) / mint one (`name`; the raw token is returned **once**) |
| `/auth/tokens/{id}` | DELETE | user | Revoke an API token |
| `/users` | GET / POST | admin | List / create users (a browser visit redirects to the page) |
| `/users/{id}/{password,admin,reset-2fa}` | POST | admin | Set a password (ends that user's sessions), toggle admin, clear 2FA |
| `/users/{id}` | DELETE | admin | Delete a user (purges their sessions, tokens, passkeys) |
| `/services` | GET | user | Hub tiles from `homehub.*` Docker labels, with state (up/degraded/down) and since when; 503 with the last known tiles when Docker is unreachable |
| `/containers` | GET | user | Containers with state, health, start time and restart count (`?stats=1` adds CPU, memory, network) |
| `/containers/{id}/start\|stop\|restart` | POST | admin | Container lifecycle (refuses the protected gateway containers with 409) |
| `/containers/{id}/logs` | GET | user | Recent log lines (`?tail=`) |
| `/uptime` | GET | user | Uptime strips: `days=1` → 24 hourly buckets, else daily; `tz` = the viewer's UTC offset in minutes |
| `/stats/system` | GET | user | Host CPU, memory, disk, temperature |
| `/stats/containers/{id}` | GET | user | One container's CPU, memory, network |
| `/backups/status` | GET | admin | Last backup run (reads the status file the backup script writes) |

`/auth/verify` is `internal` in nginx, so outside clients get a 404; only nginx's own subrequests reach it.

## API tokens (native apps)

Native clients (e.g. the document scanner uploading to the calendar) can't hold a session cookie, so they use a long-lived API token, made in **Settings → API tokens** (shown once; only its SHA-256 hash is stored). The client sends `Authorization: Bearer <token>`; nginx passes it on the `auth_request` to `/auth/verify`, which resolves it to its owner and returns `X-User`, so the token works for the proxied apps exactly like a browser session.

A token reaches the apps **only**: the dashboard's own endpoints (`/containers`, `/me`, token management) stay cookie-only. Revoke it from the same screen.
