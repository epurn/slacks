---
id: FTY-105
state: ready_with_notes
primary_lane: backend-core
touched_lanes:
  - contracts
risk: high
tags:
  - targets
  - macros
  - provenance
  - daily-summary
  - contracts
approved_dependencies:
  - FTY-094
  - FTY-095
requires_context:
  - docs/design/ux-design.md
  - docs/contracts/daily-summary.md
  - docs/contracts/target-calculator.md
review_focus:
  - effective-value-uses-override-not-derived
  - per-target-provenance-source-flag-correct
  - macro-targets-int-grams-distinct-from-float-intake-macros
  - no-target-null-representation-preserved
  - additive-read-only-no-persistence-no-migration
autonomous: true
---

# FTY-105: Surface Macro Targets (with Provenance) in the Daily-Summary Read-Model

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- **FTY-094** — the deterministic target calculator must emit
  protein/carb/fat targets (in `backend/app/schemas/targets.py`) before they can
  be surfaced. FTY-094 defines the macro target **units (int grams)**, the field
  naming parallel to `intake.protein_g/carbs_g/fat_g`, and the documented bounds.
  This story reads those targets; it never derives them.
- **FTY-095** — the persisted macro-target columns + the calorie/macro override +
  the **derived-vs-overridden read-model** (effective ?? derived + a
  `derived | user` `source` flag) must exist on `daily_targets` before they can be
  surfaced. This story **reuses FTY-095's read-model** to resolve each effective
  value and its provenance; it never re-implements the `override ?? derived` rule.
- Both are hard dependencies — this story is `ready_with_notes` (not `ready`)
  because it cannot be authored until FTY-094's macro outputs and FTY-095's
  persisted columns + read-model land. It does not touch `daily_targets`, any
  migration, or the override service itself. It carries the FTY-071 daily-summary
  foundation (`backend/app/services/daily_summary.py`,
  `backend/app/schemas/daily_summary.py`, `docs/contracts/daily-summary.md`),
  already merged.

## Outcome

The daily-summary endpoint returns, for the requested day, the **per-day macro
targets (protein, carbohydrate, fat — in grams)** alongside the existing calorie
target, each carrying the **derived-vs-overridden provenance** FTY-095 records:
the *effective* value the app measures against (`override ?? derived`), the
*derived* value a reset would restore, and a `derived | user` `source` flag. This
is the read-model the mobile Today P/C/F chips (FTY-098) and the Profile control
panel (FTY-102) consume to render consumed-vs-target macros and the "✎ set by
you" / "└ from your goal + metrics" provenance label, realising the design's
"every number shows where it came from — including the target itself"
(`docs/design/ux-design.md` §4c).

This is the **daily-summary surfacing deliberately carved out of FTY-094** (which
held one estimator boundary and explicitly left `daily-summary.md` /
`daily_summary.py` to a dependent backend-core story) and out of FTY-095 (which
owns the persistence + override + read-model, not the daily-summary DTO). Net-new:
today `DailySummaryTargetDTO` exposes only `calories: int` (the bare derived
calorie target) and `daily-summary.md` states "Macro targets are not part of the
FTY-022 contract and are not included." This story versions that contract to
expose all four targets with provenance, and corrects the calorie target to show
the **effective** value (so a user who overrode their calories sees their number,
not the stale derived one).

## Scope

A pure, additive read-model extension over data FTY-094/FTY-095 already populate.
No new persistence, no migration, no override logic — the same read-only posture
as FTY-071.

- **Extend the target DTO** (`backend/app/schemas/daily_summary.py`) to a uniform
  per-target provenance shape. Introduce a small reusable value object —
  `effective` (what the app measures against), `derived` (always present; what a
  reset restores), and a `source: Literal["derived", "user"]` flag — and apply it
  to **all four** targets:
  - `calories` (kcal, int) — now an effective/derived/source object instead of a
    bare `int`, because FTY-095 makes the calorie target overridable too.
  - `protein_g`, `carbs_g`, `fat_g` (grams, int) — the new macro targets.
  - The top-level `target` stays `DailySummaryTargetDTO | None`; `extra="forbid"`
    is preserved on every DTO.
  - Macro target values are **int grams** (FTY-094/FTY-095 store int grams),
    deliberately distinct from the **float, 0.1-rounded** consumed macros in
    `intake.protein_g/carbs_g/fat_g` — target vs. consumed must read as clearly
    separate components, not be conflated.
