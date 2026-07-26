# Contract: FDC Candidate Ranking and Common Portions

## Purpose

The **candidate-ranking** and **common-portion** rules of
[food-resolution.md](food-resolution.md): how the FDC search results for a generic
food name are gated for compatibility and ordered into a single best row
(`fdc_ranking.py`), what a total rejection means, when a cached `products` row may
still be served without a re-fetch, and how a stated count of an everyday food
resolves to grams when the source row carries no usable serving size
(`common_portions.py`). This page was extracted from `food-resolution.md` (FTY-429,
contract-only — no semantic change); the rest of the food-resolution contract
(Inputs, the FDC client and its config, nutrient mapping and the per-100g
plausibility bound, serving math, persistence, routing, and the barcode /
user-stated / prior-correction / official / model-prior tiers) stays there.

## Owner

estimator / contracts / backend-core lane (same owners as
[food-resolution.md](food-resolution.md)):
`backend/app/estimator/fdc_ranking.py`,
`backend/app/estimator/common_portions.py`, `backend/app/estimator/fdc.py`,
`backend/app/estimator/food_serving.py`, `backend/app/estimator/food_step.py`.

## Candidate ranking (FTY-254)

The FDC lookup (**Source lookup and caching** in
[food-resolution.md](food-resolution.md)) selects the **best-ranked compatible**
energy-bearing result (FTY-254, `fdc_ranking.py`) rather than the first
energy-bearing one — head-noun identity match, no
unstated density-changing form — the dehydrated/dried/powder/flour/concentrate
family plus the extracted-**`oil`** form (FTY-418): a plain "mustard" rejects
"Oil, mustard" (884 kcal/100g of pure fat) unless the query itself states the oil —
stated added ingredients present; preferred by
fewest unstated **identity-modifier** tokens — a part-of-food (FTY-388 —
`white`/`yolk`/`shell`) or an identity-shifting leaf/green/seed/cabbage sense
(FTY-424 — `greens`/`green`/`leaf`/`leaves`/`seed`/`seeds`/`spinach`/`cabbage`:
bare "mustard" prefers the prepared/condiment row over "Mustard greens", "Cabbage,
mustard", or "Mustard seed", while "mustard greens" keeps the greens row via the
stated-token exemption; this is a demotion, **not** a head-noun-position gate, so
category-led rows like "Fish, salmon" / "Cheese, mozzarella" are unaffected), then
fewest unstated demoted forms, then query-token coverage, then relevance order —
see **Version 36**, **Version 25**, **Version 15** of
[food-resolution-changelog.md](food-resolution-changelog.md).

### Rejection, the interpretation ledger, and the miss boundary (FTY-326)

Rejecting every result is a **miss**, not a wrong-food match —
but since FTY-326 the gate is a bounding pre-filter, not the final row-acceptance
authority: the bounded rejected energy-bearing rows are first recorded on the
interpretation-session ledger as `rejected_incompatible_row` evidence (sanitized
outcome + global row description + source ref), and the session may spend its one
bounded re-interpretation pass to revise the identity for a **single** retried
lookup before the miss stands. If the session keeps its hypothesis, the rejection
is deliberate and resolution falls forward exactly as before.

### Cache compatibility and rank stability

A **compatible rank-stable** cache hit makes **no** external call. Incompatible
cached rows are never served; compatible but non-rank-stable rows (e.g. `tuna`
cached to canned tuna, `scrambled eggs` to raw egg, or `large eggs` cached to the
egg-white row before FTY-388) re-fetch once and refresh the
single `(source, query_key)` row when a better result is available, otherwise
fall back to the compatible cache.

## Common-portion table (FTY-254)

When the serving math (**Serving math** in
[food-resolution.md](food-resolution.md)) resolves no grams, then before that gap
routes onward, a **stated count of an everyday common food** (FTY-254 — banana,
egg, bread/toast slice, butter
pat/stick, with small/medium/large/jumbo size cues read from the parse; plus
FTY-418 deli-meat slices — turkey/ham/bologna/salami ≈ 28 g — and sliced-cheese
slices — mozzarella/cheese/cheddar/provolone/swiss ≈ 22 g) resolves
via the documented common-portion table (`common_portions.py`, published USDA
household weights / FDA RACC vicinity), keeping the trusted-source facts and
recording an explicit
`estimated_common_portion:<food> <cue> <grams> g` assumption on the evidence row.
The table declines a **composed/assembled dish** (FTY-368 — sandwich, wrap,
burger, taco, … by closed vocabulary): the dish is the sum of its parts, so one
component's household weight never stands in for the whole dish's grams.

## Examples (tests)

The FTY-254
common-food ranking, the common-portion defaults, and the dogfood fixture set
(calorie bands + provenance) are covered by `tests/test_fdc_ranking.py`,
`tests/test_common_portions.py`, and `tests/test_common_food_resolution.py`.
