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
`backend/app/models/food_sources.py`, `backend/app/models/derived.py`
(`DerivedFoodItem` resolution columns), `backend/alembic/`.

## Version

19 (FTY-326): implements evidence tiers as session tools: sanitized tier outcomes
feed the ledger, official/reference dead ends get one bounded re-query before
`model_prior`, `not_applicable_by_session` replaces frozen generic skips, and
model-prior failures add sanitized detail. USDA row acceptance is
session-consulted: the FTY-254 ranked compatibility gate now only *bounds* the
option set — when it rejects every energy-bearing row, the bounded rejected rows
feed the ledger as `rejected_incompatible_row` records (global row description +
ref) and the session may spend its one re-interpretation pass to revise the
identity for a single retried lookup, or keep it (a deliberate miss). An
unaccepted page/snippet read's own bounded FTY-314-framed text transiently
reaches the re-interpretation prompt only (never ledger/trace/persisted/query/
fetch surfaces — see `evidence-retrieval.md`), and a revised identity is
deterministically echo-filtered before it may drive any re-query or persistence:
a staged-excerpt token survives only when the user's own words or a sanitized
ledger descriptor (identity-sanitized extraction identity, trusted row
description) authorized it, so a source-stated correction can revise the
identity while an unvetted excerpt echo cannot. No schema/DTO/source/egress
change.

18 (FTY-348, contract only): the global FTY-324 interpretation-session semantics
(the model-owned/deterministic-owned division of labour and the
evidence-tiers-as-tools framing) move to
[interpretation-session.md](interpretation-session.md); this page links there and
keeps its page-local per-tier tool table, routing, serving math, source hierarchy,
and food outcome tables. No normative change.

17 (FTY-306, contract only): adds **exact evidence upgrade routing** for an
**existing** low-trust/incomplete food item — the correction sheet's
`Make it exact` lever. Two source-specific proposal entry points (a typed or
scanned **barcode**, and a **label image** upload carrying the existing `save`
privacy flag) target an existing `derived_food_items` row through the existing
hardened OFF and label-extraction paths, produce a server-held **proposal**
(`exact` / `fallback` / `none` — `evidence-retrieval.md`, **Exact Evidence
Upgrade — FTY-306**), and an **apply** operation replaces the item's source in
place with re-match semantics after explicit preview/confirm. The current amount
is preserved by default, an optional amount adjustment applies before costing,
and an uncostable amount requires user action (`422`) instead of a guess; a
fallback is never presented as exact. No schema, migration, endpoint code, or
estimator change in this story; backend implementation is FTY-307–FTY-309,
mobile consumption FTY-310–FTY-313. See **Exact Evidence Upgrade Routing —
FTY-306** below.

16 (FTY-324, contract only): redefines food resolution's source tiers as
bounded **tools available to the `InterpretationSession`**, not a one-way
fall-through keyed on the first parsed candidate fields. The model owns tier
selection, source acceptance, ambiguity resolution, and hypothesis revision with
the raw text plus gathered evidence in view; deterministic code keeps authority
over source/fetch gates, plausibility validators, serving math, scaling math,
provenance, privacy, budgets, and persistence. No schema, migration, provider,
settings, endpoint, or estimator behavior changes land in this documentation
story; FTY-325/FTY-326 implement the target loop.

