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
| `api` | `./backend` (FastAPI) | HTTP API; serves `GET /healthz` and `GET /healthz/sources`. | `${API_PORT:-8000}` |
| `worker` | `./backend` (Celery) | Background estimation worker. | — |

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
- Images for Postgres and Redis are pinned per the security baseline's
  pinned-dependency principle.
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
| Search | `FATTY_SEARCH_*` | Optional; disabled by default (no bundled Brave key). |

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
curl -fsS http://localhost:8000/healthz          # -> {"status":"ok"}
curl -fsS http://localhost:8000/healthz/sources  # -> provider capability list
docker compose ps                                # migrate exited 0, api/postgres/redis/worker all healthy
docker compose down                              # add -v to drop all volumes
```

`GET /healthz/sources` lists each evidence source (LLM, FDC, OFF, search) with
its `enabled` and `available` flags, so you can confirm provider configuration
without making any estimation calls. The `claude_code` entry specifically shows
whether the CLI is installed and the session is valid — both must be `true` for
the provider to work.

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
