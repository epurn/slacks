# Contract: Evidence Retrieval

## Purpose

Define the **public contracts for source-backed estimation** (FTY-045): the
evidence-source records, the provider capability/status values, the normalized
nutrition-fact fields, and the official-source **search** and hardened **fetch**
boundaries that the estimator and its providers share. This fixes the source
hierarchy and the fallback semantics once, so later implementation stories can
build provider adapters (USDA FoodData Central, Open Food Facts, official-page
search/fetch, nutrition-label extraction) without re-deciding which source wins,
what a lookup may report, or what crosses a provider boundary.

This is a **contracts/documentation slice only**. It defines the shapes and the
rules; it does not implement provider adapters, web fetch/parsing, or nutrition
math (those are FTY-044 and follow-up stories). It generalizes the concrete
USDA-only mechanism already shipped in `food-resolution.md` (FTY-044 —
`evidence_sources`, `products`, the hardened-fetch/SSRF policy) into the
source-agnostic contract the remaining sources plug into.

It covers five things:

1. the **evidence source record** — the source-type taxonomy, the per-100g /
   per-serving fact snapshot, and its global-cache vs. user-owned-provenance
   split;
2. the **provider capability/status contract** — what a configured provider
   advertises and the six lookup outcomes a source lookup may report
   (`unavailable`, `disabled`, `rate_limited`, `failed`, `partial`, `success`);
3. the **normalized nutrition-fact schema** — the canonical fields needed to
   compute calories and macros;
4. the **search request/response boundary** — sanitized official-source queries
   that carry no personal context;
5. the **hardened fetch boundary** — SSRF, redirect, timeout, size,
   content-type, and raw-content retention limits.

It excludes provider-adapter code, the web fetcher/parser, nutrition math,
recipe (ingredient-sum) and similar-dish calculation, and the choice of a
hosted-service billing model for search providers (a deferred product decision —
see `docs/architecture/evidence-retrieval.md`).

## Owner

contracts lane, with estimator / backend-core / security-privacy touch:
`docs/contracts/evidence-retrieval.md` (this contract). The first concrete
implementation lives in `backend/app/estimator/` (`fdc.py`,
`hardened_fetch.py`, `food_sources.py`); see `food-resolution.md`. The Open Food
Facts barcode adapter (`off.py`, `product_database` tier) is implemented in
FTY-060 behind these same boundaries; see `food-resolution.md` (**Barcode
Source**). The user-provided nutrition-label adapter (`label_step.py`,
`user_label` tier — rank 1) is implemented in FTY-061; see `label-extraction.md`.
The official-source **search** adapter (`search.py`, the `official_source` tier's
search half) is implemented in FTY-079 behind the **Search Request / Response
Boundary** below; its result URLs are fetched by the hardened fetcher (FTY-078) and
consumed by the official-source resolution step (FTY-062). See **Search Provider
Adapter (Brave) — FTY-079**.

## Version

1 (FTY-045). The source-system identifiers are stable strings recorded on each
evidence record and on the estimation run `source_refs`: `usda_fdc`,
`open_food_facts`, `official_source`, `user_label`, `model_prior`.

FTY-079 implements the `official_source` **search** boundary (the pluggable
search-provider adapter, Brave default, disabled by default) without changing this
contract; see **Search Provider Adapter (Brave) — FTY-079**. The six lookup-status
values and the sanitized-query / header-only-key rules are exactly those fixed here.

## Source Hierarchy

The estimator selects the highest-preference applicable source and only falls
back when it is unavailable, disabled, rate-limited, or fails. This refines the
`docs/architecture/system-overview.md` source hierarchy with where each
configured v1 provider sits:

| Rank | `source_type` | Source system | Applies to |
| --- | --- | --- | --- |
| 1 | `user_label` | user-provided | nutrition-label image (OCR) or manually entered label facts; user-confirmed barcode/package facts |
| 2 | `official_source` | search + hardened fetch | official restaurant / manufacturer / product page |
| 3 | `product_database` | `open_food_facts` | barcoded and packaged food products |
| 4 | `trusted_nutrition_database` | `usda_fdc` | generic foods and common serving references |
| 5 | `model_prior` | `model_prior` | last-resort fallback only (see **Fallback Rule**) |

