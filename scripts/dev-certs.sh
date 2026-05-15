#!/usr/bin/env bash
# Generate local TLS certs for the home stack.
#
# Prefers mkcert (`brew install mkcert && mkcert -install`) so the OS trust
# store accepts the cert. Falls back to a self-signed openssl cert when mkcert
# isn't installed — browsers will warn, curl needs `-k`.
#
# Writes ./tls/home.crt + ./tls/home.key relative to the repo root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TLS_DIR="$REPO_ROOT/tls"
mkdir -p "$TLS_DIR"

if command -v mkcert >/dev/null 2>&1; then
    echo "→ Using mkcert (cert will be trusted system-wide)"
    cd "$TLS_DIR"
    mkcert -cert-file home.crt -key-file home.key home.local localhost 127.0.0.1
else
    echo "→ mkcert not installed; falling back to self-signed openssl cert"
    echo "  (Browsers will warn. Install mkcert for trusted local certs.)"
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -keyout "$TLS_DIR/home.key" \
        -out    "$TLS_DIR/home.crt" \
        -subj   "/CN=home.local" \
        -addext "subjectAltName=DNS:home.local,DNS:localhost,IP:127.0.0.1" \
        2>/dev/null
fi

chmod 644 "$TLS_DIR/home.crt"
chmod 600 "$TLS_DIR/home.key"
echo "Wrote $TLS_DIR/home.crt + home.key"
