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

2 (FTY-060) adds the **Open Food Facts barcode source** *above* USDA generic in the
source hierarchy (a confident packaged-product match is preferred over a generic
estimate for the same input), without changing the FTY-044 USDA path or its math. The
source system id `open_food_facts` (source type `product_database`) is recorded on run
evidence and on each cached product / evidence row it produces. See **Barcode Source
(Open Food Facts)** below.

3 (FTY-078) extends the shared `hardened_fetch` policy with an **official-source page
fetch** (`fetch_text` → inert text) and its egress configuration, without changing the
FTY-044 USDA path or the FTY-060 OFF path. This is the SSRF / egress prerequisite for
official-source resolution (FTY-062); it ships no search adapter or resolution pipeline
of its own. See **Official-Source Fetch Boundary (FTY-078)** below.

4 (FTY-062) adds the **official-source resolution step** (`official_step.py`): a
last-resort pipeline step that costs named restaurant / manufacturer / packaged
products USDA and OFF cannot resolve, orchestrating the FTY-079 search adapter and the
FTY-078 hardened fetch, and otherwise falling through to a **model-prior** estimate
with an explicit source status. It adds the additive `evidence_sources.assumptions`
column (`0012` migration) and an additive `brand` field on the parse candidate; it
does not change the FTY-044 USDA, FTY-060 OFF, or FTY-061 label paths. See
**Official-Source Resolution (FTY-062)** below.

5 (FTY-093) adds **item re-match** — a *list-alternatives* + *re-resolve-to-chosen-source*
capability over an existing `derived_food_items` row. It adds `FdcClient.list_matches`
(the USDA list-candidates path, surfacing every energy-bearing match rather than the
first), reusing the FTY-044 serving math, the `products` / `evidence_sources` ownership
split, and the hardened-fetch / `sanitize_query` boundaries unchanged. Re-resolve is an
**in-place `UPDATE`** of the existing resolution columns + `evidence_sources` row +
`*_estimated` snapshots, plus one appended `re_match` correction row (which supersedes
any prior `user_edit` so the item reads un-edited) — **no migration, no new table or
column**. The contract lives in `evidence-retrieval.md` (**Item Re-match — FTY-093**);
the re-snapshot-not-`user_edit` distinction is documented there and in `corrections.md`.

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
committing an impossible calorie total. (The official-source and label-extraction paths
produce per-100g facts too but are out of FTY-115's scope; they remain gated only by the
looser `MAX_ENERGY_KCAL` abuse bound.) Default
serving grams come from `servingSize` only when `servingSizeUnit` is `g` (or `ml`,
treated 1 ml ≈ 1 g); otherwise unknown.

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

- **Source match.** No confident FDC match (no result, none with energy, or none whose
  per-100g facts pass the plausibility bound above) → `needs_clarification` (the food is
  recognisable but cannot be costed; never guessed).
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
  IP required to be globally routable (allowlist-by-property: only `is_global`
  unicast addresses pass, so loopback/private/link-local incl. `169.254.169.254`,
  RFC 6598 CGNAT `100.64.0.0/10`, multicast, reserved, and unspecified are all
  blocked fail-closed), redirects refused, and bounded time/size. A non-https or
  non-allowlisted target fails closed.
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

## Barcode Source (Open Food Facts) — FTY-060

The barcode source resolves a food candidate carrying a UPC/EAN **barcode** into the
same `derived_food_items` resolution shape (canonical kcal + grams, stored evidence,
cached product) as the USDA path, but from **Open Food Facts** (OFF). It is the
`product_database` tier of the evidence-retrieval hierarchy (`evidence-retrieval.md`)
and sits **above** USDA generic: when a candidate has a barcode and OFF is enabled,
OFF is queried first; a confident match is preferred over a generic USDA estimate.

### Owner (additional)

`backend/app/estimator/off.py` (OFF client, settings, mapping, barcode normalization),
`BarcodeResolver` + the source-hierarchy routing in
`backend/app/estimator/food_step.py`, the `products.barcode` key
(`backend/app/models/food_sources.py` + `0010` migration), and the source-diagnostics
endpoint (`backend/app/routers/health.py`, `backend/app/services/sources.py`).

