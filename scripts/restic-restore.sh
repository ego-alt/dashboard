#!/usr/bin/env bash
#
# Convenience wrapper around `restic restore` for the home stack. Loads the
# repo + GCS credentials from /etc/restic/home-stack.env so you don't have to
# export them by hand, then restores the latest snapshot (or a chosen one) into
# a target dir for inspection. It never writes back into the live stack — you
# copy files into place yourself (and chown/restart the relevant container).
#
# Usage:
#   sudo scripts/restic-restore.sh                       # latest -> /var/tmp/restore
#   sudo scripts/restic-restore.sh --target /tmp/r       # custom target
#   sudo scripts/restic-restore.sh --snapshot ab12cd34   # specific snapshot
#   sudo scripts/restic-restore.sh --db library          # just one DB snapshot
#   sudo scripts/restic-restore.sh --list                # list snapshots and exit
#
set -euo pipefail

ENV_FILE="${RESTIC_ENV_FILE:-/etc/restic/home-stack.env}"
[[ -r "$ENV_FILE" ]] && { set -a; . "$ENV_FILE"; set +a; }
command -v restic >/dev/null 2>&1 || { echo "restic not found on PATH" >&2; exit 1; }
[[ -n "${RESTIC_REPOSITORY:-}" ]] || { echo "RESTIC_REPOSITORY not set (is $ENV_FILE present?)" >&2; exit 1; }

SNAPSHOT=latest
TARGET=/var/tmp/restore
DB=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list)     restic snapshots --tag "${RESTIC_TAG:-home-stack}"; exit 0 ;;
    --snapshot) SNAPSHOT="$2"; shift 2 ;;
    --target)   TARGET="$2"; shift 2 ;;
    --db)       DB="$2"; shift 2 ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$TARGET"
if [[ -n "$DB" ]]; then
  echo "restoring $DB DB from snapshot $SNAPSHOT -> $TARGET"
  restic restore "$SNAPSHOT" --target "$TARGET" --include "*/db/$DB.db"
  echo "look under: $TARGET (…/db/$DB.db). Copy into place, then chown + restart the container."
else
  echo "restoring snapshot $SNAPSHOT -> $TARGET"
  restic restore "$SNAPSHOT" --target "$TARGET"
  echo "restored to $TARGET"
fi
