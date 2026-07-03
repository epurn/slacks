# Contract: Goals + Target Reveal

## Purpose

Turn the inputs onboarding actually collects — a **goal direction** (lose /
maintain / gain) and an evidence-based **pace preset** — into a persisted,
user-owned active goal and an **authoritative computed daily calorie target
returned with its provenance**. This is the single HTTP route that sits between
onboarding's inputs and the deterministic target calculator: it owns the
pace→trajectory derivation, calls the existing `compute_daily_target` (FTY-022)
for the math, and persists today's `daily_targets` row as a side effect so the
target reveal, the Profile, and `GET daily-summary` immediately have a real
number.

It deliberately excludes the calculator math itself (see
[`target-calculator.md`](target-calculator.md), consumed unchanged), macro
targets, the manual override lifecycle (FTY-095, covered in the calculator
contract), per-day target backfill, and any mobile UI.

## Owner

backend-core / contracts lane (`backend/app/routers/goals.py`,
`backend/app/services/goals.py`, `backend/app/schemas/goals.py`,
`backend/app/enums.py`). Reuses the FTY-022 `goals` / `daily_targets` schema and
`compute_daily_target` without modification.

## Version

2. v1 introduced the write (`POST /goal`) in FTY-106; v2 adds the read-only
`GET /goal` active-goal-direction read model in FTY-189 (additive, no change to
the write path).

## Inputs

### `POST /api/users/{user_id}/goal`

Authenticated (bearer token); the `{user_id}` path is explicit and checked on
every access. Request body (`GoalTargetRequest`, `extra="forbid"`):

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `direction` | `loss \| gain \| maintain` | yes | The goal direction (`GoalDirection`). |
| `pace` | `gentle \| steady \| faster` | for `loss`/`gain` | The pace preset (`PacePreset`); **required** for a directional goal, **ignored** for `maintain`. `faster` is loss-only. |
| `start_weight_kg` | float (kg, `0 < x ≤ 1000`) | no | Trajectory origin; **defaults to the profile's stored `weight_kg`** when omitted. |
| `start_date` | date | no | **Defaults to today in the profile timezone** when omitted. |

Free-form numeric rates are **not** accepted — only the enumerated safe presets —
so an unsafe rate is structurally impossible at the boundary.

### `GET /api/users/{user_id}/goal`

Authenticated (bearer token); the `{user_id}` path is explicit and checked on
every access. No request body. Returns the **direction** of the caller's current
active goal so a returning user's Trends weight delta can be coloured by progress
toward the goal after a cold launch — the only authoritative source of the
direction, since neither the daily-summary nor the target read-model carries it.

A goal has no stored `direction` column; the direction is **recovered** from the
persisted trajectory: `target_weight_kg > start_weight_kg` → `gain`,
`target_weight_kg < start_weight_kg` → `loss`, equal → `maintain` (the exact
`maintain` path always yields `target == start`).

### Pace presets and the evidence-based bands

Each preset maps to a weekly rate as a fraction of `start_weight_kg`:

| Direction | `gentle` | `steady` (default) | `faster` |
| --- | --- | --- | --- |
| `loss` | 0.25 %/wk | **0.5 %/wk** | 1 %/wk (cap) |
| `gain` | 0.125 %/wk | **0.25 %/wk** | — (not offered) |
| `maintain` | — | — | — |

`steady` is the recommended default the UI pre-selects. The bands are
evidence-grounded (overriding the generic "faster is better" default): a safe,
lean-mass-sparing loss rate is ~0.5–1 %/wk (≈ the NIH/NIDDK ~500–1000 kcal/day
deficit); above ~1.5 %/wk measurably increases lean-mass loss, so no loss preset
exceeds 1 %/wk. Lean gain is far slower (~0.125–0.25 %/wk), so gain offers no
`faster`. The calculator's 1200/1500 kcal floor and 4000 ceiling remain the hard
safety backstop.

### Pace → trajectory derivation (this contract owns it)

Pure and deterministic, over a fixed **planning horizon** `H = 12 weeks`
(`PLANNING_HORIZON_WEEKS`, the load-bearing product constant that scales a rate
into a destination):

