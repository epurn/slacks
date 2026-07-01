# Contract: MET Exercise Burn

## Purpose

Define the deterministic **exercise-burn calculation step** (FTY-043) of the
estimation pipeline: how a parsed exercise candidate (FTY-042) becomes a costed
`derived_exercise_items` row carrying **net active calories**, computed from a
curated MET value and the user's body weight — no LLM, no external input.

This covers four things:

1. the **curated, versioned MET table** (`met_table.py`) and its activity → MET
   lookup/validation rule;
2. the **net-active burn formula** (the `(MET − 1)` convention) and its boundary
   validation (`exercise.py`);
3. the **`active_calories`** column added to `derived_exercise_items` and the
   `0006` migration;
4. the **routing and trust boundary** — how a resolved candidate completes, how an
   unmatched activity or bad duration routes to `needs_clarification`, and how a
   missing body weight fails closed.

It consumes FTY-042's `unresolved` exercise candidates (see `parse-candidates.md`)
and plugs into FTY-040's pipeline-step interface and status transitions (see
`estimation-jobs.md`). It excludes food calorie/macro resolution (FTY-044),
heart-rate or device-based estimation, editable corrections to burn, and expanding
the MET table beyond the curated v1 subset.

## Owner

estimator / contracts / backend-core lane:
`backend/app/estimator/met_table.py`, `backend/app/estimator/exercise.py`,
`backend/app/estimator/exercise_step.py`, `backend/app/models/derived.py`
(`DerivedExerciseItem.active_calories`), `backend/alembic/`.

## Version

1 (FTY-043). MET table version string `met/v1`, recorded on the estimation run.

2 (FTY-167). MET table `met/v2` — adds a `badminton` entry (social/general, MET 5.5)
for the game-count conversion — and extends the calculator to infer a duration from a
logged distance, step count, or game count via documented pace/cadence/per-game
constants. The `(MET − 1)` burn formula and the version/source/formula evidence are
unchanged.

## Inputs

### MET table (`met_table.py`)

A curated **v1 subset** of the 2011 Compendium of Physical Activities — common
everyday activities at a single representative "general / moderate" intensity each.
The LLM never supplies a MET value: the parse step extracts only an activity
*description* and duration, and the backend maps the description to a MET value
here. The table is content-addressed by `MET_TABLE_VERSION` (`met/v1`) with a
human-readable `MET_TABLE_SOURCE`; bump the version on any change to a value, key,
or alias so a run records exactly which table produced its numbers.

`lookup_met(activity)` normalises the description (lower-case, collapse whitespace,
strip surrounding punctuation) and matches it **exactly** against a curated key or
alias. No fuzzy or partial matching: an unrecognised activity returns `None` so the
calculator fails closed rather than guessing a burn. Every curated MET value is
strictly above rest (`> 1`), so the net burn is always non-negative.

### Calculator input (`resolve_exercise`)

`activity` (description), `weight_kg` (the user's canonical body weight from the
profile), and the candidate's `unit` / `amount` / `quantity_text` (the logged
duration). Duration is taken from the structured `unit` + `amount` when `unit` is a
recognised time unit (seconds / minutes / hours); a non-time unit (e.g. `km`) is not
trusted as a duration, falling back to a `<number> <time-unit>` phrase scanned from
`quantity_text`.

### Quantity → duration conversions (FTY-167)