### Config (`OffSettings`, `FATTY_OFF_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FATTY_OFF_ENABLED` | `true` | Self-host enable/disable flag. OFF is an open API (no key), so it is **on by default**; set `false` to disable the source. |
| `FATTY_OFF_BASE_URL` | `https://world.openfoodfacts.org` | API base; **must be https**. The allowlisted host is derived from it. |
| `FATTY_OFF_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `FATTY_OFF_USER_AGENT` | `Fatty/1.0 (+…)` | Non-secret identifying user-agent (OFF API etiquette / rate limits). |

OFF needs no credentials, so a provider is **available** whenever it is enabled. A
candidate carries a barcode only when one was explicitly supplied (a future scan,
FTY-063); barcodes are never invented by the model. The barcode is normalized to
digits and must be a plausible GTIN length (8/12/13/14) or it is treated as a
non-match.

### Source lookup, mapping, and caching

OFF is queried **by barcode only** — never the user's profile, weight, history, or any
other personal context — through the hardened fetch (`hardened_fetch.get_json`: HTTPS
only, OFF host allowlisted, SSRF/private-IP blocking, no redirects, bounded
time/size, JSON content-type). Resolution checks the global `products` cache by
`(source = open_food_facts, barcode)` first; a **cache hit makes no external call**
(a repeat scan is free). On a miss it calls the OFF v2 product endpoint with a pinned
`fields` list (`code,product_name,nutriments,serving_quantity,serving_size`), maps the
product to canonical per-100g facts, and caches it as a global `products` row.

Mapping (untrusted until it validates against the response schema): energy **kcal**
(`energy-kcal_100g`, **required**), protein, carbohydrate, total fat. Macros default
to 0 when absent (mirroring FTY-044). Per-100g facts are preferred; when OFF supplies
only **per-serving** facts plus a **gram** serving size (`serving_quantity`), they are
converted to per-100g (`× 100 / serving_g`) for canonical storage. A product with no
energy on a usable basis, with neither a per-100g basis nor a gram serving size, or
whose canonical per-100g facts fail the **plausibility bound** (FTY-115 — `0 ≤
calories ≤ 900` kcal/100g, non-negative macros, and all values finite, applied
*after* the per-serving → per-100g conversion so a kJ-mislabelled or corrupt row is
caught on either basis; defined under the FDC mapping above), is a **non-match**. Default serving grams come
from `serving_quantity` when positive.
Serving math (quantity → grams → calories/macros) reuses FTY-044's `resolve_grams` /
`scale_facts` unchanged.

`products` rows are keyed by barcode via the additive `barcode` column (`0010`
migration, indexed `ix_products_barcode`); the OFF row also stores the normalized
barcode in `query_key`, so the existing `(source, query_key)` uniqueness still dedupes
one cache row per product. The OFF row carries `source = open_food_facts`,
`source_ref = open_food_facts:<barcode>`, and is **global** (no user data). The
user-owned `evidence_sources` row records `source_type = product_database`,
`source_ref`, content hash, fetched timestamp, and the per-100g facts snapshot —
**never** the raw OFF response or page.

### Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| Barcode + OFF match + resolvable quantity | _(completes)_ | food `resolved` (`product_database`) + `products` (by barcode) + `evidence_sources` | `processing → completed` |
| OFF preferred over USDA for a barcode candidate | _(as above)_ | OFF facts win; USDA not consulted | `processing → completed` |
| Barcode OFF no match / invalid barcode / no usable or implausible energy | `NeedsClarification` (`barcode_unknown`) | clarification question | `processing → needs_clarification` |
| Unresolvable quantity | `NeedsClarification` (`unresolvable_quantity`) | clarification question | `processing → needs_clarification` |
| OFF transient failure (timeout/5xx) | `StepError` (`off_transient_error`, retryable) | nothing | retries within bound, then `failed` |
| OFF non-retryable error (4xx/non-JSON/policy) | `StepFailed` (`off_response_error`) | nothing | `processing → failed` |
| OFF disabled/unavailable for a barcode candidate | _(falls back)_ | next source (USDA by name) if applicable, else `needs_clarification` | per the source it falls to |

A barcode is **never** finalized from a guessed model-prior value while OFF is
available; `model_prior` would be permitted only when OFF is unavailable/disabled and
no other source applies (the model-prior persistence path itself remains deferred).
When OFF is disabled, a barcode candidate falls back to the next applicable source
(USDA generic by name). The run records the consulted source system(s)
(`open_food_facts`, and/or `usda_fdc`) in `source_refs` so estimation source status is
surfaced.

### Diagnostics

`GET /healthz/sources` returns each evidence source's capability descriptor
(`id`, `source_type`, `kinds`, `enabled`, `available`) — Open Food Facts (`barcode`)
and USDA FDC (`generic_food`) — so a self-hoster can confirm which sources are on
without any trial call. It carries no secrets and makes no external calls.

## Official-Source Fetch Boundary (FTY-078)

The **official-source fetch** retrieves an allowlisted public official-source page
(restaurant, manufacturer, or product page) and returns sanitized,
active-content-stripped text for downstream extraction (FTY-062). It is the
SSRF / egress-boundary prerequisite for official-source resolution: it ships **no**
search adapter (FTY-079) and **no** resolution pipeline of its own. It extends
FTY-044's `hardened_fetch` so official-source and USDA/OFF fetches share one audited
egress boundary; FTY-044's USDA behavior is unchanged.

### Owner (additional)

`backend/app/estimator/hardened_fetch.py` (`fetch_text` + the inert-text extractor
`strip_active_content`), `backend/app/estimator/official_fetch.py`
(`OfficialFetchSettings`, `fetch_official_source`), and the egress diagnostics
(`backend/app/routers/health.py`, `backend/app/services/sources.py`,
`backend/app/schemas/sources.py`).

### Config (`OfficialFetchSettings`, `FATTY_OFFICIAL_FETCH_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FATTY_OFFICIAL_FETCH_ALLOWED_HOSTS` | _(empty)_ | Comma-separated official-source host allowlist (lower-cased). **Empty → nothing is fetchable** (fail closed). |
| `FATTY_OFFICIAL_FETCH_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `FATTY_OFFICIAL_FETCH_MAX_BYTES` | `2000000` | Response-size cap; a larger body fails closed. |
| `FATTY_OFFICIAL_FETCH_ALLOWED_CONTENT_TYPES` | `text/html, application/xhtml+xml, text/plain` | Accepted content types; anything else fails closed. |

