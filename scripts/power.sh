#!/usr/bin/env bash
# Power the Pi off when the dashboard asks: run as root by home-stack-power.service
# once $STATE_DIR/power/shutdown appears (see app/routes/power.py).
#
# The request is cleared before anything else, and one more than two minutes old
# (left over from before a restart) is dropped, so it can never shut the Pi down
# again as it boots.

set -euo pipefail

STATE_DIR=${DEPLOY_STATE_DIR:-/var/lib/home-stack-deploy}
request="$STATE_DIR/power/shutdown"
[[ -f $request ]] || exit 0

age=$(( $(date +%s) - $(stat -c %Y "$request") ))
asked=$(head -c 200 "$request" || true)
rm -f "$request"
if [[ -e $request ]]; then
  echo "Couldn't clear $request, so not shutting down." >&2
  exit 1
fi
if (( age > 120 )); then
  echo "Dropped a shutdown request from ${age}s ago ($asked)."
  exit 0
fi

echo "Shutting down, as asked from the dashboard ($asked)."
sync
systemctl poweroff
