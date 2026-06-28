---
id: FTY-118
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - rate-limit-bruteforce
  - redis-backed-counter
  - 429-retry-after
  - mobile-retry-tolerance
  - redis-fail-open
risk: medium
tags:
  - auth
  - rate-limit
  - redis
  - security
  - api
approved_dependencies: []
requires_context:
  - docs/contracts/identity-and-profile.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-118: Rate-Limit the Auth Endpoints (backend)

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- None to schedule. This **hardens one merged write path**: FTY-020 (the local
  email+password auth service + the `register` / `login` routes). It is landed;
  this story adds a throttle in front of two endpoints with no schema change and
  no change to the auth/session contract.

## Outcome

`POST /api/auth/login` and `POST /api/auth/register` are today **fully open to
unbounded attempts** — no `slowapi`, limiter, or counter exists anywhere in
`backend/app` (confirmed by grep). Login timing is already equalized against
user-enumeration (`app/services/auth.py` `_DUMMY_HASH`, ~32–35), but **attempt
count is unbounded**, so the endpoints are exposed to online brute-force and
credential-stuffing (login) and bulk-account abuse (register). This story adds a
**per-IP (and per-account for login) rate limit** that returns `429 Too Many
Requests` with a `Retry-After` header once a threshold is exceeded, backed by the
**existing Redis** (`settings.redis_url`, settings.py:52 — already in the stack
as the Celery broker) so the limit holds **across worker processes**, not just
per-process memory.

## Scope

- **Add a small Redis-backed fixed-window counter.** A new module (e.g.
  `app/security/rate_limit.py`) increments a per-key counter in Redis with a
  window TTL (`INCR` + `EXPIRE` on first hit, or an atomic equivalent) and
  reports whether the key is over its limit plus the seconds until the window
  resets (for `Retry-After`). Use the `redis` client already pulled in
  transitively by `celery[redis]` (uv.lock ~805); if a direct import warrants it,
  add `redis` as a direct dependency in `backend/pyproject.toml`.
- **Wire it as a swappable seam on `app.state`** (mirroring the existing
  `estimation_enqueuer` / `label_processor` seams in `app/main.py` ~54–62):
  production builds the limiter from `settings.redis_url`; tests inject an
  in-memory / fakeredis double so the suite needs no live Redis. The two
  auth routes (`app/routers/auth.py`) read the seam and the client IP from the
  already-imported `Request`.
- **Throttle `/login`** on **two keys**: the source IP **and** the submitted
  account (the lower-cased login email). Either key exceeding its window →
  short-circuit with `429` **before** the credential check, so a flood never
  reaches the password verify. The per-account key blunts credential-stuffing
  that rotates IPs against one account; the per-IP key blunts a single source
  spraying many accounts.
- **Throttle `/register`** on the **source IP** (bulk-account abuse is per-source);
  a per-account key is not meaningful pre-account.
- **Return `429` + `Retry-After`** (seconds until the window resets) when a limit
  trips. Make the thresholds/windows **configurable via `Settings`** (new
  `FATTY_*`-prefixed fields, defaulting generously — see Planning Notes) so they
  tune without code change.
- **Determine the client IP safely.** Default to `request.client.host`. Honour a
  forwarded-for header **only when a trusted-proxy setting is explicitly enabled**
  (a new `Settings` flag), and then only the documented hop — **never** trust an
  arbitrary inbound `X-Forwarded-For` (it is client-spoofable and would let an
  attacker forge a fresh key per request, defeating the per-IP limit entirely).