The settings are frozen and reject unknown keys. Only the explicit result URLs handed
to the fetcher are fetched — no crawling, no multi-page traversal, no open-ended
browsing.

### SSRF / egress policy (fail-closed)

Every official-source fetch is gated, before and across the request, by the shared
`hardened_fetch` policy:

- **HTTPS + public-IP only.** The target is resolved and every resolved IP must be
  globally routable (allowlist-by-property: only `is_global` unicast addresses
  pass). Any loopback, private, link-local (incl. cloud metadata `169.254.169.254`),
  RFC 6598 CGNAT (`100.64.0.0/10`), multicast, reserved, or unspecified address is
  refused; non-HTTPS and `file:`/other schemes are refused.
- **Host allowlist.** Only the configured `FATTY_OFFICIAL_FETCH_ALLOWED_HOSTS` are
  reachable; anything off-allowlist fails closed (an empty allowlist blocks everything).
- **Redirects refused.** Every 3xx is refused rather than followed, so a redirect can
  never bounce an allowlisted request to a private/off-allowlist target.
- **Bounded size, timeout, and content type.** Each is enforced and fails closed; a
  non-allowed content type is rejected.
- **Active-content stripping.** The body is reduced to inert text — scripts, styles,
  and other active-content subtrees are dropped and every tag and attribute is
  discarded — so downstream extraction only ever sees text, never executable markup
  (no `<script>`, inline event handler, or `javascript:` URL can survive).