15 (FTY-254) adds **common-food FDC candidate ranking and common-portion
defaults**. A `trusted_nutrition_database` match now means trusted nutrition
facts for a **compatible food**, not USDA's first lexical hit
(`backend/app/estimator/fdc_ranking.py`): an energy-bearing, plausible FDC row
must also (a) name the query's **head noun** — the food identity (`hummus` in
`dill pickle hummus`; a `Pickles, cucumber, dill or kosher dill` row matching
only the flavor tokens is rejected, while plain `dill pickle` still resolves to
pickles); (b) carry no **density-changing form** the query did not state
(dehydrated / dried / dry / powder(ed) / flour / concentrate(d) / evaporated /
condensed / chips / crisps / babyfood — so `banana` never costs as banana
powder; the `dry roasted` preparation idiom is excused on both sides — a
dry-roasted row stays eligible, and a `dry roasted ...` query opts into no
dehydrated/dried/powdered form; a query stating a form opts
into that form only, directly or via its bounded synonym family —
dehydrated/dried/dry/powder(ed) is one family, chips/crisps another, since USDA
names one form several ways in a row (`Bananas, dehydrated, or banana powder`) —
never into a *different* form, so `condensed milk` still rejects a `Milk, dry`
row); and (c) name any **added ingredient** the query
states (`buttered` toast is not plain toast). Surviving rows are ordered by
fewest unstated *demoted* forms (canned / pickled / sweetened / smoked / cured /
frozen / juice / syrup), then query-token coverage (`Egg, whole, cooked,
scrambled` beats a raw-egg row for `scrambled eggs`), then USDA relevance order;
rejecting every row is a clean miss that falls forward per the existing routing.
`FdcClient.list_matches` (re-match alternatives) is deliberately unranked.
Separately, a **stated count of an everyday food** whose selected source row
lacks a serving size resolves through a closed, documented **common-portion
table** (`backend/app/estimator/common_portions.py`: banana small/medium/large
101/118/136 g, egg small→jumbo 38–63 g defaulting to the US large 50 g,
bread slice 30 g, toast slice 25 g, butter pat 5 g / stick 113 g — published
USDA household weights), recorded as an explicit
`estimated_common_portion:<food> <cue> <grams> g` evidence assumption so the
portion default stays visible and editable while the per-100g facts keep their
trusted-database provenance; anything not matching the table keeps the existing
routing. A bare, genuinely ambiguous item (`coffee`) resolves as an explicit
rough model-prior default under `estimate_first` (never the generic no-option
quantity question), and an item needing clarification (`curry`) asks an
item-specific, optioned question per `parse-candidates.md`. No migration; no
DTO change.

