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
| `postgres` | `postgres:16.4-alpine` | Application database. | `${POSTGRES_PORT:-5432}` |
| `redis` | `redis:7.4-alpine` | Celery broker / result backend. | `${REDIS_PORT:-6379}` |
| `migrate` | `./backend` (Alembic) | One-shot first-boot migration runner. | — |
| `api` | `./backend` (FastAPI) | HTTP API; serves `GET /healthz` and `GET /healthz/sources`. | `${API_PORT:-8000}` |
| `worker` | `./backend` (Celery) | Background estimation worker. | — |

- Postgres and Redis define healthchecks (`pg_isready`, `redis-cli ping`).
- The `migrate` service runs `alembic upgrade head` once and exits; it depends on
  `postgres` being healthy. The `api` and `worker` services depend on `migrate`
  completing successfully before they start.
- The API healthcheck polls its own `GET /healthz` and expects HTTP 200.
- Images for Postgres and Redis are pinned per the security baseline's
  pinned-dependency principle.

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
| Host ports | `POSTGRES_PORT`, `REDIS_PORT`, `API_PORT` | Published host ports; containers always listen on fixed ports. |
| Application | `FATTY_ENVIRONMENT`, `FATTY_LOG_LEVEL` | App config. |
| LLM provider | `FATTY_LLM_*` | Optional; defaults to `fake` (model-prior-with-status). |
| USDA FDC | `FATTY_FDC_*` | Optional; free data.gov key. Disabled when key absent. |
| Open Food Facts | `FATTY_OFF_*` | Optional, open API; enabled by default, no key required. |
| Search | `FATTY_SEARCH_*` | Optional; disabled by default (no bundled Brave key). |

## Verifying

```sh
docker compose up -d
curl -fsS http://localhost:8000/healthz          # -> {"status":"ok"}
curl -fsS http://localhost:8000/healthz/sources  # -> provider capability list
docker compose ps                                # migrate exited 0, api/postgres/redis healthy, worker running
docker compose down                              # add -v to drop the postgres volume
```

`GET /healthz/sources` lists each evidence source (LLM, FDC, OFF, search) with
its `enabled` and `available` flags, so you can confirm provider configuration
without making any estimation calls.

## Out of Scope

TLS / reverse proxy / HTTPS termination, production hardening, resource limits,
object storage, and hosted/cloud deployment are intentionally out of scope for
this local self-host stack.
