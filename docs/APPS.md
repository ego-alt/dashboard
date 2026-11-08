# Apps on the stack

How an app joins the home stack, what the stack and the app owe each other, and how the Pi deploys it.

The stack is unified at its edges, not in its code: who you are, where an app lives, whether it's up, how it ships, what crosses the wire, how it looks. Inside, each app is its own: its own repo, database, framework and code, copied rather than shared where two apps need the same thing. So any repo can join, in any language or framework, and every app still makes sense without the stack.

## What an app needs

Three files:

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

## The contract

What the stack gives every app:

- **Sign-in.** nginx lets a request through only with a dashboard session (or a dashboard API token, for native apps), and adds `X-Forwarded-User`: who it is. Deciding which apps a user may open belongs here too, once it's built, so apps never need to know.
- **Signed out.** When the session ends, nginx answers the page's requests with a 401 and `X-Signed-Out: 1`, and a full page load goes to the dashboard's sign-in.
- **Its own path:** `/<name>/`, with the prefix removed before the request reaches the app and passed as `X-Forwarded-Prefix`. `APPLICATION_ROOT` is set to `/<name>` (in Flask, `ProxyFix(x_prefix=1)` makes `url_for` use it).
- **Environment:** `APPLICATION_ROOT`, `AUTH_PROXY_HEADER=X-Forwarded-User`, and anything under `[env]`.
- **Deploys, rollbacks and backups** (below), and websockets passed through.

What every app owes the stack:

1. **Trust the user header only in the stack.** Read `X-Forwarded-User` only when `AUTH_PROXY_HEADER` is set, and create the user on their first visit.
2. **Fail safe on its own.** Without the header (run outside the stack, or reached directly) an app has its own sign-in, or refuses. It is never open to whoever reaches it.
3. **Answer the health path** without signing in, and only when it can do its job.
4. **Build every link from the prefix.** Never assume the app is at `/`.
5. **Notice being signed out.** A 401 with `X-Signed-Out` keeps what was being saved on the page and offers to sign in again (the Flask apps share `signed_out.js` for this, copied byte for byte).
6. **Send times with their zone** (`2026-11-08T03:59:44+00:00`), for the browser to show in the viewer's zone. A wall-clock time someone typed (a diary entry at 12:30) is sent as written.
7. **Keep everything worth keeping under `data`,** and nothing that can't be rebuilt anywhere else. Databases are SQLite there; add the app's database to the backup (BACKUPS.md).
8. **Look like itself, by the shared rules** in [design.md](design.md): its own theme and tokens, the shared principles and stylesheet rules.

Where the apps stand:

| | Header sign-in | On its own |
|---|---|---|
| Calendar | yes | its own sign-in |
| Library | yes | its own sign-in |
| Tapes | yes | **open**: a single local user, for development |
| Situation | no sign-in at all | **open** |

Two gaps remain (see the [roadmap](roadmap.md)): Tapes and Situation don't yet fail safe, and the apps trust the user header from anything on the compose network, not only nginx and `mcp` (the planned fix is a shared `X-Internal-Auth` secret, which `mcp` already sends).

## Adding one

1. Push the repo to GitHub under the same account as the stack. A private repo works once the dashboard has a `DEPLOY_GITHUB_TOKEN` that can read it (see [installing](#install-once-on-the-pi)); the Pi clones it with the GitHub credential git already has.
2. In the dashboard, open **Deploy → Add an app** and pick it. The checklist says what's missing, if anything.
3. Click **Deploy**. The Pi:
   - clones the repo next to the others;
   - generates its compose service and nginx route at `/<repo name>/`;
   - waits for its CI to pass, then pulls or builds the image and starts it;
   - checks that the health path answers.

   Progress shows in the app's **Log**, and its tile appears on Services.

From then on, every push that passes CI deploys within 5 minutes, and a commit that doesn't come up healthy is rolled back. **Deploy now** skips the wait; **Remove** stops the container (its folder and data stay on the Pi).

## Phone apps

An Android app joins the same way, without a Dockerfile: its `homestack.toml` says what it is.

```toml
title = "Scanner"
kind = "android"
package = "com.scanner.app"      # its applicationId
description = "Scan documents"
icon = "icon.svg"
accent = "#7dd3fc"
```

- **Its CI publishes the builds.** Each push that builds produces a signed APK, released on GitHub with the tag `v<versionCode>`, named after its `versionName`, and the APK attached. A release exists only when CI passed, so the rule holds: nothing ships that didn't pass. Sign every build with the same key, or phones refuse the update.
- **Adding it** (Deploy → Add an app) lists it under **Phone apps** on Services. Nothing runs on the Pi: the dashboard fetches each new release's APK once and keeps it (in the dashboard's `data/phone-apps/` on the Pi), so phones install over the tailnet.
- **Services** offers Install, Update to 1.0.12, or Up to date. A web page can't see what a phone has installed, so the app says so itself when it checks for updates.
- **The app checks for updates** with `GET /phone-apps/<name>/latest?installed=<versionCode>&installed_name=<versionName>` and downloads from `GET /phone-apps/<name>/download`. Both take the dashboard API token the app already holds (`Authorization: Bearer …`); a token reaches nothing else in the dashboard.

The code is `app/routes/phone_apps.py`.

## How deploys work

All the repos sit side by side on the Pi, and each runs CI on GitHub on every push and pull request. On a push to the deploy branch, once the checks pass, CI also builds the app's image for the Pi (ARM) and publishes it as `ghcr.io/<owner>/<repo>:<commit>` (the dashboard's `mcp` as `…/dashboard-mcp:<commit>`).

