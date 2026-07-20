# FTY-418 — Diagnosis: why the loosely-described meal degraded

Reproduced entry `25c3047b`'s path ("turkey sandwich": deli turkey, mozzarella,
mustard) against a **leased local backend** (the running `slacks-*` compose stack:
`SLACKS_LLM_PROVIDER=claude_code` / `sonnet`, FDC + SearXNG + OFF all enabled) by
submitting `"2 slices of deli turkey, 1 slice of mozzarella, and 15g of mustard"`
through the live API and reading the persisted rows + run trace from Postgres.

## What actually happens (pre-fix, main)

The meal does **not** reliably flat-line — it **resolves** in 4/4 live runs
(44–53 s each, under the 75 s per-run ceiling), but with two real defects, plus a
rare degrade tail:

| item | source | grams | calories | defect |
| --- | --- | --- | --- | --- |
| mustard (`15g`) | `usda_fdc:172337` = **"Oil, mustard"** | 15 | **132.6** | wrong-variant: matched mustard **oil** (884 kcal/100g, 100 % fat); real prepared mustard ≈ 9 kcal |
| deli turkey (`2 slices`) | `reference_source` | 113.4 | 122 | portion 2× high (a slice costed ≈ 57 g, real ≈ 28 g) |
| mozzarella (`1 slice`) | `model_prior` | 28 | 78.4 | ✅ food-aware slice + real macros (the reasoning path works when reached) |

Deterministic across every run: **`mustard` → `Oil, mustard`**. FDC returns
`Oil, mustard` (884) first by relevance; the FTY-254 density-form gate did not list
`oil`, so the oil row passed as "compatible" and won on relevance over
`Mustard, prepared, yellow` (60).

## The flat-line (2 cal/g + null macros + 100 g) is a wall-clock **tail event**

The reported all-items-flat-lined outcome (all `model_prior`, exactly 2 cal/g,
macros null, "1 slice" → 100 g) is the signature of `processing._degrade_and_complete`
— the FTY-372 worker safety net that fires only on a **hard FTY-363 per-run
ceiling breach** (`run_wall_clock_deadline_exceeded`; a 3-item meal makes ~7
provider calls, far under the 128-call cap). It discards all partial resolution and
re-casts every candidate through the budget-free deterministic coarse prior
(`degrade.py`: `COARSE_ENERGY_DENSITY_KCAL_PER_100G = 200` × a 100 g default,
`protein/carbs/fat = None`). With the slow `claude_code` CLI provider this is the
documented "75 s run-deadline" tail on a contended stack — a genuine emergency, not
the common outcome. It is **rare** (0/4 here) but, when it fires, it flat-lines the
whole meal.

## Fix (this lane: resolution tiers + portion resolution + degrade prior)

1. **Sensible match** — `fdc_ranking.REJECTED_FORM_TOKENS` now rejects the
   extracted-`oil` form: a plain "mustard" no longer resolves to mustard oil; a
   stated "mustard oil" / "olive oil" keeps it. (general — also peanut→peanut oil,
   coconut→coconut oil.)
2. **Food-aware portions** — `common_portions.py` gains deli-meat (≈ 28 g/slice) and
   sliced-cheese (≈ 22 g/slice) sandwich slices, so counted slices resolve to a
   realistic gram mass, never a flat default serving.
3. **Emergency degrade prior is food-aware** — `degrade.py`'s budget-free
   deterministic prior resolves counted everyday foods through the common-portion
   table and carries a documented Atwater-consistent mixed-food macro split, so even
   the rare last-ditch is never `2 cal/g + null macros + 100 g`.

## Known residuals (filed as planner notes, out of this lane's clean scope)

- FDC lexical ranking still can't distinguish the *condiment* "mustard" from
  "Mustard greens"/"Cabbage, mustard" (identity-shifting modifiers `greens`/`seed`),
  so after the oil fix a bare "mustard" lands a sane-calorie mustard-family row
  rather than exactly "Mustard, prepared". Calories are correct (single digits for
  15 g); the exact-variant ranking is a broader `fdc_ranking` story.
- "2 slices of deli turkey" via the `reference_source` page costs a ~57 g slice
  (2× real). That portion comes from the reference/model estimate's own serving; a
  deterministic override of a source-provided serving for counted deli meat is a
  broader change.
