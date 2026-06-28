---
id: FTY-113
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - security-privacy
review_focus:
  - rate-limit-retry-classification
  - backoff-determinism
  - max-attempts-bound
  - secret-safe-backoff-logging
risk: medium
tags:
  - estimator
  - llm-provider
  - transport
  - hardening
  - retry
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/standards/testing-standards.md
  - docs/standards/coding-standards.md
  - docs/security/security-baseline.md
autonomous: true
---

# FTY-113: Retry LLM Provider Rate-Limits With Jittered Backoff (estimator)

## State

ready_with_notes

## Lane

estimator

## Dependencies

- None to schedule. This **hardens merged code**: the provider transport and the
  shared retry loop landed with FTY-041 (provider config) and FTY-042 (the
  `structured_completion` flow). This story changes only the error-classification
  seam in `app/llm/transport.py` and the retry loop in `app/llm/base.py`; it adds
  no contract, no migration, and no config-schema change.

## Outcome

When an LLM provider (OpenAI/Anthropic) answers a parse / label / official-facts
call with a **429 rate-limit**, the estimation step **retries with a short
jittered backoff** instead of hard-failing on the first hit. Today a 429 takes
down the step immediately, and even genuinely-transient failures retry with **no
delay** — a tight loop that would hammer a provider that is already throttling
us. After this change a transient throttle is absorbed by the existing bounded
retry budget, a brief backoff gives the provider room to recover, and a
*persistent* 429 still ultimately **fails closed** to the same clean error the
caller already handles — no new failure mode, no unbounded retry.

This closes a real availability hole on the LLM path. In `transport.py`
(lines 61-67) the `urllib.error.HTTPError` handler maps **every** non-`5xx`
status — including `429` — to a non-retryable `LLMResponseError`. In `base.py`
(`_complete_with_retries`, lines 155-191) the loop retries **only**
`LLMTransientError`, so a 429 is never retried; and where it does retry it does
so with a bare `continue` and **no sleep**. The fix makes a rate-limit
(and the comparable `408 Request Timeout` / `425 Too Early`) classify as the
existing retryable `LLMTransientError`, and inserts a deterministic, jittered
exponential backoff between attempts through an **injectable sleep seam** so the
behaviour is real in production but instant and reproducible under test.

## Scope

- **Classify 429 / 408 / 425 as transient in `transport.py`.** In the
  `HTTPError` handler (lines 61-67) a status of `429` (Too Many Requests),
  `408` (Request Timeout), or `425` (Too Early) maps to `LLMTransientError`
  (joining the existing `>= 500` branch); every other `4xx` (400/401/403/404,
  …) stays the non-retryable `LLMResponseError` exactly as today. The raised
  message stays content-free (`f"provider returned HTTP {status}"`) — no URL,
  header, key, or body, per the module's existing redaction contract.
- **Add a jittered exponential backoff between retries in `base.py`.** In
  `_complete_with_retries`, after a `LLMTransientError` and *before* the next
  attempt (only when another attempt remains — never sleep after the final
  attempt), wait `base * 2**(attempt-1)` seconds with full jitter, capped at a
  ceiling. **Recommended defaults (pinned, reversible):** base `0.5s`, cap
  `8.0s`, full jitter (`random.uniform(0, computed)`). The existing
  `max_retries` bound is unchanged — backoff only governs the gap between the
  same number of attempts.
- **Make the wait an injectable seam so tests never really sleep.** Add a
  `sleep` callable parameter to the `Provider` constructor (default
  `time.sleep`), stored on the instance and invoked by the backoff. Tests pass a
  fake that records the requested durations and returns instantly, so retry +
  backoff are asserted deterministically with **zero wall-clock delay**. The
  jitter source should be similarly overridable (or the test asserts the
  *bounds* of the recorded delays rather than exact values) so determinism does
  not depend on the RNG.
- **(Optional, note only) Honour `Retry-After` when present.** A 429/503 may
  carry a `Retry-After` header. Honouring it requires carrying the value from
  the `HTTPError` in `transport.py` up to the backoff in `base.py` (the only
  clean route is an optional `retry_after_seconds: float | None` attribute on
  `LLMTransientError`, defaulting `None`). **Recommend deferring** unless it is
  cheap to thread through: if implemented, clamp it to the same cap, parse only
  the integer-seconds form, ignore an unparseable value, and never log the raw
  header. The jittered-backoff default is sufficient on its own; this is a nice-
  to-have, not a requirement.

## Non-Goals

- **No change to the non-retryable 4xx policy.** `400` / `401` / `403` / `404`
  and other client errors stay `LLMResponseError` and are **not** retried —
  retrying a malformed request or a bad key cannot succeed and only wastes the
  budget.
