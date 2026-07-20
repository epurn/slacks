# Contract: Official-Source / Reference / Model-Prior Food Resolution

## Purpose

The expensive **named / branded resolution tiers** of
[food-resolution.md](food-resolution.md): the official-source fetch boundary
(FTY-078) and the official-source resolution step (FTY-062) — with its
reference-source tier (FTY-166), model-prior / default-serving fallback, the
FTY-370/FTY-418 budget/transience degrade prior, count-serving named-food
evidence (FTY-252), the search-result snippet fallback (FTY-314), and the
brand-aware packaged-product routing (FTY-253). These are the search + fetch +
LLM-extraction paths that run only after a USDA/OFF miss, and the model-prior
estimate of last resort. This page was extracted **verbatim** from
`food-resolution.md` (FTY-426, contract-only — no semantic change); the rest of
the food-resolution contract (Inputs, serving math, routing, the USDA / barcode /
prior-correction / user-stated tiers, exact-evidence-upgrade routing) stays there.

## Owner

estimator / contracts / backend-core / security-privacy lane (same owners as
[food-resolution.md](food-resolution.md)): the official-fetch, official-step, and
reference modules named in the `### Owner (additional)` subsection below —
`backend/app/estimator/hardened_fetch.py`, `backend/app/estimator/official_fetch.py`,
`backend/app/estimator/official_step.py`, `backend/app/estimator/reference_fetch.py`,
`backend/app/estimator/branded_routing.py`, `backend/app/estimator/degrade.py`,
`backend/app/schemas/official_source.py`, and the egress diagnostics
(`backend/app/routers/health.py`, `backend/app/services/sources.py`,
`backend/app/schemas/sources.py`).

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

### Config (`OfficialFetchSettings`, `SLACKS_OFFICIAL_FETCH_` env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLACKS_OFFICIAL_FETCH_ALLOWED_HOSTS` | _(empty)_ | Comma-separated official-source host allowlist (lower-cased). **Empty → nothing is fetchable** (fail closed). |
| `SLACKS_OFFICIAL_FETCH_TIMEOUT_SECONDS` | `10` | Per-request wall-clock timeout. |
| `SLACKS_OFFICIAL_FETCH_MAX_BYTES` | `2000000` | Response-size cap; a larger body fails closed. |
| `SLACKS_OFFICIAL_FETCH_ALLOWED_CONTENT_TYPES` | `text/html, application/xhtml+xml, text/plain` | Accepted content types; anything else fails closed. |

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
- **Host allowlist.** Only the configured `SLACKS_OFFICIAL_FETCH_ALLOWED_HOSTS` are
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
  `needs_clarification`); a *generic* candidate is deferred too **when it is detail-rich**
  (identity plus a usable amount — FTY-167), and under `estimate_first` a recognizable
  amountless generic candidate is deferred to rough reference/model/default-prior
  estimation before any question. `balanced`/`strict` may still ask the older amount
  question. A branded item USDA/OFF resolves with a **brand-compatible,
  quantity-costable** row (FTY-253) never reaches this step; an incompatible or
  un-costable hit is treated as a miss and deferred here.
- The model never supplies a `brand` it was not given, and `brand` is stored as data,
  never interpreted.

Inside the official step, a **branded** candidate is searched against official sources
first (a named product has an authoritative page); a **generic** candidate has no brand
page, so official search is skipped whether it is detail-rich or a default
`estimate_first` amountless rough-estimate candidate. On an official-source miss a
**branded/hinted** candidate then consults the **Open Food Facts name-search tier**
(FTY-369, the `product_database` rank between official source and reference — see
**Name search for barcode-less branded products** in
[food-resolution-barcode-source.md](food-resolution-barcode-source.md)); a foreign OFF hit is rejected
and the chain continues. Either way, on a miss the candidate falls through to the
**reference-source tier** (FTY-166 — a public-nutrition-reference search +
searched-result fetch), and only when that also produces nothing confident to the
**model-prior** estimate, whose `assumptions` name the per-tier reason (e.g.
`"generic food (no official page to search); reference_source returned no confident
match; estimated from model prior"`). The result always carries its explicit
`source_type` and stays user-editable — never a silent guess.

