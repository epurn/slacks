# Local Development Stack

The repo-root `docker-compose.yml` (FTY-011, self-host setup FTY-072) brings up
the full local backend stack over plain HTTP:

```sh
cp .env.example .env           # copy template; set FATTY_AUTH_SECRET
docker compose up              # starts all services; migrations run first
```

For the full self-host walkthrough (prerequisites, provider config, first-boot
checklist, smoke check) see the README **Self-Hosting** section.

## Services

| Service | Image / build | Purpose | Host port |
| --- | --- | --- | --- |
| `postgres` | `postgres:16.4-alpine` | Application database. | — (internal only) |
| `redis` | `redis:7.4-alpine` | Celery broker / result backend. | — (internal only) |
| `migrate` | `./backend` (Alembic) | One-shot first-boot migration runner. | — |
| `api` | `./backend` (FastAPI) | HTTP API; serves `GET /healthz` (liveness), `GET /readyz` (readiness — checks DB), and `GET /healthz/sources`. | `${API_PORT:-8000}` |
| `worker` | `./backend` (Celery) | Background estimation worker. | — |
| `searxng` | `searxng/searxng` (pinned) | Private, keyless metasearch backing the official-source search adapter (FTY-164/165). | — (internal only) |

- Postgres and Redis are **not published to host interfaces by default** (FTY-109).
  The `api`, `worker`, and `migrate` services reach them over the internal compose
  network by service name (`postgres`, `redis`). This removes an unauthenticated
  Redis and Postgres exposure from the self-host box's LAN. To re-enable direct
  host access (e.g. for a DB GUI or local `psql`), add a loopback-only mapping to
  the relevant service in `docker-compose.yml`:
  ```yaml
  ports:
    - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"   # postgres
    - "127.0.0.1:${REDIS_PORT:-6379}:6379"       # redis
  ```
  Alternatively, access the database without a host port via:
  ```sh
  docker compose exec postgres psql -U fatty fatty
  ```
- `api`, `worker`, `postgres`, and `redis` all declare `restart: unless-stopped`;
  they restart automatically if they crash. The one-shot `migrate` service has no
  restart policy and exits after applying migrations.
- Postgres and Redis define healthchecks (`pg_isready`, `redis-cli ping`).
- The `migrate` service runs `alembic upgrade head` once and exits; it depends on
  `postgres` being healthy. The `api` and `worker` services depend on `migrate`
  completing successfully before they start.
- The API healthcheck polls its own `GET /healthz` and expects HTTP 200.
- The worker healthcheck runs `celery inspect ping` against the configured
  `app.worker:celery_app` to confirm the worker is alive and connected to Redis.
- Images for Postgres, Redis, and SearXNG are pinned to exact tags per the
  security baseline's pinned-dependency principle.
