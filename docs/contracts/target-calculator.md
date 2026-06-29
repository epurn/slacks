# Contract: Target Calculator

## Purpose

Turn a user's profile and weight goal into a daily calorie target through pure,
deterministic math — no LLM, no external input. This contract covers three
things:

1. the `goals` and `daily_targets` persistence schema and their migration
   (FTY-022 owns these tables);
2. the calculator's input contract (profile fields + goal trajectory) and output
   contract (RMR, TDEE, the daily calorie target, the derived protein/carb/fat
   gram targets, and the assumptions snapshot), which are estimator contracts;
3. the documented assumptions behind every number (baseline activity multiplier,
   the NIDDK-style dynamic model parameters, rounding, the safety floor/ceiling,
   and the evidence-based macro default ratios).

It deliberately excludes logging exercise burn into the daily allowance, adaptive
calibration from observed weight trend, profile capture UI (FTY-021), and the
identity/profile model (FTY-020).

## Owner

estimator / contracts / backend-core lane (`backend/app/estimator/`,
`backend/app/schemas/targets.py`, `backend/app/schemas/goals.py`,
`backend/app/models/targets.py`, `backend/app/services/targets.py`,
`backend/alembic/`).

## Version

4 (introduced in FTY-022; macro targets added in FTY-094; manual calorie/macro
override + reset with derived-vs-overridden provenance added in FTY-095;
read-path carry-forward within the goal horizon added in FTY-127/FTY-103).

## Inputs

### Persistence

The `0002` migration creates two user-owned tables:

- **`goals`** — a weight goal. Columns: `id` (UUID, PK), `user_id` (UUID, FK →
  `users.id`, `ON DELETE CASCADE`), `start_weight_kg` (float), `start_date`
  (date), `target_weight_kg` (float), `target_date` (date), `is_active` (bool),
  `created_at`, `updated_at`. The start snapshot is stored so the planned
  trajectory is deterministic and does not drift as measured weight changes.
- **`daily_targets`** — a daily target row carrying both the derived value and an
  optional user override. Columns:
  - **Identity / ownership**: `id` (UUID, PK), `user_id` (UUID, FK → `users.id`,
    `ON DELETE CASCADE`), `goal_id` (UUID, FK → `goals.id`, `ON DELETE CASCADE`),
    `for_date` (date), `created_at`.
  - **Derived** (the calculator output; source of truth for what a reset
    restores): `rmr_kcal` (float), `tdee_kcal` (float),
    `daily_calorie_target_kcal` (int), `clamped` (bool), `protein_target_g` (int),
    `carbs_target_g` (int), `fat_target_g` (int), `macros_clamped` (bool),
    `inputs` (JSON), `assumptions` (JSON). The macro `*_target_g` / `macros_clamped`
    columns persist the FTY-094 derivation (added by FTY-095's `0014` migration —
    FTY-094 derived these in the calculator but did not store them) so the
    read-model reports the derived macro value straight from the row.
  - **User override** (FTY-095; `NULL` while the target is derived):
    `override_calorie_target_kcal` (int, nullable),
    `override_protein_target_g` (int, nullable),
    `override_carbs_target_g` (int, nullable),
    `override_fat_target_g` (int, nullable), and `override_set_at` (timezone-aware
    DateTime, nullable) — when the override was last set; a bare timestamp for
    provenance/audit, carrying no PII.

Canonical units only: weight in kilograms, energy in kcal.

### Calculator input (`TargetCalculatorInput`)

`metabolic_formula` (`mifflin_st_jeor_plus5` | `mifflin_st_jeor_minus161` — the
two computable variants; the unspecified `mifflin_st_jeor` family default is
rejected as an incomplete profile), `height_m` (m), `age_years` (int),
`start_weight_kg`, `target_weight_kg` (kg), `start_date`, `target_date`. The
profile supplies height, age (derived from `birth_year`), and the formula
preference; the goal supplies the trajectory.

## Outputs

### Calculator output (`TargetCalculatorResult`)