### Orchestration

For each deferred candidate, the step resolves in order, all egress through the
injected adapters (the step itself opens no socket):

1. **Search** the sanitized **item identity only** (never profile, weight, history,
   or event metadata) through the FTY-079 adapter. Since FTY-253 each tier tries a
   bounded, deterministic set of identity-query variants — the `name + brand` base,
   the quantity-phrase product hint in both token orders, and the static retailer
   alias expansion (see **Brand-aware packaged-product routing** below) — in order,
   stopping at the first fully supported result.
2. **Fetch** each candidate result URL through the FTY-078 hardened fetcher, taking
   back sanitized, active-content-stripped inert text.
3. **Extract** the nutrition facts the page states by sending that inert text to the
   provider with the strict `NamedFoodEstimate` schema (`schemas/official_source.py`,
   `official_source/v2`). The schema accepts `per_100g`, `per_serving`, and
   `as_logged` facts plus an optional structured `serving_count` for count-serving
   facts (`3 strips`, `1 slice`, `2 eggs`, `5 crackers`); count units validate
   against the closed synonym map above.
   The page text is **untrusted data**; the reply is trusted only after it validates,
   and a low-confidence / fact-less reply is not trusted.
4. **Recompute** canonical calories/macros from the validated facts with the FTY-044
   serving math — the model never supplies the stored numbers. Per-serving facts with
   a gram/millilitre serving size are canonicalised to per-100g and scaled to the
   consumed quantity; per-serving facts with a structured counted serving are scaled
   by `consumed_count / source_count` and only need grams when the logged item itself
   needs a gram value. A source that states both count and grams uses the count
   relation for count logs before any default-serving fallback. The canonical
   per-100g facts must clear the **FTY-115 plausibility bound** (`≤ 900` kcal/100g,
   non-negative, finite — the same gate FDC/OFF enforce), applied after any
   per-serving → per-100g conversion. Count-serving facts with no gram serving cannot
   be canonicalised to per-100g, so they are bounded by the schema and only scale
   compatible explicit counts. An implausible result (e.g. a kJ value mislabelled as
   kcal) is a **non-match**: the official page falls through to model-prior, and an
   implausible *model-prior* estimate routes to `needs_clarification` rather than
   committing an absurd total (FTY-132).

### Reference-source tier (FTY-166, before any model prior)

When the official tier misses — or does not apply (a generic candidate) — the step
runs the same search → fetch → extract → recompute chain against **public nutrition
reference evidence**: the query is the sanitized identity plus the fixed
`nutrition facts` intent, and each result URL is fetched through the
**searched-result** policy (`reference_fetch.py`; no host allowlist, full SSRF
posture — see `evidence-retrieval.md`). A confident, plausible transcription
resolves the item with `source_type = reference_source` and
`source_ref = reference_source:<url>`; like an official page it writes **no**
global `products` row.

### Model-prior / default-serving fallback (with status, never a silent guess)

When the search provider is **disabled** or **unavailable** (no key), when a tier's
fetch is off (**official**: empty allowlist; **reference**:
`SLACKS_REFERENCE_FETCH_ENABLED=false`), or when **nothing confident is found** on
either tier, the candidate falls through to a **model-prior** `NamedFoodEstimate`
from sanitized identity, bounded amount/unit fields, and evidence-view records —
never raw diary text, search queries, pages, or snippets. It is recorded with
`source_type = model_prior`, `source_ref = model_prior`, and an
explicit `assumptions` reason naming each tier's outcome
(e.g. `"official_source returned no confident match; reference_source returned no
confident match; estimated from model prior"`) plus the model's own assumptions,
so the entry surfaces an explicit source status and stays user-editable — never a
silent guess (per the `evidence-retrieval.md` Fallback Rule). If serving math
cannot infer grams, it may record `estimated_default_serving` or bounded `basis =
as_logged`; unusable estimates clarify with legacy unavailable/unusable labels
plus sanitized detail (`provider_error`, `low_confidence`,
`non_resolved_disposition`, or `unusable_facts`).

