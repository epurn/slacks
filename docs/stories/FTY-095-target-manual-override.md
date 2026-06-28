---
id: FTY-095
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - migration-rollback
  - object-level-authz
  - input-validation
  - override-provenance-read-model
  - recompute-preserves-override
risk: high
tags:
  - targets
  - override
  - provenance
  - contracts
  - migration
approved_dependencies:
  - FTY-094
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/target-calculator.md
  - docs/contracts/daily-summary.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-095: Calorie- and Macro-Target Manual Override + Reset, with Provenance

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- FTY-094 — macro targets must exist on `daily_targets` before they can be made
  overridable. FTY-094 also owns the immediately prior additive change to
  `daily_targets`, so this story's migration must be authored **after** FTY-094's
  has landed (both touch the same table; the schema changes serialize — see the
  Readiness Sanity Pass). FTY-094 in turn carries the FTY-022 target foundation.

## Outcome

A user can manually override their daily calorie target (and their macro targets)
to a value of their choosing, and reset it back to the value Fatty derives from
their goal and body metrics. Today, the only way to change the target is to edit
the goal: `daily_targets` rows are always deterministically derived from
goal + profile, and the existing `clamped` flag marks only safety-floor clamping —
there is **no user-override concept anywhere in the model** (verified against
`backend/alembic/versions/0002_goals_and_daily_targets.py`,
`backend/app/models/targets.py`, `backend/app/services/targets.py`, and
`docs/contracts/target-calculator.md`). This story adds that concept end-to-end in
the backend so the read-model can honestly distinguish a derived target
("└ from your goal + metrics") from a user-set one ("✎ set by you") with a reset,
realising the design's "every number shows where it came from — including the
target itself" stance (`docs/design/ux-design.md` §4c). It is the backend the
mobile Profile control panel (FTY-102) and onboarding target reveal (FTY-103)
read; both are out of scope here.

## Scope

