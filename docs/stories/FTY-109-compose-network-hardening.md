---
id: FTY-109
state: merged
primary_lane: infra
touched_lanes:
  - security-privacy
  - docs
review_focus:
  - port-exposure
  - redis-auth-surface
  - healthcheck
  - restart-policy
risk: medium
tags:
  - docker-compose
  - self-host
  - hardening
  - audit-quick-win
approved_dependencies: []
requires_context:
  - docs/operations/local-dev-stack.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
autonomous: true
---

# FTY-109: Compose Network / Ops Hardening (infra)

## State

ready_with_notes

## Lane

infra

## Dependencies

- None to schedule. This is an audit quick win that hardens the **merged**
  `docker-compose.yml` stack from FTY-011 (the dev compose stack) and FTY-072
  (self-host first-boot). All changes are in the single root `docker-compose.yml`,
  so the slice stays in the infra lane.

## Outcome

The self-host / dev compose stack stops exposing its datastores and stays up
across crashes. Today `postgres` publishes `${POSTGRES_PORT:-5432}:5432` and
`redis` publishes `${REDIS_PORT:-6379}:6379` on **all host interfaces** — and
Redis has no `requirepass`, so an unauthenticated Redis (the Celery broker, which
can carry task payloads) is reachable on the self-host box's LAN. Only `api`,
`worker`, and `migrate` need those datastores, and they reach them over the
internal compose network by service name — never via the host port. This story
removes that exposure, gives the `worker` a healthcheck it currently lacks, and
adds a restart policy so a crashed long-lived service comes back on its own.

## Scope

- **Stop publishing the datastore ports to all host interfaces.** Remove the
  host port mappings from `postgres` (`${POSTGRES_PORT:-5432}:5432`, ~line 30–31)
  and `redis` (`${REDIS_PORT:-6379}:6379`, ~line 42–43). The recommended default
  is to drop them entirely (api/worker/migrate reach both over the compose
  network by hostname). If direct host access is kept as a documented opt-in,
  bind to loopback only — `127.0.0.1:${POSTGRES_PORT:-5432}:5432` /
  `127.0.0.1:${REDIS_PORT:-6379}:6379` — so the port is never on the LAN. Pick
  one default (see Planning Notes) and document how a self-hoster re-enables
  direct access if they need it.
- **Add a `worker` healthcheck** (~line 107). The worker currently has none while
  `postgres`/`redis`/`api` all do. Use a Celery ping against the confirmed app
  path: `.venv/bin/celery -A app.worker:celery_app inspect ping` (the worker
  command already references `app.worker:celery_app`). Give it sensible
  `interval`/`timeout`/`retries`/`start_period`, mirroring the `api` healthcheck
  shape.
- **Add a restart policy to the long-lived services.** Set `restart: unless-stopped`
  on `api`, `worker`, `postgres`, and `redis`. The one-shot `migrate` service
  keeps **no** restart policy (it is meant to run once and exit).
- **Keep the docs consistent.** The host-port column in
  `docs/operations/local-dev-stack.md` (and the `Host ports` env group there)
  describes ports this story removes/loopback-binds; update that doc so the
  documented stack matches the compose file.

## Non-Goals

- **No Redis password / auth.** Adding `requirepass` requires a matching
  `FATTY_REDIS_URL` change in app config and the worker/api broker URL — that
  touches backend config, a different boundary. Call it out as a follow-up; this
  story only closes the host-exposure surface.
- No compose network restructuring (no custom `networks:` blocks, no segmenting
  the datastores onto a separate network).
- No Dockerfile changes. The non-root container user is a separate backend-core
  story.
- No TLS / reverse proxy / resource limits / production hardening — those remain
  out of scope for the local self-host stack per `docs/operations/local-dev-stack.md`.

## Contracts

- The compose **service names** (`postgres`, `redis`, `migrate`, `api`, `worker`),
  the API host port (`${API_PORT:-8000}`), and the env-var names are a documented
  contract (compose header + `docs/operations/local-dev-stack.md`) and stay
  **unchanged**. Only the `postgres`/`redis` host-port mappings, the `worker`
  healthcheck, and the four `restart:` lines change.
- `POSTGRES_PORT` / `REDIS_PORT` remain meaningful only if the opt-in loopback
  form is kept; if the mappings are dropped, note that those env vars no longer
  publish anything by default (document, don't delete the `.env.example` entries
  without a follow-up).

## Security / Privacy

