---
id: FTY-106
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
risk: high
tags:
  - backend
  - goals
  - target
  - target-reveal
  - provenance
  - onboarding
approved_dependencies:
  - FTY-020
  - FTY-021
  - FTY-022
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/target-calculator.md
  - docs/contracts/identity-and-profile.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
review_focus:
  - pace-band-vocabulary-and-evidence-defaults
  - pace-to-trajectory-derivation-determinism
  - goal-ownership-and-active-goal-replacement
  - target-provenance-and-clamp-surfacing
  - router-registration-and-contract-shape
autonomous: true
---

# FTY-106: Goals + Target-Reveal Endpoint (Direction + Pace → Goal → Computed Target with Provenance)

## State

ready_with_notes

> **Gating note (read before promoting to `ready`):** this is the **backend-core**
> prerequisite the goal-led onboarding (FTY-103) is blocked on. FTY-103's front
> matter and Dependencies call this prerequisite **"FTY-104"** — that was a
> placeholder id; **this story (FTY-106) is that prerequisite**, and FTY-103's
> dependency pointer must be repointed from `FTY-104` to `FTY-106` when this is
> promoted (see Readiness Sanity Pass). FTY-022 (merged) shipped the deterministic
> calculator (`compute_daily_target`) and the `goals` / `daily_targets` tables, but
> **none of it is reachable over HTTP**: `main.py` registers no goals/targets
> router, `compute_daily_target` requires a pre-existing `goal_id` that only tests
> create directly, and `GET daily-summary` merely *reads* a stored `daily_targets`
> row (or returns `null`). This story adds the missing route. Held at
> `ready_with_notes` (not `ready`) only because four bounded product decisions —
> the exact pace-preset bands, the pace→trajectory planning horizon, the provenance
> field shape (to align with the not-yet-written FTY-095 override), and the
> clamp-surfacing copy — should be confirmed first; each has a recommended answer
> below.

## Lane

backend-core (with a `contracts` big rock: one new public endpoint contract).

## Dependencies

- Builds on **merged FTY-020** (auth + user identity; `CurrentUser`, object-level
  ownership pattern), **merged FTY-021** (profile capture — `weight_kg`,
  `height_m`, `birth_year`, and the concrete `metabolic_formula` variant the
  calculator needs), and **merged FTY-022** (the deterministic
  `compute_daily_target` service, the `goals` / `daily_targets` schema, and the
  `GoalCreateRequest` / `GoalDTO` / `DailyTargetDTO` DTOs). All reused; **no new
  table, no migration** in this story.

## Related

<!-- Reverse reference only — NOT a scheduling dependency (this story BLOCKS
     FTY-103, it does not depend on it). Kept out of Dependencies so the parser
     does not read it as a blocker. -->

- **Blocks FTY-103** (mobile goal-led onboarding): FTY-103 step 1 (goal + pace)
  and step 3 (target reveal) consume this endpoint. FTY-103 must not be authored
  until this merges.

## Outcome

A single authenticated HTTP route turns the onboarding inputs the app actually
collects — a **goal direction** (lose / maintain / gain) and an **evidence-based
pace preset** — into a persisted user-owned goal and an **authoritative computed
daily calorie target returned with its provenance**, so the FTY-103 target reveal
("└ from your goal + your metrics") and the Profile have a real number to show.
Today's `daily_targets` row is persisted as a side effect, so the existing
`GET daily-summary` (FTY-071) immediately returns a non-`null` target for the day
the goal is created, closing the "opens to a `null` target" gap.

The endpoint owns the one piece of math that sits between onboarding's inputs and
FTY-022's calculator: converting **direction + pace + start weight** into the
concrete `(start_weight, target_weight, start_date, target_date)` trajectory the
calculator consumes. That conversion, the pace vocabulary, and the safe-pace
bands are this contract's responsibility — not the client's, and not FTY-022's.

## Scope

- **New router, registered in `app/main.py`.** Add `app/routers/goals.py`
  (`prefix="/api/users"`, `tags=["goals"]`) following the established
  `routers/profile.py` / `routers/daily_summary.py` conventions: explicit
  `{user_id}` path, `CurrentUser` dependency, `get_session` dependency, fail-closed
  `404` on cross-user / missing (no existence oracle). **Wire
  `app.include_router(goals.router)` into `create_app`** — without this the route
  does not exist, which is the entire reason FTY-103 is blocked.