- **No change to `max_retries`.** The attempt count stays config-driven
  (`settings.max_retries`); this story changes *whether* 429 counts as retryable
  and *what happens between* attempts, not how many attempts there are.
- **No circuit breaker / token-bucket / global rate-limiter.** Cross-call
  throttle coordination is out of scope; this is per-call bounded retry only.
- **No FDC/OFF evidence-client changes.** Those clients fail closed under FTY-110
  and have their own error types; this story touches only the LLM provider
  transport and retry loop.
- **No provider config-schema change.** The backoff constants are internal
  defaults; introducing `FATTY_LLM_*` knobs for base/cap/jitter is explicitly
  out of scope (pin the defaults instead).
- **No transport rewrite.** The `urllib`-only, dependency-free transport and its
  redaction posture are preserved; only the status-class mapping changes.

## Contracts

- **None.** This is internal transport/retry behaviour. `LLMTransientError` and
  `LLMResponseError` already exist and are already the retry/fail-closed signals
  the loop consumes; the public `structured_completion` contract (a schema-
  validated object out, or a bounded failure) is unchanged. `docs/contracts/`
  `llm-provider.md` describes the *capability*, not the retry-status taxonomy, so
  it needs no version bump (an optional one-line note that rate-limits are
  retried is welcome but not required).

## Security / Privacy

- **No new surface.** No new input boundary, no new external call, no image /
  fetch / OCR / upload path — an existing transient-classification rule is being
  widened and a delay inserted. This is not a new untrusted-input trust boundary
  and adds no big rock.
- **Backoff must stay secret-safe.** The new per-retry log fields and any new
  exception attribute must keep the module's existing redaction guarantee: never
  log or embed the prompt, the key, the request URL, request/response bodies, or
  the raw `Retry-After` header. The transient log line already emits only
  `provider` / `attempt` / `max_attempts` / `error_type`; a `backoff_seconds`
  field (a bounded number) is safe to add, raw provider text is not.
- **Availability, not exfiltration, is the failure mode addressed.** The bounded
  retry budget and the cap prevent the fix from becoming an amplification vector
  against a throttling provider; a persistent 429 still terminates at the
  existing clean error after at most `max_retries + 1` attempts.
- **Rated medium:** a transport-layer hardening that touches **every** LLM step
  (parse, label, official). The blast radius is real (a classification bug could
  make a hard-error retry forever or a real failure never retry), but the change
  is local, bounded, and behaviour-preserving on the non-429 paths.

## Acceptance Criteria

- **429 retries then succeeds:** a provider that returns `429` on the first
  attempt and a valid body on the second resolves successfully; the injected
  `sleep` seam is invoked exactly once (between the two attempts) with a delay
  within the `[0, cap]` jittered bound. Proven without any real wall-clock wait.
- **Persistent 429 fails closed within the bound:** a provider that returns `429`
  on every attempt exhausts exactly `max_retries + 1` attempts and then raises
  the existing terminal error (`LLMTransientError`) — no unbounded loop, no new
  exception type leaking to the caller. The injected `sleep` is invoked exactly
  `max_retries` times (once between each pair of attempts, never after the last).
- **408 / 425 are retryable too:** a `408` (and a `425`) classify as transient
  and follow the same retry-with-backoff path as `429`.
- **Non-retryable 4xx still does NOT retry:** a `400` and a `401` each raise
  `LLMResponseError` on the **first** attempt with **zero** retries and **zero**
  `sleep` invocations — the existing
  `test_http_401_is_response_error` behaviour is preserved.
- **No backoff after the final attempt:** when the last attempt fails, `sleep` is
  not called again (no needless trailing wait before raising).
- **Tests never really sleep:** the whole suite runs with the injected fake
  sleep; no test depends on real time, and the default `time.sleep` is used only
  in production wiring (asserted by construction, e.g. the default parameter).
- **Secret-safe logging preserved:** the per-retry log line and any new exception
  attribute carry no prompt, key, URL, or body; existing redaction tests stay
  green.
- **Behaviour-preserving on the happy path:** a first-attempt success calls
  `sleep` zero times and returns identically to today.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Transport classification tests** in `tests/llm/test_transport.py`: add a
  `test_http_429_is_transient` (and `408` / `425`) mirroring the existing
  `test_http_500_is_transient`, asserting `pytest.raises(LLMTransientError)`; keep
  `test_http_401_is_response_error` and add a `400` case asserting
  `LLMResponseError` is **unchanged**.
