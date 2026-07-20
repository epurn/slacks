# FTY-425 verification — run-budget headroom for the slow-provider degrade

**Story:** Run-budget headroom so a slow provider's degrade lands real macros, not the
coarse prior.

**Change (one boundary):** `backend/app/estimator/run_budget.py` — the soft
degradation deadline is now pinned an explicit, documented reserved headroom
(`DEFAULT_DEGRADE_HEADROOM_SECONDS = 45.0`) below the hard ceiling, so the soft→hard
gap widens from the FTY-371 shipped **30 s → 45 s**
(`DEFAULT_SOFT_RUN_DEADLINE_SECONDS = 75 − 45 = 30 s`, down from 45 s). Nothing else
changes: the hard ceiling (`75 s < 90 s` poll window), the call budgets, the degrade
producer, and the never-fail contract states are untouched.

## Why the old behaviour produced the coarse prior

On the slow `claude_code` CLI provider a normal multi-item meal's
official→reference→model-prior cascade costs **several provider calls per candidate**.
With the soft deadline at 45 s, resolution kept spending the wall-clock budget until
only ~30 s remained; the fall-forward degrade producer's own per-candidate model-prior
calls then ran out of hard-ceiling headroom and the overflow candidate(s) fell to the
**budget-free deterministic coarse prior** (`degrade.py`
`COARSE_ENERGY_DENSITY_KCAL_PER_100G = 200.0`, macros from the fixed split) with
provenance `degraded_budget_free` — matching operator dogfood entry `25c3047b`
(turkey sandwich, 2026-07-16 `run_wall_clock_deadline_exceeded` casualty class).
Reserving more of the *existing* hard budget for the good degrade path — not raising
the hard ceiling (a Non-Goal, it only moves the red past the 90 s poll window) — is the
fix.

## Diagnosis + proof (latency-injected, network-free — the sanctioned reproduction)

The story sanctions a latency-injected stub for the diagnosis (a leased live
`claude_code` stack needs authenticated-provider secret access that is unavailable in
this headless author run — see **Live proof** below). The reproduction drives the
**real** `OfficialSourceResolveStep` + `BudgetedProvider` + `DegradeProducer` with an
injected call-count clock (elapsed = provider calls × per-call latency, **no real
sleeping**) for an 8-item meal at a simulated ~8 s/call slow provider. Each candidate's
resolution costs two provider calls (reference-page extract miss → model prior); a
degrade costs one — the real cost asymmetry the soft budget converts to cheap degrades.

```
Constants: soft=30.0s  hard=75.0s  reserved_headroom=45.0s

=== BEFORE FTY-425 (narrower reserved headroom: soft 45s) ===
pipeline outcome: COMPLETED   total provider calls: 10
  stew 0    cal/100g=250.0  protein_g=12.0   resolved(model_prior tier, exact)
  stew 1    cal/100g=250.0  protein_g=12.0   resolved(model_prior tier, exact)
  stew 2    cal/100g=250.0  protein_g=12.0   resolved(model_prior tier, exact)
  stew 3    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 4    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 5    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 6    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 7    cal/100g=200.0  protein_g=15.0   DEGRADED_BUDGET_FREE (coarse 200 kcal/100g, the bad path)

=== AFTER  FTY-425 (reshaped reserved headroom: soft 30s, the default) ===
pipeline outcome: COMPLETED   total provider calls: 10
  stew 0    cal/100g=250.0  protein_g=12.0   resolved(model_prior tier, exact)
  stew 1    cal/100g=250.0  protein_g=12.0   resolved(model_prior tier, exact)
  stew 2    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 3    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 4    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 5    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 6    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
  stew 7    cal/100g=250.0  protein_g=12.0   DEGRADED_MODEL_PRIOR (real 250 kcal/100g macros, the good path)
```

`stew 7` is the overflow candidate: **before** the reshape it spilled to
`degraded_budget_free` (coarse 200 kcal/100g); **after** it lands
`degraded_model_prior` with real 250 kcal/100g macros, still inside the 75 s hard
ceiling (both runs `COMPLETED`, ≤ 80 s ≪ 90 s poll window). Same reshape, the runaway
guard is preserved: when the meal is slow enough that no model-prior call can complete,
the budget-free deterministic prior still fires as the last-ditch (see
`tests/test_degrade.py::test_runaway_still_degrades_budget_free_at_the_hard_ceiling`).

## Deterministic regression tests (network-free, injected clock + latency stub)

`backend/tests/test_degrade.py`:

- `test_reserved_headroom_lands_overflow_degrade_on_the_model_prior_path` — AC (a): the
  overflow candidate degrades via **model-prior** (real, non-null macros), not
  `degraded_budget_free`; the pre-FTY-425 narrower headroom (soft 45 s) spills it to
  budget-free (asserted as the contrast).
- `test_reserved_headroom_relationship_fits_the_degrade_producers_own_calls` — AC (b):
  the soft deadline is exactly the reserved headroom below the hard ceiling, and the
  headroom fits ≥ 3 slow (~12 s) per-candidate model-prior degrade calls; hard ceiling
  stays under the 90 s poll window.
- `test_runaway_still_degrades_budget_free_at_the_hard_ceiling` — AC (c): an always-slow
  runaway still stops at the hard ceiling, degrades budget-free, and terminates inside
  the poll window.
- `test_in_budget_meal_is_unchanged_by_the_reshaped_headroom` — a normal in-budget (fast
  provider) run never crosses the lower soft deadline, so every candidate still resolves
  exactly — no degraded rows (byte-identical behaviour preserved).

## Live proof status

A leased-stack multi-item meal on the real `claude_code` provider requires authenticated
provider secret access (`make food-smoke` with a logged-in CLI provider), which is
unavailable in this headless author run (`requires_secret_access: false`, no `.env`
access). The latency-injected reproduction above and the deterministic tests exercise
the identical `run_budget` → `official_step` → `degrade` boundary the live run would;
the live smoke (`make food-smoke`) is CI's/dogfooding's to run with an authenticated
provider.
