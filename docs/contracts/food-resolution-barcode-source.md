# Contract: Barcode (Open Food Facts) Food Source

## Purpose

The barcode / Open Food Facts (OFF) source tier of
[food-resolution.md](food-resolution.md): how a food candidate carrying a UPC/EAN
barcode — and, since FTY-369, a barcode-less branded product by name — resolves into
the same `derived_food_items` shape from **Open Food Facts**. This page was extracted
**verbatim** from `food-resolution.md` (FTY-409, contract-only — no semantic change);
the rest of the food-resolution contract (Inputs, serving math, routing, the USDA /
official / reference / model-prior tiers) stays there.

## Owner

estimator / contracts / backend-core / security-privacy lane (same owners as
[food-resolution.md](food-resolution.md)): the OFF client and routing modules named in
the `### Owner (additional)` subsection below —
`backend/app/estimator/off.py`, `backend/app/estimator/food_step.py`,
`backend/app/estimator/food_resolvers.py`, `backend/app/estimator/official_step.py`,
`backend/app/models/food_sources.py` (`products.barcode`),
`backend/app/routers/health.py`, and `backend/app/services/sources.py`.

## Barcode Source (Open Food Facts) — FTY-060

The barcode source resolves a food candidate carrying a UPC/EAN **barcode** into the
same `derived_food_items` resolution shape (canonical kcal + grams, stored evidence,
cached product) as the USDA path, but from **Open Food Facts** (OFF). It is the
`product_database` tier of the evidence-retrieval hierarchy (`evidence-retrieval.md`)
and sits **above** USDA generic: when a candidate has a barcode and OFF is enabled,
OFF is queried first; a confident match is preferred over a generic USDA estimate.

### Owner (additional)

`backend/app/estimator/off.py` (OFF client, settings, mapping, barcode normalization,
and the FTY-369 name-search path), `BarcodeResolver` + the source-hierarchy routing in
`backend/app/estimator/food_step.py`, the `OffNameResolver` +
`OfficialSourceResolveStep` name-search tier (`backend/app/estimator/food_resolvers.py`,
`backend/app/estimator/official_step.py`, FTY-369), the `products.barcode` key
(`backend/app/models/food_sources.py` + `0010` migration), and the source-diagnostics
endpoint (`backend/app/routers/health.py`, `backend/app/services/sources.py`).

### Name search for barcode-less branded products (FTY-369)

Not every branded packaged product carries a barcode in the log. When a **branded**
candidate cannot be costed by USDA (generic) or OFF-by-barcode, the official-source
step consults OFF **by name** as the `product_database` tier — after official source,
before reference and model prior — through `OffClient.search_by_name` +
`OffNameResolver`. It reuses this same hardened, allowlisted OFF transport
(`hardened_fetch.get_json`) against OFF's public `cgi/search.pl` name endpoint (JSON,
the same pinned `fields` list, a bounded `page_size`); the reply validates against an
`OffProductResponse`-style schema and each candidate goes through the identical
energy/plausibility gate and serving math the barcode path uses. Every name query is
**item identity only**, built from the bounded `identity_variants` machinery (name +
brand + product hint, deduplicated, capped at `MAX_IDENTITY_VARIANTS`) and passed
through the `sanitize_query` chokepoint before egress — never profile, goals, body
metrics, history, ids, or raw diary text. Each OFF hit must pass the same
`is_evidence_brand_compatible` gate FDC branded routing applies, so a search that
returns a **different** product (another brand or item) is rejected and the chain
continues. A compatible hit caches as a global name-keyed `products` row
(`source = open_food_facts`, `query_key` = the normalized name query, `barcode = NULL`,
`source_ref = open_food_facts:<code>`) and records `source_type = product_database`
evidence — never the raw OFF payload or query.

### Config (`OffSettings`, `SLACKS_OFF_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLACKS_OFF_ENABLED` | `true` | Self-host enable/disable flag. OFF is an open API (no key), so it is **on by default**; set `false` to disable the source. |
| `SLACKS_OFF_BASE_URL` | `https://world.openfoodfacts.org` | API base; **must be https**. The allowlisted host is derived from it. |
| `SLACKS_OFF_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `SLACKS_OFF_USER_AGENT` | `Slacks/1.0 (+…)` | Non-secret identifying user-agent (OFF API etiquette / rate limits). `Slacks/1.0` is the runtime literal (`backend/app/estimator/off.py`), the product's outbound identity. |

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
| Barcode OFF no match / invalid barcode / no usable or implausible energy, but recognizable identity and `estimate_first` | _(falls back)_ | next source / reference / model/default-prior rough evidence + assumptions | per the source it falls to |
| Barcode OFF no match / invalid barcode / no usable or implausible energy, no identity or active policy asks | `NeedsClarification` (`barcode_unknown`) | clarification question | `processing → needs_clarification` |
| Unresolvable quantity, `estimate_first` | _(falls back)_ | default-serving/reference/model-prior rough evidence + assumptions | per the source it falls to |
| Unresolvable quantity, active policy asks or rough paths unavailable/unsafe | `NeedsClarification` (`unresolvable_quantity`) | clarification question | `processing → needs_clarification` |
| OFF transient failure (timeout/5xx) | `StepError` (`off_transient_error`, retryable) | nothing | retries within bound, then degrades — never terminal `failed` (`estimation-jobs.md` v7, FTY-370) |
| OFF non-retryable error (4xx/non-JSON/policy) | `StepFailed` (`off_response_error`) | nothing | `processing → failed` |
| OFF disabled/unavailable for a barcode candidate | _(falls back)_ | next source / rough estimate when policy allows, else `needs_clarification` | per the source it falls to |

A barcode is **never** finalized from a guessed model-prior value **as a barcode
match** while OFF is available; if OFF misses and the candidate has a recognizable
food identity, `estimate_first` may rough-estimate from that identity with explicit
non-barcode provenance and assumptions. When OFF is disabled, unavailable, or misses,
a barcode candidate falls back to the next applicable source (USDA generic by name,
reference, then model/default-prior as allowed by policy). The run records the
consulted source system(s) (`open_food_facts`, and/or `usda_fdc`) in `source_refs` so
estimation source status is surfaced.

### Diagnostics

`GET /healthz/sources` returns each evidence source's capability descriptor
(`id`, `source_type`, `kinds`, `enabled`, `available`) — Open Food Facts
(`barcode`, `named_product` — FTY-369) and USDA FDC (`generic_food`) — so a
self-hoster can confirm which sources are on without any trial call. It carries no
secrets and makes no external calls.
