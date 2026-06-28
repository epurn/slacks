---
id: FTY-094
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - backend-core
risk: high
tags:
  - estimator
  - macros
  - targets
  - evidence
  - contracts
approved_dependencies: []
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/target-calculator.md
  - docs/contracts/daily-summary.md
  - docs/standards/testing-standards.md
review_focus:
  - evidence-based-default-ratios-documented-and-sourced
  - deterministic-pinned-macro-derivation
  - carbs-nonneg-clamp-flag-edge
  - additive-output-no-change-to-calorie-rmr-tdee
autonomous: true
---

# FTY-094: Macro Targets — Derive Protein / Carb / Fat Targets

## State

ready_with_notes

## Lane

estimator

## Dependencies

- None. Extends the merged FTY-022 deterministic target calculator
  (`backend/app/estimator/calculator.py`, output contract in
  `backend/app/schemas/targets.py`). Does not depend on FTY-071 daily-totals —
  the daily-summary *surfacing* of these targets is deliberately out of scope
  here (see Non-Goals and the Readiness Sanity Pass split note).

## Outcome

The deterministic target calculator derives **protein, carbohydrate, and fat
targets (in grams)** alongside the existing daily calorie target, using
**documented, evidence-based defaults** — protein anchored to bodyweight, with
fat held at an evidence floor and carbohydrate taking the remainder. The macro
targets become part of the target-calculator output contract
(`TargetCalculatorResult`), with their derivation and evidence basis captured in
the assumptions snapshot and `docs/contracts/target-calculator.md`. This is the
foundation the Today P/C/F chips and Profile macro targets (later mobile
stories) measure intake against, and it honours the **Evidence-backed by
default** design principle: the protein anchor is the well-supported default,
not folk wisdom.

Net-new: the FTY-022 contract explicitly states "Macro targets are not part of
the FTY-022 contract," and `daily_targets` stores only
`daily_calorie_target_kcal` (+ rmr/tdee/inputs/assumptions/clamped). This story
adds the *derivation and output contract* only; it does not persist or surface
the macros (those are separate dependent boundaries).

## Scope

Pure, deterministic, additive extension of the existing calculator. No I/O, no
LLM, no external input — same purity guarantee as `compute_targets` today.

- **Derive the three macro targets in grams**, in this fixed priority order
  (protein first → fat floor → carbohydrate fills the remainder), inside the
  estimator package (`backend/app/estimator/calculator.py`, constants in
  `backend/app/estimator/constants.py`):
  1. **Protein — anchored to bodyweight.**
     `protein_target_g = round(PROTEIN_G_PER_KG × start_weight_kg)` with
     `PROTEIN_G_PER_KG = 1.6`. Anchored to `start_weight_kg` (the goal's stored
     start-weight snapshot already on `TargetCalculatorInput`), not target
     weight — protein scales with current body mass to protect lean mass in a
     deficit.
  2. **Fat — evidence share of calories, with a hormonal-health floor.**
     `fat_target_g = max( round(FAT_PCT_OF_CALORIES × daily_calorie_target_kcal / 9),
     round(FAT_FLOOR_G_PER_KG × start_weight_kg) )` with
     `FAT_PCT_OF_CALORIES = 0.30` and `FAT_FLOOR_G_PER_KG = 0.8`. The floor
     guarantees enough fat for essential fatty acids / sex-hormone health when a
     deep deficit would otherwise push the percentage share too low.
  3. **Carbohydrate — the non-negative remainder.**
     `carbs_kcal = daily_calorie_target_kcal − 4·protein_target_g − 9·fat_target_g`;
     `carbs_target_g = round(max(0, carbs_kcal) / 4)`. When protein + fat already
     meet or exceed the (safety-clamped) calorie target, carbohydrate floors at
     0 and a **`macros_clamped` flag** is set true (the analogue of the existing
     `clamped` calorie flag) so the rare over-constrained case is honest, not
     silently negative.
  - Compute against the **already safety-clamped `daily_calorie_target_kcal`**
    the calculator returns today (so macros are consistent with the number the
    user is actually shown), and round each macro to the **nearest whole gram,
    rounding half up** (documented, deterministic — avoids banker's-rounding
    ambiguity in pinned tests).