- **Resolve targets via FTY-095's read-model** (`backend/app/services/daily_summary.py`,
  `_resolve_target`). For the active goal's `daily_targets` row on the day, obtain
  each target's effective value, derived value, and `source` flag **from FTY-095's
  read-model helper** and map them into the DTO. Do **not** re-derive
  `override ?? derived` or re-read raw override columns directly here — the effective
  rule and the `source` semantics are owned by FTY-095; this story consumes them so
  the two surfaces (daily-summary and the Profile/target endpoint) can never drift.
- **Preserve the no-target representation.** When the user has no active goal or no
  stored `daily_targets` row for the requested day, the top-level `target` remains
  `None` (explicit JSON `null`), exactly as today — a `null` target is distinct
  from a zero target. No override path changes this.
- **Leave intake and exercise untouched.** `intake` (consumed calories + macros)
  and `exercise` (burn) keep their current shape, units, rounding, and
  finalized-state filtering. This story only changes the `target` component.
- **Update `docs/contracts/daily-summary.md`** (contracts lane), version **1 → 2**:
  document the new `target` shape (the four targets, each with
  effective/derived/source), the macro target **int-gram** units and their
  distinction from the float consumed macros, the **effective = override ?? derived**
  rule, the `derived | user` provenance flag (cross-referencing FTY-095's
  read-model and `target-calculator.md`), and replace the line "Macro targets are
  not part of the FTY-022 contract and are not included" with the macro target
  definition. Keep the no-target `null` representation and the existing
  authorization, timezone, finalized-filter, and rounding sections unchanged.

## Non-Goals

- **Deriving macro targets** — FTY-094 (estimator). This story reads them.
- **Persisting macro targets, the override + reset, and the read-model provenance
  source** — FTY-095 (backend-core). This story consumes FTY-095's read-model and
  adds **no** column, migration, or override endpoint. It does not touch
  `backend/app/models/targets.py`, `backend/app/services/targets.py`, or any
  Alembic revision.
- **The mobile UI** — the Today P/C/F chips (FTY-098) and Profile macro targets +
  override display (FTY-102), which consume this DTO.
- Changing `intake` / `exercise` shape, units, rounding, the finalized-state
  filter, the timezone/day resolution, or the authorization rule.
- Adding a per-target history/audit trail (FTY-095 keeps a single
  `override_set_at` stamp; this read-model does not surface it).

## Contracts

- **`docs/contracts/daily-summary.md`** (Version 1 → 2): the single big rock — a
  public DTO/contract change. Adds the four-target provenance shape
  (effective/derived/`source`), the macro target int-gram units, and the
  effective = override ?? derived rule; removes the "macros not included" line.
  This contract change is **owned here**, not in FTY-095 (see the Readiness Sanity
  Pass coordination note): FTY-095 owns the `daily_targets` columns + read-model;
  FTY-105 owns the daily-summary surfacing of them.
- `DailySummaryTargetDTO` (+ the new per-target value object) in
  `backend/app/schemas/daily_summary.py` — the daily-summary endpoint's own output
  contract (the FTY-071/FTY-094 pattern: a component owning its DTO, with contracts
  as the touched doc lane).
- **Breaking shape change (intended, pre-v1 clean break):** `target.calories`
  changes from a bare `int` to an effective/derived/source object. This breaks the
  currently-merged FTY-075 mobile daily-summary client's flat parse; that is a
  deliberate clean break absorbed by the mobile consumer stories (FTY-098/FTY-102),
  which are built against this Version-2 shape. No back-compat shim — there are no
  users (pre-v1).
- No change to `intake`, `exercise`, `daily_targets`, the calculator, or any
  migration.

## Security / Privacy

- A **read-model of the user's own targets** — no untrusted input, no new trust
  boundary, no LLM, no external egress, no new persistence. Same posture as FTY-071.