Ingredient-based recipe calculation and similar-dish reference estimates
(system-overview ranks 6–7) are deferred; this contract reserves room for them
without defining their records yet. A source type is **applicable** only when an
input of that kind exists (e.g. `user_label` requires a label/barcode;
`official_source` requires a named restaurant/manufacturer item).

## Fallback Rule

The estimator **must not finalize** named products, restaurant items, barcodes,
nutrition labels, or generic food lookups from **model prior alone** when a
source lookup for that item is available (configured, enabled, and applicable).
`model_prior` is permitted only when, for the applicable source(s), the lookup
outcome is `unavailable`, `disabled`, `rate_limited`, or `failed`, when no
source type applies, or when the user supplied insufficient information and
declined a clarifying question.

A `model_prior` result is recorded as an evidence record with
`source_type = model_prior` and the reason it was used, so the source status is
surfaced to clients and the entry remains editable. This is a contract-level
restatement of the architecture `Lookup Rule`; adapters must not weaken it.

## Evidence Source Record

An **evidence source record** is the provenance for one resolved item: which
source produced its facts, when, and a hash of the content they were extracted
from. Records are split so global source facts never carry user-specific data:

- **Cached source facts (global).** Per-source nutrition facts that are the same
  for every user (a generic food's per-100g facts, a product's per-serving
  facts) are cached globally, keyed by `(source, query_key)` or `(source,
  barcode)`. **No `user_id`.** FTY-044's `products` table is the first instance.
- **Evidence provenance (user-owned).** The record linking a resolved
  `derived_food_items` row to the facts used: `source_type`, `source_ref`,
  `content_hash`, `fetched_at`, an **immutable fact snapshot**, and `user_id` /
  `log_event_id`. FTY-044's `evidence_sources` table is the first instance. Raw
  pages, raw OCR, and raw provider payloads are **never** stored here.

| Field | Type | Notes |
| --- | --- | --- |
| `source_type` | enum | One of the **Source Hierarchy** values. |
| `source_ref` | string | Stable reference, e.g. `usda_fdc:<fdcId>`, `open_food_facts:<barcode>`, `official_source:<url>`, `user_label:<content_hash>` (FTY-061; the SHA-256 of the label image, which a saved `log_attachments` row shares), `model_prior`. |
| `content_hash` | string | Hash of the extracted facts / fetched content the snapshot came from. |
| `fetched_at` | timestamptz | When the source was queried/extracted. |
| `facts` | normalized nutrition facts | Immutable snapshot (see below). |
| `status` | lookup status | The outcome that produced this record (see **Provider Capability / Status**). |
| `assumptions` | string[] | Any documented assumptions (density, default serving, model-prior reason). |

`source_ref` for a fetched `official_source` records the URL only (no headers,
body, or query secrets). Object-level ownership and `ON DELETE CASCADE` are
defined in `food-resolution.md` and `docs/security/data-retention.md`.

## Normalized Nutrition Fact Schema

The canonical facts every source maps into, sufficient for v1 calories+macros.
Storage is canonical units only — **kcal and grams** — per the contracts
`README.md` principle; display units are a client preference.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `basis` | enum | yes | `per_100g`, `per_100ml`, or `per_serving` — what the facts are expressed against. |
| `calories` | number (kcal) | yes | Energy for the basis quantity. A fact set with no energy value is **not** a usable match. |
| `protein_g` | number (g) | no (default 0) | Protein for the basis quantity. |
| `carbs_g` | number (g) | no (default 0) | Carbohydrate for the basis quantity. |
| `fat_g` | number (g) | no (default 0) | Total fat for the basis quantity. |
| `default_serving_g` | number (g) | no | Serving size in grams when the source supplies one (count-unit serving math). |
| `serving_label` | string | no | Human label for a serving (e.g. "1 cup"), display only. |
| `source_ref` | string | yes | The originating `source_ref`. |

Density and unit conventions (e.g. 1 ml ≈ 1 g) are documented assumptions
recorded in `assumptions` and defined per implementation (`food-resolution.md`).
Nutrition math (scaling facts to a logged quantity) is **out of scope** here and
owned by the resolution step.