- `searxng` runs a private [SearXNG](https://docs.searxng.org/) metasearch
  instance that backs the official-source search adapter (FTY-164). It is
  **keyless** and **enabled by default**, so search works out of the box — no
  Brave API key required. Like Postgres and Redis it is **not published to the
  host** (FTY-165); the `api` and `worker` reach it over the internal compose
  network at `http://searxng:8080`. The backend sends only sanitized
  item-identity queries — never any personal context. Its minimal config lives in
  `searxng/settings.yml` (mounted read-only at `/etc/searxng`), which enables the
  JSON output format the adapter consumes and sets a documented **non-secret dev
  placeholder** secret key. Exposing SearXNG to the host or the public internet is
  out of scope and would need a separate, explicit operator story. Search
  degrades gracefully (model-prior-with-status) when the service is unreachable,
  so `api`/`worker` do not hard-depend on it starting.
- The `backend/` image includes a pinned Node.js runtime and the Claude Code CLI
  (`claude`) so the `api` and `worker` services can use the `claude_code` LLM
  provider (FTY-087/088) without mounting a host binary.

## Volumes

| Volume | Mounted at | Purpose |
| --- | --- | --- |
| `postgres-data` | `/var/lib/postgresql/data` | Postgres data. Persists across restarts. |
| `claude-config` | `/claude-config` (api + worker) | Claude Code session / config dir (FTY-088). |

The `claude-config` volume is populated once by `claude login` (see **Claude Code
login** below) and persists the OAuth session so subsequent `docker compose down &&
up` cycles do not require re-login. Treat it as a **host secret**: never copy its
contents into the image or commit them. `CLAUDE_CONFIG_DIR=/claude-config` is
fixed in the compose `environment:` block for both `api` and `worker`.

## Configuration

Configuration comes from `.env` (copied from `.env.example`). `.env.example` is
the documented self-host configuration contract (FTY-072): it lists every
required and optional `FATTY_*` variable with documentation and placeholder-only
values. The real `.env` is gitignored; never commit real secrets.

Key variable groups (see `.env.example` for full documentation):

| Group | Variables | Notes |
| --- | --- | --- |
| Auth | `FATTY_AUTH_SECRET`, `FATTY_AUTH_TOKEN_TTL_SECONDS` | Auth secret is required; generate before first boot. |
| Datastores | `POSTGRES_*`, `FATTY_DATABASE_URL`, `REDIS_PORT`, `FATTY_REDIS_URL` | Service hostnames must match compose service names. |
| Host ports | `API_PORT` | Published host port for the API; containers always listen on fixed ports. `POSTGRES_PORT` / `REDIS_PORT` are meaningful only if you re-enable loopback-only host mappings for direct datastore access (see Services above). |
| Application | `FATTY_ENVIRONMENT`, `FATTY_LOG_LEVEL` | App config. |
| LLM provider | `FATTY_LLM_*` | Optional; defaults to `fake` (model-prior-with-status). See LLM providers below. |
| USDA FDC | `FATTY_FDC_*` | Optional; free data.gov key. Disabled when key absent. |
| Open Food Facts | `FATTY_OFF_*` | Optional, open API; enabled by default, no key required. |
| Search | `FATTY_SEARCH_*` | Keyless SearXNG by default (points at the `searxng` service; enabled, no key). Brave is an opt-in override; `none` turns search off. |

## LLM Providers

The `FATTY_LLM_PROVIDER` variable selects the LLM backend. It defaults to `fake`
(no network calls; estimation degrades to model-prior-with-status). Two keyless
options are available for self-hosters who want live estimation without an API key:

### `claude_code` — Claude subscription, no per-token billing

Set in `.env`:
```
FATTY_LLM_PROVIDER=claude_code
# FATTY_LLM_MODEL is optional — Claude Code picks the model from your plan
# No FATTY_LLM_API_KEY — auth is the operator's 'claude login' session
```

Then complete the **one-time Claude Code login** (see below).

### `openai_compatible` — Local model runtime (Ollama / LM Studio / vLLM)

Set in `.env`:
```
FATTY_LLM_PROVIDER=openai_compatible
FATTY_LLM_BASE_URL=http://localhost:11434/v1   # Ollama default; adjust for LM Studio / vLLM
FATTY_LLM_MODEL=<your loaded model name>
# No FATTY_LLM_API_KEY needed — local runtimes don't authenticate
```

## Claude Code Login (One-Time Setup, FTY-088)

The `claude_code` provider requires a one-time interactive login to establish a
Claude Code session. The session is written into the `claude-config` Docker volume
and shared between `api` and `worker`, so it survives restarts without re-login.

**Prerequisites:** the stack must be running (`docker compose up -d`) and
`FATTY_LLM_PROVIDER=claude_code` must be set in `.env`.

```sh
# Run the login flow in the api container (interactive — needs a terminal):
docker compose exec api claude login
```

Claude Code prints a URL. Open it in your browser, authorize with your Claude
account, and paste the device code back into the terminal. The session is written
to `/claude-config` inside the container (the `claude-config` volume).

To confirm the session persists across restarts:

```sh
docker compose down && docker compose up -d
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# Expect: {"id": "claude_code", "enabled": true, "available": true, ...}
```

**Security:** the `claude-config` volume contains OAuth credentials. Never bind-mount
it to a path with loose permissions, never copy its contents into the image, and
never commit it. The image contains only the Claude Code binary — no credentials.

## Verifying

```sh
docker compose up -d
curl -fsS http://localhost:8000/healthz          # -> {"status":"ok"} — liveness (process-up, no DB)
curl -fsS http://localhost:8000/readyz           # -> {"status":"ready"} — readiness (200 DB reachable / 503 not ready)
curl -fsS http://localhost:8000/healthz/sources  # -> provider capability list
docker compose ps                                # migrate exited 0, api/postgres/redis/worker/searxng all healthy
docker compose down                              # add -v to drop all volumes
```

`GET /healthz/sources` lists each evidence source (LLM, FDC, OFF, search) with
its `enabled` and `available` flags, so you can confirm provider configuration
without making any estimation calls. With the default keyless SearXNG search
(FTY-165) the `official_source` entry reports both `enabled: true` and
`available: true` out of the box — no API key needed:

```sh
curl -fsS http://localhost:8000/healthz/sources | python3 -m json.tool
# official_source: {"enabled": true, "available": true, ...}
# (available reflects config, not a live probe: it is true whenever the searxng
#  provider is selected. Confirm the container itself is up with `docker compose ps`.)
```

Selecting Brave without a key, or setting `FATTY_SEARCH_PROVIDER=none` /
`FATTY_SEARCH_ENABLED=false`, flips these flags so the opt-out or missing
credential is visible here. The `claude_code` entry specifically shows whether
the CLI is installed and the session is valid — both must be `true` for the
provider to work.

## Simulator Readiness Smoke (FTY-250)

Before testing Slacks in an iOS simulator, run one command to confirm the stack is
actually *ready* — not just serving `/healthz`. A stack can be healthy at the
process level yet fail the app later: backend images built from different
checkouts, Postgres behind the code's Alembic head, or a simulator pointed at the
wrong port. The smoke catches exactly those drifts and prints the connect URL.

```sh
docker compose up -d          # bring the stack up first
make sim-smoke                # read-only readiness report (prints no secrets)
```

`make sim-smoke` runs `python -m app.ops.sim_readiness` in the backend uv
environment. It is **read-only** — it detects drift and prints the fix path but
never rebuilds, migrates, or restarts anything for you — and it **never prints
secret values** (auth secret, DB password, provider keys, tokens, session
material). It reports:

- **Backend image coherence.** `api`, `worker`, and `migrate` all build from
  `./backend`, so a coherent stack resolves them to one image id. Divergent ids
  mean one was rebuilt from a different checkout than the others (the
  2026-07-05 failure mode) — the smoke flags it as image DRIFT.
- **Alembic drift.** It reads the running database's `alembic_version` (via
  `docker compose exec postgres`, so no host port is needed) and compares it to
  the code head read from `backend/alembic/versions/`. It prints **both**
  versions and fails when the database is behind (e.g. DB `0016` while code
  expects `0017`).
