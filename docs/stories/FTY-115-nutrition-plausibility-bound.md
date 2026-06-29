---
id: FTY-115
state: merged
primary_lane: estimator
touched_lanes:
  - security-privacy
review_focus:
  - plausibility-bound
  - kj-kcal-guard
  - non-match-fallthrough
risk: medium
tags:
  - estimator
  - evidence
  - third-party-data
  - nutrition
  - hardening
approved_dependencies: []
requires_context:
  - docs/contracts/food-resolution.md
  - docs/contracts/evidence-retrieval.md
  - docs/architecture/evidence-retrieval.md
  - docs/standards/testing-standards.md
  - docs/security/security-baseline.md
autonomous: true
---

# FTY-115: Reject Physically-Impossible Per-100g Nutrition Facts (estimator)

## State

ready_with_notes

## Lane

estimator

## Dependencies

- None to schedule. This **hardens merged code**: the generic-food serving math
  (FTY-044, `food_serving.py`) and the evidence sources it feeds — FDC (FTY-060)
  and the OFF barcode client (FTY-061/062). This story changes only the
  facts-mapping seam in `fdc.py` and `off.py`; it adds no contract and no
  migration.
- **Coordination (same area as FTY-110):** FTY-110 (evidence clients fail closed
  on malformed payloads) edits the same FDC/OFF facts-mapping region. Both are
  estimator-lane and therefore serialize — whichever lands second rebases on the
  first. The two are natural siblings: FTY-110 catches a *malformed* body (bad
  types, missing ids) at parse; this catches a *well-typed but physically
  impossible* body after parse. The author of the second should expect the
  `_food_to_facts` / `_facts_per_100g` neighbourhood to have moved and should
  apply the plausibility gate on top of FTY-110's fail-closed handling, not
  re-litigate it.

## Outcome

A source row whose per-100g energy or macros are **physically impossible** — Open
Food Facts frequently mislabels a kJ figure as kcal (~4.184x calorie inflation),
or yields a negative/zero energy — no longer gets stored and shown as the day's
calories. The facts mapper applies a deterministic plausibility gate to the
per-100g `NutritionFacts` it builds, and a row that fails it becomes a **clean
non-match** (the existing `None` return), so resolution falls through to the next
source and ultimately to `needs_clarification` rather than silently committing an
absurd total.

This closes a real honesty hole on a documented low-trust boundary.
`NutritionFacts` is an unbounded float dataclass (`food_serving.py:89`), and the
two mappers take each source's energy verbatim: `_food_to_facts` (`fdc.py:378`,
`calories=float(energy)` at ~396) and `_facts_per_100g` (`off.py:351`,
`calories=float(nutriments.energy_kcal_100g)` at ~359, plus the per-serving
branch at ~369). `scale_facts` (`food_serving.py:182`) then just multiplies that
value by `grams / 100`, so a 1500 "kcal"/100g row (a kJ value passed through as
kcal) becomes a calorie total roughly four times reality with no signal. Today
the only rejection is "no energy value at all"; a present-but-impossible value
sails through.

## Scope

- **Add a deterministic plausibility predicate on per-100g `NutritionFacts`.** A
  pure helper (alongside the serving math in `food_serving.py`, or a small private
  guard the two mappers call) returns whether a per-100g fact sheet is physically
  possible. The rule:
  - **Energy out of range → fail.** Reject `calories < 0` and `calories` above the
    physical maximum energy density of food (see Planning Notes: cap at **900
    kcal/100g**). Reject `calories <= 0` as not a costable match (zero energy
    cannot be a generic-food match and is the typical shape of an empty/garbage
    nutrient row; this extends the existing "no costable energy → non-match"
    rule).
  - **Negative macros → fail.** Reject any of `protein_g`, `carbs_g`, `fat_g`
    `< 0`. **Zero macros are valid** and must pass (a pure-fat food legitimately
    has zero protein and zero carbs).
- **Apply the gate at both mappers, after the facts are constructed.** In
  `_food_to_facts` (fdc.py) and in **both** branches of `_facts_per_100g` (off.py
  — the per-100g branch and the per-serving→per-100g conversion branch), check the
  built `NutritionFacts`; if implausible, **return `None`** exactly as the
  no-energy path already does. A failing row never reaches `ProductFacts` /
  `content_hash` / `scale_facts`.