- **Closes a real data-exposure surface.** An unauthenticated Redis bound on all
  host interfaces is reachable by anything on the self-host box's LAN; it is the
  Celery broker and result backend, so it can carry estimation task payloads.
  Removing the host mapping (or loopback-binding it) takes it off the LAN. The
  Postgres port mapping is the same class of exposure for the application
  database.
- No new trust boundary, no new untrusted input, no new stored data — this only
  **reduces** the reachable surface. Aligns with the pinned-dependency /
  least-exposure posture in `docs/security/security-baseline.md` and the
  self-host threat model in `docs/security/threat-model.md`.

## Acceptance Criteria

- `postgres` and `redis` no longer publish a port on all host interfaces — either
  the mappings are removed, or they are bound to `127.0.0.1` only.
- `api`, `worker`, and `migrate` still reach `postgres` and `redis` over the
  internal compose network (by service hostname); a clean `docker compose up`
  brings the stack to healthy with no behavioural change for the app.
- The `worker` service has a healthcheck using
  `.venv/bin/celery -A app.worker:celery_app inspect ping`, and `docker compose ps`
  reports the worker as `healthy` once it is up.
- `api`, `worker`, `postgres`, and `redis` each declare `restart: unless-stopped`;
  `migrate` declares no restart policy.
- `docker compose config` validates the file with no errors.
- `docs/operations/local-dev-stack.md` host-port references match the new compose
  reality.

## Verification

- `cd <repo root> && docker compose config` — validates and renders the merged
  config without error.
- `docker compose up -d` then `docker compose ps` — `migrate` exited 0;
  `postgres`, `redis`, `api`, **and now `worker`** report `healthy`; `api` serves
  `GET /healthz` (`curl -fsS http://localhost:8000/healthz` → `{"status":"ok"}`),
  confirming it still reaches db/redis over the compose network.
- Confirm the datastore ports are no longer on the host: with the stack up,
  `5432`/`6379` are not bound on a non-loopback host interface (or not bound at
  all, depending on the chosen default).
- **Note:** root `make verify` does **not** exercise compose, so the verification
  here is the `docker compose config` validation plus the `compose up` + healthcheck
  observation above — not a unit-test run.

## Planning Notes

- **Default choice (the `ready_with_notes` decision):** three reversible options —
  (a) fully remove the host port mappings, (b) loopback-bind `127.0.0.1:…`,
  (c) keep them behind an opt-in env. **Recommend remove-by-default**, since
  api/worker/migrate never use the host port; if devs commonly want direct DB
  access, the loopback form (b) is the acceptable compromise. Document the
  re-enable path either way. Flag that `migrate` and any host tooling that
  relied on the published DB ports (a local `psql`, a GUI client) would need the
  loopback form or `docker compose exec`.
- **Celery app path confirmed** as `app.worker:celery_app` from the existing
  `worker` command and `backend/app/worker.py` — use it verbatim in the ping so
  the healthcheck resolves the right Celery app.
- **`migrate` keeps no restart policy** deliberately: it is a one-shot
  `alembic upgrade head` runner that must exit, not be restarted.

## Readiness Sanity Pass

- **Product decision gaps:** one reversible call — remove vs loopback-bind vs
  opt-in for the datastore host ports. Recommended (remove-by-default, loopback as
  the documented opt-in) and justified above, hence `ready_with_notes` rather than
  blocked. No health/nutrition/behavioural question is involved, so no evidence
  research is warranted.
- **Cross-lane impact:** primary infra; security-privacy and docs ride along
  (non-serializing). **Single boundary, no big rock:** every change is in the one
  `docker-compose.yml` (path → infra). No public contract change, no schema
  migration, no new trust boundary — it only reduces exposure and adds ops
  resilience.
- **Size:** `review_focus` = 4 (under the 5 ceiling): port-exposure,
  redis-auth-surface, healthcheck, restart-policy. `requires_context` = 3 (under
  8). Comfortably one story.
- **Security/privacy risk:** medium — closes an unauthenticated-Redis LAN exposure
  and a Postgres exposure on the self-host box; touches the shared dev + self-host
  stack, so a misconfigured port/healthcheck could break local bring-up. No new
  data stored or exposed.
- **Verification path:** `docker compose config` + `compose up` to healthy
  (including the new worker healthcheck) + a host-port reachability check; root
  `make verify` is noted as not covering compose.
- **Assumptions safe for autonomy:** yes — bounded edits to one compose file plus a
  doc table, with the one judgment call (remove vs loopback) pinned here and the
  Celery ping path confirmed against the repo.