The Pi **pulls** its deploys; nothing pushes to it. A systemd timer runs `scripts/deploy.sh` every 5 minutes, and a path unit runs it at once when the dashboard asks ("Deploy now"). For each repo it:

1. fetches the deploy branch (`main` for tapes and situation, `master` for the rest);
2. stops unless there's a new commit **and** that commit's CI run passed (`app/ci.py` decides, the same rule the Deploy tab uses: a run cancelled by a newer push doesn't count). A repo that matches GitHub but whose container runs another commit's image (after a reset by hand) is redeployed;
3. fast-forwards, pulls the image CI published for that commit (tagged as the service's local `<service>:dev`) and restarts only that service; a repo with no image for the commit is built on the Pi instead. The last two pulled images of each repo are kept, for a rollback. A dashboard change also re-applies `docker-compose.yml` to the other services, reloads nginx (waiting for it if recreating its dependencies restarted it), and rebuilds the `mcp` container. Every run ends by starting nginx if it's found stopped, since it's the way in to everything. That last step is best-effort: a broken `mcp` shows as failed and never rolls the dashboard back, and "Deploy now" on its row starts just it again;
4. waits for the container's health check. If it doesn't come up healthy, it rolls back to the previous commit (pulling that commit's image), and won't retry the bad commit until a newer one lands. If the rollback doesn't come up either, it tries the rollback again every 30 minutes.

Each repo's place in this is written to `status.json` as one explicit state, with the commit it's about: `waiting-for-ci`, `no-ci`, `ci-failed`, `deploying`, `live`, `failed` (a first deploy that didn't start), `rolled-back` or `rollback-failed` (the list is at `record` in `scripts/deploy.sh`). The Deploy tab shows that state as it is while it's about GitHub's newest commit, and otherwise what GitHub says about the newer commit the Pi hasn't looked at yet.

It skips any repo with local edits or a branch that has diverged from GitHub, so hand-made changes on the Pi are never overwritten. Database migrations run when containers start (`flask db upgrade` in the Flask apps; the dashboard adds new tables and columns itself).

The pieces: the dashboard (`app/routes/deploy.py`) records enabled apps in `apps/<name>.json` and "deploy now" requests in `requests/<name>`, in the deploy state folder (`/var/lib/home-stack-deploy` on the Pi), and reads `status.json` and `logs/` from it; it never builds or starts anything itself. `scripts/deploy.sh` does the cloning, building, health checks and rollbacks, and `scripts/stack_render.py` writes the generated compose file and nginx routes into `generated/`.

A change to `deploy.sh` itself is rolled out by hand with the timer stopped: bash reads a script as it runs, so a run that pulls a new `deploy.sh` would continue partway into the new file.

### Install once on the Pi

From the dashboard folder:

```sh
sudo scripts/install-deploy-timer.sh
```

It also installs `home-stack-power.path`, which powers the Pi off when an admin taps the power icon in the dashboard (`scripts/power.sh`; `journalctl -u home-stack-power` shows who asked). Re-run it after pulling a version that adds a unit. It runs deploys as the user who owns the repos (who must be in the `docker` group), and prints two lines to add to the dashboard's `.env` (`DEPLOY_STATE_HOST_DIR`, `STACK_APPS_COMPOSE`) so compose and the Deploy tab find the deploy state. Optionally add `DEPLOY_GITHUB_TOKEN` there too: a read-only token lifts the limit of 60 API requests an hour, which the Deploy tab can otherwise use up, and lets it see private repos. Make it a fine-grained token for your account with read-only **Contents**, **Actions** and **Metadata**, on all repos or just the ones you'll deploy. It sits in a web-facing container, so don't reuse a broad token. Then:

```sh
journalctl -u home-stack-deploy -f              # watch deploys
cat /var/lib/home-stack-deploy/status.json      # each repo's state
sudo systemctl start home-stack-deploy          # check right now
systemctl list-timers home-stack-deploy.timer   # next run
```

To pause auto-deploys: `sudo systemctl stop home-stack-deploy.timer home-stack-deploy.path` (`start` to resume). To deploy by hand, run the same steps yourself: `git pull` in the repo, then `docker pull ghcr.io/<owner>/<repo>:<commit> && docker tag ghcr.io/<owner>/<repo>:<commit> <service>:dev && docker compose up -d --no-build <service>` (or `docker compose build <service>` to build it on the Pi).

### Why build images in CI, and pull?

Building an image is the heaviest thing the Pi did: during a burst of comic uploads, a build on top pushed it into swap until it stopped answering. CI builds each image once, on GitHub's ARM machines, from a clean checkout (so nothing on the Pi, like a database in `instance/`, can end up inside it), and the Pi only downloads it. What runs is exactly what CI tested, deploys take seconds, and a rollback is a pull of the previous commit's image. Moving to an x86 machine later means changing `platforms:` in each workflow.

The images are public, like the repos. The image job runs only for pushes to the deploy branch, never pull requests (so no one else's code can publish one), with the workflow's own short-lived token and write access to packages only in that job; its actions are pinned to exact commits. The Pi pulls by commit, and only commits whose CI passed.

The Pi polls rather than running a GitHub runner because GitHub advises against self-hosted runners on public repos: a pull request from anyone could run code on the Pi. Polling needs no inbound access and only reads CI results. For a private repo, the script uses `DEPLOY_GITHUB_TOKEN` or, failing that, the token git has saved for github.com, the same one that clones and fetches it.
