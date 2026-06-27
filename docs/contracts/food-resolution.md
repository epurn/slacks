# Contract: Generic Food Resolution

## Purpose

Define the deterministic **generic-food resolution step** (FTY-044) of the
estimation pipeline: how a parsed food candidate (FTY-042) becomes a costed
`derived_food_items` row carrying canonical **calories and macros**, computed from
a trusted nutrition database's per-100g facts and a deterministic serving-math rule,
with the retrieved facts stored as evidence and cached for reuse.

This covers five things:

1. the **USDA FoodData Central (FDC) client** (`fdc.py`) — its env-var config, the
   hardened/allowlisted fetch policy, and the FDC → canonical-facts mapping;
2. the **hardened fetch / SSRF policy** (`hardened_fetch.py`) shared by evidence lookups;
3. the **serving-math rule** (`food_serving.py`) — quantity → grams and grams →
   calories/macros;
4. the **`products`** (global cache) and **`evidence_sources`** (user-owned
   provenance) tables, the calories/macros columns added to `derived_food_items`, and
   the `0007` migration;
5. the **routing and trust boundary** — how a resolved candidate completes, how an
   unknown food or unresolvable quantity routes to `needs_clarification`, and how a
   transient source failure retries while a bad response fails closed.

It consumes FTY-042's `unresolved` food candidates (see `parse-candidates.md`) and
plugs into FTY-040's pipeline-step interface and status transitions (see
`estimation-jobs.md`). It excludes user nutrition-label/barcode evidence (Milestone
6), official restaurant/manufacturer sources and recipe calculation (later), complex
portion inference / `portion_memories` (later), and saved foods/aliases (Milestone 5).

## Owner

estimator / contracts / backend-core / security-privacy lane:
`backend/app/estimator/fdc.py`, `backend/app/estimator/hardened_fetch.py`,
`backend/app/estimator/food_serving.py`, `backend/app/estimator/food_step.py`,
`backend/app/models/food_sources.py`, `backend/app/models/derived.py`
(`DerivedFoodItem` resolution columns), `backend/alembic/`.

## Version

1 (FTY-044). The source system id `usda_fdc` is recorded on run evidence and on each
cached product / evidence row.

## Inputs

### Config (`FdcSettings`, `FATTY_FDC_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FATTY_FDC_API_KEY` | _(none)_ | data.gov FDC key (secret). **Absent → source disabled.** |
| `FATTY_FDC_BASE_URL` | `https://api.nal.usda.gov/fdc/v1` | API base; **must be https**. |
| `FATTY_FDC_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `FATTY_FDC_MAX_RESULTS` | `5` | Search results inspected for an energy-bearing match. |

The key is a `SecretStr`, read from the environment only, never exposed to clients,
never logged, and sent only in the `X-Api-Key` **header** (never the query string, so
it cannot leak through a logged URL). The allowlisted host is derived from the base
URL. With no key the source is disabled and food candidates are left `unresolved`
(the offline bundled-dataset fallback is a documented deferral).

### Candidate input

A parsed food candidate's `name`, `unit`, `amount`, and `quantity_text`
(`parse-candidates.md`). The LLM never supplies nutrition facts; only the food
**name** (sanitized, normalized) is sent to FDC — never the user's profile, weight,
history, or any other personal context.

## Outputs

### Source lookup and caching

The food name is normalized (lower-cased, whitespace-collapsed) into a `query_key`.
Resolution checks the global `products` cache by `(source, query_key)` first; on a
miss it calls FDC `/foods/search` (data types `Foundation` / `SR Legacy`, whose
nutrient values are **per 100 g**), takes the first result carrying an energy (kcal)
value, maps it to canonical per-100g facts, and caches it as a `products` row. A
cache hit makes **no** external call.

Nutrient mapping: energy kcal (id 1008, **required**), protein (1003), carbohydrate
(1005), total fat (1004); missing macros default to 0. A result with no energy value
is skipped. Default serving grams come from `servingSize` only when `servingSizeUnit`
is `g` (or `ml`, treated 1 ml ≈ 1 g); otherwise unknown.

### Serving math

`resolve_grams(unit, amount, quantity_text, default_serving_g)` resolves the
quantity to grams, v1-simple per the story scope:

1. structured `amount` + **mass** unit (mg/g/kg/oz/lb) → grams directly;
2. structured `amount` + **volume** unit (ml/l, 1 ml ≈ 1 g) → grams;
3. structured `amount` + **count** unit (or no unit) → `amount × default_serving_g`
   when the source supplies a default serving size;
4. otherwise scan `quantity_text` for a leading `<number> <mass|volume unit>`.

Returns `None` (→ `needs_clarification`) when none apply — e.g. a count with no known
serving size, or an unrecognised/absent quantity. Calories/macros then scale per-100g
facts by `grams / 100`, rounded to 0.1. Storage is canonical (kcal, grams); the
1 ml ≈ 1 g density and the simple grams/millilitres/count scope are documented
assumptions, with richer portion inference deferred.

### Persistence

The `0007` migration adds nullable `grams` / `calories` / `protein_g` / `carbs_g` /
`fat_g` to `derived_food_items` (additive). A resolved item carries these and
`status = resolved`; an `unresolved` candidate carries `NULL`. The migration also adds:

- **`products`** — a **global** cache of trusted-source per-100g facts. **No
  `user_id`** (global source facts shared by all users). Unique on `(source,
  query_key)`. Carries the per-100g facts, optional `default_serving_g`,
  `source_ref`, and `content_hash`.
- **`evidence_sources`** — the **user-owned** provenance for one resolved food item:
  `source_type` (`trusted_nutrition_database`), `source_ref` (`usda_fdc:<fdcId>`),
  `content_hash`, `fetched_at`, an immutable per-100g facts snapshot, a
  `derived_food_item_id`, and a nullable `product_id`. Carries `user_id` and
  `log_event_id`. Raw pages are never stored.

The source system (`usda_fdc`) is recorded on the estimation run `source_refs`.

### Worked example

```
parsed food candidate: name "white rice", quantity_text "150g", unit "g", amount 150
FDC facts (per 100 g): 130 kcal / 2.0 g protein / 28 g carbs / 0.2 g fat
  → grams = 150 (mass unit)
  → calories = 130 × 1.5 = 195.0; protein 3.0; carbs 42.0; fat 0.3
  → derived_food_items += white rice (resolved, calories 195.0, grams 150)
  → products += usda_fdc white rice (per-100g facts, cached)
  → evidence_sources += usda_fdc:<id> (hash, fetched_at, snapshot) for this user
  → run.source_refs += "usda_fdc"; event: processing → completed