- **API health.** `GET /healthz` (liveness), `GET /readyz` (DB readiness), and
  `GET /healthz/sources` (evidence-source capabilities, including the active LLM
  provider — booleans only, no key values).
- **Worker health.** It pings the Celery worker with the same
  `celery -A app.worker:celery_app inspect ping` the compose healthcheck uses
  (over `docker compose exec`, so no host port is needed) and fails when no
  worker pongs back. The HTTP probes only reach the API; a stopped or wedged
  worker serves no endpoint yet would leave estimator jobs stuck later, so the
  smoke will **not** print READY until the worker answers.
- **The simulator connect URL**, derived from `.env` `API_PORT`:
  `http://localhost:<API_PORT>`. With `API_PORT=18000` this is
  `http://localhost:18000`. This is the value to enter on the app's connect
  screen — **not** the mobile code's `localhost:8000` fallback, which is only
  correct when `API_PORT` is left at its default.

When the smoke reports drift, the coherent fix path (also printed by the command)
rebuilds the backend images from the current checkout, migrates to head, and
restarts the API and worker on the new image:

```sh
docker compose build api worker migrate   # rebuild from this checkout
docker compose run --rm migrate            # apply Alembic to head
docker compose up -d api worker            # restart on the new image
make sim-smoke                             # re-run until READY
```

### Connecting the simulator

A **fresh simulator install has no persisted connected server** — the app resolves
its API base URL from the on-device connection store, which starts empty
(`mobile/api/config.ts`). So the first-run flow is:

1. `docker compose up -d` and `make sim-smoke` until it reports **READY**.
2. Launch the app in the simulator.
3. On the connect screen, enter the printed URL (e.g. `http://localhost:18000`).
4. Sign in or create an account.

You must connect to the printed URL **before** sign-in; there is no persisted
server to fall back to on a fresh install.

### Live backend vs. hermetic E2E mock

`make sim-smoke` and the connect flow above target the **real local backend** —
the Docker Compose stack this document describes, published on `.env`'s
`API_PORT` (e.g. `http://localhost:18000`). This is the live v1 target: your
requests hit FastAPI, Postgres, the worker, and the configured providers.

That is **not** the same simulator mode `mobile/verify-e2e.sh` runs. The E2E
suite builds the app with `EXPO_PUBLIC_FATTY_E2E=true` baked in, which installs
an **in-process mock `fetch`** (see `mobile/e2e/launchMode.ts`) so no request
ever leaves the app. In that mode the app's server URL is the synthetic
`E2E_SERVER_URL = 'http://localhost:8000'` in `mobile/e2e/fixtures.ts` — it is a
hermetic placeholder that is only ever *matched* by the mock, never *connected*
to. Nothing listens there, and it is **deliberately unrelated** to the live
stack's `API_PORT`.

So do not read that `localhost:8000` as the live v1 backend: when `.env`
publishes `API_PORT=18000`, the real target is `http://localhost:18000` (what
`make sim-smoke` prints), while `localhost:8000` in the E2E fixtures is a mocked
constant that never touches the network. Use the printed smoke URL for live
simulator testing; use `mobile/verify-e2e.sh` only for the hermetic Maestro
suite.

## Container User

The backend image runs all three services (`migrate`, `api`, `worker`) as a
dedicated non-root user — `fatty` (UID/GID 10001) — rather than root (FTY-116).
This limits the blast radius of an in-container exploit to an unprivileged
account. The `claude-config` volume mountpoint is created owned by this user so
`claude login` and subsequent session writes succeed without elevated privileges.

## Out of Scope

TLS / reverse proxy / HTTPS termination, production hardening, resource limits,
object storage, and hosted/cloud deployment are intentionally out of scope for
this local self-host stack.