`rmr_kcal`, `tdee_kcal`, `daily_calorie_target_kcal`, `direction`
(`loss` | `gain` | `maintain`), `horizon_days`, `clamped` (true when the raw
target was outside the safety band and clamped to the boundary), the three macro
targets `protein_target_g` / `carbs_target_g` / `fat_target_g` (whole grams),
`macros_clamped` (the macro analogue of `clamped`; see below), and an
`assumptions` snapshot. All fields are additive; existing consumers see no change
to the calorie/RMR/TDEE numbers.

### The math

1. **RMR — Mifflin-St Jeor.** `RMR = 10·weight_kg + 6.25·height_cm − 5·age + s`,
   with the sex-dependent constant `s = +5` (`mifflin_st_jeor_plus5`) or
   `s = −161` (`mifflin_st_jeor_minus161`) chosen by `metabolic_formula`. Height
   is converted from canonical metres to centimetres internally.
2. **TDEE.** `TDEE = RMR × 1.2`, the baseline (sedentary) activity multiplier.
   Logged exercise burn is added to the day's allowance **separately** by the
   exercise calculator (FTY-043, `exercise-burn.md`) and is deliberately excluded
   here. To avoid double-counting the resting energy this multiplier already
   includes, that calculator credits only the energy **above rest** (the `MET − 1`
   net convention).
3. **Daily target — single-compartment, NIDDK-style dynamic energy balance.**
   Rather than dividing the total energy deficit by the horizon (which ignores
   that expenditure falls with body mass), the model linearizes the NIDDK/Hall
   insight that expenditure tracks current mass. With `m` = activity multiplier,
   `b` = 10 kcal/kg/day (the Mifflin mass coefficient), `ρ` = 7700 kcal/kg
   (energy density of weight change), `a` = the weight-independent part of RMR,
   and `N` = horizon days, the constant daily intake that moves the user from
   `w0` to `wT` in `N` days is the closed-form solution of
   `ρ·dw/dt = I − m·(a + b·w)`:

   ```
   k  = m·b/ρ
   E  = exp(−k·N)
   w* = (wT − w0·E) / (1 − E)
   I  = m·(a + b·w*)
   ```

   This is a deterministic linearization of the NIDDK Body Weight Planner, not
   the full multi-compartment Hall model. Limits: `wT == w0` returns exactly
   TDEE; a longer horizon gives a gentler target approaching goal-weight
   maintenance; an impossibly short horizon gives an extreme target that the
   safety band then refuses.

### Macro targets (FTY-094)

Alongside the calorie target the calculator derives **protein, carbohydrate, and
fat targets in whole grams**, computed against the **already safety-clamped**
`daily_calorie_target_kcal` (so the macros are consistent with the number the
user is shown) in this fixed, evidence-based priority order — protein first, then
the fat floor, then carbohydrate as the remainder:

1. **Protein — anchored to bodyweight.**
   `protein_target_g = round(1.6 × start_weight_kg)`
   (`PROTEIN_G_PER_KG = 1.6`). Anchored to `start_weight_kg` — the goal's fixed
   start-weight snapshot — **not** the (lower) target weight: in a deficit you
   anchor protein to *current* body mass to protect lean tissue.
2. **Fat — an energy share with a hormonal-health floor.**
   `fat_target_g = max( round(0.30 × daily_calorie_target_kcal / 9),
   round(0.8 × start_weight_kg) )`
   (`FAT_PCT_OF_CALORIES = 0.30`, `FAT_FLOOR_G_PER_KG = 0.8`). The floor
   guarantees enough fat for essential fatty acids / sex-hormone health when a
   deep deficit would otherwise push the percentage share too low.
3. **Carbohydrate — the non-negative remainder.**
   `carbs_kcal = daily_calorie_target_kcal − 4·protein_target_g − 9·fat_target_g`;
   `carbs_target_g = round(max(0, carbs_kcal) / 4)`. When protein + fat already
   meet or exceed the calorie target, carbohydrate floors at 0 and **`macros_clamped`
   is set true** (the analogue of the calorie `clamped` flag) so the rare
   over-constrained case is honest, never silently negative.

Each macro is rounded to the **nearest whole gram, rounding half up** — a
documented, deterministic rule (not Python's default banker's rounding) so a
future edit cannot silently shift a pinned macro. The macros are derived, not
user-set: their machine-readable provenance is the assumptions snapshot (the
defaults below); the UI provenance label is rendered by a later Profile story.

The Atwater energy factors used (kcal per gram) are protein 4, carbohydrate 4,
fat 9.

