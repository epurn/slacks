# Contract: Target Calculator

## Purpose

Turn a user's profile and weight goal into a daily calorie target through pure,
deterministic math — no LLM, no external input. This contract covers three
things:

1. the `goals` and `daily_targets` persistence schema and their migration
   (FTY-022 owns these tables);
2. the calculator's input contract (profile fields + goal trajectory) and output
   contract (RMR, TDEE, daily calorie target, and the assumptions snapshot),
   which are estimator contracts;
3. the documented assumptions behind every number (baseline activity multiplier,
   the NIDDK-style dynamic model parameters, rounding, and the safety
   floor/ceiling).

It deliberately excludes logging exercise burn into the daily allowance, adaptive
calibration from observed weight trend, profile capture UI (FTY-021), and the
identity/profile model (FTY-020).

## Owner

estimator / contracts / backend-core lane (`backend/app/estimator/`,
`backend/app/schemas/targets.py`, `backend/app/schemas/goals.py`,
`backend/app/models/targets.py`, `backend/app/services/targets.py`,
`backend/alembic/`).

## Version

1 (introduced in FTY-022).

## Inputs

### Persistence

The `0002` migration creates two user-owned tables:

- **`goals`** — a weight goal. Columns: `id` (UUID, PK), `user_id` (UUID, FK →
  `users.id`, `ON DELETE CASCADE`), `start_weight_kg` (float), `start_date`
  (date), `target_weight_kg` (float), `target_date` (date), `is_active` (bool),
  `created_at`, `updated_at`. The start snapshot is stored so the planned
  trajectory is deterministic and does not drift as measured weight changes.
- **`daily_targets`** — a derived daily target. Columns: `id` (UUID, PK),
  `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`), `goal_id` (UUID, FK →
  `goals.id`, `ON DELETE CASCADE`), `for_date` (date), `rmr_kcal` (float),
  `tdee_kcal` (float), `daily_calorie_target_kcal` (int), `clamped` (bool),
  `inputs` (JSON), `assumptions` (JSON), `created_at`.

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
target was outside the safety band and clamped to the boundary), and an
`assumptions` snapshot.

### The math

1. **RMR — Mifflin-St Jeor.** `RMR = 10·weight_kg + 6.25·height_cm − 5·age + s`,
   with the sex-dependent constant `s = +5` (`mifflin_st_jeor_plus5`) or
   `s = −161` (`mifflin_st_jeor_minus161`) chosen by `metabolic_formula`. Height
   is converted from canonical metres to centimetres internally.
2. **TDEE.** `TDEE = RMR × 1.2`, the baseline (sedentary) activity multiplier.
   Logged exercise burn is added to the day's allowance **separately** by later
   logging stories and is deliberately excluded here, to avoid double-counting
   MET-based active calories.
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

Object-level: a caller may compute or store a daily target only for **their own**
goal. The service fails closed (`GoalForbidden`) on any cross-user access, and an
unowned or missing goal is indistinguishable (no existence oracle). `user_id` on
both tables is the ownership key.

## Privacy and Retention

- Operates on sensitive body data but produces derived numbers; no external
  providers, no untrusted input, no LLM.
- Body data is privacy-minimal: only `birth_year` is stored (age is a whole-year
  approximation), and biological sex is not stored as such — the metabolic
  formula preference carries the only sex-dependent constant the math needs.
- Retention follows the owning profile/goal: derived targets live until the goal
  is edited/replaced or the account is deleted. `ON DELETE CASCADE` on `user_id`
  (and `goal_id`) removes derived rows when the user or goal is deleted.

## Errors

| Condition | Result |
| --- | --- |
| `target_date` ≤ `start_date`, out-of-range metric, unknown field | `ValidationError` at the boundary. |
| Profile missing height/birth year, or formula on the unspecified default | `IncompleteProfileError`. |
| Cross-user, unowned, or missing goal | `GoalForbidden` (fail closed). |
| Raw target outside the safety band | Clamped to floor/ceiling, `clamped = true`. |

## Examples

- **Maintenance.** Male, 80 kg, 1.80 m, age 30, target 80 kg → RMR 1780,
  TDEE 2136, daily target 2136 kcal.
- **Weight loss.** Same profile, target 75 kg over 90 days → daily target
  1678 kcal (a deficit below TDEE); over ~365 days → 1998 kcal (gentler).
- **Refused plan.** Same profile, target 60 kg in 30 days → raw target is
  negative; clamped up to the 1500 kcal floor, `clamped = true`.

## Migration / Compatibility

- `0002` applies cleanly on top of the `0001` baseline (`alembic upgrade head`)
  and is fully reversible (`alembic downgrade 0001`), verified by a migration
  apply/rollback test against a throwaway database.
- `metabolic_formula` has two computable variants (`mifflin_st_jeor_plus5`,
  `mifflin_st_jeor_minus161`) plus the unspecified `mifflin_st_jeor` family
  default; FTY-021 profile capture must offer exactly the two variants. The
  profile column type is unchanged (string), so no data migration is needed; the
  model default (`mifflin_st_jeor`) is a pre-capture placeholder only.
- Consumers (daily summaries, later targeting stories) depend on the
  `daily_targets` shape and the calculator output contract defined here.
