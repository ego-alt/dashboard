#!/usr/bin/env bash
# Install the home-stack auto-deploy timer on the Pi. Run once, with sudo,
# from anywhere:   sudo scripts/install-deploy-timer.sh
#
# Deploys run as the user who owns the repos (they need git and docker
# access), every 5 minutes. Check on it with:
#   systemctl list-timers home-stack-deploy.timer
#   journalctl -u home-stack-deploy -f
#   cat /var/lib/home-stack-deploy/status.json

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

SCRIPT="$(cd "$(dirname "$0")" && pwd)/deploy.sh"
RUN_AS=${SUDO_USER:-$(stat -c '%U' "$SCRIPT")}
STATE_DIR=/var/lib/home-stack-deploy

if ! id -nG "$RUN_AS" | grep -qw docker; then
  echo "$RUN_AS isn't in the docker group; add it first: sudo usermod -aG docker $RUN_AS" >&2
  exit 1
fi

chmod +x "$SCRIPT"
mkdir -p "$STATE_DIR"
chown "$RUN_AS": "$STATE_DIR"

cat >/etc/systemd/system/home-stack-deploy.service <<EOF
[Unit]
Description=Deploy new home-stack commits that passed CI
Wants=network-online.target
After=network-online.target docker.service

[Service]
Type=oneshot
User=$RUN_AS
Environment=DEPLOY_STATE_DIR=$STATE_DIR
ExecStart=$SCRIPT
# Image builds on a Pi can take a while.
TimeoutStartSec=45min
EOF

cat >/etc/systemd/system/home-stack-deploy.timer <<EOF
[Unit]
Description=Check for home-stack deploys every 5 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now home-stack-deploy.timer
echo "Installed. Deploys run as $RUN_AS from $SCRIPT every 5 minutes."
echo "Watch:  journalctl -u home-stack-deploy -f"
echo "Now:    sudo systemctl start home-stack-deploy"