#### Evidence basis for the macro defaults

- **Protein 1.6 g/kg bodyweight.** The largest meta-analysis to date (Morton et
  al., *Br J Sports Med* 2018) identifies ~1.6 g/kg/day as the breakpoint beyond
  which added protein yields no further lean-mass benefit; systematic reviews of
  hypocaloric diets in adults with overweight/obesity find **1.2–1.6 g/kg/day**
  optimal for fat loss with lean-mass preservation. 1.6 g/kg sits at the top of
  that protective band and at the muscle-protein-synthesis ceiling — a strong,
  simple, total-bodyweight-anchored default. This overrides the intuition that
  protein should scale with the lower *goal* weight: in a deficit you anchor to
  *current* mass to protect lean tissue.
- **Fat ≥ 0.30 of calories, floored at 0.8 g/kg.** The Dietary Guidelines for
  Americans place fat at 20–35% of energy; evidence shows dropping below ~20% of
  energy / ~0.8 g/kg lowers sex-hormone (e.g. testosterone) levels. 30% is a calm
  midpoint; the 0.8 g/kg floor protects hormonal health when a deep deficit would
  otherwise shrink the percentage share.
- **Carbohydrate as remainder.** Carbohydrate is the least essential macro to pin
  (no essential-carbohydrate requirement); letting it flex as the remainder after
  the two evidence-anchored macros is the standard evidence-based macro-setting
  order (protein first, fat floor, carbs fill).

#### Bodyweight-anchor limitation

Anchoring protein to `start_weight_kg` keeps derivation deterministic and
consistent with the trajectory math, but within a single goal protein does not
drift down as the user loses weight; re-anchoring to *current* weight is future
adaptive-calibration work (already out of scope per the FTY-022 adaptive
exclusion). Total-bodyweight scaling also slightly overestimates protein need at
high adiposity — lean-mass- or reference-weight-based anchoring is more precise —
a known refinement, not a v1 blocker.

## Manual override + reset, with provenance (FTY-095)

A user can manually override their daily **calorie** target and any of their
**macro** targets, and reset each back to the derived value. The override lives on
`daily_targets` beside the derived columns, realising the design's "every number
shows where it came from — including the target itself" stance.

### Effective value and the read-model

The **effective** value a consumer displays/measures against is a pure read-time
`override ?? derived`: the override column when set, else the derived column. The
target **read-model** exposes, per target (calorie and each macro):

- **`effective`** — the value the app uses (override when set, else derived);
- **`derived`** — always present; the current deterministic derivation, i.e. what
  a reset would restore;
- **`source`** — a `derived | user` provenance flag (`user` when an override is in
  force for that target, else `derived`).

This read-model is the shape `daily-summary.md`'s `target` component and the
owner-scoped target endpoint surface.

### Target resolution: carry-forward reads vs exact-date writes (FTY-127/FTY-103)

A `daily_targets` row is materialised only on **goal-creation day** (and, going
forward, whenever an override write materialises one). The daily target is
**constant across a goal's horizon** — the calculator derives it from the goal's
fixed `(start_weight, target_weight, start_date, target_date)` snapshot and
`for_date` enters only through whole-year age — so the stored value is valid for
every day in the horizon. Resolution therefore differs between reads and writes:

- **Reads carry forward.** `GET /api/users/{id}/target` (and `daily-summary.md`'s
  `target` component, single and range) resolve the **most recent stored row at or
  before the requested day**, while that day is on or before the goal's
  `target_date`. So the target is present for **every in-horizon day**, not just the
  creation day — this is what keeps a returning user's target (and the onboarding
  completeness probe that reads this endpoint) from vanishing the day after
  onboarding. The endpoint returns `404` (and daily-summary returns `null`) only
  when there is no active goal, the day predates the goal's first stored row, or the
  day is **past** `target_date` (the planned trajectory is complete; the user is
  steered to set a new goal rather than shown a stale deficit). Cross-user access is
  the same `404` — no existence oracle.
