# FTY-419 — Live run (leased `slacks` stack, my branch)

The shared `slacks-*` compose stack was rebuilt in place from this branch
(`worker` + `api`) per the estimator-lane live-run recipe
(`SLACKS_LLM_PROVIDER=claude_code`/`sonnet`; FDC + SearXNG + OFF + reference-source
enabled), the exact dogfood meal submitted through the live API, and the result read
back from Postgres and from the client-facing `log-events/by-date` endpoint. The
stack was restored to `main` afterwards.

Input (the operator's 2026-07-20 §10 dogfood entry, entry `25c3047b`):

```
half a 300 calorie sub bun with mustard, mozzarella and turkey
```

→ event `completed`, meal name **"Turkey sandwich"** (the bun was *not* folded into
the name — it is its own item).

## Persisted `derived_food_items` (Postgres)

```
    name    |  status  |  cal  | prot | carb | fat | amount | grams
------------+----------+-------+------+------+-----+--------+-------
 sub bun    | resolved | 150.0 |  4.6 | 30.0 | 1.7 |    0.5 |         ← the anchored item
 mustard    | resolved |   1.4 |  0.1 |  0.3 | 0.0 |      1 |     5
 mozzarella | resolved |  88.5 |  4.2 |  6.4 | 5.2 |     28 |    28
 turkey     | resolved | 119.1 |  6.5 |  2.7 | 9.1 |     57 |    57
```

**Four described items → four persisted rows.** The bun — the one item the operator
gave an explicit number, and the one the original bug dropped — is present.

## Client-facing view (`GET /log-events/by-date`, what the app renders)

```
- sub bun     | cal=150.0 P=4.6 C=30.0 F=1.7 | amt=0.5 | src="You logged" | basis=reference_source
- mustard     | cal=1.4   P=0.1 C=0.3  F=0.0 | amt=1.0 | src="USDA"
- mozzarella  | cal=88.5  P=4.2 C=6.4  F=5.2 | amt=28  | src="USDA"
- turkey      | cal=119.1 P=6.5 C=2.7  F=9.1 | amt=57  | src="USDA"
```

Daily intake total: **359.0 kcal** (150 + 1.4 + 88.5 + 119.1) — every item counts,
the bun included.

## Bun provenance (`evidence_sources`)

```
source_type      = user_text
basis            = as_logged
field_provenance = {"calories":"user_stated","protein_g":"estimated",
                    "carbs_g":"estimated","fat_g":"estimated"}
assumptions      = [
  "calorie_anchor: 300 kcal/unit × 0.5 = 150 kcal",
  "macro estimate basis: reference_source",
  "protein_g, carbs_g, fat_g estimated from reference_source (…White_sub_bun…) scaled to the stated 150 kcal",
  "search_result_snippet"
]
```

No raw diary phrase is retained in any evidence field.

## Acceptance criteria, proven live

| Criterion | Evidence |
| --- | --- |
| Entry contains **the bun** plus the other items — no described item missing | 4 rows persisted (sub bun + mustard + mozzarella + turkey); meal name "Turkey sandwich" did not absorb the bun |
| Bun resolves to **150 kcal** (300 × half), honoring the anchor over an independent estimate; quantity modifier respected | `sub bun` = 150.0 kcal at `amount 0.5`; `calorie_anchor: 300 kcal/unit × 0.5 = 150 kcal`; `calories` provenance `user_stated` |
| Anchored bun still carries **estimated macros** (not null) | P 4.6 / C 30.0 / F 1.7, `field_provenance` macros `estimated`, scaled to the 150 kcal anchor from a reference source |
| A described food that can't be resolved is an honest editable/clarify item, never dropped | Every item persisted; the never-drop path is pinned deterministically in `backend/tests/test_calorie_anchor_resolution.py::test_unresolvable_described_food_is_editable_not_dropped` |

## Deterministic proof

`backend/tests/test_calorie_anchor_resolution.py` (end-to-end, migrated DB):
no-item-dropped (multi-item), calorie-anchor hard-override + quantity modifier
(half → 150, 2× → 600, whole → 300), measured-portion-not-scaled, anchored-item
still-has-estimated-macros, and the no-silent-drop editable path.