- **Endpoint: create/replace the active goal from direction + pace, then compute
  and return the target.** Recommended shape:
  `POST /api/users/{user_id}/goal`. Request DTO (new, `extra="forbid"`):
  - `direction`: `loss | gain | maintain` (the existing `GoalDirection` enum).
  - `pace`: a **preset enum** (see pace bands below), required for `loss`/`gain`,
    **ignored/omitted for `maintain`**. Free-form numeric rates are **not**
    accepted — only the enumerated safe presets — so an unsafe rate is structurally
    impossible at the API boundary.
  - `start_weight_kg` (optional): canonical kg; **defaults to the profile's stored
    `weight_kg`** when omitted (matching `GoalCreateRequest`'s "omit to default to
    current weight" semantics). Reject with a clear error if both are absent.
  - `start_date` (optional): defaults to **today in the profile timezone**.
  - "Create/update" semantics: a user has **one active goal**; creating a new goal
    **deactivates any prior `is_active` goal** (sets `is_active=False`) and inserts
    the new one active, so onboarding re-entry or a later goal change replaces
    rather than accumulates. Keep this a single committed transaction.

- **Pace → trajectory derivation (this contract owns it).** Map the chosen
  `direction` + `pace` preset to a weekly rate as a fraction of `start_weight_kg`,
  then derive the goal's destination over a **documented fixed planning horizon**
  `H` (recommended **12 weeks**, a constant in `app/estimator/constants.py` or the
  goals service, not a request field):
  - `rate_kg_per_week = pace_fraction × start_weight_kg`
  - `target_weight_kg = start_weight_kg − rate_kg_per_week × H_weeks` (loss);
    `+` for gain; **`maintain` → `target_weight_kg = start_weight_kg`** (the
    calculator's documented `wT == w0 → TDEE` path).
  - `target_date = start_date + H_weeks` (positive horizon, satisfying the
    calculator's `target_date > start_date` rule).
  The derivation must be **pure and deterministic** (same inputs → same goal),
  documented in the contract, and unit-tested. The planning horizon is the
  load-bearing product choice (it scales the rate into a destination); it is
  flagged for confirmation in the Readiness Sanity Pass.

- **Compute + persist + return the target.** After persisting the goal, call the
  **existing** `compute_daily_target(session, owner_id, goal.id, current_user,
  for_date=today)` (FTY-022) — do **not** re-implement the NIDDK math. Return a
  combined response DTO:
  - `goal`: the `GoalDTO` for the created active goal.
  - `target`: `daily_calorie_target_kcal` (as `calories`), plus `rmr_kcal`,
    `tdee_kcal`, `direction`, and `clamped` from the computed `DailyTarget`.
  - `provenance`: a small object marking the number as **derived** — recommended
    `source: "derived"` with a stable `basis: "goal_and_metrics"` (the human line
    "from your goal + your metrics" is the client's; the API carries the stable
    token). Design this field as the **shared provenance shape** a future manual
    override (FTY-095) extends with `source: "manual_override"` — see Non-Goals.
  - `clamp`: surface the calculator's `clamped` honestly (boolean + a stable
    reason token, e.g. `clamped_to_floor` / `clamped_to_ceiling`) so the reveal can
    show a calm note instead of presenting a clamped number as the plan.

- **Validation / error mapping** (render service exceptions as HTTP):
  - `GoalForbidden` (cross-user / unowned) → `404` (fail closed, no oracle).
  - `IncompleteProfileError` (missing height/birth year, formula still on the
    unspecified `mifflin_st_jeor` placeholder, or no stored `weight_kg` and no
    `start_weight_kg` supplied) → a clear `4xx` (recommended `409`/`422`) telling
    the client the profile must be completed first — onboarding writes profile
    (step 2) before calling this.
  - Pydantic boundary `ValidationError` (bad direction/pace, out-of-range weight,
    `target_date <= start_date`) → `422`.

## Non-Goals

- **The mobile onboarding UI / routing** (FTY-103) — this story is backend only;
  no mobile code.
- **The target calculator math** (merged FTY-022) — consumed via
  `compute_daily_target`, never re-derived.
- **Macro targets** (FTY-094 / FTY-105) — out of the FTY-022 calculator contract;
  this returns the calorie target only.
- **The manual target override** (FTY-095, not yet written) — this story does
  **not** implement override. It only **aligns the provenance field shape** so
  FTY-095 can extend `source` from `"derived"` to `"manual_override"` without a
  breaking change. If FTY-095's field names are not yet settled, this story's
  `provenance` shape is the proposal FTY-095 should adopt.
- **Per-day target generation / backfill.** This persists *today's*
  `daily_targets` row (so the reveal and Today work on day one). Generating a
  target row for arbitrary future days (so `daily-summary` is non-`null` every
  day) is a known follow-up, not this story — `daily-summary` keeps returning
  `null` for days without a stored row, per its FTY-071 contract.
- **Design tokens** (FTY-097) — not a backend concern.

## Contracts

- **Introduces one new public contract:** the goals + target-reveal endpoint
  (`POST /api/users/{user_id}/goal`). Document it as a new
  `docs/contracts/goals-target-reveal.md` (or an addition to
  `target-calculator.md`, owner's choice — recommended a new sibling doc that
  *references* `target-calculator.md` for the math and clamp semantics it surfaces
  rather than restating them). The contract must specify: the request shape
  (direction + pace preset + optional start weight/date), the **pace-preset
  vocabulary and the evidence-based bands**, the **pace→trajectory derivation and
  the planning-horizon constant**, the combined response (goal + target +
  provenance + clamp), the authorization/fail-closed rule, and the error table.
- Reuses, unchanged: `GoalDirection` / `MetabolicFormula` enums, the
  `goals` / `daily_targets` schema, `compute_daily_target`, and the FTY-071
  `daily-summary` read path (which now finds a row).

## Security / Privacy

- **Authenticated, user-owned write.** Bearer token via `CurrentUser`; the
  explicit `{user_id}` path is checked on every access and fails closed `404` on
  any cross-user attempt (no existence oracle), exactly as `profile` /
  `daily_summary` do and as `compute_daily_target`'s `_authorize` /
  `GoalForbidden` already enforce at the service layer.
- **No new untrusted-input trust boundary:** no vision/image, fetched pages, OCR,
  or uploads; inputs are a constrained enum + bounded numerics. Pace is restricted
  to safe presets at the boundary; the calculator's 1200/1500 kcal floor (and 4000
  ceiling) remain the hard safety backstop that clamps and flags an over-aggressive
  derived plan.
- **Sensitive body data** (weight, derived RMR/TDEE/target) is processed but
  **never logged** — mirror the `daily-summary` no-log-personal-numbers rule. Log
  only non-sensitive labels (e.g. the environment), never the metrics or the
  computed target.
- High risk: an authenticated write that introduces a new public contract and
  produces the number the whole app's guidance is anchored to. A wrong pace band,
  a non-deterministic trajectory, or a missing ownership check each have real cost
  — hence the evidence-grounded bands, the determinism requirement, and the
  fail-closed tests below.

## Acceptance Criteria

- `POST /api/users/{user_id}/goal` exists and is registered in `main.py`; an
  authenticated owner can create a goal from `direction` + `pace` and receives a
  `200`/`201` with `goal`, `target` (calories + rmr/tdee + direction + clamped),
  `provenance` (`source: "derived"`), and `clamp` status.
- **Pace presets** are an enum with evidence-based bands (see Planning Notes):
  loss offers gentle/steady/faster with **steady (~0.5%/wk) as the default** and no
  preset above ~1%/wk; gain offers correspondingly gentler presets; **maintain
  takes no pace**. Free-form numeric rates are rejected.
- The **pace→trajectory derivation is deterministic**: identical inputs produce an
  identical persisted goal `(start_weight, target_weight, start_date, target_date)`
  and target; `maintain` yields `target_weight == start_weight` and the target
  equals TDEE.
- `start_weight_kg` **defaults to the profile's stored `weight_kg`** when omitted;
  `start_date` defaults to **today in the profile timezone**.
- Creating a goal **deactivates any prior active goal** (one active goal per user)
  in a single transaction.
- The computed daily target is **persisted as today's `daily_targets` row**, so a
  subsequent `GET daily-summary` for that day returns a **non-`null`** target.
- **Authorization fails closed:** a caller targeting another user's `{user_id}`
  gets `404` and learns nothing; an incomplete profile (missing height/birth year,
  unspecified formula variant, or no weight available) returns a clear, non-leaking
  error rather than a bogus target.
- The calculator's **`clamped` case is surfaced honestly** in `target.clamped` +
  `clamp` reason; the returned number is the safe boundary, flagged, not presented
  as the achievable plan.
- No weight, RMR, TDEE, or target value appears in logs.
- `make verify` (and `cd backend && ./verify.sh`) passes; the contract doc is
  added.

## Verification

- Backend tests per `docs/standards/testing-standards.md` (root `make verify` /
  `cd backend && ./verify.sh`):
  - **Goal-from-direction+pace:** each direction + each pace preset persists a goal
    with the expected derived trajectory; `maintain` ignores pace and yields
    `target_weight == start_weight`.
  - **Pace-band validation:** the default is the steady (~0.5%/wk) preset; no
    accepted preset exceeds ~1%/wk for loss; gain presets are gentler; an unknown
    pace / free-form rate / `loss` without a pace is rejected `422`.
  - **Determinism:** the same request produces byte-identical goal + target across
    repeated calls (modulo timestamps/ids); the horizon constant is exercised.
  - **Target computation + provenance:** the response carries the calculator's
    `daily_calorie_target_kcal`, RMR/TDEE, direction, and a `provenance.source ==
    "derived"`; the value matches a direct `compute_daily_target` computation for
    the same goal.
  - **Start-weight / start-date defaulting:** omitting `start_weight_kg` reads the
    profile `weight_kg`; omitting `start_date` uses today in the profile timezone;
    an explicit value pins the plan.
  - **Active-goal replacement:** a second create deactivates the first; exactly one
    `is_active` goal remains.
  - **Clamp behavior:** an over-aggressive derived plan (e.g. faster pace on a low
    start weight) returns `clamped == true` with the floor reason and the floor
    value, not a sub-floor number.
  - **Authorization (fail closed):** cross-user `{user_id}` → `404`, no oracle; an
    incomplete profile → the documented `4xx`, not a bogus target.
  - **daily-summary integration:** after a create, `GET daily-summary` for that day
    returns a non-`null` target equal to the revealed value.
  - **No-log assertion:** a log spy captures no weight / RMR / TDEE / target value.
  - **Router registration:** the route is mounted on the app built by
    `create_app` (a request reaches it, not `404`-by-absence).

## Planning Notes

- **Why this story exists / the boundary split.** The FTY-103 premise "onboarding
  consumes an existing endpoint" was factually wrong (verified against
  `app/main.py`, `app/services/targets.py`, `app/routers/daily_summary.py`): the
  calculator and schema are merged but **unreachable over HTTP**. The goal-led
  feature therefore spans two serializing boundaries — **mobile-core** (FTY-103)
  and **backend-core + a new public contract** (this story). Per the scope
  guardrail those cannot be one story, so the backend boundary is pulled out here
  and FTY-103 depends on it.