- **Override writes resolve by exact date.** `set`/`reset` (below) operate on the
  concrete `daily_targets` row for the requested day, because an override must be
  persisted on a real row. **Known limitation (tracked in FTY-127):** since rows are
  only materialised on creation day, an override write on a *non-creation* in-horizon
  day currently returns `404` (`TargetNotFound`) — there is no row to land on. The
  residual FTY-127 work materialises the row on demand (via the calculator,
  carrying any in-force override forward) so override-on-a-later-day succeeds. The
  read carry-forward above is unaffected.

### Set / reset semantics

- **Set** records a calorie and/or macro override on the active goal's target row,
  stamps `override_set_at`, and returns the read-model with `source: user` for the
  overridden targets. Calorie and each macro can be set independently.
- **Reset** clears the targeted override column(s) back to `NULL` (calorie and/or
  macros, independently; resetting with no targets named clears all in-force
  overrides). The effective value falls back to the derived value and `source`
  returns to `derived`. Reset is idempotent. When the last in-force override is
  cleared, `override_set_at` is cleared too.

### Override lifetime (documented rule)

An override is an explicit user choice that **persists across derived recomputes**
and is cleared **only** by (a) an explicit reset, or (b) deletion/replacement of
the owning goal. The override columns live on `daily_targets`, which already
`ON DELETE CASCADE`s from `goal_id`, so a replaced/deleted goal drops the override
with its target — no orphaned overrides. No other event silently clears it.

- **Recompute preserves the override.** Editing goal/pace/metrics recomputes the
  **derived** columns in place but leaves any set override intact and still in
  force; the read-model reports the freshly recomputed derived value (so a future
  reset restores the *current* derivation, not a stale one) while `source` stays
  `user`. When a recompute materialises a target row for a **new** `for_date`, the
  goal's in-force override is carried forward onto it so the choice does not
  silently lapse on a date rollover.

### Override validation — reject, do not clamp

Because an override is explicit user input, an out-of-band value is **rejected**
with a `422` validation error (nothing persisted) rather than silently clamped —
the user sees their value refused, not quietly altered. (The derived path's
`clamped` behaviour is unchanged: the system clamps numbers *it* produced.)

- **Calorie override** must fall within the existing safety band the row was
  derived against (read from its `assumptions` snapshot): floor 1500 kcal
  (`mifflin_st_jeor_plus5`) / 1200 kcal (`mifflin_st_jeor_minus161`); ceiling 4000
  kcal. The exact band constants are reused — no new numbers.
- **Macro override** must be a non-negative whole-gram value whose energy
  (grams × the Atwater factor: protein 4, carbohydrate 4, fat 9) does not exceed
  the calorie safety ceiling — i.e. each macro is bounded by `ceiling ÷ factor`
  (protein/carbs ≤ 1000 g, fat ≤ 444 g at the 4000 kcal ceiling). FTY-094 documents
  no separate per-macro clinical band, so the override reuses the existing calorie
  safety ceiling and Atwater factors as a sanity bound rather than introducing a
  new number.

## Validation

- `height_m` ∈ (0, 3]; `age_years` ∈ [13, 120]; `start_weight_kg`,
  `target_weight_kg` ∈ (0, 1000]; `target_date` strictly after `start_date`
  (positive horizon). Unknown fields are rejected.
- The service rejects an incomplete profile (missing height or birth year, or a
  metabolic formula still on the unspecified `mifflin_st_jeor` default) rather
  than computing a bogus target.
- **Safety floor/ceiling.** The daily target is clamped to a documented band and
  `clamped` is set when the raw value falls outside it: a floor of 1500 kcal
  (`+5` variant) / 1200 kcal (`-161` variant) — clinically conservative minimums
  for unsupervised dieting, so a dangerously low target is refused, not returned —
  and a ceiling of 4000 kcal to refuse implausibly aggressive weight-gain plans.

## Authorization

Object-level: a caller may compute, store, override, or reset a daily target only
for **their own** goal. The service fails closed (`GoalForbidden`) on any
cross-user access, and an unowned or missing goal is indistinguishable (no
existence oracle). `user_id` on both tables is the ownership key. The override
set/reset endpoints are owner-scoped: cross-user access and a caller with no active
goal / no stored target for the day both fail closed as `404` (the same
`GoalForbidden` / `TargetNotFound` → `404` discipline, no existence oracle), proven
by negative authorization tests.

## Privacy and Retention

- Operates on sensitive body data but produces derived numbers; no external
  providers, no untrusted input, no LLM.
