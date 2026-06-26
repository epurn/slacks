# Local Development Stack

The repo-root `docker-compose.yml` (FTY-011) brings up the full local backend
stack over plain HTTP for development:

```sh
cp .env.example .env
docker compose up
```

This starts four services. The service names, the API port, and the env-var
names are a contract that later infra and backend stories build on.

## Services

| Service | Image / build | Purpose | Host port |
| --- | --- | --- | --- |
| `postgres` | `postgres:16.4-alpine` | Application database. | `${POSTGRES_PORT:-5432}` |
| `redis` | `redis:7.4-alpine` | Celery broker / result backend. | `${REDIS_PORT:-6379}` |
| `api` | `./backend` (FastAPI) | HTTP API; serves `GET /healthz`. | `8000` |
| `worker` | `./backend` (Celery) | Background worker; no tasks defined yet. | — |

- Postgres and Redis define healthchecks (`pg_isready`, `redis-cli ping`). The
  `api` service waits for both to be healthy before it starts, and the `worker`
  waits for Redis.
- The API healthcheck polls its own `GET /healthz` and expects HTTP 200.
- Images for Postgres and Redis are pinned per the security baseline's
  pinned-dependency principle.

## Configuration

Configuration comes from `.env` (copied from `.env.example`). Only placeholder,
non-secret values are committed; the real `.env` is gitignored. See
`backend/README.md` for the full `FATTY_`-prefixed settings table.

| Variable | Used by | Notes |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | postgres | Local dev credentials (not secrets). |
| `POSTGRES_PORT` / `REDIS_PORT` / `API_PORT` | host port mapping | Published host ports (containers always listen on 5432 / 6379 / 8000). |
| `FATTY_ENVIRONMENT` / `FATTY_LOG_LEVEL` | api, worker | Application config. |
| `FATTY_DATABASE_URL` | reserved | Postgres DSN for the later database story. |
| `FATTY_REDIS_URL` | api, worker | Celery broker + result backend. |

## Verifying

```sh
docker compose up -d
curl -fsS http://localhost:8000/healthz   # -> {"status":"ok"}
docker compose ps                          # api/postgres/redis healthy, worker running
docker compose down                        # add -v to drop the postgres volume
```

## Out of Scope

TLS / reverse proxy / HTTPS termination (deferred to FTY-072, self-host setup),
production hardening, resource limits, object storage, and hosted/cloud
deployment are intentionally not part of this stack.