```
rate_kg_per_week = pace_fraction × start_weight_kg
target_weight_kg = start_weight_kg − rate_kg_per_week × H      (loss)
                 = start_weight_kg + rate_kg_per_week × H      (gain)
                 = start_weight_kg                              (maintain)
target_date      = start_date + H
```

`maintain` yields `target_weight == start_weight` (the calculator's
`wT == w0 → TDEE` path). The horizon guarantees `target_date > start_date`. Same
inputs → identical persisted goal and target.

## Outputs

`201 Created` with `GoalTargetResponse`:

- `goal` — the `GoalDTO` for the created active goal (the persisted trajectory).
- `target` — `RevealedTarget`: `calories` (the derived
  `daily_calorie_target_kcal`), `rmr_kcal`, `tdee_kcal`, `direction`, and
  `clamped`.
- `provenance` — `{ source: "derived", basis: "goal_and_metrics" }`. `source` is
  the shared `TargetSource` discriminator a manual override (FTY-095) also uses; a
  freshly derived target is always `derived`. The human line ("from your goal +
  your metrics") is the client's; the API carries the stable tokens.
- `clamp` — `{ clamped: bool, reason: "clamped_to_floor" | "clamped_to_ceiling" |
  null }`. When the derived plan was clamped to a safety boundary the returned
  `calories` is that boundary value, honestly flagged — not presented as the
  achievable plan.

### `GET /api/users/{user_id}/goal`

`200 OK` with `ActiveGoalDirection`: `{ "direction": "loss" | "gain" | "maintain" }`
— the single recovered direction, nothing else. No weight, RMR, TDEE, or target
number is exposed. When the caller has no active goal, the response is `404`
(fail closed; indistinguishable from a cross-user attempt — no existence oracle).

### Side effects

- Creating a goal **deactivates any prior active goal** (`is_active = False`) and
  inserts the new one active — one active goal per user — in a **single committed
  transaction** with the target write.
- Today's `daily_targets` row is computed via `compute_daily_target` and
  persisted, so `GET daily-summary` for that day returns a non-`null` target
  equal to the revealed value. Later in-horizon days need no stored row: the
  daily-summary and target reads **carry this value forward** to every day up to
  `target_date` (the daily target is constant across the horizon), so a returning
  user keeps a target every day — see `target-calculator.md` (Target resolution)
  and `daily-summary.md`. Days past `target_date` stay `null`.

## Validation

- `direction` / `pace` outside their enums, `start_weight_kg` out of range, or an
  unknown field → Pydantic `422`.
- `loss`/`gain` without a `pace`, or `faster` for `gain` → `422`.
- A computed `target_date <= start_date` is impossible (positive horizon) and the
  calculator's positive-horizon rule still guards the boundary.

## Authorization

Bearer token via `CurrentUser`; the explicit `{user_id}` path is checked on every
access and **fails closed `404`** on any cross-user attempt (no existence
oracle), exactly as `profile` / `daily_summary` / `targets` do. The service-level
`GoalForbidden` enforces ownership before any read or mutation.

## Privacy and Retention

Weight, the derived RMR/TDEE, and the computed target are sensitive body data and
are **never logged** — only non-sensitive labels (e.g. the environment) appear in
diagnostics. The goal and its derived target follow the FTY-022 retention rule:
they live until the goal is replaced/edited or the account is deleted
(`ON DELETE CASCADE`).

## Errors

| Condition | Status |
| --- | --- |
| Cross-user / unowned `{user_id}` | `404` (fail closed, no oracle) |
| `GET /goal` when the caller has no active goal | `404` (fail closed, no oracle) |
| Incomplete profile (no resolvable weight, missing height/birth year, or formula still the unspecified `mifflin_st_jeor` family default) | `409` (complete the profile first; non-leaking) |
| `loss`/`gain` without a pace, `faster` for `gain` | `422` |
| Malformed body (bad enum, out-of-range weight, unknown field, free-form rate) | `422` |
| Missing/invalid bearer token | `401` |
