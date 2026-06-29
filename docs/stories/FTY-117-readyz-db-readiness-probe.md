---
id: FTY-117
state: merged
primary_lane: backend-core
touched_lanes:
  - security-privacy
review_focus:
  - readiness-vs-liveness
  - db-probe-fail-to-503
  - no-internal-detail-leak
risk: medium
tags:
  - health
  - readiness
  - ops
  - api
approved_dependencies: []
requires_context:
  - docs/operations/local-dev-stack.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-117: Real Readiness Probe That Checks the DB (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. This **extends the merged backend skeleton** (FTY-012: the
  health route/service split and the request-scoped DB session dependency). It
  adds one new read-only endpoint; no schema and no existing-endpoint change.

## Outcome

An orchestrator can gate traffic until the database is actually reachable. Today
only `/healthz` exists — a **liveness** probe that returns a static `{"status":
"ok"}` as long as the process is up (`app/routers/health.py` ~15;
`app/services/health.py` ~12, whose own docstring flags that "real readiness
checks (database, queue) are added later"). Nothing verifies DB connectivity, so
a freshly-started API reports healthy before its database is ready to serve.

Add a `/readyz` **readiness** probe that runs a cheap `SELECT 1` against the
request-scoped DB session: `200` when the database answers, `503 Service
Unavailable` (never `500`) when it does not. `/healthz` liveness semantics are
untouched.

## Scope

- **Add `GET /readyz`** to `app/routers/health.py`, next to the existing
  `healthz()` liveness handler, delegating to the health service so the route
  stays a thin HTTP boundary (the pattern that module already documents). Inject
  the DB session via the existing dependency
  (`session: Annotated[Session, Depends(get_session)]`, `app/db.py` ~65), matching
  every other router (e.g. `app/routers/daily_summary.py` ~36).
- **Probe the DB cheaply.** In `app/services/health.py`, add a readiness check
  that executes `SELECT 1` (`session.execute(text("SELECT 1"))`) and reports
  reachable/not-reachable. Keep `check_health()` (liveness) exactly as is — a
  static process-up check.
- **Fail to `503`, never `500`.** When the probe query raises (DB down,
  connection refused, pool exhausted), the handler catches it and returns a
  `503` with a **generic** body — e.g. `HTTPException(status_code=503,
  detail="not ready")`. The exception must be caught in the handler so a probe
  failure produces a deliberate `503`, not an unhandled `500`. (Note: the
  `get_session` dependency re-raises on the *yield* boundary; the probe query
  runs inside the handler, so catch it there.)
- **Distinct response shape from liveness, kept minimal.** `/readyz` returns a
  typed body (e.g. a small `ReadinessStatus` in `app/schemas/health.py` mirroring
  `HealthStatus`) carrying only a coarse status — no error string, no driver
  message, no host/DSN. `200` ⇒ ready; the `503` carries the generic detail only.
- **Document `/readyz` alongside `/healthz`** in `docs/operations/local-dev-stack.md`
  wherever `/healthz` liveness is described (the service table ~21 and the smoke
  block ~149): one line stating `/readyz` is the readiness probe (`200` ready /
  `503` not-ready, checks DB reachability) versus `/healthz` liveness
  (process-up). Keep it minimal.

## Non-Goals

- **No queue/Redis readiness check.** The Celery/Redis broker readiness probe is
  explicitly **deferred to a follow-up** (the health service docstring lists
  "database, queue"; this story does the database half only).
- **No change to `/healthz` semantics.** Liveness stays a static process-up check
  with its existing `{"status": "ok"}` contract; do not make it touch the DB.
- **Do not wire `/readyz` into docker-compose healthchecks.** The compose
  healthcheck/orchestration wiring lives in the infra lane (FTY-109); this story
  only adds the endpoint and documents it.
- **No auth on the probe.** Readiness is an unauthenticated ops endpoint, like
  `/healthz`; do not add auth — but do not echo anything sensitive either.
- No metrics endpoint, no detailed component-by-component health JSON, no
  `/healthz/*` diagnostic siblings.

## Contracts

- **`docs/operations/local-dev-stack.md` (ops doc):** documents the new public
  `/readyz` ops endpoint next to `/healthz` — readiness (`200`/`503`, DB
  reachability) vs liveness (process-up). Minimal addition; no other contract doc
  changes.
- **No schema change, no migration.** The probe issues a read-only `SELECT 1`
  through the existing session dependency.

## Security / Privacy

- **The `503` body must not leak internal detail.** A DB-down path must never
  surface a stack trace, driver/exception message, DSN, host, or query in the
  response — only a generic `not ready`. This is the whole point of catching the
  probe error and returning a deliberate `503` instead of an unhandled `500`
  (which can leak a trace). Proven by an assertion that the `503` body contains no
  internal/DB detail.
- **Read-only, no auth, no secrets.** The probe runs a constant `SELECT 1`, takes
  no input, writes nothing, and exposes no configuration — consistent with the
  existing unauthenticated health endpoints in `docs/security/security-baseline.md`.
- **Rated medium:** a new ops endpoint on the DB path whose correctness hinges on
  failing *closed* to `503` without leaking detail; no migration, no contract
  change beyond the ops doc, no new untrusted-input surface.

## Acceptance Criteria

- **Ready path:** `GET /readyz` against a reachable DB returns `200` with the
  typed readiness body.
- **Not-ready path:** with the DB session made to fail the probe query, `GET
  /readyz` returns `503` (not `500`) and the body contains **no** internal/DB
  error detail (generic only).
- **Liveness unchanged:** `GET /healthz` still returns `200` with `{"status":
  "ok"}` and never touches the DB; its existing tests stay green.
- **Distinct probes:** `/readyz` and `/healthz` are separate routes with distinct
  bodies; readiness reflects DB reachability while liveness does not.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Ready test:** `GET /readyz` with the test SQLite-backed session → `200`,
  typed body.
- **Not-ready test:** override `get_session` (or the probe) so `SELECT 1` raises
  (e.g. a session whose `execute` throws / a closed engine), assert `503`, assert
  status is not `500`, and assert the response body has no exception/DB string.
- **Liveness-unchanged test:** keep the existing `/healthz` `{"status": "ok"}`
  test green; assert `/readyz` and `/healthz` are independent.

## Planning Notes

- **`SELECT 1` over a richer check:** the cheapest portable round-trip that proves
  the connection pool can reach and get an answer from the DB; works identically
  on the SQLite test engine and runtime Postgres. Anything heavier (counting rows,
  checking migration head) belongs to a separate, more opinionated probe.
- **Catch in the handler, not the dependency:** `get_session` only rolls back and
  re-raises on the `yield` boundary, which would surface as `500`. The probe query
  runs in the handler, so the handler owns the try/except that converts failure to
  `503` — keep that explicit.
- **Why defer the queue check:** Redis/Celery readiness is a different dependency
  with its own failure modes and is not needed to gate DB-dependent traffic;
  bundling it would widen the slice. Left as a clearly-scoped follow-up.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The judgment calls — `SELECT 1`
  as the probe, `503`-not-`500` on failure, defer the queue check, handler-owned
  catch — are decided and justified above. No health/nutrition/behavioural
  question is involved, so no evidence research is warranted.
- **Cross-lane impact:** primary backend-core; security-privacy rides along
  (non-serializing, the no-leak requirement). **Single boundary, zero big rocks:**
  no public app-contract change (only the ops doc), no schema migration / new
  table, no new untrusted-input trust boundary (constant read-only query, no
  input).
- **Size:** `review_focus` = 3 (under the 5 ceiling); `requires_context` = 3
  (under 8). Comfortably one story — a quick win.
- **Security/privacy risk:** medium — correctness of failing closed to `503`
  without leaking internal detail on the DB path; read-only, unauthenticated like
  the existing health endpoints, no secrets.
- **Verification path:** `make verify` + ready (`200`) + not-ready (`503`, not
  `500`, no detail leak) + liveness-unchanged tests.
- **Assumptions safe for autonomy:** yes — one new read-only endpoint plus a thin
  service method and a one-line ops-doc note, no migration, no app-contract
  change, no UI, no external provider, with the failure-handling shape pinned
  above.
