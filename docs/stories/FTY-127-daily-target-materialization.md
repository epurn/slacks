---
id: FTY-127
state: ready_with_notes
primary_lane: backend-core
touched_lanes: []
review_focus:
  - target-materialization-correctness
  - override-reset-on-later-day
  - provenance-honesty
  - contract-doc-alignment
  - existing-tests-green
risk: high
tags:
  - targets
  - daily-summary
  - goals
  - release-blocker
approved_dependencies: []
requires_context:
  - docs/contracts/target-calculator.md
  - docs/contracts/daily-summary.md
  - docs/contracts/goals-target-reveal.md
  - docs/architecture/repo-layout.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-127: Daily Target Materialization Beyond The Goal-Creation Day (backend)

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- None to schedule. All referenced code is already merged: FTY-022/FTY-094/FTY-095
  (`targets` service, `daily_targets` derived + override columns), FTY-106
  (`goals.create_goal_with_target`), FTY-071/FTY-105/FTY-123 (`daily_summary`
  single + range read), and FTY-120 (the consolidated `_resolve_active_target_row`
  + `app/timeutils.py`).
- **Rebase note:** this edits `app/services/targets.py` and
  `app/services/daily_summary.py`. **FTY-140** also edits `daily_summary.py` (the
  range exception type). Whichever merges first, the second should **rebase on it**
  to avoid a churn conflict — the two changes are in different functions and do not
  semantically overlap, but they touch the same file.

## Outcome

Today the "calories/macros vs target" surface — the core of Today, Trends
adherence, and the Profile target panel — is **empty for every returning user
starting the day after onboarding.** A `DailyTarget` row is created in exactly one
place (`compute_daily_target`, `targets.py` ~130–178), whose only caller is
`create_goal_with_target` (`goals.py:211`) with `for_date=today`. There is **no
scheduler/Celery beat and no read-path materialization.** Every read does an exact
`DailyTarget.for_date == requested_day` match:

- `GET /api/users/{id}/target` → `get_active_target` → `_resolve_active_target` →
  `_resolve_active_target_row` (`targets.py` ~333–366): no exact-day row →
  `TargetNotFound` → **404**.
- `GET .../daily-summary` and `.../daily-summary/range` → `_resolve_target` /
  `_resolve_targets_by_day` (`daily_summary.py` ~336–381): no exact-day row →
  `None` → `target: null`.
- `PUT .../target/override` and `POST .../target/override/reset` also resolve via
  `_resolve_active_target`, so they **404 on any day after the creation day** —
  the user literally cannot adjust their target tomorrow.

