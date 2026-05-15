# One-time migration (May 2026)

This Pi stack was consolidated so dashboard auth is the single login for
library and calendar. That work is **done** on this deploy; you do not need to
re-run any migration script.

## What changed

- Dashboard SQLite moved from `dashboard.db` (repo root) to **`data/dashboard.db`**
  (bind-mounted into the container at `/data/dashboard.db`).
- Library/calendar keep their own `instance/*.db` files; usernames are mirrored
  via `scripts/sync_household_users.py` (shadow `users` rows, no shared passwords).
- Orphan library accounts outside the household roster were cleaned up once.

## Docker ownership

The dashboard container runs as uid **10001**. If you create or modify
`data/dashboard.db` on the host (e.g. with `uv run python -m app.cli …`),
ensure the bind mount is writable in Docker:

```sh
sudo chown -R 10001:10001 data/
docker compose restart dashboard
```

Without this, login can succeed at the password check but fail with HTTP 500
(`attempt to write a readonly database`).

## Ongoing operations

| Task | Command |
|------|---------|
| Add dashboard user | `docker compose exec dashboard python -m app.cli create-admin …` |
| Sync library/calendar users | `uv run python scripts/sync_household_users.py` |
| Reset password | `docker compose exec dashboard python -m app.cli passwd …` |