## Provider Capability / Status

### Capability (what a configured provider advertises)

A provider declares a small, static capability descriptor so the estimator can
route without trial calls and so health/config diagnostics can surface provider
state (per the architecture doc):

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Source-system id (`usda_fdc`, `open_food_facts`, `official_source`, …). |
| `source_type` | enum | The hierarchy slot it fills. |
| `kinds` | enum[] | Lookup kinds it serves: `generic_food`, `barcode`, `named_product`, `restaurant_item`, `label`. |
| `enabled` | bool | Self-host config flag; a disabled provider is never called. |
| `available` | bool | Whether required config/credentials are present (e.g. an API key). |

A self-hosted deployment may disable any optional provider; v1 must make
provider `enabled`/`available` explicit in health/config diagnostics.

### Lookup status (the outcome of one source lookup)

Every source lookup resolves to exactly one status. These are the values
surfaced (with `source_type`) to clients on the resulting entry:

| Status | Meaning | Estimator response |
| --- | --- | --- |
| `unavailable` | Provider not configured / missing credentials. | Try next source; `model_prior` if none. |
| `disabled` | Provider turned off by self-host config. | Try next source; `model_prior` if none. |
| `rate_limited` | Provider returned a rate-limit / quota signal. | Treat as transient; bounded retry, then next source / `model_prior`. |
| `failed` | Timeout, connection error, 5xx, 4xx, non-conforming, or policy-blocked response. | Next source / `model_prior`; nothing from this source is trusted. |
| `partial` | A match was found but lacks a usable field (e.g. no energy value, or macros only). | Not finalizable alone; route to clarification or try next source. |
| `success` | A usable, schema-valid fact set was returned. | Finalize from these facts. |

`rate_limited` and a transient `failed` (timeout/5xx) are retryable within a
bound; a non-retryable `failed` (4xx/non-JSON/oversized/policy violation) is
terminal for that source. This generalizes the FTY-044 routing table in
`food-resolution.md`, which is the first concrete mapping of these statuses onto
the estimation-job state machine.

## Search Request / Response Boundary

Official-source lookup uses a configurable search provider (Brave Search is the
initial candidate) behind the backend; the estimator never browses directly.

**Request (estimator → search provider).** A single sanitized query string plus
a result cap. The query is built from the **item identity only** — product /
restaurant / dish name, brand, and barcode digits. It **must not** contain the
user's profile, body metrics, goals, food/exercise history, free-text message
beyond the item phrase, location, or account identifiers. Queries are
length-bounded and stripped of control characters before egress.

**Response (search provider → estimator).** A bounded list of candidate result
URLs + titles, treated as **untrusted**. The estimator selects candidate
official URLs to fetch; result text is never trusted as nutrition facts. Only
public HTTP(S) result URLs are eligible for the fetch step.

## Fetch Request / Response Boundary

The backend owns all network egress through a **hardened fetcher**; the
estimator gets no open-ended browser. The first implementation is FTY-044's
`hardened_fetch.py`. Every fetch enforces:

- **HTTPS only**, host **allowlisted** (provider hosts, or vetted official-page
  hosts) — non-https or non-allowlisted target **fails closed**.
- **SSRF defense**: every resolved IP must be public; loopback, private,
  link-local (incl. `169.254.169.254` metadata), multicast, reserved, and
  unspecified addresses are blocked.
- **Redirects refused** (or re-validated against the same policy).
- **Timeout** and **response-size** caps; oversized or slow responses fail.
- **Content-type allowlist** (e.g. JSON for APIs, HTML for pages); unexpected
  types are rejected.
- **Active content stripped** — scripts and active markup removed before
  extraction.
- **Raw content not retained**: store the extracted facts, the URL, the fetch
  timestamp, and a content hash — **never the raw page, payload, or OCR**.

Fetched pages, search results, OCR text, and provider JSON are **untrusted**
until validated by the normalized-fact schema and the deterministic
calculators. Provider keys are env/secret-manager only, never sent to clients,
never logged, and carried in headers (never the query string) so they cannot
leak through a logged URL. Fetch error messages carry no URL, headers, request
body, or response body.

## Validation

