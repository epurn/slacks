---
id: FTY-132
state: ready
primary_lane: estimator
touched_lanes: []
review_focus:
  - plausibility-gate-on-official-source
  - per-100g-canonical-space
  - falls-through-not-raises
  - parity-with-fdc-off
risk: medium
tags:
  - estimator
  - official-source
  - model-prior
  - nutrition-plausibility
  - fail-closed
approved_dependencies: []
requires_context:
  - docs/contracts/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/standards/testing-standards.md
  - docs/standards/coding-standards.md
autonomous: true
---

# FTY-132: Apply the Physical-Plausibility Gate to Official-Source / Model-Prior Facts (estimator)

## State

ready

## Lane

estimator

## Dependencies

- **None to schedule.** `approved_dependencies: []` — the plausibility gate
  (`nutrition_facts_plausible`, FTY-115) and the official-source step (FTY-062) are
  both merged. This story wires the existing gate into the one resolution path that
  skips it.
- **Serialization note:** one of four estimator-lane release-audit fix-stories
  (FTY-131/132/135/137) that serialize on the estimator lane by changed-file path.
  This story edits `backend/app/estimator/official_step.py`; the others edit
  different estimator files, so there is no content overlap, but they cannot author
  simultaneously. **Rebase on whatever estimator work merges first** before opening
  the PR.

## Outcome

The **least-trusted** nutrition source — facts an LLM transcribed from a scraped
official-source page or produced as a model-prior estimate — gets the **same**
physical-plausibility gate already enforced on the more-trusted FDC and OFF
database paths. Today it is the least guarded source.

1. **The official-source/model-prior path skips the FTY-115 gate.**
   `_to_per_100g` (`backend/app/estimator/official_step.py` ~425–450) and
   `_build_item` (~347–411) convert the LLM-supplied `EstimatedFacts` to canonical
   per-100g and persist them **without** calling `nutrition_facts_plausible`
   (≤ ~900 kcal/100g, non-negative macros, finite values). The FDC path
   (`backend/app/estimator/fdc.py:411`) and both OFF paths
   (`backend/app/estimator/off.py:387`, `:398`) run the gate and return `None` on
   failure.
2. **The only existing bound is far too generous.** The official-source schema caps
   `calories` at `MAX_ENERGY_KCAL = 10_000` (`backend/app/schemas/official_source.py`
   ~51, ~98) — explicitly "a fail-closed ceiling on the transcribed numbers, not a
   nutrition judgement." A kJ-value-mislabelled-as-kcal (the canonical OFF failure
   FTY-115 was written for) lands ~4× inflated at ~3700 kcal/100g: well under
   10,000, so it passes the schema and gets **committed into the day's totals**.

After this story, an implausible official-source or model-prior fact sheet falls
through to the resolver's existing non-match / clarify behaviour (page → model-prior;
model-prior → `needs_clarification`) exactly as an implausible FDC/OFF row does —
never a stored absurd total.

## Scope

All edits are in `backend/app/estimator/official_step.py` and its tests.

- **Run `nutrition_facts_plausible` in the canonical per-100g space.** The gate
  lives in per-100g space (FTY-115), and `_to_per_100g` is exactly where the facts
  become per-100g. Add the check there: after computing the per-100g
  `NutritionFacts` (both the `PER_100G` direct-use branch and the converted
  `PER_SERVING` branch), return `None` when `nutrition_facts_plausible(per_100g)` is
  `False`. Returning `None` from `_to_per_100g` already means "cannot canonicalise →
  caller falls through," so this reuses the established non-match channel.
- **Confirm `_build_item` honours the fall-through.** `_build_item` already returns
  `None` when `_to_per_100g(facts)` is `None` (~372–374), so gating inside
  `_to_per_100g` is sufficient and `_build_item` needs no separate gate — but verify
  the call site treats a `None` from `_build_item` as "try the next source / fall to
  model-prior," matching how an unresolvable-canonicalisation already behaves. (If
  the implementer finds a code path that reaches `_build_item` without going through
  `_to_per_100g`, gate it there too — but none is expected.)
- **Import the gate** from `app.estimator.food_serving` (where FDC/OFF import it),
  not a re-implementation.
- **Add focused unit tests** (see Verification) for the inflated-kJ-as-kcal case on
  both the page-transcription (official-source) and model-prior branches, and for
  `per_serving` facts that are plausible per serving but convert to an implausible
  per-100g.

## Non-Goals

- **No contract change.** `docs/contracts/evidence-retrieval.md` (the Fallback Rule)
  and `docs/contracts/food-resolution.md` describe the fall-through-to-model-prior /
  clarify behaviour this change conforms to; neither is modified. The observable
  contract is unchanged — an implausible source now produces the *already-specified*
  fall-through outcome instead of a stored bad total.
- **No change to the gate itself.** `nutrition_facts_plausible` and its thresholds
  (≤ ~900 kcal/100g, non-negative, finite) are reused verbatim; do not re-tune them
  here — uniform thresholds across all sources is the point.
- **No change to the schema ceiling.** `MAX_ENERGY_KCAL = 10_000` stays as the
  outer fail-closed transcription cap; the plausibility gate is the *inner* nutrition
  bound applied after canonicalisation. They are complementary, not duplicative.
- **Do not alter the search/fetch/extract orchestration, the model-prior prompt, or
  the provenance/evidence-row writing** beyond adding the gate.
- **Do not touch the FDC/OFF paths** — they already gate correctly; this is bringing
  the official-source path up to their level, not refactoring them.

