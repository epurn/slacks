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
   unknown food or unresolvable quantity falls forward to rough estimation or, only for
   allowed policy reasons, `needs_clarification`, and how a transient source failure
   retries while a bad response fails closed.

It consumes FTY-042's `unresolved` food candidates (see `parse-candidates.md`) and
plugs into FTY-040's pipeline-step interface and status transitions (see
`estimation-jobs.md`). It excludes user nutrition-label/barcode evidence (Milestone
6), official restaurant/manufacturer sources and recipe calculation (later), complex
portion inference / `portion_memories` (later), and saved foods/aliases (Milestone 5).

## Owner

estimator / contracts / backend-core / security-privacy lane:
`backend/app/estimator/fdc.py`, `backend/app/estimator/hardened_fetch.py`,
`backend/app/estimator/food_serving.py`, `backend/app/estimator/food_step.py`,
`backend/app/estimator/correction_resolution.py` (FTY-406 prior-correction tier),
`backend/app/models/food_sources.py`, `backend/app/models/derived.py`
(`DerivedFoodItem` resolution columns), `backend/alembic/`.

## Version

Version history moved to [food-resolution-changelog.md](food-resolution-changelog.md).

## Inputs

### Clarify policy config (FTY-298)

Food resolution consumes the shared estimator policy defined by
[estimator-policy.md](estimator-policy.md). This contract owns how that active mode is
applied to source misses, missing default servings, unresolvable serving math, food
item routing, and rough/default-prior fallback.