- **Content-free errors.** Fetch error messages never include the URL, request
  headers, request body, or response body, so a failed fetch is always safe to log.

### Diagnostics (egress policy)

`GET /healthz/egress` returns the configured egress policy — the host allowlist, the
size/timeout/content-type limits, and the fixed invariants (`https_only`,
`public_ip_only`, `redirects_followed=false`, `active_content_stripped`) — so an
operator can see the egress boundary without reading code. It carries **no** secrets
and makes no external calls.

## Official-Source Resolution (FTY-062)

The **official-source resolution step** (`official_step.py`,
`OfficialSourceResolveStep`) costs **named** restaurant items, manufacturer products,
and named packaged products that USDA (FTY-044) and Open Food Facts (FTY-060) cannot
resolve. It is the `official_source` tier of the evidence-retrieval hierarchy
(`evidence-retrieval.md`), but in the **pipeline ordering** it runs as the **last
resort before model-prior** — only *after* a USDA/OFF miss — because it is the
expensive path (search + fetch + LLM extraction) compared with the deterministic
trusted databases. It orchestrates the two upstream boundaries it consumes and owns
nothing of their egress: the **search adapter** (FTY-079) and the **hardened fetch**
(FTY-078).

### Trigger: the `brand` candidate field

The parse step (FTY-042, `parse-candidates.md`) gains an additive optional `brand`
field on each food candidate: the restaurant / manufacturer / packaged-product brand
when the item names a *specific* branded product (`"Big Mac"` → `"McDonald's"`), left
empty for a generic food (`"white rice"`). A candidate carrying a non-blank `brand` is
**official-source-eligible**:

- The food step (FTY-044/060) tries USDA/OFF first. On a **miss**, a *branded*
  candidate is **deferred** to the official-source step (it does not stop at
  `needs_clarification`); a *generic* candidate keeps the FTY-044 behavior (a USDA miss
  clarifies). A branded item USDA/OFF **does** resolve never reaches this step.
- The model never supplies a `brand` it was not given, and `brand` is stored as data,
  never interpreted.

### Orchestration

For each deferred candidate, the step resolves in order, all egress through the
injected adapters (the step itself opens no socket):

1. **Search** the sanitized **item identity only** (name + brand — never profile,
   weight, history, or event metadata) through the FTY-079 adapter.
2. **Fetch** each candidate result URL through the FTY-078 hardened fetcher, taking
   back sanitized, active-content-stripped inert text.
3. **Extract** the nutrition facts the page states by sending that inert text to the
   provider with the strict `NamedFoodEstimate` schema (`schemas/official_source.py`).
   The page text is **untrusted data**; the reply is trusted only after it validates,
   and a low-confidence / fact-less reply is not trusted.
4. **Recompute** canonical calories/macros from the validated facts with the FTY-044
   serving math (per-serving facts are canonicalised to per-100g via the page's gram
   serving size, then scaled to the consumed quantity) — the model never supplies the
   stored numbers.

### Model-prior fallback (with status, never a silent guess)

When the search provider is **disabled**, **unavailable** (no key), the **fetcher is
unconfigured** (empty allowlist), or **nothing confident is found**, the candidate
falls through to a **model-prior** estimate of the same `NamedFoodEstimate` shape,
from the item identity alone. It is recorded with `source_type = model_prior`,
`source_ref = model_prior`, and an explicit `assumptions` reason (e.g.
`"official_source disabled; estimated from model prior"`) plus the model's own
assumptions, so the entry surfaces an explicit source status and stays user-editable —
never a silent guess (per the `evidence-retrieval.md` Fallback Rule). A model that
cannot estimate the item routes to `needs_clarification`.

### Persistence

A resolved official-source / model-prior candidate becomes a `resolved`
`derived_food_items` row plus a user-owned `evidence_sources` row, exactly like the
USDA/OFF path, with two differences:

