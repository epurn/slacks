# HTTPS over Tailscale (FTY-367)

The paved path for reaching the Slacks backend with **encrypted transport** is
`tailscale serve`: TLS terminated by `tailscaled` on the standard port **443**,
with a **valid certificate** for the host's MagicDNS name, reverse-proxying to
the locally published API port. The endpoint is reachable **only inside your
tailnet** — never the public internet — and the mobile app connects to
`https://<host>.<tailnet-name>.ts.net` with no port in the URL.

No reverse-proxy container and no certificate files to place or rotate:
`tailscaled` provisions and renews the tailnet HTTPS certificate for the node
automatically. The commands below were **confirmed against Tailscale 1.98.8**;
the `serve` CLI syntax has changed across releases, so if your `tailscale
version` is much older, check `tailscale serve --help` before pasting.

## Prerequisites

- The Compose stack is up on the host (`docker compose up -d`; see
  [Local Development Stack](local-dev-stack.md)).
- [Tailscale](https://tailscale.com/download) is installed and logged in on the
  host (`tailscale status` shows the node connected).
- **MagicDNS** and **HTTPS certificates** are enabled for your tailnet in the
  [Tailscale admin console](https://login.tailscale.com/admin/dns) (DNS page:
  "MagicDNS" and "HTTPS Certificates" toggles). Without them,
  `tailscale serve` cannot obtain a certificate — it fails with an explicit
  error telling you to enable HTTPS certificates. Confirm your node's MagicDNS
  name with:

  ```sh
  tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
  # -> <host>.<tailnet-name>.ts.net
  ```

## Serve the API on 443

**1. Bind the published API port to loopback** (the served posture — see
[Cleartext posture](#cleartext-posture) below). In `.env`, set:

```sh
API_BIND_HOST=127.0.0.1
```

then re-create the API container so the new bind takes effect:

```sh
docker compose up -d api
```

**2. Start the serve proxy** (confirmed form for Tailscale 1.98.8; `--bg` keeps
it running after your shell exits — the config persists across reboots until
you turn it off):

```sh
tailscale serve --bg --https=443 http://127.0.0.1:${API_PORT:-8000}
```

Replace the port with your `.env` `API_PORT` if you changed it. Or run the
bundled helper, which reads `API_PORT` from `.env` and prints the resulting
URL:

```sh
make tailscale-serve      # wraps scripts/tailscale-serve.sh
```

**3. Read back the active config and URL:**

```sh
tailscale serve status
# https://<host>.<tailnet-name>.ts.net (tailnet only)
# |-- / proxy http://127.0.0.1:8000
```

## Verify

From **another device on your tailnet** (laptop, phone on the Tailscale app):

```sh
curl -fsS https://<host>.<tailnet-name>.ts.net/healthz          # -> {"status":"ok"}
curl -fsS https://<host>.<tailnet-name>.ts.net/readyz           # -> {"status":"ready"}
curl -fsS https://<host>.<tailnet-name>.ts.net/healthz/sources  # -> provider capability list
```

No `-k`/`--insecure` flag: the certificate is a real, valid cert for the
MagicDNS name. If curl reports a certificate error, HTTPS certificates are not
enabled for the tailnet (see Prerequisites).

**Connect the app:** on the mobile connect screen, enter
`https://<host>.<tailnet-name>.ts.net` (no port — HTTPS defaults to 443). The
connect flow validates the URL, probes `/healthz`, and proceeds exactly as it
does over plain HTTP; no app configuration is needed.

## Cleartext posture

In the served posture, the **only network-facing entrypoint is HTTPS/443 over
the tailnet**; no cleartext is reachable off-box:

- `tailscale serve` runs on the host and reaches the API over loopback, so the
  published API port only needs a `127.0.0.1` bind. Setting
  `API_BIND_HOST=127.0.0.1` in `.env` (the same loopback-bind convention as the
  FTY-109 datastore ports) keeps the plain-HTTP listener reachable only on-box.
- The plain-HTTP port **stays available for local dev**: on the host,
  `curl http://localhost:${API_PORT:-8000}/healthz` still answers. It is simply
  no longer the network-facing ingress when serve is on.
- The **default** (no `API_BIND_HOST` set) is unchanged: the API port binds all
  host interfaces, exactly as before, for pure local development.
- `tailscale serve` — **not** `tailscale funnel` — keeps the endpoint reachable
  only to devices on your own tailnet (least privilege). Funnel would publish
  it to the public internet and is out of scope.

## Certificate and secret handling

Certificate provisioning and renewal are handled entirely by `tailscaled` on
the host. No certificate files, private keys, tailnet auth keys, or node keys
live in this repository, in `.env.example`, or in any image — and the
`tailscale-serve.sh` helper prints URLs and status only, never certificate or
key material.

## Turning it off

```sh
tailscale serve --https=443 off   # remove the 443 proxy
tailscale serve status            # confirm empty
```

## If you already run a reverse proxy

The alternative — an in-Compose reverse proxy (Caddy/nginx) with certificates
provisioned by `tailscale cert` and mounted in — was considered and rejected as
the paved path: it adds a proxy container, on-disk certificate material to
store and rotate, and manual renewal wiring, for no self-host benefit over
`tailscale serve`. If you already operate a reverse proxy, you can point it at
`127.0.0.1:${API_PORT}` and source certificates from `tailscale cert` yourself;
that setup is yours to maintain and is not covered here.

## Scope

This page covers transport encryption on your private tailnet only. Public
internet ingress, WAF, rate-limit tuning, backups, HA, and cloud/managed
deployment remain out of scope for the self-host stack.