- **Object-level authorization is unchanged and load-bearing:** every path stays
  behind the existing fail-closed `_authorize` (cross-user access → `404`, no
  existence oracle). A negative authorization test must remain green.
- Targets, including any user override value, are **sensitive derived body data**:
  returned only to the owner and **never logged** (use user/goal ids, not target
  numbers), inheriting the existing daily-summary never-log discipline.
- Rated **high**: a public DTO/contract change that drives user-facing health
  numbers (the Today chips and Profile measure intake against these targets). A
  wrong effective-vs-derived resolution or a wrong `source` flag ships a misleading
  number or a false "set by you" provenance to every user — correctness of the
  read-model mapping is the load-bearing risk, not a new attack surface. Per the
  sizing rule, when risk is ambiguous, estimate big.

## Acceptance Criteria

- `DailySummaryTargetDTO` exposes `calories`, `protein_g`, `carbs_g`, `fat_g`,
  each as a provenance object with `effective` (int), `derived` (int), and
  `source` (`"derived" | "user"`); `extra="forbid"` preserved on every DTO. The
  top-level `target` is still `DailySummaryTargetDTO | None`.
- When a `daily_targets` row exists for the active goal on the day, all four
  targets are returned with `effective = override ?? derived`, `derived` = the
  derived value, and `source` resolved from FTY-095's read-model. The service
  obtains these **from FTY-095's read-model**, not by re-deriving `override ??
  derived` or reading override columns directly — proven by the override case
  below resolving identically to FTY-095's own surface.
- A target with a **calorie override** in force returns
  `calories.effective` = the override, `calories.derived` = the derived value, and
  `calories.source = "user"`; a non-overridden target returns
  `effective == derived` with `source = "derived"`. Proven by a test.
- A target with a **macro override** (e.g. protein) on a particular macro returns
  `source = "user"` for that macro only, with the others `derived` — calorie and
  per-macro provenance are independent (matching FTY-095's independent
  override/reset). Proven by a test.
- Macro targets are **int grams** and are distinct from the **float** consumed
  macros: a test asserts `intake.protein_g` (float) and
  `target.protein_g.effective` (int) are both present and not conflated.
- **No-target case preserved:** a user with no active goal or no stored
  `daily_targets` row for the day still gets top-level `target = null`; no override
  path regresses this. Proven by the existing no-target test staying green.
- **Authorization unchanged:** cross-user / unowned access still fails closed as
  `404`; the existing negative authorization test passes unchanged.
- `docs/contracts/daily-summary.md` documents the four-target provenance shape,
  the int-gram macro units vs. float consumed macros, and the effective =
  override ?? derived rule; the "Macro targets are not part of the FTY-022
  contract" line is removed; the contract **Version reads 2**.
- `make verify` passes.

## Verification

- **Root `make verify`** (runs `backend/verify.sh`: `uv sync --frozen --dev`,
  `ruff check`, `ruff format --check`, `mypy`, `pytest`). Equivalent direct run:
  `cd backend && ./verify.sh`.
- **Focused daily-summary tests** (`backend/tests/test_daily_summary_api.py`,
  extended): assert the daily-summary response includes the four targets with
  `effective`/`derived`/`source`; pin the calorie-override case
  (`effective` = override, `source = "user"`, `derived` still reported), the
  macro-override case (per-macro `source` independence), the derived-only case
  (`effective == derived`, `source = "derived"`), and the int-gram-target vs.
  float-intake-macro distinction.
- Assert the **no-target** path still returns top-level `target = null` and the
  **cross-user negative authorization** test still fails closed `404` — both
  unchanged from FTY-071.
- Confirm `docs/contracts/daily-summary.md` Version reads **2** and documents every
  new field.

## Planning Notes

- **Why reuse FTY-095's read-model rather than re-resolve here.** FTY-095 owns the
  `override ?? derived` rule and the `derived | user` semantics, and exposes the
  same shape on the Profile/target endpoint. If the daily-summary re-implemented
  the resolution it could drift from the Profile surface (e.g. a future change to
  what counts as "user"). Consuming one read-model keeps the two surfaces identical
  by construction — the author should locate FTY-095's read-model helper and map
  it, not re-read raw columns.
- **Uniform provenance on all four targets (incl. calories).** FTY-095 makes the
  calorie target overridable, so surfacing only macros with provenance while
  leaving `calories` a bare derived int would (a) misreport an overridden calorie
  target and (b) make the client special-case one target. A single value object
  applied to all four is the honest, consistent shape and matches the design's
  "every number shows where it came from — including the target itself."
- **Int target grams vs. float intake grams.** FTY-094 emits int gram targets and
  FTY-095 persists them as ints; consumed macros are float sums rounded to 0.1.
  Keeping the target ints (not coercing to float) preserves each component's native
  precision and keeps target-vs-consumed visibly distinct in the DTO.

## Readiness Sanity Pass

- **Product decision gaps:** none. The DTO shape (four targets, each
  effective/derived/`source`), the units (int target grams vs. float intake grams),
  the effective = override ?? derived rule, the no-target `null` preservation, and
  the reuse-FTY-095's-read-model directive are all resolved. The dependency-coupled
  details (exact macro column/field names, the read-model helper signature, the
  macro bounds) are pinned to FTY-094/FTY-095's definitions, which is why this is
  `ready_with_notes` rather than `ready` — buildable the moment both land. No
  health/nutrition decision is made here (the evidence-based ratios were settled in
  FTY-094), so no research is required.
- **Cross-lane impact / sizing — within limits.** Single serializing boundary: all
  code is **backend-core** (`schemas/daily_summary.py`, `services/daily_summary.py`),
  the DTO being the endpoint's own output contract. One big rock: a public
  contract change (`daily-summary.md` DTO, version 1 → 2). **No second boundary** —
  no migration/table (FTY-095 owns the columns), no new untrusted-input trust
  boundary (read-model of the user's own data), no second serializing lane.
  Contracts is the non-serializing doc lane and rides along. `review_focus` = 5 (at
  the ceiling, not over); `requires_context` = 3 (≤ 8). This is exactly the slice
  FTY-094 carved out to avoid a second backend-core boundary + a second
  public-contract change in one story — kept as its own dependent boundary here.
- **Dependency ordering (recorded).** FTY-094 (calculator emits macro targets) →
  FTY-095 (persists macro columns + override + read-model on `daily_targets`) →
  **FTY-105** (surfaces them in daily-summary). FTY-105 must be authored only after
  both have merged: it reads FTY-095's persisted columns and read-model, which
  depend on FTY-094's macro outputs. FTY-105 touches no migration, so it does not
  serialize against the `daily_targets` schema (FTY-094/FTY-095 own that ordering).
- **Contract-ownership coordination (flag for the steward/planner).** FTY-095's
  current Contracts section also claims the `daily-summary.md` version bump
  ("jointly with FTY-094"). Per this carve-out, the **daily-summary surfacing is
  owned by FTY-105**, not FTY-095 — FTY-095 owns the `daily_targets` columns,
  override, and read-model (and its own Profile/target endpoint contract). To avoid
  a double edit / merge conflict on `daily-summary.md`, FTY-095's daily-summary
  version-bump line should defer to FTY-105; recommend trimming FTY-095's Contracts
  note to its `target-calculator.md` + Profile-endpoint surface before both author.
  This is a planning-doc reconciliation, not a blocker for building FTY-105.
- **Security/privacy risk:** high by content (a public contract change driving
  user-facing health numbers), not by surface — a read-only model of the user's own
  data, existing fail-closed authz reused and tested, never-log discipline inherited.
- **Verification path:** `make verify` + extended
  `tests/test_daily_summary_api.py` cases pinning the override/derived provenance,
  per-target independence, int-vs-float distinction, and proof the no-target and
  negative-authz paths are unchanged.
- **Assumptions safe for autonomy:** yes, once FTY-094 and FTY-095 have merged. The
  change is additive and read-only over data those stories populate, with the one
  dependency coupling (read-model helper + macro field names) explicitly pinned to
  FTY-095/FTY-094. The only break is the intended pre-v1 `target.calories` shape
  change, absorbed by the mobile consumer stories.
