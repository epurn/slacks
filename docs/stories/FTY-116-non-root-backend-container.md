---
id: FTY-116
state: ready
primary_lane: backend-core
touched_lanes:
  - security-privacy
review_focus:
  - non-root-user
  - filesystem-permissions
  - migrate-worker-api-parity
risk: medium
tags:
  - docker
  - container-hardening
  - self-host
  - security
approved_dependencies: []
requires_context:
  - docs/security/security-baseline.md
  - docs/operations/local-dev-stack.md
autonomous: true
---

# FTY-116: Run the Backend Container as a Non-Root User (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. This **hardens a merged image**: FTY-012 (backend skeleton +
  `GET /healthz`) and FTY-072 (self-host Docker stack). Both are landed; this
  story changes only `backend/Dockerfile` so the same image runs unprivileged.
  Note: `backend/Dockerfile` maps to **backend-core** via the steward's
  `lane_for_path` (`backend/` prefix), not infra, so it serializes with the other
  backend-core stories.

## Outcome

The backend image currently has **no `USER` directive**
(`backend/Dockerfile` CMD `.venv/bin/python -m app`), so all three services that
build from it — `api`, `worker`, and the one-shot `migrate` — run as **root**.
Add a dedicated non-root user/group, give it the paths the runtime reads and the
few it writes, and switch to that user before the entrypoint. Standard container
hardening: a backend RCE or arbitrary file-write is contained to an unprivileged
account instead of root, shrinking the blast radius across all three services.

## Scope

- **Create a dedicated non-root user/group** in `backend/Dockerfile` (e.g. a
  system group + user `fatty`, fixed UID/GID like `10001`, with a real home dir
  so the runtime has a writable `HOME`). Pin the UID/GID rather than letting it
  auto-assign, so behaviour is reproducible across rebuilds.
- **Give the new user the paths the runtime needs.** Read access: the app source
  (`/app/app`, `/app/alembic`, `alembic.ini`) and the uv virtualenv
  (`/app/.venv`, where `.venv/bin/python`, `.venv/bin/alembic`, and
  `.venv/bin/celery` live — all three service commands resolve here). `chown` the
  app dir + `.venv` to the new user (or build/install them as that user) so the
  interpreter and entrypoints are readable/executable by it.
- **Cover the few writable paths.** `PYTHONDONTWRITEBYTECODE=1` is already set, so
  no runtime `.pyc` writes; bytecode is compiled at build time. The remaining
  runtime write path is the **`/claude-config` volume** the api and worker mount
  (FTY-088, `CLAUDE_CONFIG_DIR=/claude-config`): the `claude` CLI writes its
  session there. Ensure the new user can write it — create `/claude-config` in the
  image **owned by the new user** before the volume is first populated (a named
  volume mounted onto a path that exists in the image inherits that path's
  ownership on first use), and ensure `HOME` resolves to a user-writable directory
  for any incidental CLI scratch/cache. The volume's host contents stay
  operator-managed; this only fixes the in-container ownership of the mountpoint.
- **Switch user before the entrypoint.** Add `USER fatty` (after all
  root-requiring build steps — apt, npm global install, `uv sync`, `COPY`s, the
  `chown`s) so the default API CMD and the compose-overridden `migrate`/`worker`
  commands all launch unprivileged.

## Non-Goals

- **No read-only root filesystem and no capability drops** (`cap_drop`,
  `no-new-privileges`, seccomp). Those are separate hardening; this story only
  adds the non-root user.
- **No `docker-compose.yml` change.** Port exposure and compose-level hardening
  are FTY-109's lane (infra) — out of this boundary. The same compose commands
  (`migrate`/`api`/`worker`) must keep working unmodified.
- **No base-image or build-stage logic change.** Same `python:3.12-slim-bookworm`
  base, same uv install, same Node/Claude Code layers — only ownership + the
  trailing `USER` are added.
- No change to app behaviour, env vars (beyond an optional `HOME`), exposed port,
  or the healthcheck command shapes.

## Contracts

- **None.** No public contract, no API shape, no schema. The compose service
  names, commands, port (8000), and `/healthz` healthcheck are all unchanged — the
  image just runs them as a non-root user.

## Security / Privacy

- **Defense-in-depth, blast-radius reduction.** Running unprivileged means a
  compromised backend process (RCE, path-traversal write, dependency exploit)
  cannot trivially modify root-owned files, the interpreter, or installed
  packages, and cannot escalate as easily inside the container. This advances the
  least-privilege posture in `docs/security/security-baseline.md`.