- **Retry + backoff tests** (against a fake provider with an injected sleep, e.g.
  in `tests/llm/test_structured_completion.py`): (a) 429-then-success retries once,
  succeeds, and records exactly one bounded backoff; (b) persistent 429 exhausts
  `max_retries + 1` attempts, raises the terminal `LLMTransientError`, and records
  exactly `max_retries` sleeps each within `[0, cap]`; (c) a non-retryable error
  records zero sleeps and raises on the first attempt; (d) the final attempt's
  failure does not trigger a trailing sleep. All with the fake sleep — **no real
  delay** anywhere.
- **Redaction test** stays green: the transient log line / new attribute exposes
  no prompt, key, URL, or body.
- Existing transport and provider tests remain green unchanged.

## Planning Notes

- **Why 429/408/425 are the transient set.** `429` is the canonical rate-limit;
  `408 Request Timeout` and `425 Too Early` are server-side "try again" signals
  semantically closer to a `5xx` hiccup than to a malformed request. Everything
  else in `4xx` (auth, not-found, bad-request) is a deterministic client error
  where retrying is pointless and the current `LLMResponseError` is correct.
- **The injectable sleep seam is the `ready_with_notes` driver.** A real
  `time.sleep` in the retry loop would make tests slow and flaky; a `sleep`
  constructor parameter defaulting to `time.sleep` keeps production behaviour real
  while tests stay instant and deterministic. This is the small design choice
  pinned here: **recommend an injectable `sleep: Callable[[float], None] =
  time.sleep` on `Provider`**, invoked by the backoff. The jitter RNG should be
  overridable or its output asserted by bounds, so determinism never hinges on
  the random draw.
- **Backoff schedule (reversible defaults).** Full-jitter exponential
  (`uniform(0, min(cap, base * 2**(attempt-1)))`) with `base=0.5s`, `cap=8.0s` is
  a standard, gentle schedule that respects a throttling provider without
  meaningfully lengthening a healthy run (most calls succeed on attempt one and
  never sleep). These are internal constants, trivially tunable later; they are
  **not** promoted to config in this story.
- **Retry-After is deliberately optional.** Honouring it is strictly better but
  needs the header value carried from `transport.py` to `base.py` (via an optional
  `retry_after_seconds` on `LLMTransientError`). The jittered default already
  fixes the bug, so this is a documented nice-to-have, not a blocker; if added it
  must clamp to the cap and never log the raw header.
- **Audit confirmed against source.** `transport.py` lines 61-67 map all
  non-`5xx` `HTTPError`s (including 429) to `LLMResponseError`; `base.py`
  `_complete_with_retries` (lines 155-191) retries only `LLMTransientError` with a
  bare `continue` and no delay; attempts derive from `settings.max_retries`
  (`factory.py`). No nutrition/health/behavioural question is involved, so no
  evidence research is warranted — this is transport robustness.

## Readiness Sanity Pass

- **Product decision gaps:** none load-bearing. The judgment calls — the transient
  status set (429/408/425), the full-jitter schedule and its constants, the
  injectable `sleep` seam, and deferring `Retry-After` — are decided and justified
  above. `ready_with_notes` only for the (recommended) sleep-seam shape and the
  pinned-but-reversible backoff defaults. No health/nutrition/behavioural decision
  is involved, so no evidence research applies.
- **Cross-lane impact:** primary estimator; security-privacy rides along
  (non-serializing) since it touches a secret-redacting transport. **Single
  boundary, zero big rocks:** no public contract change, no schema migration, no
  new untrusted-input trust boundary (an existing transient classification is
  widened and a delay added). Stays wholly in the estimator lane.
- **Size:** `review_focus` = 4 (rate-limit-retry-classification,
  backoff-determinism, max-attempts-bound, secret-safe-backoff-logging);
  `requires_context` = 4. Well under both ceilings (6 / 9) — a deliberately small
  quick-win, kept as one story.
- **Security/privacy risk:** medium — a transport-layer change touching every LLM
  step; the fix removes a hard-fail-on-throttle and a no-delay retry loop, adds a
  bounded backoff, and preserves the existing no-secrets-in-logs/errors posture.
- **Verification path:** `make verify` + transport classification tests
  (429/408/425 transient, 400/401 unchanged) + retry/backoff tests via an injected
  sleep (retry-then-succeed, persistent-429 fails closed within the bound, no-retry
  on hard errors, no trailing sleep) + redaction test; existing tests stay green.
  No real sleeping in tests.
- **Assumptions safe for autonomy:** yes — a local change to two files with the one
  design call (injectable sleep) and the backoff defaults pinned here, no contract,
  no migration, no config-schema change, and no live provider call (transport is
  monkeypatched / the provider is faked in tests). No UI.