### Config (`FdcSettings`, `SLACKS_FDC_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLACKS_FDC_API_KEY` | _(none)_ | data.gov FDC key (secret). **Absent → source disabled.** |
| `SLACKS_FDC_BASE_URL` | `https://api.nal.usda.gov/fdc/v1` | API base; **must be https**. |
| `SLACKS_FDC_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `SLACKS_FDC_MAX_RESULTS` | `5` | Search results inspected for an energy-bearing match. |

The key is a `SecretStr`, read from the environment only, never exposed to clients,
never logged, and sent only in the `X-Api-Key` **header** (never the query string, so
it cannot leak through a logged URL). The allowlisted host is derived from the base
URL. With no key the FDC source is disabled; no request is attempted and the candidate falls
forward to the next source or rough/default-prior estimate with `source_disabled:usda_fdc` provenance; the bundled-dataset fallback remains deferred.

### Candidate input

A parsed food candidate's `name`, `unit`, `amount`, and `quantity_text`
(`parse-candidates.md`). A candidate may also carry user-stated nutrition facts in
its `stated_*` fields (FTY-279) — those feed the `user_text` evidence path
(`evidence-retrieval.md`), **not** this FDC lookup. Into the FDC request itself the
parser supplies **no** nutrition facts; only the food **name** (sanitized,
normalized) is sent to FDC — never the stated facts, the user's profile, weight,
history, or any other personal context.

### Interpretation loop and evidence tools (FTY-324)

Food resolution runs inside the `InterpretationSession` defined in
[interpretation-session.md](interpretation-session.md), not a frozen one-shot
parse. A `CandidateDraft` entering food resolution is the current
`InterpretationHypothesis` item; its `name`, `brand`, `quantity_text`, `unit`,
`amount`, `barcode`, and `stated_*` fields are hypothesis features deterministic
code may validate, sanitize, query, scale, and persist, but not final authority
over what the user meant. The model-owned/deterministic-owned division of labour
and the general evidence-tiers-as-tools contract are defined there; this page owns
the concrete per-tier tools, routing, serving math, and food outcome tables below.

The evidence tiers are the **tools** the interpretation loop may call in a bounded
order, with deterministic code enforcing the caps and preconditions for each call:

| Tool | Structured input allowed | Deterministic boundary |
| --- | --- | --- |
| `user_text` | Explicit `stated_*` facts extracted from the raw text for the current item. | Finite/non-negative/as-logged abuse cap and Atwater consistency before persistence. |
| `user_label` | User-provided label facts or image extraction owned by `label-extraction.md`. | Label schema validation, serving math, ownership, and label retention rules. |
| `prior_correction` | The acting user's own prior corrected value for this normalized item name (FTY-406). | Per-user, name-normalized lookup over the `corrections` trail; stable-value/ambiguity gate; direct-portion match or per-gram rescale serving math; no cross-user reads. See **Prior-Correction Resolution (FTY-406)** ([food-resolution-prior-correction.md](food-resolution-prior-correction.md)). |
| `open_food_facts` | Barcode digits explicitly supplied by the user plus item identity for fallback context. | Barcode normalization, OFF enablement, HTTPS/allowlisted fetch, per-100g plausibility, serving math. |
| `usda_fdc` | Sanitized item identity for trusted-database lookup. | FDC enablement/API key boundary, ranked compatibility, per-100g plausibility, common-portion table, serving math. |
| `official_source` | Bounded sanitized identity variants for named/branded items. | Search/fetch/provider caps, host allowlist, active-content stripping, `NamedFoodEstimate` validation, compatibility and serving gates. |
| `reference_source` | Bounded sanitized identity variants plus fixed `nutrition facts` intent. | Search/fetch caps, searched-result hardened fetch, snippet bounds, extraction validation, compatibility and plausibility gates. |
| `model_prior` | Sanitized item identity plus bounded quantity/unit fields and content-free tier-miss reasons. | Provider schema validation, calibrated/cold-pass agreement where required, plausibility bounds, serving math, rough provenance. |

Tier order remains evidence-first: source-backed evidence is tried before pure
model prior whenever an applicable provider is configured and available. The
`prior_correction` tier (FTY-406) sits **above every guessed source**
(`usda_fdc` / `open_food_facts` by name / `official_source` / `reference_source` /
`model_prior`) — the user's own curated value beats any re-guess — but **below the
current entry's own explicit evidence** (`user_text`, `user_label`, and a scanned
barcode), which describe *this* log rather than remembered ground truth for the
name. FTY-324 changes **who may reinterpret** between tiers, not the privacy or
safety posture.
A failed or rejected read feeds the evidence view for re-interpretation:

- OFF/USDA miss, disabled/unavailable source, incompatible branded hit, or
  uncostable serving may trigger a revised brand/product/amount hypothesis before
  the next tool is chosen.
- Search miss, fetch failure, snippet-only evidence, extraction
  `unresolved`/low-confidence, compatibility rejection, or implausible facts feed
  back as bounded sanitized evidence-view records; they do not silently erase the
  user's raw detail or force the remaining tiers to keep the stale item shape.
- A model-prior unavailable/unusable result is a feedback signal. It may lead to a
  revised hypothesis, an item-scoped clarification when allowed, or a fail-closed
  deterministic outcome; it is never persisted as trusted-looking nutrition.

The **re-interpretation trigger points** for food resolution are:

| Trigger | Required interpreter action |
| --- | --- |
| `source_gap` | When an applicable source is disabled, unavailable, misses, or returns no usable energy, consult the current hypothesis plus tier status before selecting the next tool. |
| `identity_incompatible` | When a database row/page/snippet/product name fails compatibility, decide whether to revise the item identity/brand or reject the evidence and continue. |
| `serving_uncostable` | When facts are plausible but cannot cost the logged quantity, decide whether to revise the amount/unit/count relation or continue to a rough/default/as-logged path. |
| `evidence_conflict` | When two evidence surfaces point at different items or nutrition bases, revise/split/merge the hypothesis or reject one source before persistence. |
| `rough_fallback` | Before `model_prior` or default-serving rough estimation finalizes, ensure source-backed tools that apply have been tried or recorded unavailable. |
| `clarification_last_resort` | Ask only if the interpretation loop concludes the remaining item is genuinely indeterminate under the active FTY-298 mode, or if deterministic gates independently require clarification/failure. |

When a mixed multi-item entry contains both costable and still-indeterminate
components, the required output shape remains FTY-278 item-scoped partial
resolution: resolved siblings are committed and counted, while each remaining
allowed question belongs to its specific unresolved component. FTY-324 does not
reopen that contract.

#### Tool budgets and fail-closed gates

Implementations of this contract must keep the existing deterministic authority
intact:

- bounded candidate count, query-variant count, search-result count, fetch size,
  timeout, content-type, retry, parse-repair, and trace-entry caps;
- all network egress through the configured search/fetch adapters only;
- no open-ended browser, crawling, filesystem, shell, email, calendar, or broad
  personal tools in the estimator;
- source/fact validation and serving math before persistence;
- rough estimates marked with rough/model/default/reference provenance and kept
  editable;
- deterministic plausibility, contradiction, abuse, schema, and egress gates may
  clarify or fail closed on their own authority, even if the model would prefer to
  estimate.

## Outputs

### Source lookup and caching

The food name is normalized (lower-cased, whitespace-collapsed) into a `query_key`.
Resolution checks the global `products` cache by `(source, query_key)` first; on a
miss it calls FDC `/foods/search` (data types `Foundation` / `SR Legacy`, whose
nutrient values are **per 100 g**), selects the **best-ranked compatible**
energy-bearing result (FTY-254, `fdc_ranking.py` — head-noun identity match, no
unstated density-changing form — the dehydrated/dried/powder/flour/concentrate
family plus the extracted-**`oil`** form (FTY-418): a plain "mustard" rejects
"Oil, mustard" (884 kcal/100g of pure fat) unless the query itself states the oil —
stated added ingredients present; preferred by
fewest unstated part-of-food tokens (FTY-388 — `white`/`yolk`/`shell`), then
fewest unstated demoted forms, then query-token coverage, then relevance order —
see **Version 25**, **Version 15**), maps it to canonical per-100g facts, and
caches it as a `products` row. Rejecting every result is a **miss**, not a wrong-food match —
but since FTY-326 the gate is a bounding pre-filter, not the final row-acceptance
authority: the bounded rejected energy-bearing rows are first recorded on the
interpretation-session ledger as `rejected_incompatible_row` evidence (sanitized
outcome + global row description + source ref), and the session may spend its one
bounded re-interpretation pass to revise the identity for a **single** retried
lookup before the miss stands. If the session keeps its hypothesis, the rejection
is deliberate and resolution falls forward exactly as before. A
**compatible rank-stable** cache hit makes **no** external call. Incompatible
cached rows are never served; compatible but non-rank-stable rows (e.g. `tuna`
cached to canned tuna, `scrambled eggs` to raw egg, or `large eggs` cached to the
egg-white row before FTY-388) re-fetch once and refresh the
single `(source, query_key)` row when a better result is available, otherwise
fall back to the compatible cache.

Nutrient mapping: energy kcal (id 1008, **required**), protein (1003), carbohydrate
(1005), total fat (1004); missing macros default to 0. A result with no energy value
is skipped, as is one whose mapped per-100g facts fail the **plausibility bound**
(FTY-115): `calories` must be `≥ 0` and `≤ 900` kcal/100g (just above pure oil at
~884; a kJ value mislabelled as kcal lands ~4× higher and is rejected) and every
macro must be `≥ 0` (zero is valid — a pure-fat food has zero protein/carbs).
Exactly-zero calories is **valid** — genuine zero-calorie foods (water, black
coffee, diet sodas) carry `energy = 0`, and a missing energy value is already
filtered upstream, so only a *negative* calorie value is rejected here. Every
value must also be finite — untrusted fetched JSON can carry bare `NaN`/`Infinity`
tokens, and `NaN` slips every comparison, so non-finite calories or macros are
rejected. The same
bound governs **both trusted-database lookups** — FDC here and OFF (below) — in the
canonical per-100g space, applied *after* any per-serving → per-100g conversion; an
implausible row is a non-match (`None`), so resolution falls through rather than
committing an impossible calorie total. The same bound also gates the
**official-source and model-prior path** in canonical per-100g space (FTY-132),
applied *after* any per-serving → per-100g conversion. (The label-extraction path
produces per-100g facts too but is out of FTY-115's scope; it remains gated only by the
looser `MAX_ENERGY_KCAL` abuse bound.) Default
serving grams come from `servingSize` only when `servingSizeUnit` is `g` (or `ml`,
treated 1 ml ≈ 1 g); otherwise unknown.

### Serving math

`resolve_grams(unit, amount, quantity_text, default_serving_g)` resolves the
quantity to grams, v1-simple per the story scope:

1. structured `amount` + **mass** unit (mg/g/kg/oz/lb) → grams directly;
2. structured `amount` + **volume** unit (ml/l, 1 ml ≈ 1 g) → grams. The volume
   vocabulary includes the standard **household / cooking measures** (FTY-275) —
   `cup` (240 ml), `tsp` (5 ml), `tbsp` (15 ml), `fl oz` (30 ml), `pint` (473 ml),
   `quart` (946 ml), `gallon` (3785 ml), and their common spellings — each converted
   at its standard millilitre volume under the same `1 ml ≈ 1 g` assumption, so a
   stated "1/3 cup" or "a tsp" costs at that portion. Bare `oz` stays **mass**
   (28.35 g); bare single-letter `t`/`T` are unrecognised;
3. **named-food count-serving facts** (`serving_count = N <count_unit>`) plus a
   structured consumed `amount` and compatible count unit → source facts ×
   `consumed_count / source_count`. If the same source/model also supplies the gram
   mass for that counted serving (`5 crackers (19 g)` or `serving_size = 30 g` with
   `serving_count = 5 crackers`), logged grams are `serving_g × consumed_count /
   source_count`. This path is used before any generic default-serving fallback so
   `4 crackers` against `90 kcal per 5 crackers (19 g)` resolves to `72 kcal` and
   `15.2 g`, not four full servings. Count-unit matching is closed and bounded:
   concrete singular/plural units such as `strip(s)`, `piece(s)`, `slice(s)`,
   `egg(s)`, `cracker(s)`, and `bar(s)` normalize; broad or incompatible units
   (`cup`, `handful`, unknown spellings) do not fuzzy-match.
4. structured `amount` + **count** unit (or no unit) → `amount × default_serving_g`
   when the source supplies a default serving size. The count vocabulary includes the
   common serving/portion nouns a casual log uses — `slice`, `sandwich`, `handful`,
   `ring`, `finger`, `bowl`, `scoop`, … (FTY-167) — so "a slice of pizza", "3 cracker
   sandwiches", or "a handful of onion rings" resolve via the default serving size
   instead of stopping at clarification;
5. otherwise scan `quantity_text` for a leading `<number> <mass|volume unit>`.

Returns `None` when none apply — e.g. a count with no known serving size, or an
unrecognised/absent quantity. Before that gap routes onward, a **stated count of
an everyday common food** (FTY-254 — banana, egg, bread/toast slice, butter
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
Otherwise the active shared policy ([estimator-policy.md](estimator-policy.md))
determines whether that gap falls forward to rough default-serving/reference/
model-prior estimation or asks for more detail. Calories/macros then scale per-100g
facts by `grams / 100`, rounded to 0.1 when grams are resolved; count-serving facts
scale the source serving facts by the count ratio; rough-prior paths store their own
basis and assumptions. Once serving math lands a **final total**, the
resolved-value plausibility gate (FTY-368, `resolved_plausibility.py`) re-routes
a dish-class total outside the generous dish band — or with grams beneath a
stated component amount — back through the rough tiers, tagged
`resolved_plausibility_refit:<reason>`, instead of committing the absurd value;
the terminal model-prior tier itself stays ungated. Storage is canonical (kcal, grams); the 1 ml ≈ 1 g density
and the simple grams/millilitres/count scope are documented assumptions, with richer
portion inference deferred.

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

- **Source match.** No confident FDC match (no result, none with energy, or none whose
  per-100g facts pass the plausibility bound above) is a non-match, not a final
  question under `estimate_first`: the resolver tries the next applicable source and
  then rough reference/model/default-prior estimation with explicit provenance. Under
  `balanced`/`strict`, or when every rough path is unavailable/unsafe, the same miss may
  route to `needs_clarification`.
- **Quantity.** Deterministic serving math is preferred. An unresolvable quantity falls
  forward to rough default-serving/reference/model-prior estimation under
  `estimate_first`; it asks only when the active policy allows asking or the fallback
  cannot produce a plausible, provenance-backed estimate.
- **Source response.** FDC JSON is untrusted until it validates against the response
  schema; only the fields used are trusted, and the description is length-bounded.

## Outputs / Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| All food candidates resolve | _(completes)_ | food items `resolved` + `products` + `evidence_sources` | `processing → completed` |
| Recognizable item with a **valid user-stated nutrition fact** (FTY-279) | _(resolves from `user_text`)_ | food item `resolved` (`user_text`, `as_logged`) + `evidence_sources` (`user_text:<hash>`, no `product_id`); missing macros estimated or `null` | `processing → completed` |
| User-stated facts **self-contradictory / implausible** (FTY-279) | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| No confident source match, recognizable generic food **without** usable amount, `estimate_first` | _(falls forward → rough estimate)_ | `reference_source` / `comparable_reference` / `model_prior` or default-prior evidence + assumptions | `processing → completed` |
| No confident source match, recognizable generic food **without** usable amount, `balanced`/`strict` asks | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| No confident source match, **detail-rich** generic food (FTY-167) | _(deferred → model-prior)_ | via official step (`model_prior`) | per the official step |
| Unresolvable quantity, `estimate_first` | _(falls forward → rough estimate)_ | default-serving/reference/model-prior evidence + assumptions | `processing → completed` |
| Unresolvable quantity, active policy allows amount asking or all rough paths unavailable/unsafe | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Transient source failure (timeout/5xx) | `StepError` (retryable) | nothing | retries within bound, then degrades to a rough estimate / honest still-working `processing` — never terminal `failed` (`estimation-jobs.md` v7, FTY-370) |
| Non-retryable source error (4xx/non-JSON/policy) | `StepFailed` (terminal) | nothing | `processing → failed` |
| Source unconfigured (no key) | _(skipped; falls forward under `estimate_first`)_ | next source / reference / model/default-prior rough evidence + `source_disabled:usda_fdc` assumption for recognizable items; clarification only when no identity remains, all rough paths are unavailable/unsafe, or active policy asks | per resulting source / policy |
| No food candidates (exercise-only) | _(no-op, completes)_ | — | _(unchanged)_ |

A `needs_clarification` outcome records a fixed, sanitized question for the later
answer flow. A rough-estimate outcome records source type, source reference,
field/basis provenance where applicable, and content-free assumptions instead of a
question; rough items remain editable. Resolved items, their evidence rows, and the cached products are
committed in the **same transaction** as the terminal status — `completed` today,
and, under the FTY-278 item-scoped contract, `partially_resolved` too (see
**Item-scoped partial resolution (FTY-278)** below).

### Item-scoped partial resolution (FTY-278, contract only)

FTY-278 splits the routing tables above per **component** rather than per event —
the step resolves each candidate independently and only the un-costable one is asked
about:

| Entry shape | Costable components | Amountless / un-costable component | Event outcome (target) |
| --- | --- | --- | --- |
| All components costable | resolved + evidence + products | — | `processing → completed` (unchanged) |
| **Mixed** (≥1 costable, ≥1 amountless) | committed `resolved`, **counted** | keeps `unresolved`, owns an **item-scoped** question (`derived_food_item_id`) | `processing → partially_resolved`, carrying the committed siblings |
| No component costable | — | one or more event-level questions | `processing → needs_clarification`, nothing committed |

- Under the FTY-298 default, a component with **no stated portion** is first treated as
  a recognizable rough-estimate candidate; it raises a question only when
  `balanced`/`strict` asks, every rough path is unavailable or unsafe, or the component
  lacks a recognizable identity. A question names the component through
  `derived_food_item_id` and its sanitized `name`, never the raw diary phrase. An
  *implausible* candidate still routes the **whole** event to `needs_clarification`
  (`parse-candidates.md`) — distinct from a merely un-costable one.
- Committed siblings are ordinary `resolved` `derived_food_items` rows with their
  `evidence_sources` (and, for trusted-database sources, cached `products`) — the
  same shape the all-costable path writes — so they surface and count with no new
  read path. Answering the item-scoped question re-estimates the **same** event and
  preserves those siblings without duplicating or double-counting them
  (`daily-summary.md`, `log-events-history.md` v6, `estimation-jobs.md` v3).
- **Baseline** (ships until the downstream estimator follow-ups land): the historical
  whole-event routing tables may still send an amountless/unknown/unresolvable
  component to `needs_clarification`, nothing costed. FTY-298 changes the target
  contract: `estimate_first` falls forward to rough provenance before asking, and
  FTY-278 keeps any remaining question item-scoped when some siblings are costable.

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
  IP required to be globally routable (allowlist-by-property: only `is_global`
  unicast addresses pass, so loopback/private/link-local incl. `169.254.169.254`,
  RFC 6598 CGNAT `100.64.0.0/10`, multicast, reserved, and unspecified are all
  blocked fail-closed), redirects refused, and bounded time/size. A non-https or
  non-allowlisted target fails closed.
- **No personal context leaves the system.** Only the normalized food name is sent;
  no profile, weight, history, or event metadata.
- **Raw text stays at the LLM interpretation boundary.** The
  `InterpretationSession` may show the raw log text and accumulated clarification
  answers to the configured LLM provider, but food-resolution tools must not send
  that raw text to USDA, OFF, search, fetch, official/reference pages, or evidence
  persistence. Search queries are sanitized item identity only; fetch requests are
  selected URLs only; traces, assumptions, source refs, errors, and logs carry only
  bounded sanitized labels, source ids, and safe source refs.
- **Key safety.** The FDC key is env-only, never sent to clients, never logged, and
  carried in the `X-Api-Key` header so it never appears in a URL; fetch error
  messages never include the URL, headers, request body, or response body.
- **Evidence, not pages.** `evidence_sources` stores the source reference, content
  hash, fetch timestamp, and extracted per-100g facts — never a raw page. `products`
  holds global source facts only (no user data). See `docs/security/data-retention.md`.
- **Rough-estimate provenance without raw text.** Default-serving/model-prior fallback
  reasons and source-miss diagnostics follow the shared privacy invariant in
  [estimator-policy.md](estimator-policy.md): they record content-free assumption
  labels and source ids only, never raw diary text, provider/fetched output, URLs with
  secrets, request/response bodies, provider error bodies, or credentials.

## Errors

| Condition | Result |
| --- | --- |
| No FDC match / no energy value | Non-match; under `estimate_first`, fall forward to the next source or rough estimate with provenance. `needs_clarification` (`unknown_food`) only when active policy allows asking or all rough paths are unavailable/unsafe. |
| Quantity not resolvable to grams | Under `estimate_first`, fall forward to rough default-serving/reference/model-prior estimation. `needs_clarification` (`unresolvable_quantity`) only when active policy allows asking or no plausible rough estimate survives. |
| User-stated facts self-contradictory / implausible (FTY-279) | `needs_clarification`; nothing costed for that item (a usable, valid stated fact resolves instead — never re-asked). |
| Timeout / connection error / 5xx | `StepError` (`fdc_transient_error`); retried within the bound. |
| 4xx / non-JSON / oversized / policy violation | Terminal `failed` (`fdc_response_error`); nothing persisted. |
| No FDC key configured | FDC is skipped with an explicit disabled-source reason; under `estimate_first`, a recognizable item falls forward to the next source or rough/default-prior estimate with provenance. `needs_clarification` only when no recognizable identity remains, every rough path is unavailable/unsafe, or the active policy asks. |

## Examples

```
parsed food candidate: name "crackers", quantity_text "", unit null, amount null
  → USDA/OFF exact serving unavailable or unresolvable
  → estimate_first falls forward to reference/model/default-prior rough estimation
  → derived_food_items += crackers (resolved, rough calories/macros, grams nullable or
    assumption-backed)
  → evidence_sources += source_type model_prior/reference_source (or trusted source
    with a default-serving assumption), source_ref, field/basis provenance, assumptions
  → event: processing → completed
  # NOT needs_clarification solely because the user omitted a count.
