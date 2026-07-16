#!/bin/sh
# Tailnet HTTPS ingress helper (FTY-367). Starts (or re-applies) `tailscale
# serve` so the local Slacks API is reachable at
# https://<host>.<tailnet-name>.ts.net — TLS terminated by tailscaled on 443
# with a valid tailnet certificate, proxying to the loopback API port.
#
# Serve command confirmed against Tailscale 1.98.8; see
# docs/operations/tailscale-https.md for prerequisites (MagicDNS + HTTPS
# certificates enabled) and the served cleartext posture
# (API_BIND_HOST=127.0.0.1).
#
# Prints URLs and serve status only — never certificate/key material or any
# other value from .env.
set -eu

if ! command -v tailscale >/dev/null 2>&1; then
  echo "error: tailscale CLI not found. Install Tailscale and log in first:" >&2
  echo "       https://tailscale.com/download" >&2
  exit 1
fi

# Read only API_PORT from .env, without sourcing the file (no other value is
# read or printed). Default matches docker-compose.yml.
api_port=8000
if [ -f .env ]; then
  env_port="$(sed -n 's/^API_PORT=\([0-9][0-9]*\)[[:space:]]*$/\1/p' .env | tail -n 1)"
  [ -n "${env_port}" ] && api_port="${env_port}"
fi

echo "Serving https://…:443 -> http://127.0.0.1:${api_port} (tailnet only)"
tailscale serve --bg --https=443 "http://127.0.0.1:${api_port}"

dns_name="$(tailscale status --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"

echo
echo "Connect the app to:  https://${dns_name}"
echo "Verify:              curl -fsS https://${dns_name}/healthz"
echo "Read back config:    tailscale serve status"
echo "Turn off:            tailscale serve --https=443 off"
