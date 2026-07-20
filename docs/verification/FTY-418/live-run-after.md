# FTY-418 — Live run AFTER the fix (leased `slacks` stack)

Same leased `slacks-*` stack and same live path as `live-run-before.md`
(`SLACKS_LLM_PROVIDER=claude_code`/`sonnet`; FDC + SearXNG + OFF enabled). The
fix (`fdc_ranking.py` + `common_portions.py` + `degrade.py`) was loaded into the
running worker and the stale `mustard` cache row cleared, then the **same** meal
re-submitted through the live API and read back from Postgres.

Input: `"2 slices of deli turkey, 1 slice of mozzarella, and 15g of mustard"`
→ event `completed`. Persisted rows:

```
name         | source                                | grams | cal  | prot | carb | fat | assumption
-------------+---------------------------------------+-------+------+------+------+-----+---------------------------------------
deli turkey  | trusted_nutrition_database (fdc:168092)| 56    | 75.0 | 11.0 | 0.5  | 3.2 | estimated_common_portion:turkey slice 28 g
mozzarella   | trusted_nutrition_database (fdc:169011)| 22    | 69.5 | 3.3  | 5.0  | 4.0 | estimated_common_portion:mozzarella slice 22 g
mustard      | trusted_nutrition_database (fdc:169891)| 15    | 4.2  | 0.2  | 0.8  | 0.0 | (none)
```

## Before → after (per acceptance criterion)

| item | before (main) | after (fix) | criterion |
| --- | --- | --- | --- |
| mustard | `Oil, mustard` — **132.6 cal**, macros 0/0/15 | mustard-family FDC row — **4.2 cal**, real macros | AC3 sensible match (no oil variant), AC1 |
| deli turkey "2 slices" | 113.4 g / 122 cal (reference) | **56 g** (2 × 28 g food-aware slice) / 75 cal, trusted FDC + macros | AC1 food-aware portion |
| mozzarella "1 slice" | 28 g / 78.4 cal (model_prior) | **22 g** food-aware slice / 69.5 cal, trusted FDC + macros | AC1 food-aware portion |
| meal total | 332.6 cal (mustard-oil dominated) | **148.7 cal** (≈ the Opus reference ~135 for these 3 items) | AC1 real nutrition |

Every item now resolves to **real per-food calories + non-null macros with a
food-aware portion** (turkey ≈ 28 g/slice, mozzarella ≈ 22 g/slice — never a flat
100 g), via a **trusted database** source — never the coarse degrade prior, never
mustard oil.

Residual (documented, filed as planner notes): the exact-condiment FDC row for a
bare "mustard" is a mustard-family row (`169891`, ~28 kcal/100 g) rather than
"Mustard, prepared, yellow" specifically — sane calories, slightly-off identity;
the hermetic regression (`test_loosely_described_food_resolution.py`) pins the
ideal "prepared mustard" outcome when both oil and prepared rows are in the result
set.

## Reproduction

- Diagnosis + before: `diagnosis.md`, `live-run-before.md`.
- Deterministic proof of the fix: `backend/tests/test_loosely_described_food_resolution.py`
  (end-to-end), `test_fdc_ranking.py` (oil reject + stated-oil keep + prepared-mustard
  selection), `test_common_portions.py` (deli/cheese slices), `test_degrade.py`
  (food-aware budget-free prior with macros).
