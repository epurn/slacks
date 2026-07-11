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
Adapter — FTY-079 / FTY-164**.

## Version

10 (FTY-308): implements the **barcode** exact-evidence proposal generator (the
`kind = barcode` half of the **Exact Evidence Upgrade** below). It reuses the existing
hardened cache-first Open Food Facts path and plausibility gate for the `exact`
`product_database` proposal and the existing reference-source → model-prior tiers (from
the item's sanitized identity only) for a `fallback`, signed into the FTY-307
`proposal_ref`. This fixes the concrete barcode `failure_reason` vocabulary the shape
below references: `barcode_invalid` (non-GTIN input), `barcode_no_match` (OFF has no
product for the barcode), `no_usable_facts` (OFF returned a product but its facts are
unusable/plausibility-rejected), and `source_unavailable` (OFF disabled by config); a
fallback records a fixed content-free provenance assumption, never provider output, and
the source hierarchy, statuses, fact schema, egress, and retention rules are unchanged.

9 (FTY-326): food-resolution evidence tiers now write bounded sanitized evidence-view records into the run-local `InterpretationSession` ledger. Records may include trace-safe source refs,
surfaces, and source-stated descriptors needed for interpretation, but never raw
pages, snippets, queries, diary text, or provider output blobs. After an
official/reference evidence dead end, the resolver may spend the session's one
bounded re-interpretation pass and re-query once before falling to `model_prior`,
which receives only sanitized identity, bounded structured portion fields, and
evidence-view records; its terminal trace adds `provider_error`,
`low_confidence`, `non_resolved_disposition`, or `unusable_facts`. As the
transient model-facing half of that split, an unaccepted page/snippet read's own
bounded FTY-314-framed inert text may reach the session's re-interpretation
prompt at prompt-construction time — model boundary only, consumed by that one
re-ask; it is never written to ledger records, traces, assumptions, source refs,
persisted rows, or the model-prior prompt, and is never used to build a search
query or fetch URL. That last rule is enforced deterministically, not assumed of
the model: the session retains the token set of every staged excerpt, and the
resolver bridge drops any revised-identity word carrying a staged-excerpt token
that no sanitized surface of the run authorized — the user's own entry/answers,
or the ledger's sanitized source-stated descriptors (an extraction identity
already reduced through identity sanitization, a trusted database row
description) — before the revised hypothesis may drive a re-query, fetch, or
persisted item field. A source-stated identity correction the descriptor also
carries (`PC` → `Presidents Choice`) therefore survives to drive the bounded
re-query, while an unvetted excerpt payload cannot reach an outbound query even
if the provider returns it.
USDA row acceptance joins the loop the same way: rows the FTY-254 ranked
compatibility gate rejects are recorded as bounded `rejected_incompatible_row`
ledger records (global row description + ref, no user data) and may trigger the
same single bounded re-interpretation plus one retried lookup. Source hierarchy,
statuses, egress, schema, provenance, and retention rules are unchanged.

8 (FTY-348, contract only): relocates the global FTY-324 interpretation-loop framing
to [interpretation-session.md](interpretation-session.md); page-local rules unchanged.

7 (FTY-306, contract only): adds the **exact evidence upgrade** — the correction
sheet's `Make it exact` lever — as an in-place source replacement for **low-trust
or incomplete food items**: a server-built barcode/label **proposal** (opaque
`proposal_ref`, `kind`, `quality` `exact`/`fallback`/`none`, `failure_reason`,
preview, costability flag) that the user previews and explicitly applies, with
re-match semantics (provenance rewrite, `*_estimated` re-snapshot, one `re_match`
audit row, `is_edited = false`). No new source tier: an exact barcode proposal is
`product_database`, an exact label proposal is `user_label`, and a fallback keeps
honest low-trust provenance (`reference_source`, `model_prior`, or the
`comparable_reference` marker). The source hierarchy, lookup statuses, normalized
fact schema, search/fetch boundaries, and retention rules are unchanged. See
**Exact Evidence Upgrade — FTY-306**; backend implementation is FTY-307–FTY-309,
mobile consumption FTY-310–FTY-313.

6 (FTY-324, contract cross-reference): reclassifies source tiers as bounded
evidence tools available to the `InterpretationSession` defined in
[parse-candidates.md](parse-candidates.md) and
[food-resolution.md](food-resolution.md). The source hierarchy, lookup statuses,
normalized fact schema, sanitized search boundary, hardened fetch boundary,
retention rules, and provenance vocabulary are unchanged; raw log text still never
egresses to search/fetch providers or persisted evidence metadata.

5 (FTY-314) admits the **search-result snippet** as a bounded, lower-confidence
untrusted evidence surface. A search candidate now carries the provider's result
snippet (SearXNG `content` / Brave `description`) alongside its URL and title —
optional, length-bounded, empty when the provider sends none, and never required
for a `success` lookup. In the searched-reference chain the fetched page stays
first: only when a candidate's page fetch fails, returns no usable text, or
extracts no accepted facts may that candidate's bounded title+snippet be
extracted through the **same** untrusted-text framing, `NamedFoodEstimate`
schema validation, compatibility checks, and deterministic serving math. A
snippet-derived result keeps the result URL as `source_ref` and records the
content-free `search_result_snippet` assumption label; the raw snippet is never
persisted. Confidence rank: **below** a fetched official/reference page, **above**
pure model prior. See **Search-Result Snippet Evidence — FTY-314**.

4 (FTY-253) allows the official/reference search consumer to send a **bounded,
deterministic set of item-identity query variants** per lookup instead of exactly
one query: the `name + brand` base, the quantity-phrase product hint in both token
orders (for parses that strand product tokens in `quantity_text`), and a static
private-label/retailer alias expansion (e.g. Compliments ↔ Sobeys). Each variant is
still **item identity only**, composed from parsed candidate fields, sanitized
through the identity sanitizer where it derives from the quantity phrase, and
passed through the same `sanitize_query` chokepoint; the set is deduplicated and
hard-capped, never open-ended. Evidence candidates for a **branded** item must also
pass a deterministic brand/product-compatibility check before they may back the
item (see `food-resolution.md` **Brand-aware packaged-product routing**). The
search request/response shapes, status vocabulary, and fetch boundaries are
unchanged.

3 (FTY-252) adds **count-serving named-food evidence** to the normalized estimate
shape used by official-source, reference-source, and model-prior resolution. A
fact set may include `serving_count = {amount, unit}` for facts stated per counted
serving (`3 strips`, `1 slice`, `2 eggs`, `5 crackers`). Count units validate
against a bounded synonym map; compatible consumed counts scale by
`consumed_count / source_count`, while incompatible or missing units are rejected so
the resolver tries the next evidence result/tier.

2 (FTY-298, contract only): clarifies rough-estimate provenance under the shared
`estimate_first` policy now owned by
[estimator-policy.md](estimator-policy.md). This evidence contract keeps the source
hierarchy, evidence record shape, source provenance, search/fetch/re-match rules, and
retention rules that carry those provenance requirements in the read and persistence
models.

1 (FTY-045). The source-system identifiers are stable strings recorded on each
evidence record and on the estimation run `source_refs`: `usda_fdc`,
`open_food_facts`, `official_source`, `user_label`, `user_text` (FTY-279),
`reference_source` (FTY-166), `model_prior`.

FTY-279 makes **explicit nutrition facts stated in the log entry text** first-class
user-provided evidence: the rank-1 user-provided tier gains the `user_text`
source system (a calorie total and/or macros the user typed, recorded `as_logged`
with a `user_text:<content_hash>` reference over the extracted facts — never the raw
phrase), the normalized-fact schema gains the `as_logged` basis and per-field
provenance so a user-stated number and an estimated/unknown one stay honestly
distinct, and the fallback rule makes a user-stated fact outrank external lookup for
the exact field the user gave. See **User-Stated Nutrition Evidence — FTY-279**.

FTY-079 implements the `official_source` **search** boundary (the pluggable
search-provider adapter) without changing this contract; see **Search Provider
Adapter — FTY-079 / FTY-164**. The six lookup-status values and the
sanitized-query / header-only-key rules are exactly those fixed here.

FTY-164 makes search a **keyless default capability**: the default backend becomes
a local/self-hosted **SearXNG** instance (no API key), Brave becomes the explicit
keyed opt-in, and `none` is the explicit operator off switch. The registered
provider ids are `searxng`, `brave`, and `none`. The status vocabulary, the
sanitized-query chokepoint, and the header-only-key rule (for Brave) are unchanged.

FTY-093 adds the **item re-match** capability (list alternative source matches +
re-resolve an item to a chosen source) on top of the existing resolution pipeline,
without changing the source hierarchy, the lookup-status vocabulary, the fallback
rule, the normalized-fact schema, the serving math, or the `evidence_sources` record
shape. It introduces **no** schema migration. See **Item Re-match — FTY-093**.

FTY-166 adds the **`reference_source`** evidence tier: when official sources miss
(or do not apply — a detail-rich generic food has no brand page), the estimator
searches for **public nutrition reference evidence**, fetches the bounded result
page through the hardened **searched-result** fetch policy, and transcribes the
stated facts — so `model_prior` becomes the final fallback only after evidence
search/fetch fails. See **Reference-Source Fallback — FTY-166**.

## Source Hierarchy

The estimator selects the highest-preference applicable source and only falls
back when it is unavailable, disabled, rate-limited, or fails. This refines the
`docs/architecture/system-overview.md` source hierarchy with where each
configured v1 provider sits:

| Rank | `source_type` | Source system | Applies to |
| --- | --- | --- | --- |
| 1 | `user_label` | user-provided | nutrition-label image (OCR) or manually entered label facts; user-confirmed barcode/package facts |
| 1 | `user_text` | user-provided | explicit nutrition facts stated in the log entry text — a calorie total and/or macros, recorded `as_logged` (FTY-279) |
| 2 | `official_source` | search + hardened fetch | official restaurant / manufacturer / product page |
| 3 | `product_database` | `open_food_facts` | barcoded and packaged food products |
| 4 | `trusted_nutrition_database` | `usda_fdc` | generic foods and common serving references |
| 5 | `reference_source` | search + hardened searched-result fetch | public nutrition reference pages, when the higher tiers miss or do not apply (FTY-166) |
| 6 | `model_prior` | `model_prior` | last-resort rough/default-prior fallback only, with explicit assumptions and editability (see **Fallback Rule**) |

