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
die() { LAST_ERR="$*"; log "ERROR $*"; exit 1; }

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

# --- run-status file (consumed by the dashboard "Backups" card) -------------
# Written on EVERY exit, success or failure, so a silently-failing backup is
# still visible. The dashboard mounts this file read-only — never the repo
# password or GCS key, which stay in /etc/restic on the host only.
STATUS_FILE="${BACKUP_STATUS_FILE:-/var/lib/home-stack-backup-status/status.json}"
STARTED="$(date -u +%FT%TZ)"
START_EPOCH="$(date +%s)"
STAGE="starting"
DB_RESULTS=""
SNAPSHOT_COUNT=null
REPO_BYTES=null
LAST_ERR=""

write_status() {
  local rc=$? ok=false finished err
  [[ $rc -eq 0 ]] && ok=true
  finished="$(date -u +%FT%TZ)"
  if [[ $rc -eq 0 ]]; then err=null; else err="\"${LAST_ERR:-failed during: $STAGE}\""; fi
  mkdir -p "$(dirname "$STATUS_FILE")"
  cat > "$STATUS_FILE" <<JSON
{
  "ok": $ok,
  "exit_code": $rc,
  "stage": "$STAGE",
  "started_at": "$STARTED",
  "finished_at": "$finished",
  "duration_seconds": $(( $(date +%s) - START_EPOCH )),
  "databases": [$DB_RESULTS],
  "snapshot_count": $SNAPSHOT_COUNT,
  "repo_bytes": $REPO_BYTES,
  "error": $err
}
JSON
  chmod 644 "$STATUS_FILE" 2>/dev/null || true
}

DB_STAGE="$STAGING/db"
rm -rf "$DB_STAGE"
mkdir -p "$DB_STAGE"
trap 'write_status; rm -rf "$DB_STAGE"' EXIT

# --- 1. consistent SQLite snapshots -----------------------------------------
# app:relative-db-path — the online-backup API is safe while the apps run.
DB_SPECS=(
  "dashboard:data/dashboard.db"
  "library:instance/library.db"
  "calendar:instance/events.db"
  "tapes:instance/music.db"
)

STAGE="snapshotting databases"
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
  if [[ "$result" == "ok" ]]; then
    DB_RESULTS="${DB_RESULTS:+$DB_RESULTS,}{\"app\":\"$app\",\"ok\":true}"
  else
    DB_RESULTS="${DB_RESULTS:+$DB_RESULTS,}{\"app\":\"$app\",\"ok\":false}"
    die "$app snapshot failed integrity_check: $result"
  fi
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
STAGE="backing up"
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
STAGE="pruning"
log "applying retention (daily=$KEEP_DAILY weekly=$KEEP_WEEKLY monthly=$KEEP_MONTHLY)"
restic forget \
  --tag "$TAG" \
  --keep-daily "$KEEP_DAILY" \
  --keep-weekly "$KEEP_WEEKLY" \
  --keep-monthly "$KEEP_MONTHLY" \
  --prune

# --- 4b. repo stats for the status card (best-effort; never fails the run) ---
STAGE="collecting stats"
_stats="$(restic stats --mode raw-data --json 2>/dev/null || true)"
REPO_BYTES="$(printf '%s' "$_stats" | grep -oE '"total_size":[0-9]+' | grep -oE '[0-9]+' || true)"
SNAPSHOT_COUNT="$(printf '%s' "$_stats" | grep -oE '"snapshots_count":[0-9]+' | grep -oE '[0-9]+' || true)"
[[ "$REPO_BYTES"     =~ ^[0-9]+$ ]] || REPO_BYTES=null
[[ "$SNAPSHOT_COUNT" =~ ^[0-9]+$ ]] || SNAPSHOT_COUNT=null

# --- 5. optional structural check (RUN_CHECK=1) ------------------------------
if [[ "${RUN_CHECK:-0}" == "1" ]]; then
  STAGE="checking"
  log "running restic check"
  restic check
fi

STAGE="done"
log "backup complete"
