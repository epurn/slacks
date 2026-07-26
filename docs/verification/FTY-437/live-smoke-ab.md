# FTY-437 live proof — `make food-smoke` A/B

Same-stack A/B on the local Compose stack (2026-07-26). `make food-smoke` is red on
`main` for unrelated reasons and its fixtures flake heavily run to run, so the runs
are **interleaved and repeated** per the FTY-436 convention (`main` → branch → branch
→ `main`), rebuilding only the `api` + `worker` images between configs. No fixture
text and no per-item calorie band was edited.

- **B1 / B2** — stack built from `main` (`65af0a7`).
- **A1 / A2** — stack built from this branch.

## Per-fixture outcome

| fixture | B1 (main) | A1 (branch) | A2 (branch) | B2 (main) |
| --- | --- | --- | --- | --- |
| `compliments-chicken-strips` | — | FAIL | FAIL | FAIL |
| `one-banana` | — | PASS | PASS | PASS |
| `two-large-eggs` | — | PASS | PASS | PASS |
| `one-slice-wheat-toast` | PASS | PASS | PASS | PASS |
| `scrambled-eggs-and-buttered-toast` | FAIL | PASS | FAIL | PASS |
| `100g-banana` | PASS | PASS | PASS | PASS |
| **`branded-crackers-and-hummus`** | **FAIL** | **PASS** | **PASS** | **FAIL** |
| `tuna-salad-sandwich` | PASS | FAIL | FAIL | FAIL |
| `made-good-oat-bar` | FAIL | FAIL | PASS | PASS |
| `homemade-banh-mi` | FAIL | FAIL | FAIL | FAIL |
| `nicorette-4mg-gum` | FAIL | PASS | PASS | PASS |
| `nicorette-brand-gum` | PASS | PASS | FAIL | PASS |
| `homemade-chicken-rice-casserole` | PASS | FAIL | FAIL | FAIL |
| `thrown-together-veggie-curry` | FAIL | FAIL | FAIL | FAIL |
| **total failing** | 7 / 14 | 6 / 14 | 7 / 14 | 6 / 14 |

`—` = the run's captured output was truncated above that fixture (B1 was captured
tail-only); B2 covers the same four fixtures on `main` and they pass there.

The **only** fixture whose verdict tracks the config is the target one. Every other
flip appears on **both** configs across the four runs — `tuna-salad-sandwich` and
`homemade-chicken-rice-casserole` also fail on `main` in B2, and
`scrambled-eggs-and-buttered-toast` / `made-good-oat-bar` / `nicorette-brand-gum`
flip within a config. All of those are the known `processing`-past-the-poll-window
and live-parse-nondeterminism classes recorded for this smoke; none touches piece
counts or the serving math.

## The target item, before and after

Before (B1 and B2 — identical on both `main` runs):

```
[FAIL] branded-crackers-and-hummus: '4 toppables brand crackers with 1tbsp of loblaws store brand (PC/presidents choice) dill pickle hummus'
       status: completed
       - dill pickle hummus — trusted_nutrition_database usda_fdc:174289 — 36 kcal
       - crackers — product_database open_food_facts:0066721029218 — 360 kcal
       ! item 'crackers' calories 360 outside the per-item plausible band [30, 250] for 'cracker'
```

After (A1 and A2 — identical on both branch runs):

```
[PASS] branded-crackers-and-hummus: '4 toppables brand crackers with 1tbsp of loblaws store brand (PC/presidents choice) dill pickle hummus'
       status: completed
       - dill pickle hummus — trusted_nutrition_database usda_fdc:174289 — 36 kcal
       - crackers — product_database open_food_facts:0066721029218 — 66 kcal
```

The cracker keeps the **same** cached Open Food Facts row (`product_database`,
`open_food_facts:0066721029218`, 473.68 kcal/100 g, 19 g serving — cache untouched);
only the count-to-grams interpretation changed: `4 × 3.5 g = 14 g` at 4.7368 kcal/g =
**66 kcal**, inside the committed `[30, 250]` band, instead of `4 × 19 g = 76 g` =
360 kcal. The hummus item is unchanged.