Ingredient-based recipe calculation and similar-dish reference estimates
(system-overview ranks 6–7) are deferred; this contract reserves room for them
without defining their records yet. A source type is **applicable** only when an
input of that kind exists (e.g. `user_label` requires a label/barcode; `user_text`
(FTY-279) requires an explicit nutrition fact in the entry text;
`official_source` requires a named restaurant/manufacturer item).

The two rank-1 tiers are both **user-provided** and apply to different inputs; for
the same item each backs only the **fields it carries** — a stated calorie total
(`user_text`) and a scanned label (`user_label`) do not compete, and a missing
field on either falls to a lower tier with its own provenance (**Field
provenance**, **Fallback Rule**).

## Fallback Rule

The estimator **must not finalize** named products, restaurant items, barcodes,
nutrition labels, or generic food lookups from **model prior alone** when a
source lookup for that item is available (configured, enabled, and applicable).
`model_prior` is permitted only when, for the applicable source(s), the lookup
outcome is `unavailable`, `disabled`, `rate_limited`, or `failed`, when no
source type applies, or when the user supplied insufficient information and
declined a clarifying question. Since FTY-166 the applicable sources include the
`reference_source` tier, so the model prior is never asked to invent nutrition
facts while a reference search/fetch is still available: it runs only after
official **and** reference evidence returned no confident match (or could not be
consulted), and its `assumptions` name the per-tier reason.

A `model_prior` result is recorded as an evidence record with
`source_type = model_prior` and the reason it was used, so the source status is
surfaced to clients and the entry remains editable. This is a contract-level
restatement of the architecture `Lookup Rule`; adapters must not weaken it.

**Rare clarification / rough-estimate fallback (FTY-298).** The shared
estimate-first and rough-provenance semantics are defined in
[estimator-policy.md](estimator-policy.md). This evidence contract owns the concrete
`source_type`, `source_ref`,
`field_provenance`, `estimate_basis`, `assumptions`, status, and retention shapes that
make exact/product-backed, official/reference-backed, comparable aggregate, and
model/default-prior estimates distinguishable in persistence and read models.

**Evidence tools inside the interpretation loop (FTY-324).** Source tiers remain
ordered by the hierarchy above, but they are bounded tools the
`InterpretationSession` may consult with the current hypothesis and evidence view
rather than a blind one-way fall-through; the session/tool contract and its
raw-text-egress limits are defined in
[interpretation-session.md](interpretation-session.md). This page still owns the
source hierarchy, statuses, egress/fetch gates, fact-schema validation, serving
math, budget caps, and persisted provenance. FTY-326 records tier hits, misses,
fetch/extraction failures, compatibility rejections, and snippet-surface outcomes as
bounded sanitized evidence-view records; after an evidence dead end the resolver may
re-open interpretation once and re-query with a revised identity. The ledger never
carries raw diary text, search queries, pages, snippets, or provider output blobs,
and it never changes the source hierarchy or math/provenance authority.

**User-stated facts and the fallback rule (FTY-279).** A nutrition fact the user
stated in the entry text (`user_text`) is the **highest-preference** source for
the exact field(s) they gave — it outranks every external lookup for those fields
(the user's own "580 cals" wins over a database guess for that item's calories).
This does **not** weaken the rule for **missing** fields: a field the user did not
state may still be estimated from `model_prior` (or filled from a reference/official
lookup), recorded on the **same** item with its own `field_provenance = estimated`
and the model-prior reason in `assumptions` — never presented as a user-provided
fact. A missing field may also be left `unknown`/`null` when no credible estimate is
produced. See **User-Stated Nutrition Evidence — FTY-279**.

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
| `source_ref` | string | Stable reference, e.g. `usda_fdc:<fdcId>`, `open_food_facts:<barcode>`, `official_source:<url>`, `reference_source:<url>` (FTY-166), `user_label:<content_hash>` (FTY-061; the SHA-256 of the label image, which a saved `log_attachments` row shares), `user_text:<content_hash>` (FTY-279; the SHA-256 of the **extracted, normalized facts** — never the raw diary phrase), `model_prior`. |
| `content_hash` | string | Hash of the extracted facts / fetched content the snapshot came from. |
| `fetched_at` | timestamptz | When the source was queried/extracted (for `user_text`, when the facts were extracted at log time). |
| `facts` | normalized nutrition facts | Immutable snapshot (see below). |
| `status` | lookup status | The outcome that produced this record (see **Provider Capability / Status**). |
| `field_provenance` | map | _(FTY-279, optional)_ Per-field provenance when a record's fields have **heterogeneous** origins (user-stated calories + estimated/unknown macros): maps each of `calories` / `protein_g` / `carbs_g` / `fat_g` to `user_stated`, `estimated`, or `unknown`. Absent → every present fact field shares this record's `source_type`. |
| `assumptions` | string[] | Any documented assumptions (density, default serving, model-prior reason, per-field estimate reason, active rough-estimate basis). Assumptions are content-free labels and source ids only; never raw diary text, prompts, provider output, fetched text, URLs with secrets, request/response bodies, or provider error bodies. |

`source_ref` for a fetched `official_source` or `reference_source` records the
URL only (no headers, body, or query secrets). Object-level ownership and
`ON DELETE CASCADE` are defined in `food-resolution.md` and
`docs/security/data-retention.md`.

## Normalized Nutrition Fact Schema

The canonical facts every source maps into, sufficient for v1 calories+macros.
Storage is canonical units only — **kcal and grams** — per the contracts
`README.md` principle; display units are a client preference.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `basis` | enum | yes | `per_100g`, `per_100ml`, `per_serving`, or `as_logged` — what the facts are expressed against. `per_serving` may be a gram/millilitre serving or a structured count serving (`serving_count`, FTY-252). `as_logged` facts are the **totals for the exact logged item** and are **not** scaled by the serving math. It is used for user-stated facts (`user_text`, FTY-279/280) and for bounded rough model-prior totals when grams cannot honestly be inferred (FTY-301). |
| `calories` | number (kcal) | yes | Energy for the basis quantity. A fact set with no energy value is **not** a usable match. |
| `protein_g` | number (g) \| null | no (default 0) | Protein for the basis quantity. |
| `carbs_g` | number (g) \| null | no (default 0) | Carbohydrate for the basis quantity. |
| `fat_g` | number (g) \| null | no (default 0) | Total fat for the basis quantity. |
| `default_serving_g` | number (g) | no | Serving size in grams when the source supplies one (count-unit serving math). |
| `serving_label` | string | no | Human label for a serving (e.g. "1 cup"), display only. |
| `serving_count` | object | no | Structured counted serving relation `{amount, unit}` when facts are stated per `N <count_unit>` (FTY-252). `unit` is normalized through the bounded count-serving map (`strip`, `piece`, `slice`, `egg`, `cracker`, `bar` and singular/plural synonyms); no fuzzy matching. |
| `source_ref` | string | yes | The originating `source_ref`. |

Density and unit conventions (e.g. 1 ml ≈ 1 g) are documented assumptions
recorded in `assumptions` and defined per implementation (`food-resolution.md`).
Nutrition math is **out of scope** here and owned by the resolution step. An
`as_logged` fact set is the consumed total, stored without scaling; `model_prior`
as-logged rows must carry rough assumptions such as `as_logged_model_prior`.

**Count-serving scaling (FTY-252).** For official/reference/model-prior named-food
facts with `serving_count`, the resolver scales a compatible logged count as
`source facts × consumed_count / source_count`. If the fact set also has
`default_serving_g` / serving-size grams for the counted serving, logged grams are
scaled by the same count ratio. A source such as `90 kcal per 5 crackers (19 g)` and
a logged `4 crackers` therefore records about `72 kcal` and `15.2 g`; it must not
be treated as four whole servings. When the logged unit is absent or incompatible
(`per 3 strips` vs. `2 cups`), the fact set is not usable for that logged quantity
and the resolver continues through remaining evidence results/tier fallback. Count
relations must come from structured, schema-validated fields; free-text
`assumptions` are never parsed for serving math.

**Unknown vs. zero macros (FTY-279).** The `default 0` for a missing macro is the
convention for a **trusted-database / label / official / reference** fact set,
where an absent nutrient is genuinely ~0 for the item. For an **`as_logged`
user-stated** record a macro the user did **not** state and the estimator did
**not** estimate is `null` (**unknown**) — never silently `0`. An unknown macro
(`null`) is **not** the same as a real zero macro (`0 g`) and must stay
distinguishable at the item detail / provenance level (`daily-summary.md`); a
`null` macro contributes **no** grams to a daily macro total rather than counting
as `0`. `calories` stays required for a usable match on every basis, including
`as_logged`.

## User-Stated Nutrition Evidence — FTY-279

When a user states explicit nutrition facts in a log entry — a calorie total
("…580 cals…"), or a macro fact ("30g protein") — those facts are **first-class
user-provided evidence**, the same rank-1 tier as a scanned or manually entered
label. The LLM is allowed to **read the text and extract what the user actually
said**; the safety boundary is **not** "ignore nutrition in raw text." The boundary
is: a persisted number must be backed by explicit evidence/provenance, validated for
plausibility, and honest about which fields the user supplied versus which were
estimated or left unknown.

### Source system and reference

- **Source system id / `source_type`:** `user_text` (rank 1, the user-provided
  tier). Distinct from `user_label` so a client can tell a number the user **typed
  into a log** from one **scanned off a label**.
- **`source_ref`:** `user_text:<content_hash>` — the SHA-256 of the **extracted,
  normalized facts**, never the raw diary phrase. The raw text is never stored in the
  source ref, the evidence record, `assumptions`, logs, or provider traces
  (**Privacy and Retention**).

### `as_logged` basis (no per-100g lie)

A user-stated total is expressed **as logged**: it is the value for the exact item
the user logged, not a per-reference-quantity fact. Such facts carry `basis =
as_logged` and are **not** scaled by the serving math. A stated `580 cals` is
recorded `basis = as_logged, calories = 580` — it **must not** be recorded as
`per_100g` / `per_serving` (e.g. `580 kcal per 100g`) unless the user also stated a
real mass/serving basis to anchor it. This keeps an as-logged number from being
silently reinterpreted as a density.