- **Extend the output contract** (`backend/app/schemas/targets.py`):
  - Add `protein_target_g: int`, `carbs_target_g: int`, `fat_target_g: int`, and
    `macros_clamped: bool` to `TargetCalculatorResult` (additive; existing
    fields unchanged, `extra="forbid"` preserved).
  - Extend `TargetAssumptions` with the documented macro defaults so every
    derived target is reproducible and explainable:
    `protein_g_per_kg` (1.6), `protein_anchor` (`"start_weight_kg"`),
    `fat_pct_of_calories` (0.30), `fat_floor_g_per_kg` (0.8), and a macro
    rounding note. New constants live in `constants.py` with their evidence
    citation in the docstring, mirroring the existing constants' style.
- **Update `docs/contracts/target-calculator.md`** (docs lane): document the
  macro outputs, the derivation order, the evidence-based default ratios and
  their sources, the carbohydrate clamp/`macros_clamped` flag, the
  bodyweight-anchor choice and its limitation, and bump the contract **Version
  to 2**. Remove the line "Macro targets are not part of the FTY-022 contract"
  and replace it with the macro output definition.
- **Provenance:** the macro targets carry the same "derived from your target /
  goal + metrics" provenance as the calorie target — they are computed numbers,
  not user-set. (The UI provenance label is rendered by the later Profile
  story; here the assumptions snapshot is the machine-readable provenance.)

### Evidence basis (fold into the contract + constants docstrings)

- **Protein 1.6 g/kg bodyweight.** The largest meta-analysis to date (Morton et
  al., *Br J Sports Med* 2018) identifies ~1.6 g/kg/day as the breakpoint beyond
  which added protein yields no further lean-mass benefit; systematic reviews of
  hypocaloric diets in adults with overweight/obesity find **1.2–1.6 g/kg/day**
  optimal for fat loss with lean-mass preservation. 1.6 g/kg sits at the top of
  that protective band and at the muscle-protein-synthesis ceiling — a strong,
  simple, total-bodyweight-anchored default. This **overrides the intuition**
  that protein should scale with the (lower) *goal* weight: in a deficit you
  anchor to *current* mass to protect lean tissue.
- **Fat ≥ 0.30 of calories, floored at 0.8 g/kg.** The Dietary Guidelines for
  Americans place fat at 20–35% of energy; evidence shows dropping below
  ~20% of energy / ~0.8 g/kg lowers sex-hormone (e.g. testosterone) levels.
  30% is a calm midpoint; the 0.8 g/kg floor protects hormonal health when a
  deep deficit would shrink the percentage share.
- **Carbohydrate as remainder.** Carbohydrate is the least essential macro to
  pin (no essential-carbohydrate requirement); letting it flex as the remainder
  after the two evidence-anchored macros is the standard evidence-based
  macro-setting order (protein first, fat floor, carbs fill).

## Non-Goals

- **Surfacing the macro targets in the daily-summary response** (the
  `daily-summary.md` DTO / `backend/app/services/daily_summary.py` change). That
  is backend-core consumer work and a second public-contract change — a separate
  dependent boundary story (see Readiness Sanity Pass). `daily-summary.md` is
  context here only to keep the gram units and field naming parallel to
  `intake.protein_g/carbs_g/fat_g` so a later story can compare like-for-like.
- **Persisting macro targets and the manual override + reset** — owned by
  **FTY-095**, which owns the `daily_targets` schema migration and the override.
  This story changes no persistence: it does not touch
  `backend/app/services/targets.py`, `backend/app/models/targets.py`, the
  `daily_targets` table, or any migration. The new `TargetCalculatorResult`
  fields are simply not yet persisted.
- The mobile UI — Today P/C/F chips (FTY-098) and Profile macro targets +
  override display (FTY-102).
- The calorie-target manual override.
- Adaptive re-anchoring of protein to *current* (vs. start) weight as the user
  loses weight within a goal — a documented limitation tied to the adaptive
  calibration already excluded by the FTY-022 contract; future work.
- Any change to the existing RMR / TDEE / `daily_calorie_target_kcal` math or
  the calorie safety clamp.