When a log states a **distance**, a **step count**, or a **game count** instead of a
duration, the duration is inferred deterministically from a documented, evidence-based
assumption so a detail-rich entry ("ran 5 km", "walked 13000 steps", "played 3 games
of badminton") is costed rather than sent to clarification. Resolution order is
explicit-time → distance → steps → games; the first signal present wins, and an
explicit duration never triggers an inference. The constants are documented tunables
in `exercise.py`:

- **Distance → duration** via a representative pace per curated activity
  (`PACE_KM_PER_HOUR`): walking 5 km/h, running 10 km/h, swimming 2.5 km/h. An
  activity with no documented pace cannot be costed from distance alone.
- **Steps → walking duration** via the documented cadence `STEPS_PER_MINUTE` = 100
  steps/min (Tudor-Locke et al. 2011, the moderate-walking threshold): `13000 ÷ 100 =
  130 min`.
- **Game count → duration** via `GAME_DURATION_MINUTES` per curated activity
  (badminton 15 min/game). An activity with no documented per-game duration cannot be
  costed from a game count.

Each inferred conversion appends a **content-free assumption** string (numbers plus
the curated activity key only — never raw diary text) to the run `assumptions`, so the
inference is visible and the entry stays user-editable. The inferred duration is still
gated by the `(0, 24 h]` plausibility band below.

## Outputs

### The math

Gross active energy uses the MET identity `1 MET ≈ 1 kcal/kg/hour`:

```
gross_kcal = MET × weight_kg × duration_hours
```

The daily allowance already counts resting energy in TDEE (RMR × the baseline
activity multiplier; see `target-calculator.md`). Crediting the **gross** burn would
double-count the resting component, so only energy **above rest** is credited — the
`(MET − 1)` adjustment, since 1 MET is rest:

```
net_active_kcal = (MET − 1) × weight_kg × duration_hours   (rounded to 0.1 kcal)
```

This is the documented convention chosen to align with the FTY-022 TDEE model and
avoid double-counting.

### Persistence

The `0006` migration adds **`active_calories`** (nullable float, kcal) to
`derived_exercise_items` (additive; no other table is changed). The calculator writes
the net burn there and advances the row to `status = resolved`; an `unresolved`
candidate (parsed but not yet costed) carries `active_calories = NULL`. The MET-table
version/source and the net-active formula are recorded on the **estimation run**
(`source_refs` / `assumptions`), not duplicated per row.

### Worked examples

| Activity | MET | Weight | Duration | Net active kcal |
| --- | --- | --- | --- | --- |
| running | 7.0 | 70 kg | 30 min | `(7.0−1)·70·0.5` = **210.0** |
| walking | 3.5 | 80 kg | 60 min | `(3.5−1)·80·1.0` = **200.0** |
| cycling | 7.5 | 60 kg | 45 min | `(7.5−1)·60·0.75` = **292.5** |

## Validation

- **Activity.** No confident MET match → `needs_clarification` (the input is
  recognisably exercise but cannot be costed; never guessed).
- **Duration.** Must be present and in `(0, 24 h]`. Missing, zero/negative, or
  implausibly large (> 24 h) → `needs_clarification`.
- **Body weight.** Must be present and in `(0, 1000] kg`. Missing/implausible →
  fails closed (`StepFailed`): an incomplete profile, not an answerable ambiguity.

## Outputs / Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| All exercise candidates resolve | _(completes)_ | exercise items `resolved` with `active_calories` | `processing → completed` |
| Unknown activity | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Missing / zero / implausible duration | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Missing / implausible body weight | `StepFailed` (terminal) | nothing | `processing → failed` |
| No exercise candidates (food-only) | _(no-op, completes)_ | — | _(unchanged)_ |

A `needs_clarification` outcome records a fixed, sanitized question so the event
always has one for the later answer flow. Resolved items are committed in the **same
transaction** as the terminal `completed` status.

## Authorization

Every `derived_exercise_items` row carries `user_id` at the persistence boundary and
is written scoped to the owning event's user (the worker already loaded the event
scoped to the job's `user_id`; see `estimation-jobs.md`). The body weight is read
from the **owning user's** profile, never supplied by the model. `ON DELETE CASCADE`
from both `users` and `log_events` enforces object-level ownership.

## Privacy and Retention

- **Deterministic backend math, no untrusted numbers.** The MET value comes from the
  curated table, never the LLM; only the activity description and duration come from
  the (schema-validated) parse, and they are validated before use.
- **Body weight is sensitive and never logged.** It is read from the profile to
  compute the burn and is never written to the run `trace`, `source_refs`,
  `assumptions`, or `error`; the run records only the MET-table version/source and
  the net-active formula (content-free metadata).
- **Retention** follows the owning log event: costed exercise items live until the
  event, user, or account is deleted (`ON DELETE CASCADE`), per
  `docs/security/data-retention.md`.

## Errors

| Condition | Result |
| --- | --- |
| Activity not in the curated MET table | `needs_clarification` (`unknown_activity`); nothing costed. |
| Missing duration | `needs_clarification` (`missing_duration`). |
| Zero/negative duration | `needs_clarification` (`non_positive_duration`). |
| Duration > 24 h | `needs_clarification` (`implausible_duration`). |
| Missing/implausible body weight | Terminal `failed` (`missing_body_weight`); nothing persisted. |

## Examples

```
parsed exercise candidate: name "run", quantity_text "30 min", unit "min", amount 30
profile.weight_kg = 70
  → lookup_met("run") → running, MET 7.0
  → duration 30 min = 0.5 h
  → net_active_kcal = (7.0 − 1) × 70 × 0.5 = 210.0
  → derived_exercise_items += run (resolved, active_calories 210.0)
  → run.source_refs += "met_table:met/v1"; event: processing → completed
```

## Migration / Compatibility

- The `0006` migration applies (`alembic upgrade head`) on top of the `0005`
  derived-parse schema and is fully reversible (`alembic downgrade 0005`), verified by
  an apply/rollback test against a throwaway database.
- Additive: only `derived_exercise_items` gains a nullable `active_calories` column;
  food items are unchanged and no backfill is needed.
- FTY-043 replaces FTY-040's stub calculation step with this real exercise step in
  the default pipeline; the worker's claim → run → transition contract is unchanged.
  Food candidates still persist `unresolved` until FTY-044 resolves them.
- The curated MET subset and the `(MET − 1)` net constant are documented assumptions
  (story planning notes); expanding the table or adding intensity tiers is a later
  story and must bump `MET_TABLE_VERSION`.
- FTY-051 extends `derived_exercise_items` with a nullable `active_calories_estimated`
  snapshot (the immutable original burn paired with the editable `active_calories`)
  and lets a user correct the burn through the edit endpoint. This does not redefine
  the burn calculation above; the estimator sets the snapshot at creation. See
  `corrections.md`.
```