```

See the worked example above. The serving math, FDC mapping, SSRF policy, migration
rollback, and end-to-end resolution (with a stubbed FDC source) are covered by
`tests/test_food_serving.py`, `tests/test_fdc_client.py`, `tests/test_hardened_fetch.py`,
`tests/test_food_migration.py`, and `tests/test_food_resolution.py`. The FTY-254
common-food ranking, the common-portion defaults, and the dogfood fixture set
(calorie bands + provenance) are covered by `tests/test_fdc_ranking.py`,
`tests/test_common_portions.py`, and `tests/test_common_food_resolution.py`. The
FTY-315 end-to-end dogfood regression — the exact audited snack phrase plus
natural-language variants resolving through the FTY-254 rejection, FTY-253
identity-variant search, FTY-314 snippet fallback, and FTY-252 count math with
plausible calorie bands, honest provenance, raw-phrase redaction, and a static
no-special-case scan — is covered by `tests/test_exact_snack_phrase_resolution.py`.

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

## Prior-Correction Resolution (FTY-406)

The prior-correction resolution contract moved to
[food-resolution-prior-correction.md](food-resolution-prior-correction.md)
(FTY-414, contract-only extraction — no semantic change). That page owns this
source tier verbatim: the estimate-time prior-correction resolution step, its
precedence, per-user name-normalized lookup and authority rules, persistence and
provenance, routing, and security/privacy.

## Prior-Correction Candidate Surface + Apply (FTY-411)

The prior-correction candidate-surface + apply contract moved to
[food-resolution-prior-correction.md](food-resolution-prior-correction.md)
(FTY-414, contract-only extraction — no semantic change). That page owns this
tier verbatim: the `source-candidates` candidate list, the re-resolve apply path,
routing, security/privacy, and the FTY-407 mobile surfacing subsection.

## Barcode Source (Open Food Facts) — FTY-060

The barcode / Open Food Facts source contract moved to
[food-resolution-barcode-source.md](food-resolution-barcode-source.md) (FTY-409,
contract-only extraction — no semantic change). That page owns this source tier
verbatim: its intro and `### Owner (additional)`, the FTY-369 `### Name search for
barcode-less branded products` path, `### Config (OffSettings, SLACKS_OFF_ env vars)`,
`### Source lookup, mapping, and caching`, `### Routing`, and `### Diagnostics`.

