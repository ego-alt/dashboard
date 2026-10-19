# Deploying

All the repos (dashboard, library, calendar, tapes, and any app added in the Deploy tab) sit side by side on the Pi, and each runs CI on GitHub (`.github/workflows/ci.yml`: tests, the frontend build here, and advisory lint) on every push and pull request.

The Pi **pulls** its deploys; nothing pushes to it. A systemd timer runs `scripts/deploy.sh` every 5 minutes. For each repo it:

1. fetches the deploy branch (`main` for tapes, `master` for the rest);
2. stops unless there's a new commit **and** that commit's CI run passed;
3. fast-forwards, rebuilds and restarts only that service. A dashboard change also re-applies `docker-compose.yml` to the other services, reloads nginx, and rebuilds the `mcp` container. That last step is best-effort: a broken `mcp` shows as `"mcp": "failed"` in the status file and never rolls the dashboard back;
4. waits for the container's health check. If it doesn't come up healthy, it rolls back to the previous commit, rebuilds that, and won't retry the bad commit until a newer one lands.

The **Deploy** tab in the dashboard shows each repo's running and latest commit, CI result and deploy log, with "Deploy now". Apps added there are cloned, given a compose service and an nginx route, and deployed once their CI passes; a dashboard deploy never restarts them (see [`APPS.md`](APPS.md)). "Deploy now" starts a run at once (a systemd path unit watches for the request).

It skips any repo with local edits or a branch that has diverged from GitHub, so hand-made changes on the Pi are never overwritten. Database migrations run when containers start (library and calendar run `flask db upgrade`; the dashboard adds new tables and columns itself).

## Install once on the Pi

From the dashboard folder:

```sh
sudo scripts/install-deploy-timer.sh
```

It runs deploys as the user who owns the repos (who must be in the `docker` group), and prints two lines to add to the dashboard's `.env` (`DEPLOY_STATE_HOST_DIR`, `STACK_APPS_COMPOSE`) so compose and the Deploy tab find the deploy state. Optionally add `DEPLOY_GITHUB_TOKEN` there too: a read-only token lifts the limit of 60 API requests an hour, which the Deploy tab can otherwise use up, and lets it see private repos. Make it a fine-grained token for your account with read-only **Contents**, **Actions** and **Metadata**, on all repos or just the ones you'll deploy. It sits in a web-facing container, so don't reuse a broad token. Then:

```sh
journalctl -u home-stack-deploy -f              # watch deploys
cat /var/lib/home-stack-deploy/status.json      # last outcome per repo
sudo systemctl start home-stack-deploy          # check right now
systemctl list-timers home-stack-deploy.timer   # next run
```

To pause auto-deploys: `sudo systemctl stop home-stack-deploy.timer` (`start` to resume). To deploy by hand, run the same steps yourself: `git pull` in the repo, then `docker compose build <service> && docker compose up -d <service>`.

## Why pull, not a GitHub runner on the Pi?

The repos are public, and GitHub advises against self-hosted runners on public repos: a pull request from anyone could run code on the Pi. Polling needs no inbound access and only reads CI results. For a private repo, the script uses `DEPLOY_GITHUB_TOKEN` or, failing that, the token git has saved for github.com, the same one that clones and fetches it.