## Contracts

- **`docs/contracts/target-calculator.md`** (Version 1 → 2): adds the macro
  target outputs (`protein_target_g`, `carbs_target_g`, `fat_target_g`,
  `macros_clamped`), the documented evidence-based default ratios and sources,
  the derivation order, the bodyweight-anchor choice + limitation, and the
  carbohydrate non-negative clamp. The single estimator output-contract change
  in this story (one big rock).
- `TargetCalculatorResult` / `TargetAssumptions` DTOs in
  `backend/app/schemas/targets.py` — additive only.
- No change to `DailyTargetDTO`, `daily_targets`, the calculator inputs, or
  `daily-summary.md` (the latter still says macros are not surfaced; a later
  story versions it to expose them — already anticipated in its
  Migration/Compatibility note).

## Security / Privacy

- Deterministic pure math on the user's own profile + goal — no untrusted
  input, no external providers, no LLM, no new persistence, no new trust
  boundary. Same privacy posture as FTY-022: operates on sensitive body data but
  produces derived numbers that are never logged.
- Rated **high** despite the small surface because it is a **public estimator
  contract change that drives user-facing macro numbers** (the Today chips and
  Profile measure against these). A wrong ratio or a silent divergence ships a
  health-relevant number to every user; correctness of the documented defaults,
  the derivation order, and the clamp is the load-bearing risk, not a new attack
  surface. Per the sizing rule, when risk is ambiguous, estimate big.

## Acceptance Criteria

- `TargetCalculatorResult` gains `protein_target_g`, `carbs_target_g`,
  `fat_target_g` (int grams) and `macros_clamped` (bool); `TargetAssumptions`
  gains the documented macro-default fields. All are additive; existing fields
  and `extra="forbid"` are unchanged.
- `compute_targets` derives the three macros deterministically from the
  safety-clamped `daily_calorie_target_kcal`, `start_weight_kg`, and the
  formula, in the documented protein → fat-floor → carbs-remainder order, with
  round-half-up to the nearest gram.
- **Pinned deterministic example — maintenance** (the contract's existing
  example: `+5` formula, 80 kg, 1.80 m, age 30, target 80 kg →
  `daily_calorie_target_kcal = 2136`): protein `128 g` (1.6 × 80), fat `71 g`
  (round(0.30 × 2136 / 9 = 71.2), above the 0.8 × 80 = 64 g floor), carbs
  `246 g` (round((2136 − 512 − 640.8)/4 = 245.8)), `macros_clamped = false`.
- **Pinned deterministic example — weight loss that triggers the fat floor**
  (same profile, target 75 kg over 90 days → `daily_calorie_target_kcal = 1678`):
  protein `128 g` (still anchored to the **80 kg start weight**, not the 75 kg
  goal — proves the anchor choice), fat `64 g` (the 0.8 × 80 = 64 g floor wins
  over round(0.30 × 1678 / 9 = 55.9 g)), carbs the non-negative remainder,
  `macros_clamped = false`. A test asserts protein did **not** drop with the
  lower goal weight and that the floor (not the percentage) set fat.
- An over-constrained case (protein + fat kcal ≥ the clamped calorie target)
  yields `carbs_target_g = 0` and `macros_clamped = true` — proven by a test, so
  carbohydrate is never negative.
- The documented defaults (1.6 g/kg, 0.30, 0.8 g/kg) and their evidence sources
  appear in `constants.py` docstrings, the assumptions snapshot, and
  `docs/contracts/target-calculator.md`; the contract Version is bumped to 2.
- **Existing calorie/RMR/TDEE outputs and all existing target-calculator and
  target-service tests pass unchanged** — the macro addition does not alter the
  calorie target, the clamp, or any prior number.
- `make verify` passes.

## Verification

- **Root `make verify`** (runs `backend/verify.sh`: `uv run ruff check` +
  `ruff format --check` + `mypy` + `uv run pytest`).
- **Focused estimator unit tests** (the load-bearing check):
  `cd backend && uv run pytest tests/test_target_calculator.py` — add
  deterministic cases pinning the two worked examples above (maintenance and the
  fat-floor weight-loss case) plus the `macros_clamped` over-constrained edge.
  Pin exact gram values per the documented round-half-up rule so a future edit
  cannot silently shift a macro.