- **Keep the gate in the canonical per-100g space.** Apply it to the final
  per-100g `NutritionFacts` (after OFF's per-serving conversion), so the same
  threshold governs every source uniformly and a per-serving row converted to a
  huge per-100g figure is caught too.

## Non-Goals

- **No automatic kJ→kcal conversion or repair.** This story *detects and
  fail-closes only*. Dividing a suspected-kJ value by 4.184 guesses the upstream's
  intent (the row may be genuinely garbage, double-counted, or a different unit)
  and risks fabricating a confident-but-wrong number — the opposite of the honesty
  guarantee. Auto-conversion is explicitly out of scope.
- **No malformed-payload / type handling.** Bad types, missing ids, and unparseable
  bodies are FTY-110's job. This story assumes a well-typed `NutritionFacts` and
  judges only its *values*.
- **No LLM-transport change** (FTY-113/114) and **no change to evidence-retrieval
  contracts** or the resolver fallback ordering. The resolve / clarify / non-match
  outcomes keep their current shapes; this only changes whether a given row is
  offered as a match.
- **No cross-macro Atwater reconciliation.** Checking that energy implied by macros
  (4/4/9) agrees with reported energy is a richer, false-reject-prone check left
  out of this slice; only the absolute physical bounds are enforced.

## Contracts

- **None.** This is internal mapper behaviour. A failing row produces the existing
  `None` non-match the resolvers and `food_step.py` already consume, which routes
  through the documented fall-through to `needs_clarification`
  (`docs/contracts/food-resolution.md`). The resolve / clarify / non-match shapes
  are unchanged; no contract doc needs a version bump.

## Security / Privacy

- **Hardens a documented low-trust third-party-data boundary.** OFF is explicitly
  "uneven" community data and FDC is external; `docs/architecture/`
  `evidence-retrieval.md` treats both as untrusted until mapped. Today an
  impossible value is committed verbatim as the user's calories — a silently-wrong
  total is the worst failure for an app whose core promise is an honest count.
  After the fix, a physically-impossible row fails closed to a clean
  non-match/clarify.
- **Not a new trust boundary.** This hardens an existing untrusted input; it adds
  no image/fetch/OCR/upload surface, no contract, and no migration. The gate is a
  pure value check that never echoes raw provider text.
- **Rated medium:** third-party-data hardening on the estimation path. The cost of
  the current bug is a silently inflated/garbage calorie total on hostile or
  mislabelled upstream data; the fix is bounded, deterministic, and local.

## Acceptance Criteria

- **kJ-as-kcal inflation rejected (OFF):** an OFF product whose `energy_kcal_100g`
  is a mislabelled kJ figure (e.g. ~1500/100g) maps to `None` — no `ProductFacts`,
  nothing stored — so resolution falls through to the next source / clarify rather
  than committing a ~4x calorie total. Cover the per-serving branch too (a
  per-serving energy that converts to an over-cap per-100g value is rejected).
- **kJ-as-kcal inflation rejected (FDC):** an FDC food with a per-100g energy above
  the cap makes `_food_to_facts` return `None` (both via `_first_match`/`lookup`
  and via `list_matches`).
- **Negative / zero energy rejected:** a row with `calories < 0` or `calories == 0`
  maps to `None` on both sources.
- **Negative macro rejected:** a row with a negative `protein_g` / `carbs_g` /
  `fat_g` maps to `None`.
- **Legitimate high-fat food still resolves:** a row just under the cap (e.g. olive
  oil at ~884 kcal/100g, fat ~100g, protein 0, carbs 0) resolves to the same
  `ProductFacts` as before — zero macros do **not** trip the gate, and a genuine
  energy-dense food is not a false reject.
- **`scale_facts` unchanged on valid rows:** a well-formed per-100g fact sheet
  produces the identical `ScaledNutrition` (and the mapped `ProductFacts` /
  `content_hash`) as before — the gate is behaviour-preserving on plausible data.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New plausibility tests** in `tests/test_off_client.py` and
  `tests/test_fdc_client.py`: an over-cap (kJ-as-kcal, ~1500/100g) energy, a
  negative energy, a zero energy, and a negative macro each map to `None`
  (non-match), asserted at the mapper / client `lookup` (and FDC `list_matches`)
  level — nothing reaches `ProductFacts`. Cover the OFF per-serving→per-100g branch
  with an energy that converts to an over-cap per-100g value.
- **No-false-reject test:** a legitimate high-fat row just under the cap (olive
  oil ~884 kcal/100g, macros fat ~100 / protein 0 / carbs 0) still resolves to the
  expected `ProductFacts`.
- **Behaviour-preserving test:** a known-good FDC and OFF payload maps to the same
  `ProductFacts` / `content_hash` as before, and `scale_facts` on a valid
  `NutritionFacts` returns the same `ScaledNutrition` as today.
- Existing FDC/OFF mapper and serving-math tests remain green unchanged.

## Planning Notes

- **The 900 kcal/100g cap (the decision behind `ready_with_notes`).** Recommend a
  conservative absolute ceiling of **900 kcal/100g**. Rationale: by the standard
  Atwater factors the most energy-dense macronutrient is fat at 9 kcal/g, so a
  hypothetical 100% fat food is ~900 kcal/100g; pure cooking oils sit at ~884
  kcal/100g (≈99% fat), and alcohol (7 kcal/g) and the other macros (4 kcal/g) are
  all lower. 900 is therefore just above the physical maximum — it admits every
  real food including the densest oils, while a kJ-as-kcal value (×4.184) lands far
  above it (a 600 kcal/100g food mislabelled in kJ reads ~2510). Picking the cap
  *just above* the true max rather than tight to it is deliberate: it makes a false
  reject of a legitimate food effectively impossible, which matters more here than
  catching a borderline-inflated row. The author may pin a small explicit margin
  constant; do **not** lower the cap toward typical foods.
- **Non-match vs needs_clarification (the second small decision).** Recommend a
  **clean non-match** — return `None`, identical to the existing no-energy path —
  rather than minting a new `needs_clarification` outcome from inside the mapper. A
  `None` lets resolution fall through to the next configured source, and only if
  *no* source yields a plausible match does the documented routing land on
  `needs_clarification` (`docs/contracts/food-resolution.md`: "No confident source
  match → NeedsClarification"). This reuses the contract's existing semantics, adds
  no new outcome type, and keeps the slice inside one boundary.
- **Why the gate lives on per-100g facts.** Applying it after OFF's
  per-serving→per-100g conversion means one threshold governs every source and
  every basis uniformly, and a per-serving figure that balloons into an absurd
  per-100g value is caught by the same rule.
- **Sibling of FTY-110.** FTY-110 maps a *malformed* body to a fail-closed error
  type; this maps a *well-typed but impossible* body to a non-match. They touch the
  same mappers, so they serialize and the second rebases — see Dependencies.

## Readiness Sanity Pass

- **Product decision gaps:** two small, reversible calibration calls — the cap
  value (recommended **900 kcal/100g**, justified by the Atwater max-density
  reasoning above) and non-match-vs-clarify (recommended clean non-match, reusing
  the existing `None` path) — are both decided and pinned here; `ready_with_notes`
  only for those. The cap rests on a factual nutrition question (food energy
  density), but it is settled textbook science — Atwater factors (fat 9, carb/
  protein 4, alcohol 7 kcal/g) put the physical ceiling at ~900 kcal/100g — so it
  is grounded inline rather than via a research subagent; the cost of being wrong
  is low because the cap is set conservatively above the true maximum.
- **Cross-lane impact:** primary estimator; security-privacy rides along
  (non-serializing) since it hardens a low-trust data boundary. **Single boundary,
  zero big rocks:** no public contract change, no schema migration, no new
  untrusted-input trust boundary (an existing untrusted input is being hardened).
  Stays wholly in the estimator lane and serializes behind/ahead of FTY-110.
- **Size:** `review_focus` = 3 (plausibility-bound, kj-kcal-guard,
  non-match-fallthrough); `requires_context` = 5. Well under both ceilings — a
  deliberately small quick-win, kept as one story.
- **Security/privacy risk:** medium — third-party-data hardening on the estimation
  path; the fix removes a silently-wrong-calorie-total hole, with no new surface
  and no contract change.
- **Verification path:** `make verify` + new FDC/OFF plausibility tests (over-cap
  kJ-as-kcal, negative/zero energy, negative macro → non-match, including the OFF
  per-serving branch) + a no-false-reject high-fat test + a behaviour-preserving
  good-payload / `scale_facts` test; existing mapper and serving-math tests stay
  green.
- **Assumptions safe for autonomy:** yes — a local, pure value-check added to two
  existing mappers with both judgment calls (the 900 kcal/100g cap, clean
  non-match) pinned here; no contract, no migration, no external provider call
  (sources are injected/faked in tests), no UI.