- **The `/claude-config` volume stays a host secret.** It holds the operator's
  `claude login` OAuth session. Changing the in-container mountpoint owner to the
  unprivileged runtime user does not weaken that — it scopes session access to the
  same low-privilege account the CLI runs as. Do not bake any session content into
  the image.
- **Rated medium:** a container-runtime change where a wrong UID or missed
  `chown` breaks startup (the interpreter/venv unreadable, or `claude` unable to
  write its session), but no contract, schema, or new untrusted-input surface.

## Acceptance Criteria

- **Builds clean:** `docker compose build` (or `docker build ./backend`) succeeds
  with the new user, `chown`s, and trailing `USER`.
- **Runs unprivileged:** after `docker compose up`, `docker compose exec api
  whoami` prints the non-root user (not `root`), and the api process inside the
  container is owned by that user.
- **All three services healthy under the new user:**
  - `migrate` applies migrations to head and exits successfully (Alembic runs as
    the non-root user, reading `/app/alembic` + `.venv/bin/alembic`).
  - `api` reaches `healthy` — `GET /healthz` returns 200 via the existing
    healthcheck.
  - `worker` reaches `healthy` — the Celery `inspect ping` returns `pong`.
- **Claude Code session path works:** the api/worker can write `/claude-config`
  (no permission error on `claude` session access) under the non-root user.
- **No regression:** same image, base, port (8000), env, and compose commands; no
  `docker-compose.yml` edit.

## Verification

- **Root `make verify` does not exercise the image** (it runs lint/type/pytest on
  the host), so verification is the **build + compose-up observation**, not a unit
  test:
  - `docker compose build` succeeds.
  - `docker compose up` brings `migrate` to successful completion and `api` +
    `worker` to `healthy` (migrations applied, worker `pong`, api serves
    `/healthz`).
  - `docker compose exec api whoami` returns the non-root user.
  - Confirm `claude`-session access works (no `/claude-config` permission error in
    the api/worker logs on first use).
- Keep `make verify` green (unchanged; the Dockerfile change does not touch app
  code).

## Planning Notes

- **Why pin UID/GID and create a real home:** a fixed UID/GID keeps the
  in-container owner stable across rebuilds and matches named-volume ownership
  predictably; a real `HOME` gives the `claude` CLI and any incidental cache a
  writable location, avoiding a `$HOME`-unset surprise that only shows up at
  runtime.
- **Order matters:** all root-requiring steps (apt, the NodeSource + npm global
  install, `uv sync`, the `COPY`s) must stay **before** `USER`, and the `chown`s
  must cover `/app` (incl. `.venv`) and `/claude-config`. Placing `USER` too early
  breaks the build; missing a `chown` breaks startup — the two failure modes this
  story is sized around.
- **`/claude-config` ownership nuance:** an empty named volume mounted onto an
  image path inherits that path's ownership on first population, so creating
  `/claude-config` owned by the new user in the image is what makes the runtime
  write succeed. The compose volume definition is unchanged.
- **migrate/worker/api parity:** all three commands invoke a binary under
  `/app/.venv/bin`, so a single `chown` of `/app` covers every service — verify
  all three, not just the default API CMD.

## Readiness Sanity Pass

- **Product decision gaps:** none. No health/nutrition/behavioural question is
  involved, so no evidence research is warranted. The standard hardening approach
  (dedicated UID, `chown` app+venv, own the `/claude-config` mountpoint, trailing
  `USER`) is pinned above.
- **Cross-lane impact:** primary backend-core (`backend/Dockerfile` →
  `lane_for_path` `backend/`, not infra); security-privacy rides along
  (non-serializing). **Single boundary, zero big rocks:** no public contract
  change, no schema migration / new table, no new untrusted-input trust boundary.
  The compose change is deliberately excluded (FTY-109, infra) to keep this in one
  lane.
- **Size:** `review_focus` = 3 (under the 5 ceiling); `requires_context` = 2
  (under 8). Comfortably one story.
- **Security/privacy risk:** medium — a container-runtime hardening change; a
  wrong UID or missed `chown`/`HOME` breaks startup, but no contract, schema, or
  untrusted-input surface. The approach is standard and pinned; the only thing to
  confirm at build time is that the new UID can read `/app/.venv` and write
  `/claude-config`.
- **Verification path:** build + `docker compose up` observation (migrate exits 0;
  api/worker `healthy`; `whoami` non-root; `/claude-config` writable) — root `make
  verify` does not exercise the image, so the compose-up is the real gate.
- **Assumptions safe for autonomy:** yes — a bounded edit to one Dockerfile (add
  user, `chown`s, `USER`), no app code, no compose, no contract, no migration, no
  external provider, with the ordering and the `/claude-config` ownership nuance
  pinned above.