### Field provenance (explicit vs. estimated vs. unknown)

A user-stated item routinely has **mixed** provenance — the user gave calories but
not macros. Each nutrition field carries its own provenance via the record's
`field_provenance` map:

- **user-stated fields** are evidence-backed user-provided facts (`user_stated`);
- **missing fields may be estimated** — source-backed lookup first, then
  comparable-source aggregation (rough reference evidence), then the model prior —
  **when a usable identity exists** (`estimated`), with the estimate's
  assumptions/provenance recorded — never presented as a user-provided fact (see
  **Estimating a missing field** below);
- **missing fields may instead remain unknown/`null`** (`unknown`) when no credible
  estimate is produced;
- an **unknown** macro (`null`) is **not** the same as a **zero** macro (`0 g`) — the
  two are stored and surfaced differently (**Normalized Nutrition Fact Schema**;
  `daily-summary.md`).

For the fields the user stated, `user_text` **outranks** any external lookup
(evidence-first, **Fallback Rule**); missing fields fall to a lower tier with their
own provenance.

### Estimating a missing field (source-backed lookup → comparable-source aggregation → model prior)

A field the user did not state (a missing macro on a `user_text` calorie item, or any
other absent field) is filled in a **fixed preference order**, so a real number is
never invented while better evidence is still reachable:

1. **Source-backed lookup first.** When a **sanitized item-identity query** exists
   (`sanitize_query`, item identity only — **Search Request / Response Boundary**), a
   single confident match from the source tiers (official / product / trusted-database /
   reference) fills the field before any model prior is consulted. This is the same
   evidence-before-`model_prior` guarantee as the **Fallback Rule**, applied per missing
   field: `field_provenance = estimated` with the source's `source_ref` recorded. When
   this single-source reference lookup fills a `user_text` item's missing macros, the
   read-model also surfaces the rough basis via the additive optional
   `ItemSourceDTO.estimate_basis = reference_source` (FTY-350), derived at read time from
   the item's own `assumptions` marker with **no** new persisted column — the item stays
   `user_text`, exactly as step 2 surfaces `comparable_reference`.
2. **Comparable-source aggregation — rough reference evidence.** When no single source
   confidently resolves the field but several comparable references exist, the estimator
   may derive a **rough reference estimate** by aggregating the comparable facts. This
   aggregate is explicitly **reference-grade, not an authoritative source fact**: it
   ranks **below** a single-source match and **above** a pure model prior, and it is
   bounded by three guardrails so it can never become provenance-free averaging:
   - **Source refs, always.** The aggregate names **every** contributing source in
     `assumptions` — each `reference_source:<url>` with its **content hash** and its
     immutable **per-100g fact snapshot** — never a single anonymous blended number, so
     a client can audit exactly which references, with which facts, produced the
     estimate. The read-model also surfaces the rough basis via the additive optional
     `ItemSourceDTO.estimate_basis = comparable_reference` (the item stays `user_text`).
   - **Compatibility checks.** Only facts for a **comparable item on a comparable
     basis** are aggregated — normalized to the same canonical basis (per-100g) and
     restricted to the same food identity/kind. An incompatible-basis or unrelated-item
     fact is **excluded**, never blended in.
   - **Plausibility / outlier filtering.** Contributing values must pass the same
     plausibility bound used for source facts (FTY-115/132, canonical per-100g space);
     values outside the bound, or that are statistical **outliers** relative to the
     sample, are **dropped before** aggregation, so one bad reference cannot skew the
     result. If too few comparable, plausible references survive, the aggregate is **not
     produced** — the field falls through to step 3 rather than averaging noise.
   The result is recorded `field_provenance = estimated` with the aggregation method and
   the contributing `source_ref` list in `assumptions` — never presented as a
   user-stated or single-source fact. **Implemented in FTY-281**
   (`app/estimator/comparable_reference.py`, wired into `UserTextMacroEstimator`): after
   the exact (identity + brand) reference lookup misses, a **brand-dropped** identity +
   `nutrition facts` search surfaces comparable pages; each transcribed page is
   compatibility-checked (food form/category **and** ingredient/flavor overlap against
   the item identity — the overlap must be a real **food** term: prompt-injection /
   chat-framing / personal-context words the raw diary phrase and an adversarial page
   happen to share are excluded, so a page with no shared ingredient/flavor can never
   read as compatible) and canonicalised to per-100g (per-serving facts with no gram
   basis, and implausible facts, are excluded), outliers are dropped in Atwater
   macro-fraction space, and the survivors' **median** grams-per-kcal density per macro
   is scaled to the stated calorie total. The minimum counts **distinct** reference
   sources: duplicate search hits sharing one `reference_source:<url>` collapse to a
   single source before the count, so repeated hits of one page can never satisfy
   `MIN_COMPARABLE_SOURCES`. Fewer than `MIN_COMPARABLE_SOURCES` distinct survivors,
   or a material disagreement after outlier filtering, falls through to step 3. The tier
   is recorded on the run `source_refs` as `comparable_reference`; the item's own
   `source_type` stays `user_text` (only its missing macros are filled).
3. **Model prior last — cold-pass, never a one-shot guess.** Only when neither a
   source-backed lookup nor a plausible comparable-source aggregate is available does the
   field fall to a pure `model_prior` estimate (`field_provenance = estimated`, the reason
   in `assumptions`), or remain **unknown/`null`** when no credible estimate is produced.
   When this cold-pass fills a `user_text` item's missing macros, the read-model surfaces
   the rough basis via the additive optional `ItemSourceDTO.estimate_basis = model_prior`
   (FTY-350), derived at read time from the item's own `assumptions` marker with **no** new
   persisted column — the item stays `user_text`, consistent with the `comparable_reference`
   and `reference_source` surfacing above.
   An **uncertain** missing-field model-prior estimate is produced through the same
   **cold-pass self-consistency** path the parse step uses (FTY-158/FTY-159;
   `app/estimator/self_consistency.py`, `parse-candidates.md`): the field is drawn over
   **N independent passes** and its **sampling agreement** — not a single verbalized
   confidence number — is scored against the **FTY-159 calibrated operating point**
   (`app/estimator/clarify_policy.py`), so a lone over-confident sample can never finalize
   a fabricated number. Because a missing macro on an **already-resolved `user_text`
   item** is an **optional** estimate — not the resolve-vs-ask decision — its cold-pass
   fails closed **toward the field, not toward asking**: when the passes **disagree**
   (agreement below the calibrated operating point) the field is left **rough or
   `unknown`/`null`**, and this disagreement **never triggers a second clarification
   question about a detail the user already supplied** (the item is already resolved from
   user evidence; see `food-resolution.md`, no-second-follow-up). This inverts the parse
   step's fail-closed-toward-asking precisely because the item's identity and stated facts
   are already committed.

The recipe (ingredient-sum) and similar-dish sources reserved in the **Source
Hierarchy** are the future authoritative form of this reference tier; comparable-source
aggregation is the interim rough-reference evidence with the guardrails above, not a
licence to average provenance-free.

### Validation (bounded, plausibility-checked, fail-closed)

User-stated facts are **untrusted until validated** and cannot back a resolved item
until they pass deterministic checks:

- every stated value must be **finite and non-negative**; a negative,
  `NaN`/`Infinity`, or absurd value is rejected;