### Budget/transience-degraded rough estimates (FTY-370)

A candidate degraded because its run breached the FTY-363 per-run ceiling
(`run_wall_clock_deadline_exceeded` / `run_provider_call_budget_exceeded`) or
exhausted the bounded transient retries (`provider_transient_error`-class —
`estimation-jobs.md` v7, **Never-fail degrade semantics**) commits with **rough
provenance, never as a trusted value**: it reuses the model-prior /
default-serving rough evidence shapes above (`source_type = model_prior`, or
the concrete source whose facts the run already gathered plus a
default-serving assumption — fact bases per `evidence-retrieval.md`) and
carries an explicit, **content-free** assumption marking it a
budget/transience-degraded estimate (a fixed label built from the breach/
exhaustion reason, e.g. `degraded:run_wall_clock_deadline_exceeded` — never
raw diary text, prompts, or provider output), so the item stays visibly
distinguishable from trusted/exact/saved/edited values and user-correctable
like any rough estimate (`estimator-policy.md`, **Rough provenance and
editability**).

The degrade producer must be able to run **without further provider budget**:
when no provider headroom remains, it produces a deterministic rough estimate
— from evidence the run already gathered, a default serving over already-known
facts, or a documented deterministic prior — so degradation can never itself
block on the exhausted budget. The concrete producer is the downstream
**FTY-371**; the worker routing that invokes it is **FTY-372**.

The **documented deterministic prior** (FTY-418) is food-aware, so even this rare
last-ditch is never a flat-lined `2 cal/g + null macros + 100 g` row: it resolves a
counted everyday food through the common-portion table above (a mozzarella slice
≈ 22 g, a deli-turkey slice ≈ 28 g — never a blanket 100 g default serving), and it
carries a documented mixed-food macro split (≈ 50 % carbohydrate / 20 % protein /
30 % fat by energy, Atwater-consistent) alongside the coarse energy-density prior,
marked `estimated` per field — a resolved rough row carries macros, never a silent
`null` (**Macros are never silently null for a resolved food**). The coarse
energy-density prior stays a genuine emergency (true budget exhaustion); the meal
flat-lined in the 2026-07-20 dogfood was a per-run wall-clock ceiling **tail
event**, not the common outcome — a healthy re-run resolves each item.

### Persistence

A resolved official-source / model-prior candidate becomes a `resolved`
`derived_food_items` row plus a user-owned `evidence_sources` row, exactly like the
USDA/OFF path, with two differences:

- **No global cache.** Official-source / reference-source pages are per-URL and
  model-prior estimates are per-resolution, so none writes a `products` row; the
  evidence `product_id` is `NULL`.
- **Provenance.** `source_ref` is `official_source:<url>` or `reference_source:<url>`
  (the **URL only** — never the raw page) or `model_prior`; the immutable per-100g
  facts snapshot, content hash, and fetch time are stored as for any source. The
  `0012` migration adds the additive, nullable **`evidence_sources.assumptions`**
  JSON column carrying the documented assumptions (the model-prior reason); a
  USDA/OFF/label row leaves it `NULL`.

The consulted source systems (`official_source`, `reference_source`, and/or
`model_prior`) are recorded on the run `source_refs`, and the assumptions on the run
`assumptions`.

### Count-serving named-food evidence (FTY-252)

Official/reference pages and model-prior estimates may state facts per counted
serving. The count relation is structured output, never mined from free-text
assumptions. Source-backed count servings keep the page URL in `source_ref` and do
not add invented assumptions; a model-prior count serving records a content-free
assumption such as `model_prior_count_serving:5 cracker` so the rough count relation
is visible. If the user's logged unit is absent or incompatible with the source count
unit (`per 3 strips` vs. `2 cups`), the resolver rejects that result and continues to
the next evidence result/tier; only when no usable result remains does policy decide
whether to ask.