Net effect: a target appears **only on the goal-creation day** and vanishes from
midnight (in the user's timezone) onward. This is the release blocker.

This story makes the active goal's target **present and adjustable for every day
within the goal's horizon**, without a scheduler and without changing the
`daily_targets` schema, by reading forward from the most recent stored row and
materialising a row on the override write path.

## Scope

Implement a **two-part fix** — a read-path carry-forward and a write-path
materialisation — that share the existing active-goal lookup. No migration, no new
column, no DTO shape change.

### 1. Read paths: carry-forward (no write in a GET)

Add a carry-forward resolver beside `_resolve_active_target_row` in `targets.py`
(it owns the targets domain and that predicate) that, for a requested `day`,
returns the **most recent active-goal `DailyTarget` row with `for_date <= day`**,
bounded to the active goal's horizon (see Non-Goals for the boundary rule), or
`None`. The dynamic-energy-balance model produces a **constant daily intake across
the goal horizon** (the calculator output depends on `for_date` only through the
whole-year `age_years`, and `N = target_date − start_date` is fixed), so the most
recent stored row is the correct value for every later in-horizon day. Wire it
into the three read paths:

- `targets.get_active_target` (behind `GET /target`): resolve via carry-forward;
  raise `TargetNotFound` only when there is genuinely no in-horizon row to carry
  (so cross-user / no-goal still fails closed 404, but "day after creation"
  returns the carried target).
- `daily_summary._resolve_target` (single-day): carry forward, then
  `build_target_read_model`; still `None` when nothing to carry (predates the
  first row, or past the horizon).
- `daily_summary._resolve_targets_by_day` (range): replace the exact-`for_date`
  bulk map with a **forward-fill** over the active goal's rows — fetch the active
  goal's rows with `for_date <= end` ascending, then for each requested day map to
  the most recent row at or before it, within the horizon. Days before the first
  row (and after the horizon) stay absent → `null`, preserving the
  no-target-is-not-zero distinction. Keep it one query + an in-Python fill (no N
  round-trips), matching the FTY-123 performance contract.

The read carry-forward returns the **real most-recent row's** read-model,
including any **in-force override** on it — honest per the documented override
lifetime ("an override persists … and is carried forward onto a new-date row").

### 2. Write paths: materialise then write

`set_target_override` and `reset_target_override` must succeed on a later
in-horizon day. When no exact-`for_date` row exists but the user has an active goal
covering `day`, **materialise the row via the existing `compute_daily_target`**
(which already creates the row, runs `_carry_forward_override` to bring any in-force
override onto the new date, and applies the fresh derived columns), then apply the
override/reset to that concrete row. When there is no active goal (or the day is
outside the horizon), keep failing closed with `TargetNotFound` → 404. This reuses
the already-tested materialisation/carry-forward machinery rather than inventing a
second writer.

### 3. Contract docs (the one big rock)

Update the three specs the behaviour change touches so docs and server agree:

- `docs/contracts/daily-summary.md` **No-target representation**: `target` is now
  present (carried forward) for in-horizon days after the first stored row; drop
  the "target was never computed for that date" clause and state the carry-forward
  rule. `null` remains for days before the goal's first row and after the horizon.
  Bump the version line with an FTY-127 note.
- `docs/contracts/target-calculator.md`: note that the override set/reset endpoints
  **materialise** an in-horizon day's row on demand (carrying the override forward)
  rather than 404ing; update the Errors row ("Override set/reset with no active
  goal or stored target for the day → 404") to "with **no active goal covering the
  day** → 404" (an active goal with no row yet now materialises and succeeds).
- `docs/contracts/goals-target-reveal.md`: correct the now-stale "Future days are
  unaffected — daily-summary keeps returning `null` for days without a stored row"
  line to reflect carry-forward within the horizon.

### 4. Tests (see Verification)

Cover "day after goal creation" for all three read surfaces, override-on-a-later
day, and the boundary cases, plus keep every existing target/daily-summary test
green.

## Non-Goals

- **No scheduler / Celery beat / nightly job.** Materialisation stays lazy
  (read-time carry-forward + write-time row creation); no background process is
  introduced.
- **No schema change, no migration, no new column.** Everything reuses the
  existing `daily_targets` columns and `compute_daily_target`.
- **No write inside a GET.** The read paths (`GET /target`, daily-summary single +
  range) must remain side-effect-free and idempotent. A pure materialise-on-read
  was **rejected** (see Planning Notes): the range read would write up to 366 rows
  per call (write amplification, breaks read-replica routing, an abuse vector).
- **Horizon boundary:** present a target for `day ∈ [first stored row's for_date,
  goal.target_date]` while the goal is active. Days **before** the first row →
  `null`/404 (predates the goal's materialised history, matches the current
  contract). Days **after** `target_date` → `null`/404: carrying the deficit
  number past the planned end would misrepresent a goal that should be in
  maintenance, so the user is steered to set a new goal rather than shown a stale
  deficit. (Decision flagged in Planning Notes.)
- **Do not change the calculator math, the derived numbers, the override safety
  bands, or the read-model DTO shape.** Only *when a row is present* changes.
- **Do not touch FTY-140's range-ordering exception** — that is its own story.

## Contracts

- **`docs/contracts/daily-summary.md`** — version bump; No-target representation
  rewritten for carry-forward (DTO shape unchanged).
- **`docs/contracts/target-calculator.md`** — override set/reset materialisation
  note + Errors-row wording.
- **`docs/contracts/goals-target-reveal.md`** — correct the stale "future days
  return null" side-effect note.

No request/response **shape** changes; this is a behavioural correction (a target
now appears where it was wrongly absent), so the single big rock is the contract
wording, not a new field.

## Security / Privacy

- **Authorization unchanged and still fail-closed.** Every path keeps running
  through `_authorize` first; the carry-forward and materialisation only run after
  ownership is confirmed, so a cross-user caller still sees an indistinguishable
  404 and learns nothing (no existence oracle). The horizon/active-goal checks are
  scoped to the owner's own goal.
- **No new input, surface, or external egress.** Pure internal read/compute over
  the owner's own rows.
- **Target numbers stay sensitive** — never logged; diagnostics use user/goal ids
  only, exactly as today.
- **No write amplification on reads** (the rejected materialise-on-read would have
  let an unbounded range GET create rows) — keeping GETs read-only is itself the
  safe choice.

## Acceptance Criteria

- For an active goal created on day D, **`GET /target`, `GET .../daily-summary`,
  and `GET .../daily-summary/range`** all return the goal's target (carried
  forward) for **every day in `[D, target_date]`** — not just day D. Before the
  first stored row and after `target_date` the target is absent (`404` / `null`),
  per the horizon rule.
- The carried target's read-model reports the correct effective/derived values and
  honest `derived | user` source, including a previously-set override carried
  forward.
- `PUT .../target/override` and `POST .../target/override/reset` **succeed on a
  later in-horizon day** (materialising the row + carrying any override forward),
  and the override is then reflected by all three read surfaces for that day.
- A user with **no active goal**, a **cross-user** caller, and a day **outside the
  horizon** all still fail closed (`404` for the target/override endpoints,
  `null` for daily-summary) — no existence oracle, no stack traces.
- The range read stays **one query + in-Python fill** (no per-day round trips),
  preserving the FTY-123 performance contract.
- The three contract docs match the implemented behaviour.
- **All existing target, override, daily-summary, and goal-reveal tests pass**
  (assertions adjusted only where they encoded the old "404/null on a later day"
  bug, with the change called out).
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New: day-after-creation reads.** With a goal created on day D (frozen clock or
  injected `for_date`), assert `GET /target`, daily-summary single, and
  daily-summary range all return the target for D+1, D+7, and an arbitrary
  in-horizon day — equal to the day-D derived value (constant-intake invariant).
- **New: override on a later day.** Set a calorie + a macro override on day D+5
  (no pre-existing row); assert it succeeds, the row is materialised, the override
  is carried forward, and the three read surfaces report `source: user` with the
  overridden effective value for D+5; then reset and assert it falls back to
  `derived`.
- **New: carried override across the rollover.** Set an override on day D, read day
  D+3, assert the carried read-model reports the override as in force (honest
  lifetime).
- **New: boundary cases.** Day before the first row → `null`/404; day after
  `target_date` → `null`/404; no active goal → `null`/404; cross-user → 404 (no
  oracle).
- **New: range forward-fill.** A range spanning before-first-row, in-horizon, and
  past-horizon days returns `null` outside the horizon and the carried target
  inside it, dense and oldest-first, in a single query.
- **Regression:** existing `test_target_service`, `test_target_override`,
  `test_active_target_resolver`, `test_daily_summary_api`, and
  `test_goal_target_reveal` stay green (with any old-bug assertions updated and
  noted).

## Planning Notes

- **Why carry-forward on reads + materialise on writes (the cleanest shape).** Two
  candidate shapes were considered:
  - *(a) Materialise-on-read* — compute and persist a row whenever a read misses.
    **Rejected:** it writes inside GETs (a semantic violation), and the range read
    would persist up to 366 rows per request — write amplification, an abuse
    vector, and incompatible with read-replica routing. It also buys nothing the
    constant-intake invariant doesn't already give for free.
  - *(b) Read-only carry-forward* — return the most recent in-horizon row. **Chosen
    for reads**, because the dynamic-energy-balance model yields a constant daily
    intake across the horizon, so the creation-day number is valid every later day;
    GETs stay side-effect-free and idempotent.
  The override **write** path legitimately needs a concrete row to hold the
  override, so it materialises via the existing, already-tested
  `compute_daily_target` (which runs `_carry_forward_override`). This is the
  minimal honest mechanism: reads never write; writes reuse one writer.
- **Constant-intake invariant (the correctness backbone).** `compute_daily_target`
  derives from the goal's fixed `(start_weight, target_weight, start_date,
  target_date)` snapshot; `for_date` enters only via whole-year `age_years`. Over a
  12-week horizon the derived target is constant except for the negligible, at-most
  one-increment birthday age tick — so carrying the most recent row forward is
  numerically faithful, not an approximation that drifts.
- **Post-horizon decision (flagged).** A target is carried only to `target_date`;
  beyond it the goal's planned trajectory is complete and the honest value is
  maintenance at goal weight, which the stored deficit row does **not** represent —
  so we return `null`/404 past the horizon and let the user set a new goal rather
  than display a stale deficit. This is a defensible product call; if dogfooding
  shows users want a rolling maintenance target after the horizon, that is a
  separate follow-up (it needs the calculator's `wT == w0 → TDEE` path, not just a
  read change).
- **No evidence research warranted.** The pace/macro/deficit science is already
  settled and cited in `target-calculator.md` / `goals-target-reveal.md`; this
  story changes *when a target is shown*, not any health number, so no new
  evidence lookup is needed.

## Readiness Sanity Pass

- **Product decision gaps:** the two open judgment calls — read-vs-write
  materialisation strategy and the post-horizon boundary — are both decided above
  with rationale. No further product decision blocks implementation.
- **Cross-lane impact:** primary backend-core, **no touched lanes.** The contract
  doc edits ride along in the same lane (docs are non-serializing). **Single
  boundary; exactly one big rock** (the public contract wording change across three
  related specs). **No schema migration / new table** (reuses existing columns and
  `compute_daily_target`), **no new untrusted-input trust boundary** (pure internal
  read/compute over the owner's own rows). Stays one story.
- **Size:** `review_focus` = 5 (at the ceiling, not over); `requires_context` = 6
  (under 8). One story.
- **Security/privacy risk:** medium-to-high blast radius because it sits on the
  core target surface, but the change *removes* a correctness defect without adding
  input, surface, or egress; authorization stays fail-closed and is exercised by
  negative tests; reads stay write-free. Tagged `risk: high` so the steward routes
  the strongest model.
- **Verification path:** `make verify` + new day-after-creation, override-on-later
  day, carried-override, boundary, and range-fill tests + existing target /
  daily-summary / goal-reveal suites green.
- **Assumptions safe for autonomy:** yes — fully specified mechanism, the
  constant-intake invariant pinned, every boundary and not-found policy named, and
  no migration / external provider / UI. `ready_with_notes` for the two flagged
  (non-blocking) decisions.
</content>
</invoke>