## Official-Source Fetch Boundary (FTY-078)

The official-source fetch (SSRF / egress) boundary contract moved to
[food-resolution-official-source.md](food-resolution-official-source.md) (FTY-426,
contract-only extraction — no semantic change). That page owns this boundary
verbatim: its intro and `### Owner (additional)`, `### Config (OfficialFetchSettings,
SLACKS_OFFICIAL_FETCH_ env vars)`, the `### SSRF / egress policy (fail-closed)`, and
the `### Diagnostics (egress policy)`.

## Official-Source Resolution (FTY-062)

The official-source resolution contract moved to
[food-resolution-official-source.md](food-resolution-official-source.md) (FTY-426,
contract-only extraction — no semantic change). That page owns this source tier
verbatim: the `brand`-candidate trigger, orchestration, the `### Reference-source
tier (FTY-166, before any model prior)`, the `### Model-prior / default-serving
fallback`, the `### Budget/transience-degraded rough estimates (FTY-370)`,
persistence, `### Count-serving named-food evidence (FTY-252)`, the `### Search-result
snippet fallback (FTY-314)`, the `### Brand-aware packaged-product routing (FTY-253)`,
its `### Routing` table, `### Security / Privacy`, and `### Examples (tests)`.

## Exact Evidence Upgrade Routing — FTY-306