- Assert additivity: the existing maintenance/loss/refused-plan calorie
  assertions in `tests/test_target_calculator.py` and the persistence path in
  `tests/test_target_service.py` remain green unchanged (no calorie/RMR/TDEE
  drift, no persistence change).
- Confirm `docs/contracts/target-calculator.md` documents every default with its
  source and the Version reads 2.

## Planning Notes

- **Why grams, parallel to intake.** Macro targets are emitted in grams to
  mirror `daily-summary` `intake.protein_g/carbs_g/fat_g`, so a later
  surfacing story can compare target vs. intake in the same unit the Today chips
  render (`§4` macro chips, `§4c` macro targets).
- **Anchor weight choice.** `start_weight_kg` is the only bodyweight on the
  calculator input and is the goal's fixed start snapshot, keeping derivation
  deterministic and consistent with the existing trajectory math. Limitation
  (documented in the contract): within a single goal, protein does not drift
  down as the user loses weight; re-anchoring to current weight is future
  adaptive-calibration work, already out of scope per FTY-022.
- **Obesity nuance (documented, not blocking).** Total-bodyweight scaling
  slightly overestimates protein need at high adiposity (lean-mass- or
  reference-weight-based anchoring is more precise); 1.6 g/kg of total
  bodyweight is the standard simple evidence-based default for v1, noted as a
  known refinement.

## Readiness Sanity Pass

- **Product decision gaps:** none — the defaults (protein 1.6 g/kg of start
  weight; fat 0.30 of calories with a 0.8 g/kg floor; carbs as the non-negative
  remainder), the derivation order, the rounding rule, and the clamp flag are
  all resolved and evidence-grounded. The evidence was researched, not assumed:
  the protein anchor cites the Morton 2018 meta-analysis + hypocaloric
  lean-mass-preservation reviews, and the fat floor cites the DGA range +
  sex-hormone evidence; both are folded into the contract and constants. The
  research surfaced one intuition override (anchor protein to *current/start*
  weight, not the lower goal weight) which the spec calls out explicitly.
- **Cross-lane impact:** primary lane **estimator** (`calculator.py`,
  `constants.py`); the output DTOs in `schemas/targets.py` are the calculator's
  own output contract (touched_lanes: backend-core), exactly the FTY-082
  pattern — one logical boundary (the estimator output contract). The contract
  doc is the non-serializing docs lane. No service/persistence/migration change.
- **Sizing — split decision (recorded).** The brief's wider ask ("expose them in
  the daily-summary") would add `backend/app/services/daily_summary.py` +
  `schemas/daily_summary.py` (a second serializing **backend-core** boundary)
  **and** a second public-contract change (`daily-summary.md` DTO) — two big
  rocks across two lanes. Per the scope guardrail that is a split, so the
  daily-summary surfacing is carved out into a **dependent backend-core story**
  (depends on this FTY-094 for the calculator output, and on FTY-095 for the
  persisted macro columns it reads). Likewise persistence + override stays in
  FTY-095. This story holds exactly one boundary (the estimator output
  contract) and one big rock. `review_focus` = 4 (≤ 5), `requires_context` = 4
  (≤ 8) — within limits.
- **Security/privacy risk:** high by content (a public contract change driving
  user-facing health numbers), not by surface — deterministic pure math, no
  untrusted input, no new persistence or trust boundary. Mitigated by pinned
  deterministic tests and documented, sourced defaults.
- **Verification path:** `make verify` + focused
  `tests/test_target_calculator.py` cases pinning the two worked examples and
  the clamp edge + proof that existing calorie/RMR/TDEE tests are unchanged.
- **Assumptions safe for autonomy:** yes — exact files, formulas, constants,
  rounding rule, pinned example values, and the evidence basis are specified;
  the change is additive and cannot alter any existing number. `ready_with_notes`
  because the full user-visible feature needs the carved-out daily-summary and
  persistence stories to land after this; the estimator slice itself is fully
  specified and buildable now.