- **Additive, reversible migration on `daily_targets`** adding nullable
  user-override columns alongside the existing derived columns (which remain the
  source of truth for the derived value):
  - `override_calorie_target_kcal` (Integer, nullable) — the user-set calorie
    target, `NULL` when the target is derived.
  - The macro-override columns for the macro fields FTY-094 adds (one nullable
    override column per overridable macro target it introduces, named to mirror
    FTY-094's derived macro columns), `NULL` when derived.
  - `override_set_at` (timezone-aware DateTime, nullable) — when the override was
    last set, `NULL` when derived. Supports provenance/audit; carries no PII.
  The derived columns (`daily_calorie_target_kcal`, `clamped`, the FTY-094 macro
  columns, `inputs`, `assumptions`) keep their current meaning and stay populated
  with the derived value even while an override is in force. The migration applies
  cleanly on top of FTY-094's revision (`alembic upgrade head`) and rolls back
  fully (`alembic downgrade -1`), verified by an apply/rollback test.
- **A target read-model with explicit derived-vs-overridden provenance.** The
  effective calorie target a consumer should display/measure against is
  `override_calorie_target_kcal` when set, else `daily_calorie_target_kcal`. The
  read-model exposes, per target (calorie and each macro):
  - the **effective** value (what the app uses),
  - the **derived** value (always present — what a reset would restore),
  - a **`source`** provenance flag: `derived` | `user`.
  This is the shape `docs/contracts/daily-summary.md` and the Profile endpoint
  surface; the macro targets are versioned into `daily-summary.md` together with
  FTY-094 (today that contract notes "Macro targets are not part of FTY-022; when
  FTY-022 is extended with macro targets, this contract should be versioned to
  expose them").
- **A set-override operation** (extend the existing target service /
  owner-scoped target endpoint — do not invent a parallel surface) that records a
  calorie and/or macro override on the active goal's target, stamps
  `override_set_at`, and returns the updated read-model with `source: user`.
- **A reset-to-derived operation** that clears the override column(s) (calorie
  and/or macros, independently) back to `NULL`, so the effective value falls back
  to the derived value and `source` returns to `derived`.
- **Recompute preserves the in-force override.** Editing goal/pace/metrics already
  recomputes the derived target (the existing `compute_daily_target` flow). After
  this story, a recompute updates the **derived** columns but **leaves any set
  override intact and still in force** — the override is an explicit user choice
  that survives metric edits until the user resets it. The read-model still
  reports the freshly recomputed derived value (so a future reset restores the
  *current* derivation, not a stale one) while `source` stays `user`.
- **Override lifetime — documented rule (resolved here):** an override persists
  across derived recomputes and is cleared **only** by (a) explicit reset, or
  (b) deletion/replacement of the owning goal (the override columns live on
  `daily_targets`, which already `ON DELETE CASCADE`s from `goal_id`, so a
  replaced/deleted goal drops the override with its target — no orphaned
  overrides). No other event silently clears it. Document this rule in
  `target-calculator.md`.
- **Override validation reuses the existing documented safety band.** A manual
  calorie override must fall within the safety band already defined in
  `target-calculator.md` (floor 1500 kcal for `mifflin_st_jeor_plus5` / 1200 kcal
  for `mifflin_st_jeor_minus161`; ceiling 4000 kcal). Because an override is
  explicit user input, an out-of-band value is **rejected** with a clear
  validation error (`422`) rather than silently clamped — the user sees their
  value refused, not quietly altered (the derived path's `clamped` behaviour is
  unchanged). Macro overrides validate within the bounds FTY-094 documents for the
  corresponding macro target. Reuse the existing band constants; do not introduce
  new numbers.

## Non-Goals

- Deriving macro targets / the macro default split (protein anchored to
  bodyweight, the rest split) — that is FTY-094, a hard dependency.
- The mobile Profile "control panel for your numbers" UI, the "✎ set by you"
  badge, and the `[Reset]` control (FTY-102).
- The onboarding mini target-reveal and recompute animation (FTY-103); this story
  only guarantees the recompute updates the derived value and preserves the
  override server-side.
- Changing the derived calculator math, the `clamped` semantics, or the
  goal-editing flow itself.
- A target history/audit trail beyond the single `override_set_at` stamp.

## Contracts

- **`docs/contracts/target-calculator.md`** (version bump): add the override
  columns to the `daily_targets` schema; define the effective-target rule
  (override ?? derived), the `derived` | `user` provenance flag, the set/reset
  semantics, the documented override-lifetime rule (survives recompute; cleared
  only by reset or goal deletion via cascade), and the override validation rule
  (reject out-of-band `422`, reusing the existing safety band).
- **`docs/contracts/daily-summary.md`** (version bump, jointly with FTY-094):
  extend the `target` component so consumers receive, per target, the effective
  value, the derived value, and the `source` provenance flag. Preserve the
  existing no-target `null` representation for users with no active goal / no
  stored row.

## Security / Privacy

- **User-owned, object-level authorized on every path.** Set and reset operate
  only on the caller's own goal/target; reuse the existing fail-closed
  `GoalForbidden` discipline (cross-user or unowned/missing goal is
  indistinguishable — no existence oracle). Proven by negative authorization
  tests.
- **No untrusted input, no LLM, no external egress** — a bounded integer/float
  override validated against a documented band.
- **Safety floor is load-bearing:** rejecting an out-of-band override (rather than
  storing a dangerously low calorie target) keeps the clinically conservative
  minimum intact for unsupervised dieting. The band is already evidence-grounded
  in `target-calculator.md`; this story reuses it rather than re-deriving it.
- **Privacy / retention:** the override is sensitive derived body data — never
  logged (use user/goal ids, not target numbers). `override_set_at` is a bare
  timestamp, no PII. Retention follows the owning goal via the existing
  `ON DELETE CASCADE` from `goal_id`/`user_id`; document the override under the
  data-retention requirement for the new stored fields.
- Rated **high**: a schema migration on the table that drives the whole app's
  numbers, plus a public contract change to two consumed contracts and a new
  user-controllable value gated by a clinical safety bound.

## Acceptance Criteria

- The migration adds the nullable override columns to `daily_targets`, applies
  cleanly on top of FTY-094's revision (`alembic upgrade head`), and rolls back
  fully (`alembic downgrade -1`) — proven by an apply/rollback test.
- Setting a calorie override within the safety band persists
  `override_calorie_target_kcal` and `override_set_at`, and the read-model returns
  the override as the effective value with `source: user` while still reporting
  the derived value.
- Setting a macro override (for an FTY-094 macro target) behaves identically for
  that macro; calorie and macro overrides can be set and reset independently.
- Reset clears the targeted override column(s) back to `NULL`; the effective value
  falls back to the derived value and `source` returns to `derived`.
- Editing goal/pace/metrics recomputes the derived columns while any in-force
  override persists: a unit test sets an override, triggers a recompute, and
  asserts the derived value changed, the override is unchanged and still effective,
  `source` stays `user`, and a subsequent reset restores the **newly** derived
  value.
- An out-of-band override (below the variant floor or above the 4000 kcal ceiling;
  macro outside FTY-094's documented bounds) is rejected `422` and nothing is
  persisted — proven by a clamp-validation test at exact floor/ceiling and just
  outside.
- Cross-user / unowned-goal set and reset fail closed (`GoalForbidden` → the
  router's fail-closed status), proven by negative authorization tests.
- A user with no active goal / no stored target row still gets the existing
  `null`-target representation (no override path regression).
- `make verify` passes.

## Verification

- Backend verify command: from the repo root run `make verify` (which invokes
  `backend/verify.sh`: `uv sync --frozen --dev` then `ruff check`, `ruff format
  --check`, `mypy`, `pytest`). Equivalent direct run: `cd backend && ./verify.sh`.
- Migration apply/rollback test for the new override columns against a throwaway
  database, layered on FTY-094's revision.
- Unit tests for: override persistence (calorie + macro, independent),
  reset-to-derived, recompute-preserves-override (derived changes, override holds,
  reset restores the new derivation), and clamp validation (reject `422` at and
  beyond the band; accept at the floor/ceiling boundaries).
- Negative authorization tests proving cross-user/unowned set and reset fail
  closed with no existence oracle.

## Planning Notes

- The override columns live **on `daily_targets`** per the directed design, beside
  the derived columns, so a single row carries both the derivation and the user's
  choice and the effective value is a pure read-time `override ?? derived`. This is
  why "recompute" only needs to update the derived columns in place — it must not
  touch the override columns. If FTY-094 materialises a fresh `daily_targets` row
  per `for_date` rather than updating one current row, the author must carry the
  in-force override onto the newly materialised row for the same active goal so the
  override does not silently lapse on a date rollover; the contract behaviour
  (override persists until reset/goal-deletion) is the invariant, the row mechanics
  follow FTY-094's materialisation model.
- Reject-not-clamp for explicit overrides is deliberate: the derived path clamps
  and flags (`clamped`) because the system produced the number; an override is the
  user's number, so refusing it honestly beats silently altering it.

## Readiness Sanity Pass

- **Product decision gaps:** resolved. Override lives on `daily_targets` (directed);
  effective = override ?? derived; provenance is an explicit `derived` | `user`
  flag; override survives recompute and is cleared only by reset or goal-deletion
  cascade (documented rule); out-of-band overrides are rejected `422` reusing the
  existing safety band rather than silently clamped. The only dependency-coupled
  detail (exact macro column names/bounds) is pinned to FTY-094's definitions.
- **Cross-lane impact / sizing:** single boundary — all code is backend-core, one
  serializing lane. One big rock: a public contract change to two consumed
  contracts (`target-calculator.md`, `daily-summary.md`). The migration **adds
  columns, not a table**, so it is not the schema-table big rock; no new
  untrusted-input trust boundary. Contracts and security-privacy ride along and do
  not count as a second boundary. `review_focus` = 5 (at the ceiling, not over);
  `requires_context` = 6 (under 8). Within limits → one story, not a split.
  **Schema serialization:** this and FTY-094 both alter `daily_targets`; FTY-094 is
  a hard dependency precisely so the two migrations serialize (FTY-094's revision
  first, this one chained on top) and never race the same table — the reason this
  is `ready_with_notes` rather than `ready`: it cannot be authored until FTY-094's
  macro columns and macro bounds exist to reference.
- **Security/privacy risk:** high — migration on the table that drives every number
  in the app, a user-controllable value gated by a clinical safety bound, and two
  public contract changes. Mitigated by object-level fail-closed authz with
  negative tests, reject-out-of-band validation, never-log discipline, and cascade
  retention.
- **Verification path:** `make verify` + migration apply/rollback + override/reset/
  recompute/clamp unit tests + negative authz tests.
- **Assumptions safe for autonomy:** yes, once FTY-094 has landed. Scope is a
  self-contained additive schema change plus service/endpoint and contract updates,
  no external providers or LLM, with the one dependency coupling (macro
  columns/bounds) explicitly pinned to FTY-094.