The **exact evidence upgrade** re-aims an **existing** low-trust/incomplete food
item at exact product evidence the user supplies — a barcode or a nutrition-label
photo — through a **preview → explicit apply** flow. The proposal taxonomy,
eligibility, quality semantics, and source-replacement write semantics are owned
by `evidence-retrieval.md` (**Exact Evidence Upgrade — FTY-306**); this section
fixes how the two evidence kinds route against an existing item, how the current
amount is handled, and the no-silent-exact / no-silent-guess rules. Contract only:
the backend routes are **FTY-307–FTY-309**, the mobile flow **FTY-310–FTY-313**.

### Entry points (source-specific, existing item)

Both entry points target an eligible existing `derived_food_items` row (food only;
eligibility per `evidence-retrieval.md`) and produce a proposal read — **no item
mutation on propose**:

- **Barcode** —
  `POST /api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/barcode`
  with `{ "barcode": "<string>" }` (`extra="forbid"`). The barcode may be typed or
  scanned; it is untrusted input, normalized to digits and length-checked
  (GTIN 8/12/13/14) exactly as the **Barcode Source (FTY-060)** path
  ([food-resolution-barcode-source.md](food-resolution-barcode-source.md)) does, and
  looked up **server-side** through the same hardened OFF client, `products`
  cache, per-100g canonicalisation, and plausibility bound. No other candidate
  fields, no nutrition facts, no free text.
