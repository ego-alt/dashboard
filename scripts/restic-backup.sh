#!/usr/bin/env bash
#
# Off-site backup of the home stack to a restic repository (GCS backend).
#
#   1. Snapshots each app's SQLite DB *consistently* (online-backup API) and
#      runs PRAGMA integrity_check — a corrupt DB ABORTS the run rather than
#      shipping a bad snapshot over a good one.
#   2. Backs up the DB snapshots + app config (.env) + calendar attachments +
#      books + music into one restic snapshot.
#   3. Applies the keep-daily/weekly/monthly retention policy and prunes.
#
# Meant to run as root via restic-backup.service, which loads the repository
# and GCS credentials from /etc/restic/home-stack.env. See docs/BACKUPS.md.
#
# restic finds the repo + auth in the environment:
#   RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE,
#   GOOGLE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS
#
set -euo pipefail

# --- config (override via the systemd EnvironmentFile) -----------------------
# Stack root = the parent of the dashboard repo (where library/, calendar/,
# tapes/ and dashboard/ sit side by side), derived from this script's location.
STACK_ROOT="${STACK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Bulk media on the Pi's backup disk (match docker-compose.yml mounts).
BOOK_DIR="${LIBRARY_BOOK_DIR:-/mnt/backup/books}"
MUSIC_DIR="${MUSIC_HOST_DIR:-/mnt/backup/tapes}"

# Stable staging dir for the consistent DB snapshots (kept off the repo tree).
STAGING="${BACKUP_STAGING_DIR:-/var/lib/home-stack-backup}"

# Retention.
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"

# Tag applied to every snapshot this script makes; retention is scoped to it so
# we never forget snapshots made by other restic jobs sharing the repo.
TAG="${RESTIC_TAG:-home-stack}"

log() { printf '%s  %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "ERROR $*"; exit 1; }

command -v restic  >/dev/null 2>&1 || die "restic not found on PATH"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 not found on PATH"
[[ -n "${RESTIC_REPOSITORY:-}" ]] || die "RESTIC_REPOSITORY is not set (load /etc/restic/home-stack.env)"

# Resolve an app's checkout dir, tolerating the dev clone name (library-app).
resolve_app_dir() {
  local app="$1" cand
  for cand in "$app" "$app-app"; do
    [[ -d "$STACK_ROOT/$cand" ]] && { printf '%s\n' "$STACK_ROOT/$cand"; return 0; }
  done
  return 1
}

DB_STAGE="$STAGING/db"
rm -rf "$DB_STAGE"
mkdir -p "$DB_STAGE"
trap 'rm -rf "$DB_STAGE"' EXIT

# --- 1. consistent SQLite snapshots -----------------------------------------
# app:relative-db-path — the online-backup API is safe while the apps run.
DB_SPECS=(
  "dashboard:data/dashboard.db"
  "library:instance/library.db"
  "calendar:instance/events.db"
  "tapes:instance/music.db"
)

for spec in "${DB_SPECS[@]}"; do
  app="${spec%%:*}"; rel="${spec#*:}"
  if ! dir="$(resolve_app_dir "$app")"; then
    log "WARN  $app checkout not found under $STACK_ROOT — skipping"
    continue
  fi
  src="$dir/$rel"
  if [[ ! -f "$src" ]]; then
    log "WARN  $app DB not found at $src — skipping"
    continue
  fi
  dst="$DB_STAGE/$app.db"
  log "snapshot $app -> $dst"
  # .timeout lets the online backup wait out a writer instead of failing.
  sqlite3 "$src" -cmd ".timeout 10000" ".backup '$dst'"
  result="$(sqlite3 "$dst" 'PRAGMA integrity_check;')"
  [[ "$result" == "ok" ]] || die "$app snapshot failed integrity_check: $result"
done

# --- 2. assemble backup paths -----------------------------------------------
PATHS=( "$DB_STAGE" )

# App config (.env holds secrets; restic encrypts the repo at rest).
for app in dashboard library calendar tapes; do
  if dir="$(resolve_app_dir "$app")"; then
    [[ -f "$dir/.env" ]] && PATHS+=( "$dir/.env" )
  fi
done

# Calendar attachments (scanner uploads — small, irreplaceable).
if dir="$(resolve_app_dir calendar)"; then
  [[ -d "$dir/instance/attachments" ]] && PATHS+=( "$dir/instance/attachments" )
fi

# Bulk media.
[[ -d "$BOOK_DIR"  ]] && PATHS+=( "$BOOK_DIR" )  || log "WARN  books dir $BOOK_DIR missing — skipping"
[[ -d "$MUSIC_DIR" ]] && PATHS+=( "$MUSIC_DIR" ) || log "WARN  music dir $MUSIC_DIR missing — skipping"

# --- 3. back up --------------------------------------------------------------
log "backing up ${#PATHS[@]} path(s) to $RESTIC_REPOSITORY"
restic backup \
  --tag "$TAG" \
  --exclude-caches \
  --exclude='covers' \
  --exclude='_downloads' \
  --exclude='*.bak' \
  --exclude='*.corrupt-*' \
  --exclude='*.pre-*.bak' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='node_modules' \
  "${PATHS[@]}"

# --- 4. retention ------------------------------------------------------------
log "applying retention (daily=$KEEP_DAILY weekly=$KEEP_WEEKLY monthly=$KEEP_MONTHLY)"
restic forget \
  --tag "$TAG" \
  --keep-daily "$KEEP_DAILY" \
  --keep-weekly "$KEEP_WEEKLY" \
  --keep-monthly "$KEEP_MONTHLY" \
  --prune

# --- 5. optional structural check (RUN_CHECK=1) ------------------------------
if [[ "${RUN_CHECK:-0}" == "1" ]]; then
  log "running restic check"
  restic check
fi

log "backup complete"
