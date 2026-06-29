---
id: FTY-120
state: merged
primary_lane: backend-core
touched_lanes: []
review_focus:
  - helper-consolidation
  - no-behaviour-change
  - single-source-of-truth
  - tz-dst-preserved
risk: low
tags:
  - refactor
  - timezone
  - daily-summary
  - targets
  - log-events
approved_dependencies: []
requires_context:
  - docs/architecture/repo-layout.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/contracts/daily-summary.md
  - docs/contracts/target-calculator.md
autonomous: true
---

# FTY-120: Consolidate Duplicated Day-Window + Active-Target Service Helpers (backend)

## State

ready

## Lane

backend-core

## Dependencies

- None to schedule. This is a **pure refactor** over already-merged service code:
  FTY-030/FTY-051 (`log_events`), FTY-105 (`daily_summary`), and FTY-094/FTY-095
  (`targets`) created the three modules that hold the duplicated helpers. Nothing
  blocks it, but it edits three shared service files, so it should **rebase on
  whatever backend-core work merges first** to avoid a churn conflict.

## Outcome

The correctness-critical "what day is it in the user's timezone" logic and the
"active goal's target row for a day" query each get a **single source of truth**,
eliminating three copies of the former and two copies of the latter.
**Behaviour is byte-for-byte unchanged** — this only removes duplication so a
future timezone/DST fix can no longer land in one copy and silently miss the
others.

1. **Day / timezone window helpers are triplicated.** `_user_timezone`,
   `_day_bounds_utc`, and `_next_day` appear with **identical logic** in both
   `app/services/log_events.py` (~238–263) and `app/services/daily_summary.py`
   (~95–117); `app/services/targets.py` `_resolve_day` (~319–332) carries a
   **third** copy of the same `ZoneInfo(tz_name or "UTC")` profile-timezone
   default. This window logic gates the Today timeline, the daily summary, and
   target lookups — three copies invite drift.
2. **The active-target query is duplicated.** `app/services/daily_summary.py`
   `_resolve_target` (~200–227) re-implements the exact active-goal target join
   already in `app/services/targets.py` `_resolve_active_target` (~335–354) — two
   byte-identical copies of the `Goal.is_active` + `for_date` predicate. "The
   active target for a day" must have one resolver.

## Scope

- **Extract a shared time-window module (e.g. `app/timeutils.py`).** Move
  `_user_timezone(session, owner_id) -> ZoneInfo`, `_day_bounds_utc(day, tz)`,
  and `_next_day(day)` into one module (public names, no leading underscore, since
  they now cross modules) and have **all three call sites** use it:
  - `log_events.py` and `daily_summary.py` import and call the shared helpers,
    deleting their local copies.
  - `targets.py` `_resolve_day` keeps its **own** signature and not-found
    semantics but builds its timezone from the shared `_user_timezone` (i.e.
    `datetime.now(timeutils.user_timezone(...)).date()`), deleting its inlined
    `select(UserProfile.timezone)` copy. Its `for_date is not None` early-return is
    preserved exactly.
- **Consolidate the active-target lookup to one resolver.** Extract the shared
  **query** — the `DailyTarget`-joined-to-active-`Goal`-on-`for_date` predicate
  returning `DailyTarget | None` — to a single function (the natural home is
  `targets.py`, which already owns the targets domain). Then:
  - `targets.py` `_resolve_active_target` calls it and keeps its **raise**
    behaviour (`TargetNotFound` when `None`), returning the raw `DailyTarget`.
  - `daily_summary.py` `_resolve_target` calls it and keeps its **None-returning,
    read-model-projecting** behaviour (`build_target_read_model` when present,
    `None` when absent).

  The shared piece is the query predicate only; each caller's not-found policy and
  return shape stay exactly as today.
- **Add focused unit tests for the extracted helpers** (see Verification).

## Non-Goals

- **No behaviour change of any kind.** No new validation, no endpoint/router
  change, no contract change, no migration. The consolidated path must produce
  byte-for-byte identical results to the prior per-module code.
- **Do not change DST / timezone semantics.** The UTC fallback, the
  `astimezone(UTC)` half-open `[start, end)` window, and the
  `ZoneInfo(tz_name or "UTC")` default are preserved exactly — just centralised.
- **Do not unify the two active-target callers' not-found behaviour.** The
  divergence is intentional and load-bearing: `targets` raises `TargetNotFound`
  (an override targets a real row), `daily_summary` returns `None` (explicit null,
  not zero, to distinguish "no goal/row" from "zero intake"). Consolidating the
  *query* must not collapse these into one policy.
- **Do not fold in the weight-entry date bound** — that is FTY-119.
- Touch no other helper, query, or module beyond the three named services and the
  new shared module.

## Contracts

- **None.** `docs/contracts/daily-summary.md` and
  `docs/contracts/target-calculator.md` are referenced for the day-default and
  active-target behaviour the refactor must preserve, but are **not modified** —
  the observable contract is unchanged by construction.

## Security / Privacy

- **None new.** No new surface, input, or stored field. Note the positive effect:
  centralising the day-window logic removes the latent risk of a future
  timezone/DST correctness fix landing in only one of three copies — a class of
  silent drift on the Today timeline, the daily summary, and target lookups.