- an **as-logged calorie total** is bounded by a single-entry abuse cap (the
  label path's `MAX_ENERGY_KCAL`-style bound), **not** the per-100g plausibility
  bound (which needs a mass the user did not give);
- stated facts are checked for **internal consistency** — e.g. an Atwater
  cross-check (≈ 4/4/9 kcal per g protein/carb/fat) whose macro-implied energy grossly
  exceeds a co-stated calorie total is **self-contradictory**;
- a self-contradictory, implausible, or adversarial claim **fails closed** — it
  routes to clarification rather than committing a number the user could not have
  meant. Supplying a usable stated fact is never itself a reason to re-ask (see
  `food-resolution.md`, **User-Stated Resolution (FTY-279)** (its no-second-follow-up rule)).

### Security / untrusted input

The LLM may read the entry text and extract facts, but **no provider instruction
embedded in that text is executable**, and the extracted facts are validated by
trusted backend code before they back any persisted number (the parse
untrusted-output boundary, `parse-candidates.md`). Only the extracted, bounded fact
fields are trusted; the raw phrase is never persisted or interpreted.

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

**Diagnostics-only descriptors (LLM providers).** The same `GET /healthz/sources`
diagnostic also surfaces the configured **LLM provider** so an operator can confirm
the estimator's model backend is wired up, even though an LLM provider is not an
estimation **evidence source** in the **Source Hierarchy** above. Such a descriptor
carries two values that are intentionally **outside** the estimation enums:
`source_type = llm_provider` and `kinds = [estimation]`. These are
**diagnostics-only** capability values — they never appear on an evidence record,
a `source_ref`, or a lookup `status`, and they do not participate in source
selection or the **Fallback Rule**. The `claude_code` provider (FTY-087/088) is the
first instance: `id = claude_code`, `enabled` when it is the active
`SLACKS_LLM_PROVIDER`, and `available` when the CLI is on `PATH` and a login session
is detected — booleans only, no credential content surfaced. FTY-296 adds `codex`
with the same shape: enabled when selected, available when the CLI is on `PATH`
and saved `CODEX_HOME` auth or selected-provider `SLACKS_LLM_API_KEY` exists, with
no keys, tokens, identities, auth-file contents, host paths, or raw CLI output.
`llm-provider.md` owns the provider contract itself and defers diagnostics here.

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

Official-source lookup uses a configurable search provider (a local/self-hosted
SearXNG instance by default; Brave Search as the keyed opt-in) behind the
backend; the estimator never browses directly.

**Request (estimator → search provider).** A single sanitized query string plus
a result cap. The query is built from the **item identity only** — product /
restaurant / dish name, brand, and barcode digits. It **must not** contain the
user's profile, body metrics, goals, food/exercise history, free-text message
beyond the item phrase, location, or account identifiers. Queries are
length-bounded and stripped of control characters before egress. A consumer may
issue a **bounded, deterministic set of identity-query variants** for one item
(FTY-253 — the name+brand base, product-hint token orders, static retailer alias
expansion); each variant individually satisfies every rule above and passes the
same chokepoint.

**Response (search provider → estimator).** A bounded list of candidate result
URLs + titles + optional bounded snippets, treated as **untrusted**. The
estimator selects candidate official URLs to fetch; result text is never trusted
as nutrition facts — title/snippet text may become facts only through the same
bounded, schema-validated extraction a fetched page goes through (FTY-314). Only
public HTTP(S) result URLs are eligible for the fetch step. A missing or
malformed snippet is carried as empty and never affects the lookup status.

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
- **User-stated facts (FTY-279) are untrusted until validated**: a value is trusted
  only after it passes the finite/non-negative, as-logged abuse-cap, and
  internal-consistency checks above; a self-contradictory or implausible claim fails
  closed to clarification. The LLM extracts the stated facts; it never invents them,
  and no instruction embedded in the raw text is executed.
- The `model_prior` fallback is gated by the **Fallback Rule**; an adapter that
  finalizes a named/barcoded/label/generic item from model prior while an
  applicable source lookup was available violates this contract. Filling a **missing**
  field of a user-stated item from `model_prior` (with `field_provenance = estimated`)
  is permitted and is **not** such a violation.
- Under `estimate_first`, a model/default-prior rough estimate is accepted only after
  schema validation, deterministic plausibility checks, and any configured cold-pass or
  numeric floor succeeds. If the rough estimate cannot be made plausible and
  provenance-backed, the estimator asks only for an allowed rare clarification reason
  or fails closed; it never records a trusted-looking guess.

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
- **Raw log text remains model-only.** The raw diary/log sentence and accumulated
  clarification answers may be shown to the configured LLM provider for
  interpretation, but they must not be copied into search queries, fetch requests,
  source refs, assumptions, traces, logs, diagnostics, provider errors, evidence
  rows, or global caches. Evidence tools receive sanitized item identity, bounded
  amount/unit fields, explicit source refs, inert fetched text/snippets, and
  content-free lookup status labels only.
- **Evidence, not raw content.** Persist extracted facts + URL + timestamp +
  content hash; never raw pages, payloads, OCR, or raw search-result
  snippets/JSON (FTY-314 — a snippet-derived record keeps only the URL, the
  validated facts, and the `search_result_snippet` label). Nutrition-label
  images follow `docs/security/data-retention.md` (retain only while needed for
  extraction unless the user explicitly saves the attachment).
- **No raw diary text in a `user_text` record (FTY-279).** The raw phrase the user
  typed is **never** stored in the `source_ref`, evidence record, `assumptions`,
  logs, or provider traces. Only the extracted, bounded, validated facts are
  persisted; the `source_ref` is `user_text:<content_hash>` over those facts, so the
  provenance is auditable without retaining the sensitive sentence. (The raw entry
  text lives only on the owning `log_events` row per `docs/security/data-retention.md`,
  not copied into the evidence layer.)
- **No raw text/output leakage from rough estimates (FTY-298).** A rough default,
  reference/comparable, or model-prior estimate may record the source ids consulted,
  source-miss labels, cold-pass agreement labels, serving-prior labels, and the active
  clarify mode. It must not copy raw diary text, raw model/provider output, raw fetched
  page text, search result bodies, provider errors, prompts, URLs containing secrets, or
  request/response bodies into `source_ref`, `assumptions`, logs, traces, diagnostics,
  source refs, or calibration artifacts beyond explicit public fixture inputs.
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

```
recognizable amountless food under estimate_first: "some crackers"
  parser/resolver identifies the item but has no count
  trusted_nutrition_database / reference_source miss or lack a usable serving
  → model/default-prior rough estimate accepted only after schema + plausibility checks
  → evidence record: source_type=model_prior, source_ref=model_prior,
    assumptions=["clarify_mode:estimate_first", "amount_missing",
                 "default_serving_prior", "source_miss:usda_fdc"]
  # editable rough provenance, not a trusted database value and not a clarification
  # solely for missing quantity
```

```
user-stated calorie total: "Sobeys fresh to go buffalo chicken lime wrap (580 cals idk the breakdown)"
  parser extracts identity ("... buffalo chicken lime wrap", brand "Sobeys")
    + a stated calorie total (580)                      # user_text evidence, not a guess
  validate: 580 finite, ≥ 0, under the as-logged abuse cap → trusted
  → evidence record: source_type=user_text, source_ref=user_text:<content_hash>,
    facts { basis: as_logged, calories: 580, protein_g: null, carbs_g: null, fat_g: null },
    field_provenance { calories: user_stated, protein_g: unknown, carbs_g: unknown, fat_g: unknown }
  # macros unknown (null), NOT zero — the estimator MAY instead estimate them from the
  #   identity with field_provenance=estimated + a recorded assumption, or leave them null
  → run.source_refs += "user_text"; single resolved item, calories counted immediately
  # NOT needs_clarification: a usable stated detail was given (food-resolution.md)
```

## Search Provider Adapter — FTY-079 / FTY-164

The search-provider adapter is the **search half** of the `official_source` tier: it
turns a sanitized item-identity query into candidate result URLs plus an explicit
status, implementing the **Search Request / Response Boundary** above. It is a
**pluggable** adapter (FTY-079) with three registered backends (FTY-164):

- **`searxng` (default).** A local/self-hosted [SearXNG](https://docs.searxng.org/)
  instance queried via its JSON API (`/search?q=...&format=json`). **Keyless**: a
  normal dev/self-host install starts with search enabled *and available* — no paid
  API, no credential. The dev-stack container is FTY-165.
- **`brave` (explicit opt-in).** The Brave Search API; requires
  `SLACKS_SEARCH_API_KEY`. Without the key it reports `unavailable`.
- **`none` (explicit opt-out).** Search deliberately off: every lookup is
  `disabled`, nothing egresses, and diagnostics show the opt-out rather than a
  missing credential.

Search is a **non-optional default capability**: the out-of-the-box posture is
"available, keyless", and only an explicit operator choice (`none`, or
`SLACKS_SEARCH_ENABLED=false`) turns it off. The adapter ships **no fetcher** (the
result URLs are fetched by FTY-078's hardened fetcher) and **no resolution
pipeline** (FTY-062).

### Owner (additional)

`backend/app/estimator/search.py` (the `SearchProvider` interface, the
`SearXNGSearchProvider` / `BraveSearchProvider` / `NullSearchProvider` adapters,
`SearchSettings`, the `sanitize_query` chokepoint, the `SearchStatus` values, and
`build_search_provider`); the `official_source` entry in the source-diagnostics
surface (`backend/app/services/sources.py`, `backend/app/routers/health.py`). The
adapters reuse `hardened_fetch.py` for egress.

### Config (`SearchSettings`, `SLACKS_SEARCH_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLACKS_SEARCH_PROVIDER` | `searxng` | Which registered backend to use: `searxng`, `brave`, or `none`. An unknown value fails closed at config load. |
| `SLACKS_SEARCH_ENABLED` | `true` | Self-host enable/disable flag. `false` → `disabled` regardless of provider. |
| `SLACKS_SEARCH_API_KEY` | _(none)_ | Brave key (secret); only the `brave` backend uses it. **Absent with `brave` → `unavailable`.** SearXNG ignores it. |
| `SLACKS_SEARCH_BASE_URL` | `http://searxng:8080` (searxng) / `https://api.search.brave.com` (brave) | API base; the allowlisted host is derived from it. See **Base URL rules** below. |
| `SLACKS_SEARCH_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `SLACKS_SEARCH_MAX_RESULTS` | `5` | Candidate result URLs surfaced (Brave: also requested via `count`; SearXNG: bounded client-side). |

The Brave key is a `SecretStr`, read from the environment only, never exposed to
clients, never logged, and sent only in the `X-Subscription-Token` **header** (never
the query string, so it cannot leak through a logged URL). SearXNG sends **no
credential at all**.

### Base URL rules (narrow local-HTTP exception)

Provider base URLs must be **https**, with exactly one narrow carve-out:

- **SearXNG** may use plain `http` **only** for the local service targets the dev
  stack needs: the `searxng` service name, `localhost`, and loopback IP literals.
  Any other SearXNG URL — a public host, an internal DNS name, a non-loopback
  private IP — must be `https`. The rule is enforced twice: at config validation
  (`SearchSettings` rejects e.g. `http://public.example.com`) and again at egress,
  where the hardened fetcher admits the plain-HTTP host only if every resolved
  address is loopback or ordinary private (RFC 1918 / ULA) — never link-local
  (`169.254.169.254`), never public — and still pins the vetted IP.
- **Brave** is https-only, no exception.
- **`none`** never egresses; its base URL is inert.

### Capability / availability

The adapter advertises a capability descriptor — `enabled` (the self-host flag, and
`false` for the `none` provider) and `available` (required credentials present:
always `true` for keyless SearXNG, key-gated for Brave, `false` for `none`) —
surfaced in `GET /healthz/sources` under `id = official_source`,
`source_type = official_source`, `kinds = [named_product, restaurant_item]`, so a
self-hoster can confirm whether search is on without any trial call. The descriptor
carries no secret and no query content.

### Status values

Every lookup resolves to exactly one status, aligned with the **Provider
Capability / Status** vocabulary above:

| Status | When | Result |
| --- | --- | --- |
| `disabled` | `SLACKS_SEARCH_ENABLED=false`, or `SLACKS_SEARCH_PROVIDER=none`. | No call; caller tries next source / `model_prior`. |
| `unavailable` | `brave` selected with no API key. (SearXNG is keyless and never `unavailable` by config.) | No call; caller falls through. |
| `rate_limited` | Provider returned an HTTP 429 rate-limit / quota signal. | Bounded retry, then next source / `model_prior`. |
| `failed` | Timeout, connection error, 5xx, other 4xx, non-JSON, oversized, or policy-blocked (scheme / non-allowlisted / redirect / address-posture) response. | Nothing trusted; next source / `model_prior`. |
| `partial` | The provider answered but offered no usable candidate URL (or the sanitized query was empty). | Not finalizable; next source. |
| `success` | A bounded list of candidate HTTP(S) result URLs was returned. | URLs handed to the fetch step (FTY-078). |

A non-`success` status always carries an empty candidate list, so an off/failed
lookup can never be mistaken for a result.

### Query sanitization / data minimization

`sanitize_query` is the **single chokepoint** every query passes through before
egress: it strips control characters (so multi-line / structured personal context
cannot be smuggled), collapses whitespace, and length-bounds the string (≤ 256
chars). Each adapter accepts a single item-identity string and sends a **closed**
request shape — `q` (the sanitized name) + `count` for Brave, `q` + `format=json`
for SearXNG — so profile, weight, food history, and event metadata have **no
channel** to the provider. Tests prove no personal context egresses on either
backend.

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

## Reference-Source Fallback — FTY-166

The **reference-source** tier keeps the model prior from inventing nutrition facts
when official sources miss: for a food the trusted databases cannot cost, the
estimator searches for **public nutrition reference evidence** (the same pluggable
search adapter, FTY-079/164), fetches the bounded result page through the hardened
**searched-result** fetch policy, transcribes the facts the page states through the
strict `NamedFoodEstimate` schema, and recomputes calories/macros with the FTY-044
deterministic serving math. Only when this tier also produces nothing confident does
the resolver fall to `model_prior` — after the one bounded re-interpretation
pass on a failed/rejected source read — with per-tier `assumptions` naming why.

### Tier order (pipeline, after a USDA/OFF miss)

- **branded / named item:** official source search + fetch → **reference source
  search + fetch** → model prior with status;
- **detail-rich generic item (FTY-167):** no brand page exists, so the official
  search is skipped → **reference source search + fetch** → model prior with status;
- a recognizable generic item with **no usable amount** follows the same rough
  reference/model/default-prior path under `estimate_first`; it routes to
  `needs_clarification` only when `balanced`/`strict` asks or no plausible rough
  estimate can be produced.

### Owner

`backend/app/estimator/reference_fetch.py` (`ReferenceFetchSettings`,
`fetch_searched_result` — the searched-result egress policy) and the reference tier
of `backend/app/estimator/official_step.py` (`REFERENCE_SOURCE`,
`REFERENCE_SEARCH_INTENT`, the tier orchestration). Diagnostics:
`backend/app/services/sources.py` (`reference_source` capability entry, the
`searched_result_fetch` egress descriptor).

### Search (identity + fixed nutrition intent only)

The reference query is the sanitized item identity **plus the fixed string
`nutrition facts`** — nothing else. It passes through the same FTY-079
`sanitize_query` chokepoint, so raw diary text, profile, weight, history, and event
metadata have no channel to the provider. Result URLs and titles remain untrusted.

### Searched-result fetch policy (`SLACKS_REFERENCE_FETCH_` env vars)

A searched result URL points at an **arbitrary public host** the operator could not
have allowlisted in advance, so this policy deliberately has **no host allowlist**;
every other hardened-fetch protection is preserved against the attacker-influenced
URL:

- **HTTPS only** for public result pages (no local-HTTP exception on this path);
- **public IP only** — loopback, private, link-local (incl. `169.254.169.254`
  metadata), CGNAT, multicast, reserved, and unspecified targets are refused, and
  the vetted IP is pinned (no DNS-rebinding TOCTOU);
- **redirects refused**;
- **bounded timeout / size / content type** (inert text types only);
- **active content stripped** before extraction;
- **raw pages never persisted**.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLACKS_REFERENCE_FETCH_ENABLED` | `true` | Whether searched public result pages may be fetched at all. `false` turns the tier off (skipped with an explicit model-prior reason). |
| `SLACKS_REFERENCE_FETCH_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `SLACKS_REFERENCE_FETCH_MAX_BYTES` | `2000000` | Response-size cap; a larger body fails closed. |
| `SLACKS_REFERENCE_FETCH_ALLOWED_CONTENT_TYPES` | `text/html, application/xhtml+xml, text/plain` | Accepted content types; anything else fails closed. |

### Record shape / provenance

A reference-source record mirrors an official-source record: `source_type =
reference_source`, `source_ref = reference_source:<url>` (the URL only — never the
raw page), an immutable per-100g facts snapshot, `content_hash`, `fetched_at`, and
**no** global `products` cache row (`product_id` is `NULL`). Clients can therefore
distinguish a reference-page number from an official-page number and from a rough
estimate; the read-model label is the page host. The FTY-115/132 plausibility gate
applies in canonical per-100g space exactly as on the official path.

### Diagnostics

`GET /healthz/sources` lists a `reference_source` capability (`kinds =
[generic_food, named_product, restaurant_item]`; `enabled` when both search and the
searched-result fetch are on, `available` when search is). `GET /healthz/egress`
carries a `searched_result_fetch` block — the enable flag, bounds, and fixed
invariants (`https_only`, `public_ip_only`, `redirects_followed=false`,
`active_content_stripped`, `raw_pages_persisted=false`) — describing whether
searched public result fetch is enabled **without ever exposing a URL from a user
entry**.

## Search-Result Snippet Evidence — FTY-314

A search provider often shows the useful nutrition text a human already reads —
`Serving Size Per 5 crackers (19 g). Calories 90. …` — while the page itself
answers with HTTP 403 or a JavaScript shell. FTY-314 lets the searched-reference
chain use that **bounded result snippet** as a last-per-candidate untrusted
evidence surface instead of dropping it.

### Shape and bounds

- A `SearchCandidate` carries `snippet` alongside `url` and `title`: the
  provider's result description (SearXNG `content`; Brave `description`),
  length-bounded at the adapter, empty when missing, degraded to empty when
  malformed. A snippet is **optional** — it is never required for a `success`
  lookup and its absence changes nothing.
- Before extraction the composed title+snippet text is bounded **again**
  (defence in depth over the adapter bound) and injected into the same
  transcription prompt as fetched-page text, framed as the untrusted inert text
  of "a public search-result title and snippet" — data, never instructions.

### Order (fetch-first, snippet fallback, per candidate)

For each search candidate the resolver tries the **fetched page first**. Only
when that candidate's fetch fails (policy/transport/HTTP error), returns no
usable text, or extracts no accepted facts (unresolved, low confidence,
implausible, or rejected by the quantity/brand-compatibility gates) does the
resolver try the **same candidate's** title+snippet — before moving to the next
result or falling through to the next tier. An empty snippet preserves the
pre-FTY-314 fetch-only behavior exactly.

### Trust and provenance

- Snippet text is exactly as adversarial as a fetched page: it becomes facts
  only through `NamedFoodEstimate` schema validation, the plausibility gate, the
  compatibility checks, and the deterministic serving math — the model never
  supplies the stored numbers.
- Provenance stays the search-result **URL** (`official_source:<url>` /
  `reference_source:<url>`), plus the content-free **`search_result_snippet`**
  assumption label recorded on the evidence row, so a snippet-derived number is
  distinguishable from a fetched-page transcription.
- Confidence rank: a snippet is a **lower-confidence public reference surface**
  — below a fetched official or reference page, above pure model prior — usable
  only when compatible and schema-valid. In the user-stated missing-macro path
  (the single-source reference fill, which commits the first accepted result), a
  snippet-derived result must additionally pass the deterministic
  product-compatibility check (the comparable tier's gate) before its facts may
  fill macros, and the fill's recorded assumptions carry the
  `search_result_snippet` label.
- The **raw snippet is never persisted**: not in `estimation_runs.trace`,
  `assumptions`, `source_refs`, provider errors, logs, or evidence rows. For a
  snippet-derived extraction the provider-stated `assumptions` are discarded
  wholesale — only the fixed content-free `search_result_snippet` label is
  recorded — so a provider response echoing raw snippet text into its
  assumptions can never reach evidence/run assumptions.
- Fetch/search dead ends enter the interpretation loop as sanitized status
  labels such as `fetch_403` or `snippet_unavailable`; an ambiguous page or
  snippet read (`extract_unresolved` / `extract_low_confidence` /
  `extract_rejected_facts`) also carries a bounded descriptor the session can
  interpret (FTY-326): stated product identity reduced through the same identity
  sanitization as reference-search egress (never the raw transcription string),
  disposition, confidence, and facts basis. Raw snippet/page text and provider
  assumption strings still never enter the session ledger or model-prior prompt.
  The unaccepted read's own bounded, FTY-314-framed snippet/page text is staged
  transiently for the session's next re-interpretation prompt instead — the
  permitted model surface for resolving an ambiguous read. It is consumed at
  prompt-construction time and never persisted, traced, or echoed into a search
  query or fetch URL: the resolver bridge deterministically drops any
  revised-identity word carrying a token seen only in staged excerpt text, so a
  re-ask reply echoing the staged surface cannot steer an outbound query or a
  persisted item field.
- No egress change: snippets arrive on the existing search response; this adds
  no browser automation, redirects, allowlist widening, or new fetch surface.

## Item Re-match — FTY-093

The **item re-match** capability is the "Change match" lever of the correction sheet:
a user whose entry matched the **wrong food** (Slacks heard "turkey", matched chicken)
fixes it without delete-and-retype. It is two cohesive halves of one capability,
layered on the resolution pipeline — a *list-alternatives* (read) operation and a
*re-resolve-to-chosen-source* (write) operation. It is distinct from the **portion
stepper** (FTY-092, which changes the *amount* and preserves the source) and from the
**manual value override** (FTY-051, which marks the item `user_edited`): re-match
changes the *source*.

### Owner (additional)

`backend/app/estimator/re_match.py` (the `ReMatchCapability` — listing, server-side
candidate caching, re-resolve, evidence rewrite — plus the candidate-provider seam and
`FdcClient.list_matches`), the thin backend operation
(`backend/app/routers/re_match.py`, `backend/app/schemas/re_match.py`). It reuses the
FTY-044 serving math, the `products` / `evidence_sources` split, the FTY-079
`sanitize_query` chokepoint, and the FTY-092 read-model unchanged.

### (a) List alternatives

Given an existing `derived_food_items` row, the capability runs the existing
resolution providers in a **list-candidates** mode that surfaces *multiple*
energy-bearing matches (USDA FoodData Central beyond the resolver's first pick) rather
than only the first. An optional **caller-supplied query override** (the corrected
term, e.g. "turkey") re-aims the search to a different food; it is a single
item-identity string that passes through the **same** `sanitize_query` chokepoint
(FTY-079) — item identity only, control-stripped, length-bounded — so no profile,
history, or metrics can egress. Each returned candidate carries its `source_type`, a
stable `source_ref` (the opaque candidate id), a display name, the match `basis`
(per-100g — providers canonicalise to per-100g during listing), and a compact facts
preview (per-basis calories + macros). A non-schema-valid / energy-less (`partial`)
match is **excluded** — it is not an offerable match. The list is **bounded** (the
provider fan-out is capped by `SLACKS_FDC_MAX_RESULTS`, and the aggregated result by a
hard ceiling).

Each surfaced candidate's facts are extracted/validated **server-side during listing**
and cached into the global `products` cache, **addressable by `source_ref`** (a
list-mode row is keyed by its `source_ref` so several candidates from one search never
collide on the name-based `(source, query_key)` uniqueness). That cache is the **trust
anchor** the write half re-derives from.

> **v1 candidate source.** The implemented candidate provider is USDA FDC (name search,
> multi-candidate) behind a provider seam. The optional official-source search-fallback
> and barcode (OFF) participation plug into the same seam as additive providers; OFF is
> barcode-keyed (single-result) and is not a name-alternative source.

### (b) Re-resolve to a chosen source

The write operation takes the existing item plus a **chosen candidate reference**
(`source_ref`) — and **never** caller-supplied nutrition values — and re-aims the item:

1. **Re-derive the chosen source's facts server-side** from that reference, by looking
   it up in the global `products` cache (the listing step populated it). A reference
   that does not resolve to a server-cached candidate is **rejected; nothing mutates**
   (the client cannot inject facts, and re-resolve issues **no** fresh network egress).
2. **Recompute at the current portion.** The item's current `amount` / quantity is kept
   (the FTY-092 portion is the user's choice); `resolve_grams` runs against the new
   source's `default_serving_g`, then `scale_facts` produces new `calories` / macros,
   rounded 0.1 (the FTY-044 serving math, reused unchanged). If the new source cannot
   cost the current quantity, the operation routes to **`needs_clarification`** rather
   than fabricate a number (consistent with FTY-044 routing).
3. **Rewrite provenance to the new source.** The item's `evidence_sources` row is
   updated **in place** (`source_type`, `source_ref`, `content_hash`, `fetched_at`, the
   immutable per-100g facts snapshot, `product_id` link, `assumptions`). The chosen
   candidate is always a `Product`, whose density facts are always per-100g, so
   `basis` is **reset to `per_100g`** and `field_provenance` is **reset to `null`**
   (a single database source gives every fact field a homogeneous origin) — the
   rewrite never leaves a stale `as_logged` / `per_serving` basis or a stale per-field
   origin map over the new per-100g snapshot (FTY-316). The item keeps its `id`,
   `log_event_id`, name slot, and timeline position.
4. **Re-snapshot `*_estimated` to the newly computed values.** A re-match is a fresh
   source-backed estimate, not a manual override, so the estimated/original snapshot is
   **reset** to the new source's computed values and the item is **not** marked
   `user_edited`.
5. **Append the `re_match` audit row.** One immutable `re_match` correction (keyed on
   `calories`) records the re-match and **supersedes** any pre-existing `user_edit`, so a
   re-matched item reads `is_edited == false` again (see **Re-match vs. `user_edit`**).

Re-resolve is **deterministic**: given the same cached facts, the same chosen reference
yields the same recomputed item and provenance. The new source reaches the client
through FTY-092's read-model (the existing item DTO) — re-match changes **no** DTO.

### Re-match vs. `user_edit` (the honest-provenance crux)

The corrections contract (`corrections.md`, FTY-051) snapshots `*_estimated` **exactly
once** and marks any value change `user_edit`. That rule governs the **manual override**
lever. A **re-match is a re-resolution to a different real source**, so it instead
**re-snapshots** `*_estimated` to the new source's computed values and leaves the item
**un-`user_edited`** — the provenance honestly reflects the new source. **A re-match
writes no `user_edit` correction row.** This distinction is deliberate: do **not** "fix"
it back to `user_edit`.

Re-match **does** append one immutable `re_match` correction row (keyed on `calories`,
the item's headline value). That row is the dedicated re-match audit marker, and it
**reconciles a pre-existing edit**: because it is the *latest* word on the item's value,
it **supersedes** any prior `user_edit`, so `is_edited` derives back to **`false`** for a
re-matched item — even one that had been edited before the re-match (the
edit-then-rematch sequence). `is_edited` is therefore "a `user_edit` *after* the most
recent `re_match`"; a genuine new edit made after a re-match makes the item `true` again.
The change of source itself is also carried honestly by the rewritten `evidence_sources`
provenance.

### Backend operation (thin pass-through)

The exposed operations are a **thin** pass-through to the estimator capability —
request validation + object-level authz + delegate; all resolution, recompute, and
persistence live in the estimator package:

- `POST /api/users/{user_id}/derived-items/food/{item_id}/source-candidates` →
  `{ candidates: [...] }` (optional `{ "query": "<override>" }` body).
- `POST /api/users/{user_id}/derived-items/food/{item_id}/re-resolve` with
  `{ "source_ref": "<chosen ref>" }` → the updated `DerivedFoodItemDTO`.

The `re-resolve` request body is `extra="forbid"` over a single `source_ref` field, so
a client cannot smuggle nutrition values through it.

### Security / Authorization

- **No new untrusted-input boundary.** Egress flows only through the existing hardened
  source clients during the **listing** step; re-resolve performs **no** fetch. The
  SSRF/egress and query-sanitization guarantees are inherited, not reintroduced.
- **No personal-context egress.** The optional override and all provider queries are
  item-identity only, through the `sanitize_query` chokepoint. A test proves no personal
  context egresses on listing.
- **Server never trusts client-supplied facts.** Re-resolve accepts a candidate
  **reference** only and re-derives facts server-side; an un-re-derivable reference (or
  any attempt to pass facts) is rejected with no mutation.
- **Object-level authorization, fail-closed.** Both operations load the item scoped to
  the owning user; a cross-user or unknown item is a `404` (no existence disclosure, no
  mutation), matching the FTY-051 corrections posture.

### Errors

| Condition | Result |
| --- | --- |
| Cross-user / unknown item (either operation) | `404`, fail-closed, no mutation, no existence disclosure. |
| Re-resolve reference not re-derivable (uncached) | `422` `{ "error": "source_not_resolvable" }`; nothing mutates. |
| Re-resolve body carries facts / extra keys | `422` (request validation, `extra="forbid"`). |
| New source cannot cost the current quantity | `422` `{ "error": "needs_clarification", "question": … }`; no fabricated number. |
| Listing with no enabled candidate source | `200` with an empty candidate list. |
| Listing source fails transiently / answers unusably | `503` `{ "error": "alternatives_unavailable" }`; retryable. **Not** a `200` empty list — an empty list means "no matches", never "the source was down", so a source failure is surfaced honestly rather than silently looking like no alternatives exist. Mirrors the estimator's transient/response routing (`food_step.py`). |

### Examples (tests)

`backend/tests/test_item_re_match.py` proves: multi-candidate USDA listing (beyond the
first energy-bearing match) with a query override and the per-`source_ref` candidate
cache; listing egresses only the sanitized item identity; a transient/unusable
candidate-source failure during listing surfaces `503` (not an empty list);
`FdcClient.list_matches`
excludes energy-less results; re-resolve recompute + provenance rewrite + `*_estimated`
re-snapshot + not-`user_edited` + no `user_edit` row + the `re_match` audit row that
clears a pre-existing edit (`is_edited` false after edit-then-rematch, true again after a
later edit) + determinism; identity / portion preserved; an un-re-derivable reference and
client-supplied facts rejected with no mutation; needs-clarification when uncostable; and
cross-user / unknown / unauthenticated fail-closed.

## Exact Evidence Upgrade — FTY-306

The **exact evidence upgrade** is the correction sheet's `Make it exact` lever
(`docs/design/ux-design.md` §4a): for a **low-trust or incomplete food item**, the
user supplies **product evidence** — a typed or scanned barcode, or a
nutrition-label photo — Slacks builds a server-held **proposal** from that
evidence, previews the resulting item, and **applies it in place** only after the
user confirms. Nothing about the selected item changes until apply; there is no
automatic replacement.

It is **source replacement, not a manual value override**: applying a proposal
uses the same re-resolution semantics as **Item Re-match — FTY-093** (provenance
rewrite, `*_estimated` re-snapshot, one `re_match` audit row, `is_edited = false`
until a later manual override — `corrections.md`), differing only in where the new
source comes from. **Change match** fixes a *wrong* source by search; **Make it
exact** asks the user for *product evidence* and then applies the resulting exact
source — or an honestly-labelled fallback — explicitly. It covers **food items
only**; exercise items never expose this path (an exercise burn has no evidence
source to upgrade).

This section is the contract; the backend implementation is split into
**FTY-307–FTY-309** and the mobile consumption into **FTY-310–FTY-313**. The
entry-point routing, amount-preservation, costability, and no-silent-exact rules
for the existing-item flow live in `food-resolution.md` (**Exact Evidence Upgrade
Routing — FTY-306**); the label-image retention boundary lives in
`label-upload.md` / `log-attachments.md`.

### Eligibility (which items offer `Make it exact`)

Only **low-trust or incomplete** food items are eligible for the entry point:

- **`model_prior`** items — rough/default-prior estimates, including `as_logged`
  rough totals (FTY-301);
- **`user_text`** items with missing or roughly gap-filled macros — a user-stated
  calorie total whose macros are `unknown`/`null` in the read shape, or carry a
  non-null `estimate_basis`: `comparable_reference` for the comparable aggregate
  (FTY-281), `reference_source` for the single-source reference lookup, or
  `model_prior` for the model-prior cold-pass (FTY-350);
- **`reference_source`** items — rough estimates transcribed from searched
  public reference pages, including snippet-derived records (FTY-314).

Already source-backed items — `user_label`, `product_database`,
`trusted_nutrition_database`, `official_source` — keep the normal correction
levers (amount stepper, Change match, manual value override) and **do not** show
the exact-upgrade nudge. Eligibility is derived from fields the **public read
model already contracts** (`daily-summary.md` → **`source` descriptor**): the
descriptor's `source_type` and `estimate_basis` plus the item's nullable macro
facts — no new persisted flag, no new read-model field, and no new
source-hierarchy tier. `daily-summary.md` contracts the matching client-side
nudge signal in the same terms, and the propose route evaluates the same rule
server-side from the item's `evidence_sources` row (rejecting an ineligible
target with `not_upgradeable`, `food-resolution.md`), so the rendered nudge and
the server-validated eligibility can never disagree. For a `user_text` macro
gap-filled by the comparable aggregate, a single-source reference lookup, or the
model-prior cold-pass, `estimate_basis` is still **read-time-derived** from the
item's own content-free assumptions marker and records only the fill tier; it
adds no persisted column and does not change the item's `source_type`, which
stays `user_text`.

### Proposal (read shape)

A proposal is built **server-side** from the supplied evidence and held
server-side as the trust anchor apply re-derives from; the client receives a
preview plus an opaque reference, never a writable fact set. Stable fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `proposal_ref` | string | **Opaque, server-generated** reference to the server-held proposal — the only key `apply` accepts, never nutrition facts supplied by the client. Scoped to the owning user **and** the targeted item; a ref that does not resolve to a server-held proposal for that user + item is rejected with no mutation. |
| `kind` | enum | `barcode` \| `label` — which evidence kind produced the proposal. |
| `quality` | enum | `exact` — the evidence resolved through its exact source (barcode → `product_database`, label → `user_label`); `fallback` — exact evidence failed but a lower-trust estimator source produced a better rough result (see **Fallback quality** below); `none` — neither exact evidence nor a fallback could be produced (nothing applyable). |
| `failure_reason` | string \| null | `null` for `exact`; **required** for `fallback` and `none`. A **closed, content-free** label (e.g. `barcode_no_match`, `barcode_invalid`, `label_unreadable`, `not_a_label`, `source_unavailable`, `no_usable_facts`; the concrete vocabulary is fixed by FTY-307/FTY-308) suitable for calm client copy such as "No exact match from that barcode" — never raw provider output, OCR text, fetched content, or image data. |
| `preview` | object \| null | The would-be item, costed at the **current amount** when possible: the read-model `source` descriptor the applied item would carry (`source_type`, display `label`, `ref`, optional `estimate_basis` — `daily-summary.md`), `calories` / `protein_g` / `carbs_g` / `fat_g`, the current `amount`, and the proposal's serving label. `null` when `quality = none`. When the current amount cannot be costed, the preview carries the source facts on the proposal's own basis instead of invented totals (see the flag below). |
| `can_cost_current_amount` | bool | Whether the proposal's source can cost the item's **current** amount (serving math resolvable). When `false`, apply requires an explicit amount from the user — the contract forbids applying with a silently guessed portion (`food-resolution.md`). |

A `quality = none` proposal is a **failure read**, not an applyable object: it
carries the `failure_reason` for calm client copy and nothing else to apply. The
preview is a **read projection** — previewing creates no correction row, no
evidence rewrite, and no item mutation.

### Exact quality (no new tier)

An **exact** proposal resolves through the existing exact sources and reuses
their record shapes unchanged:

- **Barcode** — the hardened Open Food Facts path (`food-resolution.md`
  **Barcode Source — FTY-060**): normalized digits, GTIN length check, hardened
  fetch, per-100g canonicalisation, plausibility bound, global `products` cache
  row. Applying yields `source_type = product_database`,
  `source_ref = open_food_facts:<barcode>`.
- **Label** — the schema-validated label extraction path (`label-extraction.md`):
  image validated as data, `NutritionPanel` extraction, deterministic
  per-serving → per-100g math. Applying yields `source_type = user_label`,
  `source_ref = user_label:<content_hash>`.

### Fallback quality (plainly not exact)

When exact barcode/label evidence fails (OFF miss, unreadable label, provider
unavailable, implausible facts) but the estimator can still produce a **better
rough result** from a lower-trust source — a searched reference page, a
comparable-reference aggregate, or a model-prior estimate over the evidence's
product identity — the proposal remains applyable with `quality = fallback`. A
fallback:

- carries its true low-trust provenance: `reference_source`, `model_prior`, or
  the `comparable_reference` estimate-basis marker — **never** `product_database`
  or `user_label`;
- carries a visible `failure_reason` naming why exact evidence failed, and its
  preview `source` descriptor shows the rough source label the applied item will
  show;
- **must never be presented as exact** — not in the proposal `quality`, not in
  the preview `source` descriptor, not in the applied item's provenance. The
  source descriptor and failure reason are part of the user-visible trust
  boundary;
- when applied, updates the item in place but keeps it **visibly
  rough/incomplete** (it stays exact-upgrade-eligible, and the read model keeps
  rendering its rough provenance).

### Source replacement semantics (apply)

Applying a proposal accepts **only** the opaque `proposal_ref` plus an optional
amount adjustment (`food-resolution.md` owns the operation shape). It:

1. **preserves the item's identity** — `id`, `log_event_id`, name slot, and
   timeline position are unchanged; the log event is untouched;
2. **preserves the current amount by default**; an optional user-supplied amount
   adjustment from the preview is applied **before** costing;
3. **re-derives the facts server-side** from the server-held proposal (the same
   trust posture as re-match re-resolve: the client cannot inject facts, and
   apply issues no fresh evidence egress);
4. **rewrites the item's `evidence_sources` provenance in place** to the
   proposal's source — `source_type`, `source_ref`, `content_hash`, `fetched_at`,
   the immutable facts snapshot on the source's honest `basis`, `product_id`
   link (barcode) or `NULL` (label/fallback), `assumptions`, and a reset
   `field_provenance` consistent with the new source (no stale per-field origin
   map or stale `as_logged` basis survives the rewrite, per FTY-316);
5. **re-snapshots `*_estimated`** to the newly computed values — a fresh
   source-backed estimate, not a manual override;
6. **appends one immutable `re_match` correction row** (keyed on `calories`),
   which supersedes any prior `user_edit`, so the applied item reads
   `is_edited = false` until a later genuine manual override (`corrections.md`).

### Authorization / privacy

- **Object-level, fail-closed.** Every proposal and apply operation is scoped to
  the owning user and item; a cross-user or unknown user/item id is `404` (no
  existence disclosure, no mutation), matching the corrections/re-match posture.
- **Untrusted inputs.** The barcode string and the label image are untrusted
  input. Barcode lookups stay server-side through the existing hardened OFF path;
  label images stay server-side through the existing validation/extraction path.
  The client supplies a barcode, an image, an optional `save` flag, and later the
  opaque `proposal_ref` plus an optional amount — **never calories/macros**.
- **Retention unchanged.** Raw label images follow the existing
  discard-by-default rule (`label-upload.md`, `log-attachments.md`,
  `docs/security/data-retention.md`): discarded after extraction unless the user
  explicitly opts in to saving. No image bytes, URIs, OCR text, raw provider
  output, or nutrition values are logged; evidence rows store extracted facts +
  refs + hashes only, exactly as this contract already requires.
- **Proposal retention is bounded.** The server-held proposal holds only the
  extracted/validated facts, source ref, and content hash needed for apply —
  never the raw image, raw provider output, or OCR text — is scoped to the
  owning user + item, and is short-lived (an unapplied proposal expires; it is
  not durable user history). The concrete storage mechanism is fixed by
  FTY-307–FTY-309, which document its retention per the
  `docs/security/data-retention.md` PR requirement. **As built (FTY-307):** the
  proposal is **not stored** — the `proposal_ref` is a stateless, HMAC-signed opaque
  reference (keyed by the existing application secret) whose payload *is* the bound
  proposal (owner, item, kind/quality, source type/ref, per-100g facts + basis,
  costability metadata, issued/expiry replay guard). Apply verifies the signature,
  expiry, and owner+item binding server-side and re-derives the facts from the
  verified payload; a tampered, expired, or wrong-user/wrong-item reference is
  rejected with no mutation. No new table, no migration, and no server-side proposal
  row — see `docs/security/data-retention.md`.

## Migration / Compatibility

- **FTY-334 (brand cutover, mechanical rename).** The search, reference-fetch,
  FDC, and LLM environment keys documented here now use the `SLACKS_` prefix,
  renamed from the legacy prefix as part of the repo-wide brand cutover to
  Slacks. This is not a contract version bump — every key's meaning, defaults,
  the capability/status vocabulary, and egress behaviour are unchanged; only
  the `SLACKS_` prefix is new.
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
- **FTY-279 (contract only; no schema, no code in this story).** Adds the `user_text`
  rank-1 user-provided source system (explicit nutrition stated in the entry text),
  the `as_logged` fact basis, the optional `field_provenance` map, and nullable
  (unknown ≠ zero) macros. It is a **deliberate pre-v1 redesign**, not a shim: the
  parser may now carry user-stated nutrition as evidence (`parse-candidates.md`), the
  food step resolves a stated calorie total instead of re-asking
  (`food-resolution.md`), and the daily summary counts a calorie-only item without
  inventing macro grams (`daily-summary.md`). No migration in this story:
  `evidence_sources.source_type` / `source_ref` are strings, `basis` is a string,
  the `assumptions` column (FTY-062) carries per-field estimate reasons, and the
  derived-item macro columns are already nullable; the `field_provenance` persistence
  shape and the estimator/parser code are the **downstream FTY-280 implementation**.
  Clients gain the `user_text` value in the provenance read-model (`SourceType`) and
  `daily-summary.md`. The existing source hierarchy, lookup-status vocabulary, and
  serving math are otherwise unchanged.
- **FTY-280 (implementation of FTY-279).** Lands the estimator/parser/persistence work:
  the parser extracts the `stated_*` fields (`parse-candidates.md`), the
  `UserTextResolveStep` (`backend/app/estimator/user_text_step.py`) resolves a stated
  calorie total from the `user_text` tier and fills its missing macros in the fixed
  **reference-search → model-prior cold-pass → unknown** order above (the model-prior
  estimate drawn over N cold passes gated on agreement, never a one-shot confidence),
  and the read-model surfaces `user_text` (label "You logged"). Unlike FTY-279's
  contract-only note, this story **does** add the additive `0018` migration:
  `evidence_sources` gains `basis` (default `per_100g`) and a nullable
  `field_provenance` JSON map, and the four `*_per_100g` fact-snapshot columns become
  **nullable** so an `as_logged` user-stated record stores its calorie total with a
  macro left `NULL` (unknown) rather than a fake `0`. Existing rows keep their
  per-100g values, get `basis = 'per_100g'`, and `field_provenance = NULL`; the
  migration is fully reversible. The source hierarchy, lookup-status vocabulary, and
  serving math are unchanged.
- **FTY-281 (implements the comparable-source aggregation tier).** Lands
  `app/estimator/comparable_reference.py` and wires it into `UserTextMacroEstimator`
  (`user_text_step.py`) between the single-source reference lookup and the model-prior
  cold-pass, exactly as **Estimating a missing field** step 2 reserved. It is **additive
  and non-breaking**: no schema, migration, or client-`SourceType` change (the aggregate
  fills a `user_text` item's missing macros with `field_provenance = estimated`; the
  method + compatibility summary + **each** contributing `reference_source:<url>` with
  its **content hash and immutable per-100g fact snapshot** live in the existing
  `assumptions` list, and the run gains a `comparable_reference` entry in `source_refs`).
  The FTY-092 read-model gains one **additive, optional** field — `ItemSourceDTO.
  estimate_basis = comparable_reference` — derived at read time from the item's own
  `assumptions` (no new persisted column), so a client can tell a rough
  comparable-reference macro estimate from a plain `user_text` item while the item's
  `source_type` stays `user_text`. It reuses the FTY-166 search adapter, searched-result hardened fetch,
  `NamedFoodEstimate` extraction schema, `_to_per_100g` plausibility gate, and `sanitize_query` chokepoint —
  only the query is **brand-relaxed**, each page's transcription is drawn over the **cold-pass** self-consistency
  path (N independent passes gated on committed-macro-density agreement, wherever an LLM participates), and the
  aggregation (compatibility filtering, outlier rejection, median density) is a new **deterministic** step. No live network in tests.
- FTY-088 adds a **diagnostics-only** LLM-provider descriptor to
  `GET /healthz/sources` (`id = claude_code`, `source_type = llm_provider`,
  `kinds = [estimation]`). It is additive operator/health state only: no estimation source, schema change, or lookup status; descriptor values stay outside the estimation Source Hierarchy and `kinds` enums. Provider contract: `llm-provider.md`.
- FTY-079 adds the `official_source` search adapter (`search.py`) and an
  `official_source` entry in `GET /healthz/sources`. It is additive: a new
  `SLACKS_SEARCH_`-prefixed config block, no schema change, and a
  backward-compatible `status_code` attribute on `hardened_fetch`'s
  response/transient errors for rate-limit (HTTP 429) detection. The fetcher
  (FTY-078) and the resolution pipeline (FTY-062) remain separate.
- FTY-164 **changes the search defaults** (a deliberate pre-v1 breaking change):
  `SLACKS_SEARCH_PROVIDER` defaults to `searxng` (was `brave`) and search is
  available out of the box with **no API key**. It registers the `searxng` and
  `none` provider ids alongside `brave`, adds the per-provider default base URL
  (`http://searxng:8080` for SearXNG), and adds the narrow local-HTTP egress
  exception (see **Base URL rules**) as an opt-in `local_http_hosts` seam on
  `hardened_fetch.get_json` — every other egress path remains https-only with the
  public-address requirement. The status vocabulary, `sanitize_query` chokepoint,
  capability descriptor shape, and the Brave adapter (key in header, https-only)
  are unchanged. The dev-stack SearXNG container itself is FTY-165.
- FTY-062 adds the `official_source` resolution pipeline step (`official_step.py`)
  consuming the FTY-079 search + FTY-078 fetch, and the `model_prior` fallback. It is
  additive: an optional `brand` parse-candidate field, the `NamedFoodEstimate`
  extraction/estimate schema, and the nullable `evidence_sources.assumptions` column
  (`0012` migration). It does not redefine the hierarchy, the status vocabulary, or the
  fallback rule; it fixes the pipeline ordering (official source last before
  model-prior). See `food-resolution.md` (**Official-Source Resolution**).
- FTY-166 adds the **`reference_source`** tier (a deliberate pre-v1 breaking
  change to the resolution order): the source-system id `reference_source` joins
  the stable vocabulary, model prior moves to rank 6, and a new
  `SLACKS_REFERENCE_FETCH_`-prefixed config block governs the searched-result fetch
  policy. No schema migration: `evidence_sources.source_type` / `source_ref` are
  strings and the `assumptions` column (FTY-062) already carries the fallback
  reasons. Clients gain the `reference_source` value in the provenance read-model
  (`SourceType`), and `GET /healthz/egress` gains the `searched_result_fetch`
  block. The official-source adapter, the search boundary, the status vocabulary,
  and the serving math are unchanged.
- **FTY-314** adds the bounded search-result **snippet** to the search response
  shape (`SearchCandidate.snippet`) and the per-candidate snippet-fallback rule
  to the searched-reference chain (see **Search-Result Snippet Evidence —
  FTY-314**). It is **additive**: no schema migration (`assumptions` already
  carries content-free labels), no new provider or egress surface, no status or
  hierarchy change — only a new lower-confidence evidence surface between a
  fetched page and the model prior, labelled `search_result_snippet`.
- FTY-093 adds the **item re-match** capability (`re_match.py` + the thin
  `re-match` router/schemas) and `FdcClient.list_matches`. It is additive with **no
  schema migration**: re-resolve is an in-place `UPDATE` of the existing
  `derived_food_items` resolution columns, its `evidence_sources` row, and the
  `*_estimated` columns; surfaced candidates are cached as ordinary `products` rows
  (keyed by `source_ref`). It reuses the source hierarchy, lookup-status vocabulary,
  fallback rule, normalized-fact schema, serving math, the `sanitize_query` chokepoint,
  and the FTY-092 read-model unchanged. It deliberately diverges from the FTY-051
  captured-once rule: a re-match re-snapshots `*_estimated` and is **not** `user_edit`
  (see **Item Re-match — FTY-093**). The provenance read-model dependency is enforced by
  the steward (FTY-093 ships after FTY-092).
- **FTY-298 / FTY-303 (contract only; no schema/code in this story).** FTY-298 bumps
  the evidence contract to describe rough-estimate provenance for the
  `estimate_first` clarification policy, and FTY-303 extracts the global policy text
  to [estimator-policy.md](estimator-policy.md). It adds no new table or enum
  requirement: the existing `source_type`, `source_ref`, `field_provenance`,
  `assumptions`, run `source_refs`, and read-model estimate-basis fields carry the
  distinction between exact/product-backed, official/reference-backed, comparable
  aggregate, and model/default-prior estimates. FTY-301 adds runtime fallback only:
  existing `model_prior`, `basis`, and assumptions carry the rough provenance.
- **FTY-324 / FTY-348 (contract cross-reference only; no schema/code in this
  story).** The evidence hierarchy is referenced as the bounded tool surface for the
  `InterpretationSession` (FTY-324); FTY-348 relocated that global framing to
  [interpretation-session.md](interpretation-session.md) with no normative change.
  The lookup-status vocabulary, source hierarchy, fact schema, search/fetch
  boundaries, retention, source refs, assumptions, and rough-provenance labels are
  unchanged. FTY-325/FTY-326 wire misses/rejections back into the interpreter
  without adding providers or widening egress.
- **FTY-306 (contract only; no schema/code in this story).** Adds the **Exact
  Evidence Upgrade** section: the `Make it exact` proposal/apply taxonomy for
  existing low-trust/incomplete food items. It introduces **no new source tier,
  lookup status, or evidence-record field**: an exact barcode proposal reuses
  `product_database` / `open_food_facts:<barcode>`, an exact label proposal reuses
  `user_label` / `user_label:<content_hash>`, and a fallback reuses
  `reference_source` / `model_prior` / the `comparable_reference` marker with its
  existing rough-provenance rules. Apply reuses the FTY-093 re-match write
  semantics (in-place provenance rewrite, `*_estimated` re-snapshot, one
  `re_match` correction row). The routing/operation shapes are
  `food-resolution.md` (**Exact Evidence Upgrade Routing — FTY-306**); the audit
  semantics are `corrections.md`; label retention is `label-upload.md` /
  `log-attachments.md`. Backend implementation is **FTY-307–FTY-309**; mobile
  consumption is **FTY-310–FTY-313**.
- **FTY-307 (generic proposal apply foundation; no schema, no migration, no new
  source tier/status/field).** Implements the source-agnostic **apply** half and the
  server-verifiable **trust anchor**: `app/estimator/exact_evidence.py` (the
  `ExactEvidenceProposal` payload, the stateless HMAC-signed `proposal_ref`
  encode/decode, and `ExactEvidenceApplyCapability`), the
  `app/schemas/exact_evidence.py` DTOs (`ExactEvidenceApplyRequest`,
  `ExactEvidenceProposalDTO` + preview), `app/services/exact_evidence.py`
  (`serialize_proposal` — the proposal read projection), and the thin
  `POST .../food/{item_id}/exact-upgrade/apply` route. Apply **reuses the FTY-093
  re-match write helpers** (`app/estimator/re_match.py` `apply_resolved_facts` /
  `record_re_match_correction`) — it is a specialized re-resolution, not a second
  correction model. The `proposal_ref` is an opaque signed reference (no proposal
  table), so there is no migration and no new stored field (`docs/security/
  data-retention.md`). A `fallback` proposal writes its honest low-trust
  `source_type` / `assumptions` / `field_provenance` verbatim, so it never reads as
  `product_database` / `user_label`. Source-specific barcode/label proposal
  **generation** (which mints the `proposal_ref`) is **FTY-308/FTY-309**; this story
  ships apply against stubbed proposals.
