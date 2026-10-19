# Adding an app to the stack

Two commands on the Mac, then the Pi does the rest.

```sh
cd ~/Projects/dashboard
scripts/stack.py new weather --title "Weather" --description "Forecasts for home"
# … build it in ~/Projects/weather; commit as you go …
scripts/stack.py publish weather --icon cloud
```

`new` creates `~/Projects/<name>` from `stack/template`: a Flask app with a health check, tests, CI, a Dockerfile and gunicorn on port 8000, already set up to run under `/<name>/`.

`publish`:

1. creates `github.com/<you>/<name>` (public), using the GitHub credential git already pushes with;
2. pushes the app;
3. adds it to `stack/apps.toml` and regenerates `compose.apps.yml` and `nginx/conf.d/apps/<name>.locations`;
4. commits and pushes the dashboard.

On the Pi, the deploy timer then, within a few minutes:

1. clones the new repo next to the others;
2. deploys the dashboard: nginx now routes `/<name>/`, behind the usual sign-in;
3. waits for the app's CI to pass, builds it, starts it and checks its health;
4. shows its tile on the Services page.

From then on, every push to the app's `main` that passes CI deploys like any other app, with rollback if it doesn't start healthy.

## What every app gets

- **Sign-in:** nginx checks the dashboard session first, and the app receives `X-Forwarded-User`.
- **Its own path:** `/<name>/`, with `X-Forwarded-Prefix` set; the template's `ProxyFix` makes `url_for()` include it.
- **Storage:** `../<name>/instance` on the Pi is mounted at `/app/instance`; keep a SQLite database there.
- **Environment:** `APPLICATION_ROOT=/<name>` and `AUTH_PROXY_HEADER=X-Forwarded-User`. To add more, put them in the app's `env` table in `stack/apps.toml`, using `${VAR}` for secrets kept in the Pi's `.env`, then run `scripts/stack.py render`.

## Rules

- Names are lowercase letters, digits and dashes, and can't clash with an existing route (`library`, `calendar`, `music`, `api`, `login`…).
- The app must answer `GET /healthz` on port 8000, and its repo must have `.github/workflows/ci.yml`; the Pi deploys nothing without a passing CI run.
- Generated files are never edited by hand. The dashboard's CI fails if they don't match `stack/apps.toml`.

## Removing an app

Delete its `[[app]]` entry, run `scripts/stack.py render`, then commit and push the dashboard. On the Pi, stop it with `docker compose stop <name> && docker compose rm -f <name>`; its folder and data stay until you delete them.