- **Label** —
  `POST /api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/label?save={bool}`
  with the raw image bytes as the body and the declared `Content-Type`, exactly
  the `label-upload.md` wire shape. The image is validated as **data** fail-closed
  (size / content-type allowlist / magic number, `validate_upload`) before any
  model call, then runs the existing schema-validated extraction
  (`label-extraction.md`). The `save` query flag is the existing FTY-077 retention
  choice: default `false` discards the image after extraction; `save=true` writes
  one user-owned `log_attachments` row against the **item's owning log event**
  (`label-upload.md`, **Label exact-upgrade — FTY-306**).

Either entry point resolves to one proposal outcome — `exact`, `fallback`, or
`none` — per the quality semantics in `evidence-retrieval.md`. A `fallback`
proposal (exact evidence failed; a lower-trust reference / comparable-reference /
model-prior estimate over the evidence's product identity is offered instead)
carries its rough provenance and a `failure_reason` and is **never presented as
exact**; a `none` outcome is a clear failure read, not an error status. A
transient source failure during propose is surfaced honestly (retryable error,
not an empty `none`), mirroring the re-match listing posture.

### Amount preservation and costability

- The item's **current amount is preserved by default**: propose costs the
  preview at the item's current `amount`, and apply keeps that amount unless the
  user adjusts it. Fixing the source does not touch the user's portion choice
  (the FTY-092 stance, reused).
- An **optional amount adjustment** may accompany apply
  (`{ "proposal_ref": "...", "amount"?: number }`, `extra="forbid"` — no
  nutrition facts). When present it is validated like a quantity edit
  (positive, finite, bounded — `corrections.md`) and applied **before** costing,
  so the applied values are the new source's facts at the adjusted amount.
- **Costability is explicit, never guessed.** The proposal carries
  `can_cost_current_amount`. When the proposal's source cannot cost the current
  amount (serving math unresolvable — e.g. a count amount with no usable serving
  relation) and the user supplied no adjusted amount, apply **fails closed** with
  `422 {"error": "amount_required"}` — no silent default portion, consistent
  with the re-match needs-clarification posture. The client asks the user for an
  amount from the preview instead.

### Apply (in-place source replacement)

`POST /api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply`
accepts **only** the opaque server-generated `proposal_ref` plus the optional
`amount`. It re-derives the facts server-side from the server-held proposal
(no fresh evidence egress, no client-supplied facts), recomputes with the
FTY-044 serving math at the preserved or adjusted amount, rewrites the item's
`evidence_sources` provenance in place, re-snapshots `*_estimated`, and appends
one `re_match` correction row — the full source-replacement semantics of
`evidence-retrieval.md` and the audit semantics of `corrections.md`. The item
keeps its `id`, `log_event_id`, name slot, and timeline position; the applied
item reads `is_edited = false` until a later manual override. Applying a
`fallback` proposal writes its honest low-trust provenance
(`reference_source` / `model_prior` / `comparable_reference` marker), so the
item stays visibly rough and remains exact-upgrade-eligible.

### Errors (contract-level)

| Condition | Result |
| --- | --- |
| Cross-user or unknown user/item id (any operation) | `404`, fail-closed, no mutation, no existence disclosure. |
| Item whose parent log event is voided (FTY-321 soft void) | `404`, same shape as unknown — no void oracle, no mutation (the corrections/re-match boundary precheck, `corrections.md`). |
| Item not eligible (already source-backed, or an exercise item) | `422` `{ "error": "not_upgradeable" }`; nothing mutates. |
| Invalid barcode shape (non-GTIN after normalization) | A `none`/`fallback` proposal with `failure_reason = barcode_invalid` — user input, not a transport error. |
| Invalid label image (size / type / signature) | `413` / `415` fail-closed before any model call (`label-upload.md`); no proposal, no attachment. |
| `proposal_ref` unknown, expired, or not held for this user + item | `422` `{ "error": "proposal_not_resolvable" }`; nothing mutates. |
| Apply body carries nutrition facts / extra keys | `422` (request validation, `extra="forbid"`). |
| Uncostable current amount and no user-adjusted amount | `422` `{ "error": "amount_required" }`; no guessed portion, nothing mutates. |
| Transient source/provider failure during propose | Retryable error (`503`-family), surfaced honestly — never disguised as a `none` proposal. |

Error shapes carry stable codes and field names only — never nutrition values,
image data, OCR text, provider output, or URLs.

## Liveness & Diagnostics

The backend exposes four health-check endpoints, all returning structured JSON with no external calls:

- **`GET /healthz`** — liveness probe. Returns `{"status": "ok"}` (200) whenever the
  API process is running and able to serve requests; it performs no readiness checks
  (no database or queue probe). Used by health checks and orchestration (Kubernetes,
  Docker Compose, monitoring).
- **`GET /readyz`** — readiness probe. Runs a cheap `SELECT 1` through the
  request-scoped database session and returns `{"status": "ready"}` (200) when the
  database answers. Any database failure is caught and converted to a deliberate
  `503 {"detail": "not ready"}` with a generic body — no stack trace, driver message,
  DSN, or host is surfaced. Distinct from `/healthz` so orchestration can gate traffic
  on database reachability without coupling it to liveness.
- **`GET /healthz/sources`** — evidence source capability descriptor. Returns each
  configured source's `id`, `source_type`, `kinds` (e.g. `["generic_food"]`,
  `["barcode"]`), `enabled`, and `available` (matches the configuration and any
  credentials). Open Food Facts, USDA FDC, the official-source search, and the
  reference-source tier (FTY-166) are listed; allows self-hosters to confirm
  configuration without trial calls.
- **`GET /healthz/egress`** — evidence-fetch egress policy (FTY-078/166).
  Returns the configured official-source allowlist, size/timeout/content-type
  limits, and fixed invariants (`https_only`, `public_ip_only`,
  `redirects_followed=false`, `active_content_stripped`), plus a
  `searched_result_fetch` block describing whether searched public result pages
  may be fetched for reference-source evidence (enable flag, bounds, invariants,
  `raw_pages_persisted=false`) — never a URL from a user entry. Allows operators
  to audit the hardened-fetch boundary without reading code.

