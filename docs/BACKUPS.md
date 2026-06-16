# Off-site backups (restic → Google Cloud Storage)

The home stack is backed up nightly with [restic](https://restic.net) to a
Google Cloud Storage bucket. restic deduplicates and **encrypts client-side**,
so the bucket never sees plaintext. A single snapshot contains:

| What | Source | Notes |
|------|--------|-------|
| SQLite DBs | `dashboard.db`, `library.db`, `events.db`, `music.db` | Snapshotted via SQLite's online-backup API + `integrity_check` before upload — a corrupt DB **aborts** the run. |
| App config | each app's `.env` | Secrets; safe because the repo is encrypted. |
| Calendar attachments | `calendar/instance/attachments/` | Scanner uploads. |
| Books | `/mnt/backup/books` | EPUB library. |
| Music | `/mnt/backup/tapes` | MP3s. |

**Excluded** (regenerable / transient): tapes `covers/` thumbnails (`flask scan`
rebuilds them), `_downloads/`, `*.bak` / `*.corrupt-*` sidecars, `.git`,
`__pycache__`, `node_modules`, `.venv`.

The pieces live in `dashboard/scripts/`:

- `restic-backup.sh` — the backup job (snapshot DBs → restic backup → forget/prune).
- `restic-restore.sh` — convenience wrapper around `restic restore`.
- `restic-backup.env.example` — template for `/etc/restic/home-stack.env`.
- `systemd/restic-backup.{service,timer}` — the daily schedule.

---

## One-time setup

Assumes the dashboard repo is at `/opt/home-stack/dashboard` (adjust paths
to match your clone, including `ExecStart=` in the service unit).

### 1. Install restic

```sh
sudo apt install restic        # Debian/Raspberry Pi OS
restic version                 # need >= 0.14 for the gs: backend niceties
```

### 2. Create the GCS bucket + service account

```sh
gcloud storage buckets create gs://YOUR_BUCKET_NAME --location=US --uniform-bucket-level-access
# Service account restricted to this one bucket:
gcloud iam service-accounts create restic-home --display-name "restic home backup"
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:restic-home@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role=roles/storage.objectAdmin
gcloud iam service-accounts keys create gcs-sa.json \
  --iam-account=restic-home@YOUR_PROJECT.iam.gserviceaccount.com
```

Optional but recommended: a bucket lifecycle rule to drop objects restic has
already deleted after N days, and Object Versioning **off** (restic manages its
own history; versioning just inflates cost).

### 3. Place credentials (root-only, never in git)

```sh
sudo mkdir -p /etc/restic
sudo mv gcs-sa.json /etc/restic/gcs-sa.json
openssl rand -base64 32 | sudo tee /etc/restic/password >/dev/null   # repo password
sudo cp /opt/home-stack/dashboard/scripts/restic-backup.env.example /etc/restic/home-stack.env
sudo nano /etc/restic/home-stack.env                                 # fill in bucket + project
sudo chmod 600 /etc/restic/password /etc/restic/gcs-sa.json /etc/restic/home-stack.env
```

> **Back up the repo password offline** (password manager / paper). Lose it and
> the encrypted bucket is unrecoverable — there is no reset.

### 4. Initialise the repository (once)

```sh
set -a; . /etc/restic/home-stack.env; set +a
restic init
```

### 5. First run + install the timer

```sh
# manual first backup to confirm everything works (sources the env as root):
sudo bash -c 'set -a; . /etc/restic/home-stack.env; set +a; \
  /opt/home-stack/dashboard/scripts/restic-backup.sh'

# install + enable the schedule:
sudo cp /opt/home-stack/dashboard/scripts/systemd/restic-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now restic-backup.timer
```

(The unit loads the env file itself, so day-to-day runs don't need the manual
env sourcing above — that's only for the ad-hoc first run.)

---

## Operating it

```sh
systemctl status restic-backup.timer       # next scheduled run
systemctl list-timers restic-backup.timer
journalctl -u restic-backup.service -n 50   # last run's log
sudo systemctl start restic-backup.service  # run now, on demand
```

Inspect the repo (loads env first):

```sh
set -a; . /etc/restic/home-stack.env; set +a
restic snapshots
restic stats latest
```

### Weekly integrity check

A nightly `restic check` adds GCS egress; once a week is plenty. Either set
`RUN_CHECK=1` in the env file, or add a second timer that runs:

```sh
restic check --read-data-subset=5%   # also re-reads a sample of actual data
```

---

## Restoring

List, then restore into a scratch dir (never straight over the live stack):

```sh
sudo scripts/restic-restore.sh --list
sudo scripts/restic-restore.sh                       # latest -> /var/tmp/restore
sudo scripts/restic-restore.sh --snapshot ab12cd34   # a specific one
```

### Recover a single database

```sh
sudo scripts/restic-restore.sh --db library          # -> /var/tmp/restore/.../db/library.db
# then put it back and fix ownership + restart the container:
sudo cp /var/tmp/restore/**/db/library.db /opt/home-stack/library/instance/library.db
sudo chown 10001:10001 /opt/home-stack/library/instance/library.db   # dashboard.db too; apps run as uid 10001
docker compose restart library
```

### Browse the whole repo as a filesystem

```sh
set -a; . /etc/restic/home-stack.env; set +a
mkdir -p /mnt/restic && restic mount /mnt/restic    # Ctrl-C to unmount
```

---

## Disaster recovery (Pi died)

On a fresh machine: install restic, restore `/etc/restic/*` from your offline
copy (or recreate `home-stack.env` + drop the **saved** repo password and the
GCS service-account key back in place), then:

```sh
set -a; . /etc/restic/home-stack.env; set +a
restic snapshots                       # confirm access
restic restore latest --target /opt/home-stack-restore
```

Copy the DBs, `.env` files, attachments, books and music back into the rebuilt
stack, fix ownership (`chown 10001:10001` for the app data), and bring compose
up. The two things that are NOT in the bucket and must come from your offline
copy: the **restic repo password** and the **GCS service-account key**.