- **No global cache.** Official-source pages are per-URL and model-prior estimates are
  per-resolution, so neither writes a `products` row; the evidence `product_id` is
  `NULL`.
- **Provenance.** `source_ref` is `official_source:<url>` (the **URL only** — never the
  raw page) or `model_prior`; the immutable per-100g facts snapshot, content hash, and
  fetch time are stored as for any source. The `0012` migration adds the additive,
  nullable **`evidence_sources.assumptions`** JSON column carrying the documented
  assumptions (the model-prior reason); a USDA/OFF/label row leaves it `NULL`.

The consulted source systems (`official_source`, and/or `model_prior`) are recorded on
the run `source_refs`, and the assumptions on the run `assumptions`.

### Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| Branded candidate, USDA/OFF miss, official page resolves | _(completes)_ | food `resolved` (`official_source`) + `evidence_sources` (`official_source:<url>`, no `product_id`) | `processing → completed` |
| Search disabled / unavailable / no confident match → model-prior | _(completes)_ | food `resolved` (`model_prior`) + `evidence_sources` (`model_prior`, assumptions) | `processing → completed` |
| Branded candidate USDA/OFF **resolves** | _(as FTY-044/060)_ | official source not consulted | `processing → completed` |
| Generic candidate USDA miss | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Usable facts but unresolvable quantity, or model cannot estimate | `NeedsClarification` | clarification question | `processing → needs_clarification` |

### Security / Privacy

- **No direct egress.** The step issues no network call of its own; all search goes
  through the FTY-079 adapter and all fetches through the FTY-078 hardened fetcher
  (both injected seams), so the SSRF/egress and query-sanitization boundaries live
  upstream and this orchestration cannot bypass them. A test proves the fetcher only
  ever receives a URL the search adapter returned.
- **Untrusted-until-validated.** Fetched/searched/extracted/LLM content is validated
  against `NamedFoodEstimate` and recomputed by the deterministic calculators before
  persistence.
- **No-raw-page retention.** `evidence_sources` stores the URL, timestamp, content
  hash, and extracted per-100g facts only — never the raw page (per `data-retention.md`).
- **Data minimization.** Only item identity (name + brand) crosses the search
  boundary; no personal context.

### Examples (tests)

`tests/test_official_source_resolution.py` proves, with a stubbed search adapter and
fetcher: official-page resolution end-to-end; the official step runs only for branded
candidates and only after a USDA/OFF miss; the disabled-provider model-prior-with-status
fallback; and no direct egress. `tests/test_food_migration.py` applies/rolls back the
`0012` `assumptions` migration.

## Liveness & Diagnostics

The backend exposes three health-check endpoints, all returning structured JSON with no external calls:

- **`GET /healthz`** — liveness probe. Returns `{"status": "ok"}` (200) whenever the
  API process is running and able to serve requests; it performs no readiness checks
  (no database or queue probe). Used by health checks and orchestration (Kubernetes,
  Docker Compose, monitoring).
- **`GET /healthz/sources`** — evidence source capability descriptor. Returns each
  configured source's `id`, `source_type`, `kinds` (e.g. `["generic_food"]`,
  `["barcode"]`), `enabled`, and `available` (matches the configuration and any
  credentials). Open Food Facts and USDA FDC are listed; allows self-hosters to
  confirm configuration without trial calls.
- **`GET /healthz/egress`** — official-source fetch egress policy (FTY-078).
  Returns the configured allowlist, size/timeout/content-type limits, and fixed
  invariants (`https_only`, `public_ip_only`, `redirects_followed=false`,
  `active_content_stripped`). Allows operators to audit the hardened-fetch
  boundary without reading code.

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
- FTY-051 extends `derived_food_items` with nullable `calories_estimated` /
  `protein_g_estimated` / `carbs_g_estimated` / `fat_g_estimated` snapshots (the
  immutable originals paired with the editable current calories/macros) and lets a
  user correct values — including a deterministic servings rescale — through the edit
  endpoint. This does not redefine the resolution math above; the estimator sets the
  snapshots at creation. See `corrections.md`.