## Migration / Compatibility

- **FTY-370 (contract only; no code, no migration).** Adds the
  budget/transience-degraded rough-estimate provenance and the budget-free
  degrade requirement (**Budget/transience-degraded rough estimates** in
  [food-resolution-official-source.md](food-resolution-official-source.md));
  the transient-exhaustion routing rows now degrade instead of landing
  terminal `failed`. No schema, DTO, serving-math, or source-hierarchy change
  — the degrade reuses the existing `model_prior` / default-serving evidence
  shapes and the `0012` `assumptions` column. FTY-371/FTY-372 implement under
  `estimation-jobs.md` v7's never-fail semantics.
- **FTY-334 (brand cutover, mechanical rename).** The FDC, OFF, official-fetch,
  and reference-fetch environment keys documented here now use the `SLACKS_`
  prefix, and the Open Food Facts user-agent is `Slacks/1.0`, both renamed as
  part of the repo-wide brand cutover to Slacks. This is not a contract version
  bump — key meanings, defaults, fetch allowlists, and egress behaviour are
  unchanged.
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
- FTY-060 adds the `0010` migration: a nullable, indexed `barcode` column on the
  global `products` cache (the Open Food Facts barcode key). It applies on top of
  `0009` and is fully reversible (`alembic downgrade 0009`), verified by an
  apply/rollback test. Additive: existing FDC rows keep `barcode = NULL`; no prior
  column is altered and no backfill is needed. `products` stays global (no `user_id`).
  The barcode source reuses the FTY-044 serving math, evidence/`products` ownership
  split, and hardened-fetch policy unchanged; it only adds a higher-priority source.
- FTY-062 adds the `0012` migration: a nullable `assumptions` JSON column on
  `evidence_sources` (the model-prior fallback reason and documented assumptions). It
  applies on top of `0011` and is fully reversible (`alembic downgrade 0011`), verified
  by an apply/rollback test. Additive: existing USDA/OFF/label evidence rows keep
  `assumptions = NULL` and no backfill is needed; no prior column is altered. The
  official-source step reuses the FTY-044 serving math, the `evidence_sources` /
  `products` ownership split, and the hardened-fetch + search boundaries unchanged; it
  adds a higher-effort, lower-priority source and the gated model-prior fallback. The
  parse `brand` field is additive (the model may now emit it; old runs default it to
  `NULL`).
- FTY-166 adds the reference-source tier inside the official step (a deliberate
  pre-v1 breaking change to the fallback order: model prior now runs only after the
  reference tier). **No migration**: `evidence_sources.source_type` / `source_ref`
  are strings, and the `0012` `assumptions` column already carries the fallback
  reasons. Additive config (`SLACKS_REFERENCE_FETCH_*`), an additive
  `searched_result_fetch` egress-diagnostics block, and a new `reference_source`
  value in the provenance vocabulary/read-model. The USDA/OFF/label paths, the
  search adapter, and the serving math are unchanged.
- FTY-051 extends `derived_food_items` with nullable `calories_estimated` /
  `protein_g_estimated` / `carbs_g_estimated` / `fat_g_estimated` snapshots (the
  immutable originals paired with the editable current calories/macros) and lets a
  user correct values — including a deterministic servings rescale — through the edit
  endpoint. This does not redefine the resolution math above; the estimator sets the
  snapshots at creation. See `corrections.md`.
- **FTY-279 (contract only; no code, no migration in this story).** Adds
  **User-Stated Resolution**: a recognizable item carrying a user-stated nutrition
  fact (`parse-candidates.md` v6 `stated_*` fields) resolves from `user_text`
  evidence (`evidence-retrieval.md`) — calories counted `as_logged`, missing macros
  estimated (`field_provenance = estimated`) or `null`, never re-asked — and the
  clarification boundary is refined so a usable stated detail is **never** a second
  follow-up. A **deliberate pre-v1 refinement**: no schema, migration, or
  serving-math change (`evidence_sources.source_type` / `source_ref` / `basis` are
  strings, the `assumptions` column already carries per-field reasons, and the
  derived-item macro columns are already nullable). The estimator implementation
  (parser extraction + `user_text` step + validation) is the **downstream FTY-280
  follow-up**; the historical FTY-278/FTY-275 baseline shipped until then. See
  **User-Stated Resolution (FTY-279)**.
- **FTY-280 (implements FTY-279).** Adds `backend/app/estimator/user_text_step.py`
  (`UserTextResolveStep` + `UserTextMacroEstimator`), wired **before** the food step:
  it claims each candidate carrying a valid stated calorie total, resolves it from the
  `user_text` `as_logged` tier (calories counted directly, never scaled), validates the
  stated facts (finite / non-negative / as-logged abuse cap / Atwater cross-check),
  and fills missing macros via reference search → model-prior cold-pass → `null` — the
  no-second-follow-up rule. Unlike FTY-279 (contract-only), this story adds the
  additive `0018` migration to `evidence_sources` (a `basis` column defaulting
  `per_100g`, a nullable `field_provenance` map, and nullable `*_per_100g` fact-snapshot
  columns so an unknown user-stated macro is `NULL`, never a fake `0`). The USDA / OFF /
  official / reference / label paths and the serving math are unchanged.