- A source result is trusted only after it validates against the **normalized
  nutrition fact schema**; only the fields used are trusted, and free-text
  fields (names, labels) are length-bounded.
- A fact set with **no energy value** is `partial`, not `success` — never
  finalized as a calorie source on its own.
- Search results and fetched content are untrusted input, not facts; they become
  facts only through schema-validated extraction.
- The `model_prior` fallback is gated by the **Fallback Rule**; an adapter that
  finalizes a named/barcoded/label/generic item from model prior while an
  applicable source lookup was available violates this contract.

## Authorization

- **Cached source facts** are global (no `user_id`) and shared across users;
  they must contain no user-specific habits, history, or identifiers.
- **Evidence provenance** is user-owned, carries `user_id` / `log_event_id` at
  the persistence boundary, and cascades on user/event deletion. The link from
  provenance to a global cache row is `ON DELETE SET NULL`, so clearing the cache
  never deletes a user's evidence (see `food-resolution.md`).

## Privacy and Retention

- **Data minimization at the provider boundary.** Search queries and lookups
  carry item identity only — never profile, body metrics, goals, history,
  location, or account identifiers.
- **Evidence, not raw content.** Persist extracted facts + URL + timestamp +
  content hash; never raw pages, payloads, or OCR by default. Nutrition-label
  images follow `docs/security/data-retention.md` (retain only while needed for
  extraction unless the user explicitly saves the attachment).
- **Source status retained and surfaced.** Each entry keeps its `source_type`,
  `source_ref`, lookup `status`, and assumptions so the user can see how it was
  estimated and edit it; `model_prior` entries record why the fallback was used.
- **Key safety & redacted errors.** Provider keys are env-only and never logged;
  fetch/search errors are content-free. See `docs/security/security-baseline.md`
  and `docs/security/threat-model.md` (SSRF, prompt injection from fetched
  pages/OCR, provider-key leakage, cross-user cache leakage).

## Errors

| Condition | Lookup status | Result |
| --- | --- | --- |
| Provider unconfigured / no credentials | `unavailable` | Next source; `model_prior` if none applies. |
| Provider disabled by config | `disabled` | Next source; `model_prior` if none applies. |
| Rate-limit / quota signal | `rate_limited` | Bounded retry, then next source / `model_prior`. |
| Timeout / 5xx | `failed` (transient) | Bounded retry, then next source / `model_prior`. |
| 4xx / non-JSON / oversized / policy violation (SSRF, non-allowlisted, bad content-type) | `failed` (terminal) | Next source / `model_prior`; nothing from this source is trusted. |
| Match found but missing usable field (no energy) | `partial` | Clarification or next source; not finalized alone. |
| Usable, schema-valid facts | `success` | Finalize. |

The mapping of these statuses onto the estimation-job state machine
(`processing → completed` / `needs_clarification` / `failed`, with retries) is
defined per step; see `estimation-jobs.md` and `food-resolution.md`.

## Examples

```
named restaurant item: "grilled chicken sandwich, <brand>"
  user_label?            no label provided        → not applicable
  official_source        search("grilled chicken sandwich <brand>")  # identity only, no profile
                         → candidate official URL → hardened fetch (https, allowlisted, SSRF-checked)
                         → extract → normalized facts (per_serving), status=success
  → evidence record: source_type=official_source, source_ref=official_source:<url>,
    content_hash, fetched_at, facts snapshot; raw page NOT stored
  → run.source_refs += "official_source"
```

```
barcoded packaged product: barcode 0123456789012
  user_label?            user did not enter label → not applicable
  official_source?       no official page identified
  product_database       open_food_facts lookup by barcode → per_serving facts, status=success
  → evidence record: source_type=product_database, source_ref=open_food_facts:0123456789012
```

```
generic food with no configured source and no label:
  trusted_nutrition_database  usda_fdc → unavailable (no API key)
  → Fallback Rule allows model_prior; evidence record source_type=model_prior,
    assumptions=["usda_fdc unavailable"], surfaced to client as a model-prior estimate
```

## Search Provider Adapter (Brave) — FTY-079