### Search-result snippet fallback (FTY-314)

Both web-evidence tiers keep the **fetched page first**, but a search candidate
now also carries the provider's bounded result **snippet** (SearXNG `content` /
Brave `description`). When a candidate's page fetch fails (e.g. HTTP 403),
returns no usable text (a JavaScript shell), or extracts no accepted facts, the
resolver extracts from that candidate's bounded **title+snippet** through the
exact same chain — untrusted-text prompt framing, `NamedFoodEstimate` schema,
plausibility bound, quantity/brand-compatibility gates, deterministic serving
math — before moving to the next result or tier. Provenance stays the result URL
(`official_source:<url>` / `reference_source:<url>`) and the evidence row
records the content-free `search_result_snippet` assumption label, so a
snippet-derived number is honestly distinguishable from a fetched-page
transcription (and ranks below one, above a pure model prior). An empty or
missing snippet preserves the fetch-only behavior; the raw snippet is never
persisted in traces, assumptions, source refs, errors, or logs. See
`evidence-retrieval.md` (**Search-Result Snippet Evidence — FTY-314**).

### Brand-aware packaged-product routing (FTY-253)

For a **branded** candidate the resolver is allowed to be creative inside a bounded
policy instead of obeying a rigid first-source-wins sequence:

- **A generic FDC hit is a candidate, not an authority.** The food step accepts the
  row only when it passes the deterministic **brand/product-compatibility gate**
  (`branded_routing.is_evidence_brand_compatible`: the description names the brand
  or a static retailer alias, or carries only the item's own name/brand tokens plus
  benign preparation descriptors) *and* its serving information can cost the logged
  quantity. Otherwise the hit is a miss and the candidate defers to the
  official/reference/model-prior tiers — it never completes from the wrong product
  and never raises the generic quantity question for a supplied count. (This
  replaces the former "a branded item USDA resolves never reaches the official
  step" invariant: USDA may still win, but only when compatible **and** costable.)
- **Bounded identity-variant search.** Each web-evidence tier searches, in order:
  the `name + brand` base query; when the parser stranded product tokens in
  `quantity_text`, the sanitized **product hint** in both token orders
  (`name + hint` and the user-stated `hint + name`, so
  `4 toppabales brand crackers` parsed as `name="crackers"` still searches
  `toppabales brand crackers`); and a **static** private-label/retailer alias
  expansion (`branded_routing.RETAILER_BRAND_ALIASES`, e.g. Compliments ↔ Sobeys,
  PC → President's Choice/Loblaws). The set is deduplicated and hard-capped
  (`MAX_IDENTITY_VARIANTS`); the reference tier appends the fixed `nutrition facts`
  intent per variant.
- **Every evidence candidate is gated.** A fetched page's transcribed
  `product_name` must pass the same compatibility gate (plus the FTY-252
  quantity-costability check) before it may back the item, so the resolver
  considers multiple candidates and rejects an earlier generic/incompatible one in
  favor of a later compatible branded/reference one.
- **Clarification is the last resort** for a branded product with a supplied count:
  when sources are unavailable or fail, an explicitly labelled rough/model-prior
  estimate is preferred over asking the user to restate the amount (per the shared
  estimate-first policy).
- **Security.** Hints are extracted through the identity sanitizer, variants are
  composed from parsed fields only, and every query passes the existing
  `sanitize_query` chokepoint — item identity only, deterministic, bounded; no
  open-ended agentic browsing and no new fetch surface.

### Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| Branded candidate, USDA/OFF miss, official page resolves | _(completes)_ | food `resolved` (`official_source`) + `evidence_sources` (`official_source:<url>`, no `product_id`) | `processing → completed` |
| Official page misses (or fails the FTY-115 plausibility bound), reference page resolves (FTY-166) | _(completes)_ | food `resolved` (`reference_source`) + `evidence_sources` (`reference_source:<url>`, no `product_id`) | `processing → completed` |
| Generic candidate USDA miss, **detail-rich** (FTY-167), reference page resolves (FTY-166) | _(completes; official search skipped)_ | food `resolved` (`reference_source`) | `processing → completed` |
| A fetched page resolves but its per-100g facts fail the FTY-115 plausibility bound | _(non-match; falls through)_ | nothing for that page | `→ next tier / model-prior` |
| Page fetch fails (403) or yields no accepted facts, the candidate's compatible snippet resolves (FTY-314) | _(completes)_ | food `resolved` (tier's source type) + `evidence_sources` (URL ref, `search_result_snippet` assumption) | `processing → completed` |
| Search disabled / unavailable, a tier's fetch off, or no confident match on either tier → model-prior | _(completes)_ | food `resolved` (`model_prior`) + `evidence_sources` (`model_prior`, per-tier assumptions) | `processing → completed` |
| Model-prior estimate fails the FTY-115 plausibility bound | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Branded candidate USDA/OFF **resolves** with a brand-compatible, quantity-costable row (FTY-253) | _(as FTY-044/060)_ | official/reference source not consulted | `processing → completed` |
| Branded candidate, USDA hit **incompatible** with the brand/product identity or unable to cost the amount (FTY-253) | _(miss; defers)_ | nothing from that row | `→ official/reference/model-prior tiers` |
| Generic candidate USDA miss, **no usable amount**, `estimate_first` | _(falls forward)_ | reference/model/default-prior rough evidence + assumptions | `processing → completed` |
| Generic candidate USDA miss, **no usable amount**, `balanced`/`strict` asks | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Usable facts but unresolvable quantity, `estimate_first` | _(falls forward)_ | default-serving/reference/model-prior rough evidence + assumptions | `processing → completed` |
| Model cannot estimate, all rough paths unavailable/unsafe, or active policy asks | `NeedsClarification` | clarification question | `processing → needs_clarification` |

### Security / Privacy

- **No direct egress.** The step issues no network call of its own; all search goes
  through the FTY-079 adapter and all fetches through the injected hardened fetchers
  (FTY-078 official; FTY-166 searched-result), so the SSRF/egress and
  query-sanitization boundaries live upstream and this orchestration cannot bypass
  them. Tests prove each fetcher only ever receives a URL the search adapter
  returned.
- **Untrusted-until-validated.** Fetched/searched/extracted/LLM content — official
  and reference pages, and search-result title/snippet text alike (FTY-314) — is
  validated against `NamedFoodEstimate` and recomputed by the deterministic
  calculators before persistence; snippet text is bounded before it reaches the
  prompt and framed as inert data, never instructions.
- **No-raw-page retention.** `evidence_sources` stores the URL, timestamp, content
  hash, and extracted per-100g facts only — never the raw page or the raw
  search-result snippet (per `data-retention.md`).
- **Data minimization.** Only item identity (name + brand) crosses the search
  boundary — the reference query adds only the fixed `nutrition facts` intent; no
  personal context, no raw diary text.

### Examples (tests)

`tests/test_official_source_resolution.py` proves, with a stubbed search adapter and
fetchers: official-page resolution end-to-end; the official → reference → model-prior
tier order for a branded item and reference-before-model-prior for a detail-rich
generic item (FTY-166); the official step runs only after a USDA/OFF miss; the
disabled-provider / reference-miss model-prior-with-per-tier-status fallback; that no
raw page text is persisted; count-serving fixtures for `3 strips`, `1 slice`,
`2 eggs`, `5 crackers (19 g)`, model-prior `5 crackers = 30 g`, and incompatible
count units; and no direct egress. `tests/test_reference_fetch.py`
proves the searched-result policy negatives (HTTPS-only, private/loopback/link-local/
metadata blocked, redirects refused, oversized and non-text bodies rejected, inert
text, fail-closed off switch). `tests/test_food_migration.py` applies/rolls back the
`0012` `assumptions` migration.

