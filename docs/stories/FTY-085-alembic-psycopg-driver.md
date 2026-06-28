---
id: FTY-085
state: merged
primary_lane: backend-core
touched_lanes:
  - infra
risk: high
tags:
  - migrations
  - alembic
  - docker
  - self-host
  - release-blocker
approved_dependencies: []
requires_context:
  - docs/architecture/repo-layout.md
  - docs/operations/local-dev-stack.md
  - docs/standards/testing-standards.md
review_focus:
  - alembic-normalizes-bare-postgresql-url-to-psycopg-v3
  - single-source-of-truth-driver-normalization
  - first-boot-docker-compose-migrate-succeeds
autonomous: true
---

# FTY-085: Alembic Migrations Must Bind the psycopg v3 Driver (Fix First-Boot `docker compose up`)

## State

ready

## Lane

backend-core

## Dependencies

- none

## Outcome

A fresh `docker compose up` from a clean checkout applies migrations and reaches
a fully migrated schema with the **shipped default** `.env.example`
(`FATTY_DATABASE_URL=postgresql://...`). The FTY-072 first-boot / self-host
contract holds without the operator hand-editing the DSN scheme.

## Problem (found in the v1 release manual test)

The compose `migrate` service runs `alembic upgrade head`. `alembic/env.py`'s
`_resolve_url()` returns `load_settings().database_url` **verbatim**, so a bare
`postgresql://` DSN makes SQLAlchemy default to the **psycopg2** dialect — which
is not installed (the project ships `psycopg[binary]` v3 only). Result:
`ModuleNotFoundError: No module named 'psycopg2'`, the `migrate` service exits 1,
and the API/worker never start. The application runtime already avoids this:
`app/db.py::_normalize_url()` rewrites `postgresql://` → `postgresql+psycopg://`.
The migration path simply doesn't reuse that normalization. Tests missed it
because they run against SQLite.

## Scope

- Make `alembic/env.py` resolve the database URL through the **same driver
  normalization** as `app/db.py` (reuse `_normalize_url`, e.g. by importing it /
  promoting it to a shared, importable helper — single source of truth for the
  `postgresql://` → `postgresql+psycopg://` mapping). Apply it on **both** the
  offline (`run_migrations_offline`) and online (`run_migrations_online`) paths.
- Keep SQLite and already-qualified `postgresql+psycopg://` URLs working
  unchanged (the normalizer must be idempotent / scheme-aware).

## Non-Goals

- No change to the DSN contract in `.env.example` / docker-compose (bare
  `postgresql://` stays the documented default — that's the contract this fix
  honors).
- No new dependency (do **not** add psycopg2); the project standardizes on
  psycopg v3.
- No migration content changes; no app runtime changes beyond exposing the
  shared normalizer if needed.

## Contracts

- None changed. This restores the documented FTY-072 first-boot behavior; the
  `FATTY_DATABASE_URL` env contract is unchanged.

## Security / Privacy

- None. No new data flow, egress, or secret handling — a driver-selection fix on
  the migration path. Rated **high** only because it sits on the
  migration/first-boot/release gate (round risk up for migrations + CI/release
  paths), not because it widens any surface.

## Acceptance Criteria

- With the shipped default `.env.example` (bare `postgresql://...`), a clean
  `docker compose up` runs the `migrate` service to completion and the API/worker
  start (no `psycopg2` import error).
- `alembic upgrade head` and `downgrade base` both succeed against a Postgres DSN
  given as bare `postgresql://` (driver normalized to psycopg v3).
- SQLite-backed migration/tests still pass unchanged.
- A regression test asserts the resolved alembic URL binds the psycopg v3 driver
  for a bare `postgresql://` input (so this can't silently regress).
- `make verify` passes.

## Verification

- `make verify` (governance + backend + mobile).
- A test that feeds a bare `postgresql://` DSN through the alembic URL resolver
  and asserts the result selects `postgresql+psycopg` (and that SQLite is
  untouched).
- Manual/CI: `docker compose up` from a clean checkout with default `.env`
  reaches healthy API + worker (migrate exits 0). If a compose-level check is
  impractical in CI, assert the resolver behavior at the unit level and note the
  manual check.

## Readiness Sanity Pass

- **Product decision gaps:** none — reuse the existing, proven `_normalize_url`
  on the migration path.
- **Cross-lane impact:** backend-core (alembic/env.py + maybe promoting the
  shared helper) with an infra/first-boot effect. One touched lane.
- **Security/privacy risk:** high bucket by policy (migrations + release gate);
  no actual surface change.
- **Verification path:** `make verify` + a resolver regression test + a clean
  `docker compose up`.
- **Assumptions safe for autonomy:** yes — the bug, the root cause, and the fix
  shape (single-source-of-truth normalization) are all pinned.
- **Sizing:** 1 touched lane, 3 review_focus, 3 requires_context — within the
  scope guardrail. Small, targeted fix on a release-blocking path.