## Contracts

- **None modified.** Both referenced docs are consulted to confirm the fall-through
  semantics; the change makes the official-source path *match* the documented
  Fallback Rule rather than changing it.

## Security / Privacy

- **Trust-boundary hardening on already-existing untrusted input.** The
  official-source path consumes the **least-trusted** nutrition data in the system:
  an LLM transcription of a fetched (untrusted) web page, or a model-prior guess.
  Today an inflated/garbage value within the generous schema ceiling is committed to
  the user's day. This story applies the same physical gate the trusted database
  paths already enforce, so impossible numbers fail closed (fall through) rather than
  corrupting totals. **No new trust boundary is introduced** — the page-fetch and LLM
  surfaces already exist (FTY-062/078/079); this only adds a guard on their output.
- No new input field, endpoint, stored column, or migration. No PII handling change —
  the gate inspects only numeric facts.

## Acceptance Criteria

- `_to_per_100g` returns `None` (non-match / fall-through) when the canonical
  per-100g facts fail `nutrition_facts_plausible`, for **both** the `PER_100G`
  direct branch and the `PER_SERVING`-converted branch.
- An official-source **page transcription** reporting ~3700 kcal/100g (kJ-as-kcal,
  under the 10,000 schema ceiling) does **not** become a `derived_food_items` row;
  the resolver falls through to model-prior.
- A **model-prior** estimate with an implausible per-100g value does **not** persist;
  the candidate routes to `needs_clarification` (the model-prior fall-through), not a
  stored absurd total.
- A `per_serving` fact sheet that is plausible per serving but yields an implausible
  per-100g after conversion falls through (gate is in canonical space).
- **Plausible facts are unaffected** — a normal branded product still resolves to a
  `derived_food_items` row with its `evidence_sources` row exactly as before; a
  genuine zero-calorie item (energy = 0) still resolves (the gate permits zero).
- No schema, contract, router, or migration change; FDC/OFF paths untouched.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **New unit tests in the official-source step suite:**
  - Page-transcription branch: validated `EstimatedFacts` at ~3700 kcal/100g →
    `_to_per_100g` returns `None`; end-to-end, the candidate falls through to
    model-prior (no derived item committed for the page).
  - Model-prior branch: an implausible model-prior estimate → no persisted item;
    candidate routes to `needs_clarification`.
  - `per_serving` conversion: plausible-per-serving, implausible-per-100g → falls
    through.
  - Plausible control: a normal product (and a separate energy = 0 zero-cal item)
    still resolves and persists with its evidence row — proving the gate doesn't
    over-reject.
- **Existing official-source, FDC, and OFF step tests stay green** — no assertion
  edits; FDC/OFF behaviour is untouched and the official-source happy path is
  preserved.

## Planning Notes

- **Where the gate goes:** `_to_per_100g` is the single canonicalisation chokepoint
  for the official-source path and already returns `None` to mean "fall through," so
  it is the natural and minimal home — gating there covers both `_build_item` callers
  and keeps the fix to one function. This mirrors FDC/OFF, which gate at the point
  their facts reach canonical per-100g.
- **Why per-100g space:** FTY-115 deliberately put the gate in canonical per-100g so
  one threshold governs every source uniformly, including per-serving values
  converted up. Gating before conversion would let a per-serving inflation slip
  through; gate after.
- **Two ceilings, on purpose:** the schema's `MAX_ENERGY_KCAL = 10_000` is the outer
  anti-garbage transcription cap; `nutrition_facts_plausible` (~900 kcal/100g) is the
  inner physical-nutrition bound. The kJ-as-kcal case is precisely the gap between
  them — that gap is what this story closes.
- **No evidence research needed:** the ~900 kcal/100g threshold is already settled
  and documented in FTY-115 (pure fat ≈ 9 kcal/g; cooking oils ~884 kcal/100g); this
  story reuses it verbatim rather than re-deriving a number.

## Readiness Sanity Pass

- **Product decision gaps:** none. The threshold is reused from FTY-115's already
  evidence-grounded gate; no new health/nutrition judgement is made, so no research
  is warranted (researching the obvious / what the codebase already answers is out of
  scope).
- **Cross-lane impact:** primary **estimator**, **no touched lanes** — internal to
  the estimator pipeline. **Single boundary, zero big rocks:** no public contract
  change (the change conforms the path *to* the documented Fallback Rule), no schema
  migration / new table, **no new untrusted-input trust boundary** — the page-fetch
  and model-prior surfaces already exist; this adds a guard on their output. One
  serializing estimator-lane file.
- **Size:** `review_focus` = 4 (under the 5 ceiling); `requires_context` = 4 (under
  8). Comfortably one story.
- **Security/privacy risk:** medium — it hardens the handling of the system's
  least-trusted nutrition input (good), and the only over-reject risk (rejecting a
  legitimate high-density food) is bounded by reusing the already-vetted ~900
  kcal/100g threshold, with a plausible-control test (incl. energy = 0) proving the
  happy path survives.
- **Verification path:** `make verify` + new tests for the kJ-as-kcal inflation on
  both branches, the per-serving conversion case, and a plausible/zero-cal control;
  existing FDC/OFF/official-source suites stay green unchanged.
- **Assumptions safe for autonomy:** yes — a one-function guard reusing a merged,
  documented gate, mirroring the exact FDC/OFF pattern, with the fall-through channel
  already in place. No migration, contract, UI, or external dependency.
</content>