- **Evidence-based pace bands (research-grounded; overrides "faster is better").**
  A safe, lean-mass-sparing weight-loss rate is **~0.5–1% of body weight per week**
  (≈ the NIH/NIDDK ~500–1000 kcal/day deficit). A gradual rate (~0.5–1 lb/wk)
  preserves more lean mass and provokes less metabolic adaptation than rapid loss;
  **>~1.5%/wk measurably increases lean-mass loss**, and 20–40% of weight lost
  under aggressive restriction can be lean tissue. Lean **gain** is far slower
  (~0.25–0.5 lb/wk). This **overrides** the "faster is better" default a generic
  diet app would ship. Recommended presets (confirm in the contract):
  - **Loss:** gentle ≈ 0.25%/wk · **steady ≈ 0.5%/wk (DEFAULT)** · faster ≈
    0.75–1%/wk (cap; never the default).
  - **Gain:** gentle ≈ 0.125%/wk · **steady ≈ 0.25%/wk (DEFAULT)** (correspondingly
    gentler).
  - **Maintain:** no pace.
  The hard backstop remains FTY-022's 1200/1500 kcal floor / 4000 ceiling, which
  clamps and flags an over-aggressive derived plan. Sources:
  [Precision Nutrition — realistic rates of fat loss and muscle gain](https://www.precisionnutrition.com/rates-of-fat-loss-and-muscle-gain),
  [Shift to Strength — evidence-based sustainable weight loss](https://www.shifttostrength.com/post/sustainable-weight-loss-evidence-based-strategies).
- **Planning horizon is the load-bearing math choice.** Because onboarding captures
  pace (a rate) but not a goal weight, the endpoint synthesizes a destination over
  a fixed horizon. The horizon scales the rate into `target_weight` and
  `target_date`; the derived daily target reflects the chosen pace. 12 weeks is a
  reasonable, defensible default; document it as a named constant and confirm
  before promotion.
- **Don't re-implement the calculator.** `compute_daily_target` already authorizes,
  computes, clamps, and persists with the full inputs/assumptions snapshot. This
  story builds the goal and calls it; the only new math is the pure
  pace→trajectory derivation.
- **Provenance forward-compat with FTY-095.** FTY-095 (manual override) is not yet
  written. Define `provenance.source` as the shared discriminator now
  (`"derived"`), so FTY-095 adds `"manual_override"` without breaking this
  contract. Treat this story's `provenance`/`clamp` shape as the proposal FTY-095
  should adopt; if FTY-095 lands first, match its names instead.
- **FTY-103 id repoint.** FTY-103 references its backend prerequisite as
  "FTY-104"; that id was a placeholder. When this story is scheduled, repoint
  FTY-103's `approved_dependencies` / Dependencies / gating note from `FTY-104` to
  `FTY-106` so the DAG link is real.

## Readiness Sanity Pass

- **Product decision gaps to resolve before promotion (each has a recommended
  answer):** (1) the exact pace-preset bands and labels — recommended
  evidence-based set above, default steady ~0.5%/wk loss / ~0.25%/wk gain; (2) the
  pace→trajectory **planning horizon** — recommended 12 weeks as a documented
  constant; (3) the `provenance` / `clamp` field shape — recommended
  `source: "derived"` designed to be FTY-095-extensible; (4) the HTTP method/path
  and incomplete-profile status code — recommended `POST
  /api/users/{user_id}/goal` and `409`/`422`. All four are bounded and confirmable;
  none blocks authoring once chosen.
- **Cross-lane impact / sizing decision (the load-bearing call):** single
  serializing code boundary — **backend-core** (the router + goals service + the
  pure derivation). Exactly **one big rock**: a new public contract (the endpoint).
  **No second code lane** (the `contracts` doc/DTOs are authored in the same
  backend codebase and counted as that one big rock), **no schema migration / new
  table** (reuses FTY-022's `goals` / `daily_targets`), **no new untrusted-input
  trust boundary** (authenticated owner write, constrained enum input). Size:
  `review_focus` = 5 (at the ceiling), `requires_context` = 5 (under 8). One
  boundary + one big rock, at most one limit at its ceiling → **kept as one
  story**, not split.
- **Security/privacy risk:** high — authenticated user-owned write that mints the
  app's anchor number; fail-closed `404` ownership (service-level `GoalForbidden`
  already enforces it), pace constrained to safe presets at the boundary with the
  calculator floor/ceiling as the hard backstop, and weight/RMR/TDEE/target never
  logged. No new trust boundary, no provider secret, no credential handling.
- **Verification path:** backend `make verify` / `cd backend && ./verify.sh` —
  goal-from-pace, pace-band validation, derivation determinism, target+provenance,
  defaulting, active-goal replacement, clamp, fail-closed authorization, the
  daily-summary integration round-trip, the no-log assertion, and router
  registration.
- **Evidence basis captured:** pace bands grounded in the ~0.5–1%/wk
  safe-loss-rate evidence (NIH/NIDDK deficit guidance; >~1.5%/wk harms lean mass;
  gain ~0.25–0.5 lb/wk), recorded in Planning Notes with sources, overriding the
  generic "faster is better" default — and this is the authoritative story that
  owns those bands.
- **Assumptions safe for autonomy:** yes for the backend slice — all dependencies
  (FTY-020/021/022) are merged, the calculator/schema exist, and the four gaps have
  recommended answers. Held at `ready_with_notes` pending confirmation of those
  four; to promote to `ready`, confirm them and **repoint FTY-103's dependency
  from FTY-104 to FTY-106**.
