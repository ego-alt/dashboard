# Apps on the stack

Any repo can join the stack, in any language or framework, if it has three files:

| File | What it's for |
|---|---|
| `Dockerfile` | At the root. The image serves HTTP on the manifest's port. |
| `homestack.toml` | The manifest below. |
| `.github/workflows/ci.yml` | The Pi deploys a commit only after this workflow passes. Give it an `image` job like the library's, which publishes `ghcr.io/<owner>/<repo>:<commit>` for the Pi to pull; without one the Pi builds the image itself, which is slow and heavy on it. |

```toml
# homestack.toml (only title is required)
title = "Situation"              # its tile on Services, and its name in Deploy
description = "World news on a map"
icon = "icon.svg"                # an SVG in the repo, drawn in one colour (use currentColor)
accent = "#ffb020"               # that colour; it must stand out on the dark tile (3:1 contrast)
port = 8000                      # the port the container listens on (default 8000)
health = "/healthz"              # answers 2xx when the app is up (default /healthz)
data = "/app/instance"           # a folder kept across deploys, at <stack>/<name>/instance on the Pi

[env]                            # more environment; "${VAR}" reads the dashboard's .env on the Pi
NTFY_TOPIC = "${NTFY_TOPIC}"
```

The rules live in `app/stack_manifest.py`; the Deploy tab and the Pi both use them.

## Adding one

1. Push the repo to GitHub under the same account as the stack. A private repo works once the dashboard has a `DEPLOY_GITHUB_TOKEN` that can read it (see [DEPLOY.md](DEPLOY.md)); the Pi clones it with the GitHub credential git already has.
2. In the dashboard, open **Deploy → Add an app** and pick it. The checklist says what's missing, if anything.
3. Click **Deploy**. The Pi:
   - clones the repo next to the others;
   - generates its compose service and nginx route at `/<repo name>/`;
   - waits for its CI to pass, then builds and starts it;
   - checks that the health path answers.

   Progress shows in the app's **Log**, and its tile appears on Services.

From then on, every push that passes CI deploys within 5 minutes, and a commit that doesn't come up healthy is rolled back. **Deploy now** skips the wait; **Remove** stops the container (its folder and data stay on the Pi).

## What the app gets

- **Sign-in:** nginx lets a request through only with a dashboard session, and adds `X-Forwarded-User` (who it is).
- **Its own path:** `/<name>/`, with the prefix removed before the request reaches the app and passed as `X-Forwarded-Prefix`. Build links from it, or from `APPLICATION_ROOT`, which is set to `/<name>` (in Flask, `ProxyFix(x_prefix=1)` does this for `url_for`).
- **Environment:** `APPLICATION_ROOT`, `AUTH_PROXY_HEADER=X-Forwarded-User`, and anything under `[env]`.
- **Websockets** pass through.

## How it fits together

- **The dashboard** (`app/deploy.py`) records enabled apps in `apps/<name>.json` and "deploy now" requests in `requests/<name>`, in the deploy state folder (`/var/lib/home-stack-deploy` on the Pi). It reads `status.json` and `logs/` from the same folder. It never builds or starts anything itself.
- **The deploy script** (`scripts/deploy.sh`, run by the timer, and at once when a request appears) does the cloning, building, health checks and rollbacks. `scripts/stack_render.py` writes the generated compose file and nginx routes into `generated/`.
