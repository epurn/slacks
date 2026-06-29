---
id: FTY-138
state: merged
primary_lane: backend-core
touched_lanes:
  - security-privacy
  - docs
review_focus:
  - fail-closed-in-production
  - configurable-fail-mode
  - no-existing-path-regression
  - transient-503-not-401
  - mobile-reconnect-preserved
risk: medium
tags:
  - auth
  - rate-limit
  - fail-closed
  - security
approved_dependencies: []
requires_context:
  - docs/security/security-baseline.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-138: Auth Rate-Limit Fails Closed in Production (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. Built on already-merged FTY-118 (the Redis-backed auth
  rate-limiter and its `FATTY_RATE_LIMIT_*` settings). Nothing blocks it. It edits
  `app/routers/auth.py` and `app/settings.py` (plus tests and a docs ride-along);
  no other in-flight backend-core story is known to touch those files, but as
  always **rebase on whatever backend-core work merges first** to avoid a churn
  conflict.

## Outcome

Today the auth rate-limiter **fails open**: `app/routers/auth.py`
`_enforce_rate_limit` (~86–90) catches **any** limiter exception (e.g. Redis
unavailable) and `return`s, allowing the request. That is a deliberate
availability-over-security tradeoff (documented in `security-baseline.md`), but it
means a Redis outage **silently disables** the only online brute-force /
credential-stuffing / register-abuse protection on `/login` and `/register` — the
exact window an attacker would want, with no signal beyond a warn log.

Make the failure mode **configurable**, defaulting to **fail-open in development**
(today's behaviour, preserved for dev ergonomics and self-host robustness) and
**fail-closed in production**. When fail-closed and the limiter cannot return a
decision, the auth request is **denied as a transient `503`** (the limiter
dependency is down) rather than allowed — closing the silent-bypass window while
keeping the response honestly transient so the mobile retry/reconnect path backs
off and retries instead of treating it as an auth failure.

## Scope

- **Add a configurable fail-mode setting** to `app/settings.py`, defaulting from
  `environment`:
  - Add a field whose effective value is **fail-open when
    `environment != "production"`** and **fail-closed when
    `environment == "production"`**, with an **explicit override** so an operator
    can force either mode regardless of environment. Recommended shape (author may
    refine naming to match the module's conventions):
    - `rate_limit_fail_open_override: bool | None = Field(default=None)` (read from
      `FATTY_RATE_LIMIT_FAIL_OPEN_OVERRIDE`), plus a computed property
      `rate_limit_fail_open -> bool` returning the override when set, else
      `self.environment != "production"`.
  - Mirror the existing `_require_real_secret_in_production` pattern (an
    `environment == "production"` gate already lives in this module) and the
    `FATTY_RATE_LIMIT_*` naming from FTY-118. Document the new env var in the
    field comment alongside the other rate-limit settings.
- **Thread the decision through the enforcement helper** in `app/routers/auth.py`:
  - `_enforce_rate_limit` gains a `fail_open: bool` parameter. On a limiter
    exception:
    - `fail_open=True` → keep today's behaviour exactly: log the warn
      ("rate-limit check raised; allowing request (fail-open)") and `return`
      (allow).
    - `fail_open=False` → log a warn that the request is being **denied**
      (fail-closed; same content-free message — no key, IP, or email) and raise
      `HTTPException(status_code=503, detail="Service temporarily unavailable. Please
      try again later.", headers={"Retry-After": "<small int>"})`.
  - Both call sites (`register`, and the two checks in `login`) pass
    `settings.rate_limit_fail_open`. The `login` per-IP check still runs **before**
    the credential verify, so a fail-closed denial still pays no hash/DB cost and
    preserves equalized timing / no account-existence oracle.
- **Pick `503`, not `429`/`401`, for the fail-closed denial** (decided in Planning
  Notes): the limiter dependency is unavailable, so the honest signal is "service
  temporarily unavailable," which a well-behaved client (including the mobile
  reconnect path) treats as transient-and-retryable rather than a credential
  failure or a "you are throttled" verdict.
- **Update the docs ride-along:** correct the `security-baseline.md` auth
  rate-limit bullet (currently states "Fails open — a Redis blip allows the
  request") to describe the new configurable, environment-defaulted posture
  (fail-open in dev, fail-closed `503` in production, overridable). This is a
  non-serializing docs/security ride-along, not a contract change.

## Non-Goals

- **No change to the normal throttle path.** An allowed request and a genuinely
  throttled `429` + `Retry-After` (limit exceeded) behave exactly as in FTY-118 in
  both modes. Only the **limiter-exception** branch changes.
- **No change to the limiter backends.** `RedisRateLimiter` /
  `InMemoryRateLimiter` in `app/security/rate_limit.py` and the
  `app.state.rate_limiter` seam are untouched; the fail-mode decision lives in the
  router, where the exception is already caught.
- **No in-process fallback counter.** Considered (see Planning Notes) and not
  chosen for v1: a per-process counter gives a weaker, non-shared guarantee and
  adds state; the simpler fail-closed-in-prod posture is the decided fix.
- **No threshold/tuning change** to the existing `FATTY_RATE_LIMIT_*` values, and
  **no new endpoint or migration.**
- **No contract change.** `503` on a dependency outage is standard HTTP behaviour,
  not part of any documented contract surface.

## Contracts

- **None.** No contract doc is modified. `security-baseline.md` (a security policy
  doc, not a contract) is updated as a ride-along to keep the documented posture
  accurate. The auth request/response schemas are unchanged.

## Security / Privacy

- **This is the security fix.** Production no longer silently loses online
  brute-force / credential-stuffing / register-abuse protection during a Redis
  outage — the limiter-down case now denies (fail-closed `503`) instead of
  allowing.
- **Availability tradeoff, made explicit:** fail-closed means a Redis outage will
  deny logins/registrations in production until Redis recovers. This is the
  intended posture for the auth lane (the user accepted availability-over-security
  was the wrong default here); dev/self-host keep fail-open by default, and the
  override lets an operator choose. Document this in `security-baseline.md`.
- **No new PII in logs.** The fail-closed warn log stays content-free (no key, IP,
  or email) — same discipline as the existing fail-open warn and the FTY-118
  module's no-raw-PII rule.
- **Mobile reconnect preserved:** a `503` with `Retry-After` is transient, so the
  reconnect/retry path backs off and retries rather than surfacing an auth error —
  the same retry path FTY-118 was tuned not to break.

## Acceptance Criteria

- A new `FATTY_RATE_LIMIT_*` setting (and computed effective fail-mode) exists:
  effective value is **fail-open when `environment != "production"`**,
  **fail-closed when `environment == "production"`**, and an explicit override
  forces either mode regardless of environment.
- When the limiter `check` raises and the effective mode is **fail-open**, the
  request is **allowed** and a content-free warn is logged — byte-for-byte today's
  behaviour.
- When the limiter `check` raises and the effective mode is **fail-closed**, the
  request is **denied** with `503` + `Retry-After`, a content-free warn is logged,
  and the credential verify is **not** reached (no hash/DB cost, no
  account-existence oracle).
- The normal allowed path and the genuine over-limit `429` + `Retry-After` path
  are unchanged in both modes, for both `/login` (per-IP and per-account) and
  `/register` (per-IP).
- `security-baseline.md`'s auth rate-limit bullet describes the new configurable,
  environment-defaulted fail-mode (no longer says it unconditionally fails open).
- `make verify` passes (ruff check + ruff format --check + mypy + pytest).

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh`, i.e. root
  `make verify`.
- **New router tests** (using a limiter test double whose `check` raises) for both
  endpoints:
  - fail-open mode → raising limiter ⇒ request allowed (existing behaviour
    preserved); assert the warn is emitted.
  - fail-closed mode → raising limiter ⇒ `503` + a positive `Retry-After` header,
    and the credential service was **not** invoked (assert via a spy/mock that
    `authenticate` / `register_user` was not called).
  - both modes → normal allowed request succeeds, and an over-limit request still
    returns `429` + `Retry-After` (no regression).
- **New settings tests:** default `development` ⇒ effective fail-open;
  `environment=production` ⇒ effective fail-closed; explicit override flips each
  direction.
- **Reuse the existing FTY-118 rate-limit suite** to prove the happy-path and
  throttle behaviour is untouched.

## Planning Notes

- **Why `503`, not `429` or `401`:** the limiter could not produce a decision
  because its dependency is down — that is "service temporarily unavailable,"
  not "too many requests" (no count was observed) and not "bad credentials" (the
  verify never ran). `503` + `Retry-After` is the honest, client-friendly signal:
  the mobile reconnect path treats it as transient and retries with backoff,
  whereas a `401` would look like a credential failure and a `429` would imply a
  throttle that did not actually occur.
- **Why environment-defaulted with an override, not a bare boolean:** it gives the
  right default for each deployment shape (dev/self-host stay open and robust; prod
  closes the bypass) while leaving an operator a single env var to force either
  mode — matching the existing `_require_real_secret_in_production` "safe in prod
  by default" pattern in `settings.py`.
- **Why not an in-process fallback counter:** it would preserve some protection
  during a Redis outage without denying users, but the guarantee is per-process
  (not shared across api/worker replicas), it adds mutable state to the hot auth
  path, and it muddies the security story. For v1 the explicit fail-closed-in-prod
  posture is simpler and auditable; an in-process or local fallback can be a
  later, separately-scoped enhancement if the availability cost proves real.
- **Decision basis:** this is a security-posture/architecture decision, not a
  health/nutrition/behavioural one, so no evidence research is warranted; it is
  grounded in `docs/security/security-baseline.md` (the auth rate-limit and
  fail-closed-by-default principles) and the user's call that the auth lane should
  prefer security over availability.

## Readiness Sanity Pass

- **Product decision gaps:** none. The fail-mode default (env-driven), the
  override, and the `503` status are all decided above; the in-process-fallback
  alternative is explicitly considered and deferred.
- **Cross-lane impact:** primary backend-core; **security-privacy and docs ride
  along** (the posture change + the `security-baseline.md` edit) and do not count
  as a second boundary. **Single boundary, zero blocking big rocks:** no public
  contract change, no schema migration / new table, no new untrusted-input trust
  boundary — the change is confined to the auth router's exception branch and a
  settings field.
- **Size:** `review_focus` = 5 (at the ceiling, not over); `requires_context` = 3
  (under 8). One story.
- **Security/privacy risk:** medium — it deliberately changes an auth-path
  security posture (the reason for the medium risk rating and the security-privacy
  ride-along), but the change is small, behind a config default, fully covered by
  both-branch tests, and adds no PII to logs. The fail-open dev path is preserved
  byte-for-byte so the only behavioural change is the prod limiter-down branch.
- **Verification path:** `make verify` + new both-branch router tests (limiter
  raises ⇒ allow vs `503`, credential service not called when closed) + settings
  default/override tests + the reused FTY-118 happy-path/throttle suite.
- **Assumptions safe for autonomy:** yes — the contract surface is unchanged, the
  decision points are pinned, the dev behaviour is preserved exactly, and both the
  fail-open and fail-closed branches are pinned by tests.