- Body data is privacy-minimal: only `birth_year` is stored (age is a whole-year
  approximation), and biological sex is not stored as such — the metabolic
  formula preference carries the only sex-dependent constant the math needs.
- Retention follows the owning profile/goal: derived targets live until the goal
  is edited/replaced or the account is deleted. `ON DELETE CASCADE` on `user_id`
  (and `goal_id`) removes derived rows when the user or goal is deleted.
- The FTY-095 override columns (`override_*_target_*`, `override_set_at`) are
  sensitive derived body data on the same `daily_targets` row: user-owned, never
  logged (diagnostics use user/goal ids, not target numbers), and removed by the
  same `ON DELETE CASCADE`. `override_set_at` is a bare timestamp with no PII. See
  `data-retention.md`.

## Errors

| Condition | Result |
| --- | --- |
| `target_date` ≤ `start_date`, out-of-range metric, unknown field | `ValidationError` at the boundary. |
| Profile missing height/birth year, or formula on the unspecified default | `IncompleteProfileError`. |
| Cross-user, unowned, or missing goal | `GoalForbidden` (fail closed). |
| Override set/reset with no active goal or stored target for the day | `TargetNotFound` → `404` (fail closed, no oracle). |
| Raw **derived** target outside the safety band | Clamped to floor/ceiling, `clamped = true`. |
| Manual **override** outside the safety band (or a macro outside its bound) | Rejected `422`, nothing persisted (no clamp). |
| Empty override request (no calorie or macro provided) | Rejected `422` at the boundary. |

## Examples

- **Maintenance.** Male, 80 kg, 1.80 m, age 30, target 80 kg → RMR 1780,
  TDEE 2136, daily target 2136 kcal. Macros: protein 128 g (1.6 × 80), fat 71 g
  (round(0.30 × 2136 / 9), above the 0.8 × 80 = 64 g floor), carbs 246 g
  (round((2136 − 512 − 639) / 4)), `macros_clamped = false`.
- **Weight loss (fat floor wins).** Same profile, target 75 kg over 90 days →
  daily target 1678 kcal (a deficit below TDEE); over ~365 days → 1998 kcal
  (gentler). Macros at 1678 kcal: protein 128 g (still anchored to the **80 kg
  start weight**, not the 75 kg goal), fat 64 g (the 0.8 × 80 = 64 g floor wins
  over round(0.30 × 1678 / 9) = 56 g), carbs 148 g, `macros_clamped = false`.
- **Refused plan.** Same profile, target 60 kg in 30 days → raw target is
  negative; clamped up to the 1500 kcal floor, `clamped = true`.
- **Over-constrained macros.** Female, 90 kg, 1.60 m, target 60 kg in 30 days →
  calorie target clamped to the 1200 kcal floor; protein 144 g + fat 72 g already
  exceed it (4 × 144 + 9 × 72 = 1224 kcal), so carbs floor at 0 g and
  `macros_clamped = true`.

## Migration / Compatibility

- `0002` applies cleanly on top of the `0001` baseline (`alembic upgrade head`)
  and is fully reversible (`alembic downgrade 0001`), verified by a migration
  apply/rollback test against a throwaway database.
- `0014` (FTY-095) is an **additive, reversible** migration layered on FTY-094's
  revision: it adds the nullable `override_*` columns and the now-persisted derived
  macro columns (`*_target_g`, `macros_clamped`, NOT NULL with a `0`/`false` server
  default so the `ALTER` is safe on any existing row) to `daily_targets`. It
  applies cleanly (`alembic upgrade head`) and rolls back fully
  (`alembic downgrade -1`), dropping exactly those columns and leaving the FTY-022
  derived columns intact — verified by an apply/rollback test. No data migration.
- `metabolic_formula` has two computable variants (`mifflin_st_jeor_plus5`,
  `mifflin_st_jeor_minus161`) plus the unspecified `mifflin_st_jeor` family
  default; FTY-021 profile capture must offer exactly the two variants. The
  profile column type is unchanged (string), so no data migration is needed; the
  model default (`mifflin_st_jeor`) is a pre-capture placeholder only.
- Consumers (daily summaries, later targeting stories) depend on the
  `daily_targets` shape and the calculator output contract defined here.