```

## Validation

- **Source match.** No confident FDC match (no result, or none with energy) →
  `needs_clarification` (the food is recognisable but cannot be costed; never guessed).
- **Quantity.** Must resolve to grams via the rule above. Unresolvable →
  `needs_clarification`.
- **Source response.** FDC JSON is untrusted until it validates against the response
  schema; only the fields used are trusted, and the description is length-bounded.

## Outputs / Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| All food candidates resolve | _(completes)_ | food items `resolved` + `products` + `evidence_sources` | `processing → completed` |
| No confident source match | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Unresolvable quantity | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Transient source failure (timeout/5xx) | `StepError` (retryable) | nothing | retries within bound, then `failed` |
| Non-retryable source error (4xx/non-JSON/policy) | `StepFailed` (terminal) | nothing | `processing → failed` |
| Source unconfigured (no key) | _(skipped, completes)_ | food items `unresolved` | `processing → completed` |
| No food candidates (exercise-only) | _(no-op, completes)_ | — | _(unchanged)_ |

A `needs_clarification` outcome records a fixed, sanitized question for the later
answer flow. Resolved items, their evidence rows, and the cached products are
committed in the **same transaction** as the terminal `completed` status.

## Authorization

Every `derived_food_items` and `evidence_sources` row carries `user_id` at the
persistence boundary and is written scoped to the owning event's user (the worker
loaded the event scoped to the job's `user_id`; see `estimation-jobs.md`).
`ON DELETE CASCADE` from `users` and `log_events` enforces object-level ownership.
`products` is global (no `user_id`); `evidence_sources.product_id` is
`ON DELETE SET NULL` so clearing the cache never deletes a user's evidence.

## Privacy and Retention

- **Hardened, allowlisted egress (SSRF).** All external calls go through
  `hardened_fetch`: HTTPS only, the configured FDC host allowlisted, every resolved
  IP required to be public (loopback/private/link-local incl. `169.254.169.254`,
  multicast, reserved, unspecified blocked), redirects refused, and bounded
  time/size. A non-https or non-allowlisted target fails closed.
- **No personal context leaves the system.** Only the normalized food name is sent;
  no profile, weight, history, or event metadata.
- **Key safety.** The FDC key is env-only, never sent to clients, never logged, and
  carried in the `X-Api-Key` header so it never appears in a URL; fetch error
  messages never include the URL, headers, request body, or response body.
- **Evidence, not pages.** `evidence_sources` stores the source reference, content
  hash, fetch timestamp, and extracted per-100g facts — never a raw page. `products`
  holds global source facts only (no user data). See `docs/security/data-retention.md`.

## Errors

| Condition | Result |
| --- | --- |
| No FDC match / no energy value | `needs_clarification` (`unknown_food`); nothing costed. |
| Quantity not resolvable to grams | `needs_clarification` (`unresolvable_quantity`). |
| Timeout / connection error / 5xx | `StepError` (`fdc_transient_error`); retried within the bound. |
| 4xx / non-JSON / oversized / policy violation | Terminal `failed` (`fdc_response_error`); nothing persisted. |
| No FDC key configured | Food left `unresolved`; event still completes. |

## Examples

See the worked example above. The serving math, FDC mapping, SSRF policy, migration
rollback, and end-to-end resolution (with a stubbed FDC source) are covered by
`tests/test_food_serving.py`, `tests/test_fdc_client.py`, `tests/test_hardened_fetch.py`,
`tests/test_food_migration.py`, and `tests/test_food_resolution.py`.

## Migration / Compatibility

- The `0007` migration applies (`alembic upgrade head`) on top of the `0006`
  exercise-burn schema and is fully reversible (`alembic downgrade 0006`), verified by
  an apply/rollback test against a throwaway database.
- Additive: `derived_food_items` gains nullable resolution columns; `products` and
  `evidence_sources` are new; no prior table is altered destructively and no backfill
  is needed.
- FTY-044 appends this food step after FTY-042 parse and FTY-043 exercise in the
  default pipeline; the worker's claim → run → transition contract is unchanged. The
  food step is wired by the worker (it needs a database session for the cache and
  evidence writes); a resolver-less pipeline keeps food candidates `unresolved`.
- The grams/millilitres/count serving scope, the 1 ml ≈ 1 g density, and the
  Foundation/SR-Legacy data-type restriction are documented assumptions (story
  planning notes); per-fdc-id cache dedup, richer portion inference, and additional
  sources are later stories.
- FTY-051 extends `derived_food_items` with nullable `calories_estimated` /
  `protein_g_estimated` / `carbs_g_estimated` / `fat_g_estimated` snapshots (the
  immutable originals paired with the editable current calories/macros) and lets a
  user correct values — including a deterministic servings rescale — through the edit
  endpoint. This does not redefine the resolution math above; the estimator sets the
  snapshots at creation. See `corrections.md`.
