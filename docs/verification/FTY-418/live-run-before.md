# FTY-418 — Live run BEFORE the fix (main, leased `slacks` stack)

Stack: running `slacks-*` compose project (`SLACKS_LLM_PROVIDER=claude_code` /
`sonnet`; FDC + SearXNG + OFF enabled). Submitted via the live API
(`POST /api/users/{id}/log-events`), polled to a terminal state, rows read from
Postgres (`derived_food_items` ⋈ `evidence_sources`).

Input: `"2 slices of deli turkey, 1 slice of mozzarella, and 15g of mustard"`

Four consecutive runs — all `completed` in 44–53 s (under the 75 s ceiling), so the
meal resolved rather than flat-lining; the reported all-coarse degrade is a rarer
wall-clock tail. Persisted rows (representative, consistent across runs):

```
name         | source                     | grams | cal   | protein | carbs | fat
-------------+----------------------------+-------+-------+---------+-------+-----
deli turkey  | reference_source           | 113.4 | 122   | 18.2    | 2     | 3
mozzarella   | model_prior                | 28    | 78.4  | 6.2     | 0.6   | 6.2
mustard      | usda_fdc:172337 (OIL,      | 15    | 132.6 | 0       | 0     | 15
             |   mustard — 884 kcal/100g) |       |       |         |       |
```

Defects visible here:
- **mustard → "Oil, mustard"** (`usda_fdc:172337`), 884 kcal/100 g of pure fat: a
  wrong-variant match. 15 g costed **132.6 kcal** — ~13× real prepared mustard
  (~9 kcal). Deterministic across every run.
- **deli turkey "2 slices" → 113.4 g** (≈57 g/slice, ~2× a real ~28 g slice).
- mozzarella (`model_prior`) → 28 g slice + real macros — the reasoning path works
  when reached.