- **FTY-281 (comparable-reference aggregate fallback).** Implements step 2 of
  **Estimating a missing field** (`evidence-retrieval.md`): when the exact reference
  lookup misses for a user-stated calorie item, `UserTextMacroEstimator` now searches a
  **brand-dropped** identity for several *comparable* public reference pages, keeps only
  the compatible, plausible ones, drops outliers, and fills the missing macros from the
  **median** of the survivors before falling back to the model-prior cold-pass — still
  never re-asking a serving question for an otherwise usable item. The deterministic
  aggregation lives in `app/estimator/comparable_reference.py`. Additive and
  non-breaking: no schema, migration, or serving-math change; a `user_text` item stays
  `user_text` and only its missing macros are filled (`field_provenance = estimated`,
  the method + compatibility summary + **each** contributing `reference_source:<url>`
  with its content hash and per-100g fact snapshot in `assumptions`; the run gains a
  `comparable_reference` `source_refs` entry). The FTY-092 read-model gains one additive
  optional field (`ItemSourceDTO.estimate_basis = comparable_reference`, derived at read
  time) so a client can distinguish the rough aggregate from a plain `user_text` item.
  Exact official/reference evidence still wins, and user-stated calories/macros are never
  overwritten.
- **FTY-278 (contract only; no code, no migration in this story).** Redefines the
  clarification boundary from whole-event to **item-scoped** for a mixed food log,
  routing it to the new `partially_resolved` status (`log-events-history.md` v6): costable
  components commit as `resolved` and count while a specific amountless
  component owns the question. Every source path, the serving math, plausibility
  gate, and `evidence_sources`/`products` shapes are **unchanged** — only the
  *routing* changes. The `derived_food_item_id` question link and its
  additive migration are `parse-candidates.md` v5's, owned by the downstream
  **FTY-278 implementation follow-up** (reads/answer flow: `daily-summary.md`,
  `log-events-history.md` v6, `estimation-jobs.md` v3); the FTY-275 (v8) baseline ships until
  then.
- **FTY-253 (brand-aware packaged-product routing).** A deliberate pre-v1 breaking
  change to branded-candidate routing: the food step now applies the
  brand/product-compatibility gate to generic FDC hits for branded candidates, and
  the official/reference tiers search the bounded identity-variant set with the
  same gate on each evidence candidate (see **Brand-aware packaged-product
  routing** above). **No migration**: the gate and variants are pure routing policy
  (`backend/app/estimator/branded_routing.py`); `evidence_sources` shapes, the
  serving math, the search/fetch boundaries, generic-food FDC resolution, and
  barcode/OFF precedence are unchanged.
- **FTY-254 (common-food FDC ranking + common portions).** A deliberate pre-v1
  breaking change to generic-food FDC selection: `FdcClient.lookup` now selects
  the best-ranked *compatible* result (`fdc_ranking.py`) instead of the first
  energy-bearing one, and the food step resolves stated counts of everyday foods
  through the documented common-portion table (`common_portions.py`) with an
  explicit evidence assumption. **No migration**: both are pure routing/serving
  policy; `evidence_sources.assumptions` (the `0012` column) already carries the
  new `estimated_common_portion:*` label, and `products`/`evidence_sources`
  shapes, barcode/OFF precedence, and the official/reference/model-prior tiers
  are unchanged. A previously cached wrong-form `products` row does **not**
  survive an upgrade: the resolver re-checks the cached description against the
  compatibility gate on every read, so a stale selection is re-fetched and
  refreshed in place (or becomes a clean miss) without any cache clearing.
- **FTY-298 / FTY-303 (contract only; no code, no migration in this story).** FTY-298
  bumps the food resolution contract to the rare clarification policy, and FTY-303
  extracts the global mode semantics, allowed last-resort clarification reasons, and
  rough-provenance requirements to [estimator-policy.md](estimator-policy.md). This
  contract keeps the source lookup, serving math, item routing, fallback behavior, and
  food evidence persistence rules. FTY-301 needs no migration or DTO change.
- **FTY-324 / FTY-348 (contract only; no code or migration in this story).** Food
  evidence tiers are specified as bounded tools inside the `InterpretationSession`,
  with source gaps/rejections feeding re-interpretation instead of locking the run
  to a stale parsed candidate (FTY-324); FTY-348 relocated the global
  session/hypothesis contract to
  [interpretation-session.md](interpretation-session.md) with no normative change,
  leaving this page the per-tier tool/routing/serving-math owner. No schema,
  endpoint, migration, provider, settings, or runtime change; the FTY-298 policy
  modes, the FTY-278 item-scoped output shape, and every existing
  privacy/egress/provenance boundary are preserved. FTY-325/FTY-326 implement the
  interpreter core and tool orchestration.
- **FTY-306 (contract only; no code or migration in this story).** Adds the
  **Exact Evidence Upgrade Routing** section: barcode/label proposal entry points
  targeting an existing food item, the preserved-amount / optional-adjustment /
  `amount_required` costability rules, and the apply operation's in-place source
  replacement. It reuses the FTY-060 hardened OFF path, the FTY-061/FTY-064
  label validation/extraction boundary and `save` retention flag, the FTY-044
  serving math, and the FTY-093 re-match write semantics unchanged — no new
  source tier, no schema change (`evidence_sources` shapes and `corrections`
  strings already carry everything). Backend implementation is
  **FTY-307–FTY-309**; mobile consumption is **FTY-310–FTY-313**.
- **FTY-307 (generic apply route + trust anchor; no schema, no migration).** Lands
  the source-agnostic apply operation at
  `POST /api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply`
  (body `{ "proposal_ref": "...", "amount"?: number }`, `extra="forbid"` — no
  nutrition facts). It verifies the opaque server-signed `proposal_ref` for the
  owning user + item, preserves the current amount by default (applying an optional
  adjustment before the FTY-044 recompute, folded into the one re-resolution — no
  separate `amount_adjust` row), rewrites `evidence_sources` in place, re-snapshots
  `*_estimated`, and appends one `re_match` correction row. Fail-closed errors match
  this section's table: `404` for cross-user/unknown/voided-parent (the FTY-321
  boundary precheck), `422 proposal_not_resolvable` for a tampered/expired/
  wrong-user/wrong-item reference, and `422 amount_required` for an uncostable
  current/adjusted amount — each with no mutation. Barcode/label proposal
  **generation** is **FTY-308/FTY-309**; this story applies stubbed proposals.