14 (FTY-253) adds **brand-aware packaged-product routing**. For a **branded**
candidate (non-blank `brand`), a generic USDA FDC hit is a *candidate source, not an
automatic authority*: it is accepted only when the selected row is **compatible with
the branded product identity** (a deterministic token check — the row names the
brand or a static retailer alias, or carries only the item's own name tokens plus
benign preparation descriptors) **and** its serving information can cost the logged
quantity. An incompatible row (e.g. `DENNY'S, chicken strips` for
`brand=Compliments`) is a **miss**: it must not complete the event and must not
raise the generic quantity question — the candidate defers to the branded
official/reference/model-prior tiers. Those web-evidence tiers now search a
**bounded, deterministic set of item-identity query variants** per tier: the
`name + brand` base, the quantity-phrase **product hint** in both token orders
(covering parses that strand product tokens in `quantity_text`, e.g.
`4 toppabales brand crackers` → `name="crackers"`), and a **static
private-label/retailer alias expansion** (e.g. Compliments ↔ Sobeys, PC →
President's Choice/Loblaws). Every evidence candidate a tier considers must also
pass the same brand/product-compatibility gate, so an earlier generic/incompatible
result is rejected in favor of a later compatible one. Hint tokens pass through the
identity sanitizer and every query still egresses through the search adapter's
`sanitize_query` chokepoint; the expansion is capped, never open-ended browsing.
Generic (unbranded) candidates keep the FTY-044 first-match FDC behavior, and
barcode/OFF precedence is unchanged. Owner module:
`backend/app/estimator/branded_routing.py`.

13 (FTY-252) adds **count-serving facts for named foods** to the official /
reference / model-prior estimate schema (`official_source/v2`). A validated
`NamedFoodEstimate` can now state facts per counted serving (`serving_count`, e.g.
`3 strips`, `1 slice`, `2 eggs`, `5 crackers`) independently of any gram serving
size. When the logged quantity carries a compatible explicit count unit, the
resolver scales deterministically by `consumed_count / source_count`; when the
source also states grams for that counted serving, the same multiplier yields the
logged grams. Count units are normalized through a closed synonym map (singular /
plural concrete nouns only) and incompatible or missing count units are rejected so
the resolver tries the next evidence result/tier instead of multiplying a whole
default serving by the user's count.

12 (FTY-298, contract only) adopts the shared **rare clarification /
estimate-first** food-resolution boundary. The mode semantics, allowed last-resort
clarification reasons, rough-provenance requirements, and advisory-provider rule are
now owned by [estimator-policy.md](estimator-policy.md); this contract applies them to
source lookup, serving math, item routing, fallback behavior, and food evidence
persistence. This is a contract-only target for downstream estimator/settings stories.

11 (FTY-292) locks the dogfood regression class for **explicit count + measured
household-volume spread** entries. A parsed snack such as "6 crackers with about
1.5-2 tbsp dill pickle hummus" carries sufficient quantity detail for both
components: the cracker count resolves through the count/default-serving path and
the hummus resolves through the household-volume path. If exact product lookup
misses for the cracker or hummus brand hint, resolution falls forward through the
existing searched-reference / comparable-reference / model-prior order with rough
provenance; it must not ask the generic quantity question again. Before FTY-298, a
truly amountless phrase such as "crackers and hummus" remained clarifiable; v12
supersedes that as the default and makes it a rough estimate unless a stricter operator
mode is selected or another allowed clarification reason applies.

10 (FTY-279, contract only) makes a **user-stated nutrition fact evidence, not a
clarification trigger**. A recognizable food item carrying a concrete user-supplied
detail — a portion/count (FTY-167/275), a `brand` identity (FTY-062), **or an
explicit nutrition fact the user stated** (`stated_calories` / `stated_*` macros,
`parse-candidates.md` v6) — resolves or estimates instead of asking a second quantity
question about the **same** item. A stated calorie total resolves the item
**directly** from `user_text` evidence (`evidence-retrieval.md`), counting the
calories immediately (`basis = as_logged`, not scaled); missing macros are estimated
with `field_provenance = estimated` or left `unknown`/`null`, never invented as
user-supplied zeroes. Clarification stays a **rare last resort** — reserved for a
component with **no usable identity/detail at all**, or **self-contradictory /
implausible** stated facts — not for a detail that merely was not the field the
pipeline expected. No schema/migration/serving-math change in this story; the
estimator work is the **downstream FTY-280 follow-up** and the FTY-278/FTY-275
baseline ships until then. See **User-Stated Resolution (FTY-279)** below.

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

6 (FTY-167) **sharpened the generic-food clarification boundary** and widened the count
vocabulary. If USDA/OFF could not cost a generic (unbranded) food, the resolver no
longer always clarified:
a **detail-rich** generic candidate (identity plus a usable amount — a count, a numeric
range, or a measured quantity) is deferred to the official-source step and estimated
from the **model prior** with an explicit `source_type = model_prior` status, exactly
like the FTY-062 branded fallback but **skipping the official web search** (a generic
food has no brand page to find). Under that historical boundary, only a generic food
with **no usable amount** ("some crackers") still routed to `needs_clarification`; FTY-298
supersedes that as the default and lets `strict` retain it. The serving math's count
vocabulary also gains common serving/portion nouns (`slice`, `sandwich`, `handful`,
`ring`, `finger`, …). No schema, migration, or serving-math change beyond the count
vocabulary; the USDA/OFF/label/official paths and their plausibility gate are unchanged.

9 (FTY-278, contract only) **makes any remaining amount clarification
item-scoped** instead of whole-entry-terminal, routing a mixed log to the new
first-class **`partially_resolved`** event status. Today (v8 and earlier) the food
step is all-or-nothing: if any candidate cannot be costed — an amountless generic
food, an unknown food, or an unresolvable quantity — the **whole event** goes
`needs_clarification` with *nothing costed*, even when the entry's other components
resolved cleanly ("chicken breast 150g and some milk"). FTY-278 settled the target:
when at least one component costs and one component still has an allowed clarification
reason, the food step
**commits the costable components as `resolved` items** (with their
evidence/`products` rows) in the same terminal transaction as a `processing →
partially_resolved` transition, and raises an **item-scoped** clarification naming
only that component (the `derived_food_item_id` carrier is `parse-candidates.md` v5);
an entry with *no* costable component still routes to event-level
`needs_clarification`. FTY-298 supersedes the amountless default by trying a rough
estimate first; `strict` or an unavailable/unsafe rough path can still produce the
item-scoped question FTY-278 defined. This decides routing/counting semantics only (no
`food_step.py`/serving-math/DTO/schema/migration change); the estimator work is a
**downstream follow-up** (`log-events.md` v6, `estimation-jobs.md` v3,
`daily-summary.md`), and the **v8 baseline** ships until then.

8 (FTY-275) **widened the deterministic serving math to standard household volume
measures** and sharpened the clarification boundary to *any stated portion*. A parsed
household-measure portion — `cup`, `tsp`, `tbsp`, `fl oz`, `pint`, `quart`, `gallon`
and their common spellings — now converts to grams at its standard millilitre volume
under the existing `1 ml ≈ 1 g` v1 assumption (tsp 5 ml, tbsp 15 ml, fl oz 30 ml, cup
240 ml, pint 473 ml, quart 946 ml, gallon 3785 ml — settled FDA nutrition-labeling /
US-customary measures, not guesses), so a perfectly-parsed "1/3 cup" or "a tsp" costs
deterministically instead of failing `resolve_grams` and stopping at
`unresolvable_quantity`. Bare `oz` stays a **mass** unit (28.35 g) and bare
single-letter `t`/`T` are deliberately unrecognised (ambiguous). In parallel, the
detail-signal net (`has_food_detail`) treats a `quantity_text` carrying a stated
household unit, a colloquial measure word (`splash`/`drizzle`/`dash`/`pinch`/
`handful`/`glug`), or an indefinite-article measure (`a`/`an` = 1) as detail present,
so a generic source-miss defers to the model-prior estimate rather than clarifying —
never re-asking for an amount the user already stated in words. Only a component with
**no** stated portion ("some milk", bare "milk") clarified under that historical
boundary — and in a *mixed* entry that amountless component dragged the **whole event**
to `needs_clarification` with nothing costed. FTY-298 supersedes the amountless default:
`estimate_first` rough-estimates the recognizable identity, while `strict` may keep the
older ask. Making any remaining clarification **item-scoped** so the entry's costable
siblings are committed and counted while only the asked component is blocked is
**FTY-278** (v9 above). No schema, migration, DTO, or new prompt-string change; the LLM
still supplies no calories/macros and the deterministic serving math owns every number.

7 (FTY-166) inserts the **reference-source tier** between the official source and
the model prior inside the FTY-062 step: a branded item official sources miss — and
a detail-rich generic item, which has no brand page — is searched for **public
nutrition reference evidence** (sanitized identity + the fixed `nutrition facts`
intent), the result page fetched through the **searched-result** hardened-fetch
policy (`reference_fetch.py` — HTTPS-only, public-IP-only, no redirects, bounded,
active content stripped, no host allowlist because the target is an arbitrary
public result URL), and the stated facts transcribed/validated/recomputed exactly
like an official page, recorded as `source_type = reference_source` with
`source_ref = reference_source:<url>`. The model prior runs only after this tier
also fails, with per-tier reasons in `assumptions`. See
`evidence-retrieval.md` (**Reference-Source Fallback — FTY-166**).

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
| `open_food_facts` | Barcode digits explicitly supplied by the user plus item identity for fallback context. | Barcode normalization, OFF enablement, HTTPS/allowlisted fetch, per-100g plausibility, serving math. |
| `usda_fdc` | Sanitized item identity for trusted-database lookup. | FDC enablement/API key boundary, ranked compatibility, per-100g plausibility, common-portion table, serving math. |
| `official_source` | Bounded sanitized identity variants for named/branded items. | Search/fetch/provider caps, host allowlist, active-content stripping, `NamedFoodEstimate` validation, compatibility and serving gates. |
| `reference_source` | Bounded sanitized identity variants plus fixed `nutrition facts` intent. | Search/fetch caps, searched-result hardened fetch, snippet bounds, extraction validation, compatibility and plausibility gates. |
| `model_prior` | Sanitized item identity plus bounded quantity/unit fields and content-free tier-miss reasons. | Provider schema validation, calibrated/cold-pass agreement where required, plausibility bounds, serving math, rough provenance. |

Tier order remains evidence-first: source-backed evidence is tried before pure
model prior whenever an applicable provider is configured and available. FTY-324
changes **who may reinterpret** between tiers, not the privacy or safety posture.
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
unstated density-changing form, stated added ingredients present; preferred by
fewest unstated demoted forms, then query-token coverage, then relevance order —
see **Version 15**), maps it to canonical per-100g facts, and caches it as a
`products` row. Rejecting every result is a **miss**, not a wrong-food match —
but since FTY-326 the gate is a bounding pre-filter, not the final row-acceptance
authority: the bounded rejected energy-bearing rows are first recorded on the
interpretation-session ledger as `rejected_incompatible_row` evidence (sanitized
outcome + global row description + source ref), and the session may spend its one
bounded re-interpretation pass to revise the identity for a **single** retried
lookup before the miss stands. If the session keeps its hypothesis, the rejection
is deliberate and resolution falls forward exactly as before. A
**compatible rank-stable** cache hit makes **no** external call. Incompatible
cached rows are never served; compatible but non-rank-stable rows (e.g. `tuna`
cached to canned tuna, `scrambled eggs` to raw egg) re-fetch once and refresh the
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
pat/stick, with small/medium/large/jumbo size cues read from the parse) resolves
via the documented common-portion table (`common_portions.py`, published USDA
household weights), keeping the trusted-source facts and recording an explicit
`estimated_common_portion:<food> <cue> <grams> g` assumption on the evidence row.
Otherwise the active shared policy ([estimator-policy.md](estimator-policy.md))
determines whether that gap falls forward to rough default-serving/reference/
model-prior estimation or asks for more detail. Calories/macros then scale per-100g
facts by `grams / 100`, rounded to 0.1 when grams are resolved; count-serving facts
scale the source serving facts by the count ratio; rough-prior paths store their own
basis and assumptions. Storage is canonical (kcal, grams); the 1 ml ≈ 1 g density
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
| Transient source failure (timeout/5xx) | `StepError` (retryable) | nothing | retries within bound, then `failed` |
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
  (`daily-summary.md`, `log-events.md` v6, `estimation-jobs.md` v3).
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
| OFF transient failure (timeout/5xx) | `StepError` (`off_transient_error`, retryable) | nothing | retries within bound, then `failed` |
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
`estimate_first` amountless rough-estimate candidate. Either way, on a miss the
candidate falls through to the **reference-source tier** (FTY-166 — a
public-nutrition-reference search + searched-result fetch), and only when that also
produces nothing confident to the **model-prior** estimate, whose `assumptions` name
the per-tier reason (e.g.
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
  (GTIN 8/12/13/14) exactly as the **Barcode Source (FTY-060)** path does, and
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
  routing it to the new `partially_resolved` status (`log-events.md` v6): costable
  components commit as `resolved` and count while a specific amountless
  component owns the question. Every source path, the serving math, plausibility
  gate, and `evidence_sources`/`products` shapes are **unchanged** — only the
  *routing* changes. The `derived_food_item_id` question link and its
  additive migration are `parse-candidates.md` v5's, owned by the downstream
  **FTY-278 implementation follow-up** (reads/answer flow: `daily-summary.md`,
  `log-events.md` v6, `estimation-jobs.md` v3); the FTY-275 (v8) baseline ships until
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