- **Document the `429` + `Retry-After`** on the two auth endpoints in
  `docs/contracts/identity-and-profile.md` (the endpoints' error table, ~131–136)
  — a minimal addition, no change to request/response shapes or the existing
  status codes.

## Non-Goals

- **No global rate limiter.** Only `/login` and `/register` are throttled; the
  rest of the API is untouched. A general per-route limiting framework is out of
  scope.
- **No CAPTCHA and no account-lockout.** Progressive challenges and lock-after-N
  account states are separate, heavier stories with their own UX.
- **No auth/session contract change.** Login/register request bodies, success
  responses, tokens, and the existing `401`/`409` semantics are unchanged; only a
  new `429` is added on top.
- **No security headers.** HSTS / CSP / frame options are FTY-112.
- **No new heavy dependency** if avoidable — a small hand-rolled Redis counter is
  preferred over pulling `slowapi` (see Planning Notes).

## Contracts

- **`docs/contracts/identity-and-profile.md` (minimal addition):** document that
  `/api/auth/login` and `/api/auth/register` may return `429 Too Many Requests`
  with a `Retry-After` header when the per-IP / per-account attempt limit is
  exceeded. No other field, status, or shape changes. This is the one (small)
  contract touch.
- **Persistence:** none. The counters live in the **existing** Redis (no new
  table, no migration). Keys are short-lived (window TTL) and self-expiring.
- **Settings (env contract):** new `FATTY_*` fields for the login/register
  thresholds, the window length, and the trusted-proxy toggle, defaulting safely
  (the limit is on by default; the proxy header is **off** by default).

## Security / Privacy

- **This is a security-hardening story.** It closes online brute-force /
  credential-stuffing on `/login` and bulk-registration abuse on `/register`,
  the gap explicitly left open by FTY-111 ("No rate-limiting / brute-force
  protection on the auth path — that is a separate security story"). Align with
  `docs/security/threat-model.md` and `docs/security/security-baseline.md`.
- **The limiter runs before the credential check** (login) and before the
  insert (register), so a throttled request pays no password-hash / DB cost and
  the existing equalized-timing posture is preserved — the `429` short-circuit is
  the same for a known and an unknown email, so it adds no enumeration oracle.
- **No PII in the counter store.** The per-account key must **not** store the raw
  email in Redis: key on a salted hash of the lower-cased email (e.g.
  `sha256(email)`), and never log the IP or email as part of a limiter event.
  Rate-limit logs record the decision (allowed / throttled) and a non-reversible
  key, not the identifier.
- **Failure mode: fail OPEN, with a warning.** If Redis is briefly unavailable,
  the limiter must **allow** the request (so an infra blip never locks every user
  out of login) and emit a warn-level log so the gap is visible — availability of
  the auth path outweighs a momentary loss of throttling. Do **not** fail closed.
  (Reversible — see Readiness notes.)
- **Rated medium:** it sits on the auth path, and a too-tight limit could lock out
  legitimate users or the mobile reconnect/login path, but it adds no migration,
  no new untrusted-input trust boundary, and no auth-contract change.

## Acceptance Criteria

- **Login brute-force bounded:** N rapid `/login` attempts from one IP (N over the
  configured threshold) return `429` with a `Retry-After` header once the limit is
  hit; attempts under the limit still return the normal `200` / `401`.
- **Per-account bounded:** repeated `/login` attempts against one account email
  from rotating IPs trip the per-account limit and return `429`, independent of
  the per-IP key.
- **Register bounded:** rapid `/register` calls from one IP over the threshold
  return `429` + `Retry-After`; a fresh registration under the limit still returns
  its normal `201`.
- **Legitimate cadence unaffected:** a slow, normal sequence of logins (including
  a wrong-password retry well under the window threshold) is never throttled.
- **Shared across processes:** the counter is held in Redis (asserted via the
  injected fakeredis/seam), so two app instances sharing a Redis enforce one
  combined limit, not two independent in-memory ones.
- **IP spoofing does not bypass:** with the trusted-proxy setting **off**, an
  inbound `X-Forwarded-For` is ignored and the limit keys on the real peer; the
  forwarded hop is honoured **only** when the setting is explicitly enabled.
- **Fail-open on Redis down:** when the Redis seam errors, login/register still
  succeed (request allowed) and a warning is logged; no `500` from the limiter.
- **Contract doc** lists the new `429` + `Retry-After` on both auth endpoints.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Per-IP throttle test:** drive N+1 `/login` (and `/register`) calls from one
  IP through the injected limiter seam; assert the over-threshold call returns
  `429` with a numeric `Retry-After`, and under-threshold calls return normally.
- **Per-account throttle test:** repeated `/login` for one email across differing
  IPs trips the per-account limit → `429`.
- **Shared-counter test:** two requests against the same fakeredis instance share
  one window; assert the second over-limit call is throttled (the count is not
  per-process).
- **Spoof-rejection test:** with the proxy setting off, an inbound
  `X-Forwarded-For` does not create a fresh key (still throttled on the real
  peer); with it on, the configured hop is used.
- **Fail-open test:** make the limiter seam raise (simulated Redis outage); assert
  login/register still return their normal status and a warning is logged, never a
  `500`.
- **Regression:** existing FTY-020 happy-path login/register and `401`/`409` tests
  stay green (the limiter is transparent below the threshold).

## Planning Notes

- **Hand-rolled Redis counter vs `slowapi` (reversible — recommended: hand-rolled).**
  A small fixed-window `INCR`/`EXPIRE` counter avoids a new framework dependency
  and the middleware coupling `slowapi` brings, and reuses the Redis already in
  the stack. The interface (a seam returning allow/throttle + reset-seconds) is
  small and swappable, so if a sliding window or a library is wanted later it
  drops in behind the same seam. Fixed-window is sufficient for an abuse throttle;
  the brief boundary burst it allows is acceptable here.
- **Thresholds (reversible — recommend generous defaults, tunable via `Settings`).**
  Suggested starting points: login ~10 attempts / IP / 15 min and ~5 / account /
  15 min; register ~5 / IP / hour. Tuned to stop automated abuse while leaving
  ample headroom for a human fat-fingering a password or a mobile client
  re-authenticating after a reconnect. The mobile **offline outbox flush**
  (FTY-096 / FTY-104) hits `log-events`, **not** the auth endpoints, so it is not
  throttled here; the only auth-path retry is a reconnect re-login, which the
  generous window covers. Keep limits in config so ops can tighten/loosen without
  a redeploy of logic.
- **Why fail-open:** failing closed would convert a Redis hiccup into a total
  auth outage (no one can log in) — a worse outcome than the brief, logged loss
  of throttling. The warn log makes the degraded window observable.
- **IP trust:** the default (`request.client.host`) is correct for a direct bind;
  behind a known proxy, only an explicitly configured trusted hop is honoured.
  Trusting an arbitrary `X-Forwarded-For` would let any client forge a unique key
  per request and nullify the per-IP limit, so it is gated behind an off-by-default
  flag.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The three judgment calls —
  hand-rolled counter vs `slowapi`, the exact thresholds/windows, and fail-open vs
  fail-closed — are all **reversible** and a recommendation is pinned for each
  (hand-rolled, generous-and-configurable, fail-open-with-warn); hence
  `ready_with_notes` rather than `ready`. No health, nutrition, or behavioural
  question is involved (this is an infra/security throttle), so no evidence
  research is warranted.
- **Cross-lane impact:** primary backend-core (all code in `backend/app`);
  contracts (a one-line `429` note in the auth contract) and security-privacy ride
  along (both non-serializing). **Single boundary, zero big rocks:** no public
  contract *change* (only an additive `429` note), no schema migration / new
  table, no new untrusted-input trust boundary (the limiter consumes the request
  IP and an opaque hashed email key, not images / fetched pages / uploads). One
  serializing code lane → one story.
- **Size:** `review_focus` = 5 (at the ceiling, not over): rate-limit-bruteforce,
  redis-backed-counter, 429-retry-after, mobile-retry-tolerance, redis-fail-open.
  `requires_context` = 4 (under 8). At one limit only, so it stays one story.
- **Security/privacy risk:** medium — auth-path hardening that closes a real
  brute-force / credential-stuffing gap; limiter runs pre-credential-check so
  equalized timing is preserved; counter keys carry no raw PII; fails open with a
  warning so an infra blip is not an auth outage.
- **Verification path:** `make verify` + per-IP and per-account throttle tests
  (`429` + `Retry-After`) + shared-counter (Redis seam) test + spoof-rejection
  test + fail-open test + existing FTY-020 auth regressions stay green.
- **Assumptions safe for autonomy:** yes — a bounded throttle in front of two
  existing endpoints, reusing the in-stack Redis and the established `app.state`
  seam pattern, with the three reversible calls (counter approach, thresholds,
  failure mode) recommended above. No migration, no auth-contract change, no UI,
  no external provider, no LLM.