## Verified-Identical Note (read before implementing)

The audit confirmed the duplicated blocks against the real files:

- `_user_timezone`, `_day_bounds_utc`, `_next_day` are **logic-identical** across
  `log_events.py` and `daily_summary.py`; the only differences are docstring
  wording (e.g. "display timezone" vs "profile timezone") and that
  `daily_summary._next_day` omits a docstring. No semantic divergence — safe to
  collapse to one implementation.
- `targets._resolve_day` is a **partial** third copy: it inlines the same
  `select(UserProfile.timezone)` + `ZoneInfo(tz_name or "UTC")` default, then
  applies `datetime.now(tz).date()` and a `for_date`-passthrough. Reuse the shared
  `_user_timezone` for the default; keep the `.now(...).date()` and passthrough.
- `daily_summary._resolve_target` and `targets._resolve_active_target` share a
  **byte-identical query predicate** but **legitimately diverge** afterward
  (None-return + read-model projection vs raise + raw-ORM return). This divergence
  is **not a bug**; it is the chosen canonical behaviour and must be preserved.
  Consolidate only the predicate.

If implementation reveals any further divergence not listed here, **stop and
flag it** rather than silently picking one — but none is expected.

## Acceptance Criteria

- `_user_timezone`, `_day_bounds_utc`, and `_next_day` exist in **one** module;
  `log_events.py`, `daily_summary.py`, and `targets.py` no longer define their own
  copies (and `targets._resolve_day` no longer inlines the timezone query).
- The active-target query predicate exists in **one** resolver; both
  `daily_summary._resolve_target` and `targets._resolve_active_target` call it,
  each preserving its own not-found policy (`None` vs `TargetNotFound`) and return
  shape (read-model vs raw `DailyTarget`).
- **All existing `log_events`, `daily_summary`, and `targets` service tests pass
  unchanged** — no assertion edits. Identical days, windows, DST-transition
  behaviour, target lookups, and not-found signals as before the refactor.
- No router, schema, contract, or migration is touched.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Existing service tests stay green with zero assertion changes** — the primary
  proof the consolidation is behaviour-preserving across the three modules.
- **New focused unit tests for the extracted time-window helpers:** the UTC
  fallback when the profile has no timezone; `_day_bounds_utc` returns the correct
  half-open `[start, end)` UTC instants for a normal day; `_next_day` rolls the
  calendar day; and a **DST-transition day** (e.g. a spring-forward / fall-back
  date in a DST zone) yields the correct (not 24h-assumed) UTC bounds — locking in
  the preserved semantics.
- **New focused unit test for the consolidated active-target resolver:** the
  shared query returns the active goal's `DailyTarget` for the day and `None` when
  there is no active goal or no row, and the two callers map that result to their
  respective policies (raise vs None, raw vs read-model) — proving the consolidated
  path matches the prior per-module behaviour.

## Planning Notes

- **Home module:** the only real judgment call. The time-window helpers cross
  three services with no single owning domain, so a small dedicated
  `app/timeutils.py` is the idiomatic home (mirrors the repo's flat `app/`
  module layout in `docs/architecture/repo-layout.md`). The active-target query
  belongs in `targets.py`, which already owns the targets domain — extract it
  there and import from `daily_summary.py` rather than adding a third module.
- **Public vs private names:** helpers that previously had leading underscores
  become cross-module callees; rename to public (no underscore) on extraction so
  imports read cleanly and lint stays quiet.
- **Why keep the two active-target callers' policies separate:** see Non-Goals —
  the raise-vs-None split is the documented semantic difference between an override
  hitting a real row and a summary distinguishing absent from zero. Only the
  predicate is duplicated; only the predicate is consolidated.

## Readiness Sanity Pass

- **Product decision gaps:** none. The single judgment call (home module
  name/location) is decided above (`app/timeutils.py` for the window helpers;
  `targets.py` for the active-target query). No health, nutrition, or behavioural
  question is involved, so no evidence research is warranted.
- **Cross-lane impact:** primary backend-core, **no touched lanes** — pure
  internal refactor, no contract/security surface. **Single boundary, zero big
  rocks:** no public contract change, no schema migration / new table, no new
  untrusted-input trust boundary. All edits are in the one serializing backend-core
  lane.
- **Size:** `review_focus` = 4 (under the 5 ceiling); `requires_context` = 5
  (under 8). Comfortably one story.
- **Security/privacy risk:** low — no new input, stored field, or endpoint; the
  refactor *reduces* latent risk by removing tz/DST-fix drift across three copies.
  It touches three correctness-critical service modules, so the existing service
  tests staying green (no assertion edits) is the required safety net.
- **Verification path:** `make verify` + existing service tests unchanged + new
  unit tests for the extracted time-window helpers (incl. a DST-transition day) and
  the consolidated active-target resolver.
- **Assumptions safe for autonomy:** yes — a behaviour-preserving consolidation
  with the home-module choice pinned, the verified-identical blocks confirmed
  against the real files, and the two intentional divergences explicitly fenced off
  from the consolidation. No migration, no contract, no UI, no external provider.