The search-provider adapter is the **search half** of the `official_source` tier: it
turns a sanitized item-identity query into candidate result URLs plus an explicit
status, implementing the **Search Request / Response Boundary** above. It is a
**pluggable** adapter — **Brave Search** is the default (and v1-only) backend — and is
**disabled by default** for self-host: no key is bundled, so out of the box it reports
`unavailable` and callers (FTY-062) fall through to the model-prior path. It ships
**no fetcher** (the result URLs are fetched by FTY-078's hardened fetcher) and **no
resolution pipeline** (FTY-062).

### Owner (additional)

`backend/app/estimator/search.py` (the `SearchProvider` interface, the
`BraveSearchProvider` adapter, `SearchSettings`, the `sanitize_query` chokepoint, the
`SearchStatus` values, and `build_search_provider`); the `official_source` entry in
the source-diagnostics surface (`backend/app/services/sources.py`,
`backend/app/routers/health.py`). The adapter reuses `hardened_fetch.py` for egress.

### Config (`SearchSettings`, `FATTY_SEARCH_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FATTY_SEARCH_PROVIDER` | `brave` | Which registered backend to use; only `brave` is registered in v1. An unknown value fails closed at config load. |
| `FATTY_SEARCH_ENABLED` | `true` | Self-host enable/disable flag. `false` → `disabled` even if a key is present. |
| `FATTY_SEARCH_API_KEY` | _(none)_ | Provider key (secret). **Absent → source `unavailable`** (disabled by default). |
| `FATTY_SEARCH_BASE_URL` | `https://api.search.brave.com` | API base; **must be https**. The allowlisted host is derived from it. |
| `FATTY_SEARCH_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `FATTY_SEARCH_MAX_RESULTS` | `5` | Candidate result URLs requested / surfaced. |

The key is a `SecretStr`, read from the environment only, never exposed to clients,
never logged, and sent only in the `X-Subscription-Token` **header** (never the query
string, so it cannot leak through a logged URL). With no key the source is unavailable
and callers fall through to model-prior-with-status.

### Capability / availability

The adapter advertises a capability descriptor — `enabled` (the self-host flag) and
`available` (a key is present) — surfaced in `GET /healthz/sources` under
`id = official_source`, `source_type = official_source`,
`kinds = [named_product, restaurant_item]`, so a self-hoster can confirm whether
search is on without any trial call. The descriptor carries no secret.

### Status values

Every lookup resolves to exactly one status, aligned with the **Provider
Capability / Status** vocabulary above:

| Status | When | Result |
| --- | --- | --- |
| `disabled` | `FATTY_SEARCH_ENABLED=false`. | No call; caller tries next source / `model_prior`. |
| `unavailable` | No API key configured (default posture). | No call; caller falls through. |
| `rate_limited` | Provider returned an HTTP 429 rate-limit / quota signal. | Bounded retry, then next source / `model_prior`. |
| `failed` | Timeout, connection error, 5xx, other 4xx, non-JSON, oversized, or policy-blocked (non-https / non-allowlisted / redirect / private-IP) response. | Nothing trusted; next source / `model_prior`. |
| `partial` | The provider answered but offered no usable candidate URL (or the sanitized query was empty). | Not finalizable; next source. |
| `success` | A bounded list of candidate HTTP(S) result URLs was returned. | URLs handed to the fetch step (FTY-078). |

A non-`success` status always carries an empty candidate list, so an off/failed
lookup can never be mistaken for a result.

### Query sanitization / data minimization

`sanitize_query` is the **single chokepoint** every query passes through before
egress: it strips control characters (so multi-line / structured personal context
cannot be smuggled), collapses whitespace, and length-bounds the string (≤ 256
chars). The adapter accepts a single item-identity string and sends a **closed**
request shape — only `q` (the sanitized name) and `count` — so profile, weight, food
history, and event metadata have **no channel** to the provider. A test proves no
personal context egresses.

### Errors

Transport/policy failures are mapped to a status, never surfaced as an exception that
echoes the query, key, headers, or response body. Rate-limit detection rides on the
`status_code` carried by `hardened_fetch`'s `FetchResponseError` (a non-sensitive
integer, never the body). Egress is allowlisted to the single configured search host
by the hardened fetcher.

## Official-Source Resolution Step (FTY-062)

FTY-062 implements the consumer of the `official_source` tier: the resolution
pipeline step that turns the FTY-079 search candidates + FTY-078 fetched text into a
costed, evidence-backed `derived_food_items` row, and otherwise falls through to the
`model_prior` tier. It changes **neither** this contract's source hierarchy nor its
fallback semantics; it fixes only the **pipeline ordering** between two of the tiers.

**Hierarchy rank vs. pipeline order.** The **Source Hierarchy** above is a
*preference* ranking (which source's facts win for the same input). FTY-062 additionally
fixes where the `official_source` *work* runs in the estimation pipeline: it is the
**last resort before `model_prior`**, executing **only after** USDA (`usda_fdc`) and
Open Food Facts (`open_food_facts`) miss. The expensive path (search + hardened fetch +
LLM extraction) is therefore attempted only when the cheap deterministic databases
cannot cost the item — a deliberate ordering distinct from the preference rank, and the
reason a generic food never reaches official source (it is not `official_source`
applicable) while a named/branded item USDA misses does.

- **Applicability signal.** `official_source` is *applicable* only to a **named**
  product / restaurant / manufacturer item. The first concrete implementation marks
  this with an additive optional `brand` field on the parse candidate
  (`parse-candidates.md`): a candidate with a brand is official-source-eligible, a
  generic food is not. See `food-resolution.md` (**Official-Source Resolution**).
- **Fallback Rule, concretely.** When the search lookup reports `disabled` /
  `unavailable` / `rate_limited` / `failed` / `partial`, or no fetched page yields a
  schema-valid fact set, the named item falls through to a `model_prior` evidence
  record (`source_type = model_prior`) carrying the **reason** in `assumptions` — the
  contract's "record the reason it was used, so the source status is surfaced and the
  entry remains editable", made durable on the evidence row via the additive
  `evidence_sources.assumptions` column.
- **Record shape.** An `official_source` record's `source_ref` is
  `official_source:<url>` (the URL only — no headers, body, or query secrets, and never
  the raw page); it has no global `products` cache row. The `assumptions` field of the
  **Evidence Source Record** is now persisted (model-prior reason, density/serving
  assumptions); the `status` lookup outcome continues to be surfaced via the run
  `source_refs` and the `source_type`.

## Migration / Compatibility

- This contract is **additive documentation**; it introduces no schema or code
  change on its own. It names and fixes the source taxonomy, status values,
  normalized-fact fields, and search/fetch boundaries that FTY-044 already
  implements for USDA and that follow-up stories implement for Open Food Facts,
  official-source search/fetch, and nutrition-label extraction.
- The source-system ids (`usda_fdc`, `open_food_facts`, `official_source`,
  `user_label`, `model_prior`) and the six lookup-status values are the stable
  surface later adapters and clients depend on.
- Adding a provider means adding an adapter behind the **capability** descriptor
  and the **search**/**fetch** boundaries, mapping its response to the
  **normalized fact schema** and a lookup **status** — without changing this
  contract or re-deciding the source hierarchy or fallback semantics.
- Recipe (ingredient-sum) and similar-dish reference sources remain deferred;
  this contract leaves the hierarchy slots reserved for them.
- FTY-079 adds the `official_source` search adapter (`search.py`) and an
  `official_source` entry in `GET /healthz/sources`. It is additive: a new
  `FATTY_SEARCH_`-prefixed config block (disabled by default, no bundled key), no
  schema change, and a backward-compatible `status_code` attribute on
  `hardened_fetch`'s response/transient errors for rate-limit (HTTP 429) detection.
  The fetcher (FTY-078) and the resolution pipeline (FTY-062) remain separate.
- FTY-062 adds the `official_source` resolution pipeline step (`official_step.py`)
  consuming the FTY-079 search + FTY-078 fetch, and the `model_prior` fallback. It is
  additive: an optional `brand` parse-candidate field, the `NamedFoodEstimate`
  extraction/estimate schema, and the nullable `evidence_sources.assumptions` column
  (`0012` migration). It does not redefine the hierarchy, the status vocabulary, or the
  fallback rule; it fixes the pipeline ordering (official source last before
  model-prior). See `food-resolution.md` (**Official-Source Resolution**).
