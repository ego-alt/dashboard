#!/usr/bin/env bash
# A real TLS certificate for the Pi's Tailscale name (raspberrypi.<tailnet>.ts.net),
# from Let's Encrypt through Tailscale, so phones and laptops on the tailnet get
# no certificate warning. home.local keeps the self-signed one (scripts/dev-certs.sh).
#
# Writes ./tls/tailscale.crt + ./tls/tailscale.key and reloads nginx. Safe to
# run often: tailscale only fetches a new certificate when the old one is near
# expiry (they last 90 days). Run weekly by systemd/tailscale-cert.timer.
#
# Needs HTTPS certificates turned on for the tailnet (admin console → DNS).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TLS_DIR="$REPO_ROOT/tls"
mkdir -p "$TLS_DIR"

NAME="$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
[[ "$NAME" == *.ts.net ]] || { echo "no Tailscale name (is tailscale up?): '$NAME'" >&2; exit 1; }

tailscale cert --cert-file "$TLS_DIR/tailscale.crt" --key-file "$TLS_DIR/tailscale.key" "$NAME"
# The key stays readable only by its owner, like home.key.
chmod 600 "$TLS_DIR/tailscale.key"
[[ -n "${SUDO_USER:-}" ]] && chown "$SUDO_USER": "$TLS_DIR/tailscale.crt" "$TLS_DIR/tailscale.key"

# nginx reads the certificate per connection (see nginx/conf.d/home.conf), but
# a reload drops any cached copy.
docker exec home-nginx nginx -s reload >/dev/null 2>&1 || true
echo "certificate for $NAME: $(openssl x509 -in "$TLS_DIR/tailscale.crt" -noout -enddate)"
