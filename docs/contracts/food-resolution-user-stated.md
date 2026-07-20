# Contract: User-Stated Food Resolution

## Purpose

The user-stated (`user_text`-tier) resolution step of
[food-resolution.md](food-resolution.md): how a recognizable item whose entry
carries an **explicit nutrition fact the user stated** resolves directly from
that user-provided evidence rather than being sent back for a quantity
clarification. This page was extracted **verbatim** from `food-resolution.md`
(FTY-428, contract-only — no semantic change); the rest of the food-resolution
contract (Inputs, serving math, routing, the USDA / barcode / prior-correction /
official / model-prior tiers, exact-evidence-upgrade routing) stays there.

## Owner

estimator / contracts / backend-core / security-privacy lane (same owners as
[food-resolution.md](food-resolution.md)): `backend/app/estimator/food_step.py`,
`backend/app/models/food_sources.py`, `backend/app/models/derived.py`
(`DerivedFoodItem` resolution columns).

## User-Stated Resolution (FTY-279)

A recognizable food item whose entry carries an **explicit nutrition fact the user
stated** — a calorie total ("… 580 cals …"), a macro ("30g protein"), or both,
extracted by the parser into the `stated_*` fields (`parse-candidates.md` v6) —
resolves from that **user-provided evidence** (`user_text`, rank 1) rather than being
sent back for a quantity clarification. This is the estimation-pipeline consumer of
the `user_text` tier (`evidence-retrieval.md` → **User-Stated Nutrition Evidence**).

### Direct resolution from a stated total

For a recognizable item with a user-stated calorie total, the step resolves the item
**directly**, and `user_text` outranks USDA/OFF/official/model-prior for the stated
field(s):

1. **Validate** the stated facts — finite, non-negative, under the **as-logged abuse
   cap** (the label path's `MAX_ENERGY_KCAL`-style bound, **not** the per-100g
   plausibility bound, which needs a mass the user did not give), and internally
   consistent (the Atwater cross-check, `evidence-retrieval.md`). A
   negative/non-finite/absurd or self-contradictory claim does **not** resolve — it
   routes to `needs_clarification` (fail closed), never committing an impossible total.
2. **Record** a `resolved` `derived_food_items` row whose `calories` is the stated
   total, plus a user-owned `evidence_sources` row: `source_type = user_text`,
   `source_ref = user_text:<content_hash>`, an immutable `basis = as_logged` facts
   snapshot, and `field_provenance` marking `calories` `user_stated`. Because the facts
   are `as_logged`, the serving math does **not** scale them — the stated total is the
   consumed-quantity total. No global `products` cache row is written (per-entry facts;
   `product_id` is `NULL`).
3. **Fill missing macros honestly.** A macro the user did not state is **estimated**
   from the item identity in the fixed order defined by `evidence-retrieval.md`
   (**Estimating a missing field**) — source-backed lookup on a sanitized item-identity
   query first, then comparable-source aggregation as rough reference evidence (source
   refs + compatibility + plausibility/outlier filtering), then a pure model prior —
   recorded `field_provenance = estimated` with the reason in `assumptions`; or left
   **unknown/`null`** when no credible estimate survives — **never** silently stored as a
   user-supplied `0`. An unknown macro (`null`) stays distinct from a real `0 g` at
   item detail/provenance (`daily-summary.md`).

The consulted source system `user_text` is recorded on the run `source_refs`.

### Per-unit calorie anchors and the quantity modifier (FTY-419)

A stated calorie figure is the **energy of one logged unit** of the item — a per-unit
*anchor* — not always the whole as-logged total. When the entry describes the item's
calories and gives a **separate count/fraction quantity** ("half a **300 calorie** sub
bun", "two **200-calorie** bars"), the parser transcribes the per-unit number verbatim
into `stated_calories` and the quantity into `amount` (`half → 0.5`, `two → 2`); it must
**not** pre-multiply the calories itself. The `user_text` step then scales the stated
calories — and any stated macro — by that count (`_anchor_quantity`): "half a 300 calorie
sub bun" resolves to `300 × 0.5 = 150` kcal, honoring the explicit anchor (a **hard
override** of any independent estimate) while still respecting the quantity. The missing
macros are estimated as above, now from the **scaled** energy, so a 150 kcal anchor never
carries null macros. A scaled anchor records a content-free `calorie_anchor:` assumption
(the per-unit value, the multiplier, and the total — numbers only, never raw text).

The count multiplier applies only to a **unit count** (a bare/count-unit `amount`,
defaulting to 1 when absent). A stated total against a **measured mass/volume portion**
("100 g chips, 500 cals") is the as-logged total for that measured amount and is counted
unscaled, and a bare `(580 cals)` on a single item (`amount` absent or 1) is unchanged
from FTY-279. Gross counts are already bounded by the FTY-156 parse plausibility gate, so
the scaled total stays sane. **No described item is dropped**: the item a calorie figure
describes is itself a food item the parser must enumerate (never folded into `event_name`
or another item), and a food that cannot be resolved falls forward to a rough estimate or
an honest editable/`unresolved` row — never a vanished one.

### The no-second-follow-up rule (clarification boundary)

Once the user supplies a **usable concrete detail** for a recognizable item — a
portion/count (FTY-167/275), a `brand` identity (FTY-062), or a stated nutrition fact
(this story) — Slacks **estimates or counts with provenance** and must **not** ask a
second follow-up for that same item merely because the detail was not the exact field
the pipeline hoped for. The shared last-resort clarification reasons live in
[estimator-policy.md](estimator-policy.md); food resolution applies them after
validating source facts, serving math, and user-stated nutrition. A stated calorie
total is a usable detail even when the user adds "idk the breakdown": the item resolves
as a `user_text` calorie item, and the missing macros are estimated or left unknown —
not re-asked as "How much did you have?". Item-scoped partial resolution for a *mixed*
log with any remaining
allowed question is tracked by FTY-278; FTY-298 changes the default amountless case to
rough estimation before asking.

### Worked example (the Sobeys wrap)

```
entry: "Sobeys fresh to go buffalo chicken lime wrap (580 cals idk the breakdown)"
  parse: one food candidate, name "… buffalo chicken lime wrap", brand "Sobeys",
         stated_calories 580, stated_protein_g/carbs_g/fat_g null
  validate: 580 finite, ≥ 0, under the as-logged abuse cap → trusted
  → resolved derived_food_items row: calories 580 (as_logged); macros null (unknown)
    [or estimated from identity, field_provenance=estimated]
  → evidence_sources: source_type=user_text, source_ref=user_text:<hash>,
    facts{basis:as_logged, calories:580, protein_g:null, carbs_g:null, fat_g:null},
    field_provenance{calories:user_stated, protein_g:unknown, …}
  → run.source_refs += "user_text"; event: processing → completed
  # NOT needs_clarification, and NOT a second "How much did you have?" — a usable
  #   stated detail (the calorie total) was given.
```

### Security / Privacy

- **No raw diary text persisted.** The `evidence_sources` row stores the extracted,
  validated facts + `user_text:<content_hash>` + timestamp only — never the raw phrase
  (per `data-retention.md`; `evidence-retrieval.md` → Privacy and Retention).
- **Untrusted-until-validated.** The parser extracts the stated numbers; the food step
  validates plausibility and internal consistency before any of it backs a persisted
  number, and no instruction embedded in the entry text is executed.
- **Ownership.** The `derived_food_items` and `evidence_sources` rows carry `user_id`
  at the persistence boundary and cascade on user/event deletion, exactly as the USDA
  path (**Authorization** above).
