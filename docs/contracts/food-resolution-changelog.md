# Contract: Generic Food Resolution — Version History

## Purpose

The reverse-chronological change log for [food-resolution.md](food-resolution.md).
Every dated version entry of the Generic Food Resolution contract lives here so the
normative page stays focused on current behaviour while its history stays complete
and un-truncated. This page is **non-normative**: it records what changed and when;
the binding rules live in `food-resolution.md`.

## Owner

estimator / contracts / backend-core / security-privacy lane (same owners as
[food-resolution.md](food-resolution.md)): `backend/app/estimator/fdc.py`,
`backend/app/estimator/hardened_fetch.py`, `backend/app/estimator/food_serving.py`,
`backend/app/estimator/food_step.py`, `backend/app/models/food_sources.py`,
`backend/app/models/derived.py` (`DerivedFoodItem` resolution columns),
`backend/alembic/`.

## Version

27 (FTY-406): **corrections become a resolution source at estimate time.** A new
prior-correction tier (`backend/app/estimator/correction_resolution.py`,
`PriorCorrectionResolveStep`) reads the previously write-only `corrections` audit
trail: before the guessed source tiers run, a candidate whose normalized name matches
a food the acting user has already **hand-corrected** (a `user_edit` on `calories`,
parent event not voided) resolves from that corrected value instead of being
re-guessed — so the operator's "black coffee" (148.8 → `re_match` 4.8 → hand-edit 3,
every time) now resolves to 3. The tier runs after the rank-1 current-entry steps
(`user_text` / image-label facts) and before the USDA/OFF food step, claiming each
resolved candidate; it skips a barcode candidate. Precedence: **above** every guessed
source (`usda_fdc` / `open_food_facts`-by-name / `official_source` / `reference_source`
/ `model_prior`), **below** the current entry's own explicit evidence (`user_text` /
`user_label` / barcode). Lookup is **per-user and name-normalized** (the shared
`normalize_text` saved-food rule — no cross-user reads); it is authoritative only on a
**stable** prior value (conflicting priors fall through), matches the portion directly
or **rescales** a mass-bearing prior per-gram to a different quantity (recording the
content-free `prior_correction_rescaled` assumption), and otherwise falls through so an
item with no usable prior correction resolves exactly as today. Persisted as an
ordinary `resolved` row + `evidence_sources` (new `SourceType.PRIOR_CORRECTION`,
`source_ref = prior_correction:<hash>`, `basis = as_logged`, **no** `products` row);
read-model label "Your correction". The correction-writing path (FTY-051) and the
`re_match` pass are unchanged — this tier only **reads**. Mobile surfacing
(history-sourced typeahead, corrected-entry quick-add default) is deferred to
follow-ups. No migration. See **Prior-Correction Resolution (FTY-406)** in
`food-resolution.md`.

26 (FTY-397, contract only): the reverse-chronological Version log was **extracted
verbatim** from `food-resolution.md` into this page (`food-resolution-changelog.md`),
leaving a forwarding `## Version` pointer behind and re-pointing sibling contract
version citations (e.g. `food-resolution-changelog.md` v9 / v16 / v23) at this page.
Structure-only relocation of a non-normative change log — no wording, ordering, date,
or numbering change to any prior entry, and no contract, ranking, cache-rule, schema,
DTO, endpoint, or behaviour change.

25 (FTY-388): FDC candidate ranking demotes an **unstated part of a food**. A
row naming `white` / `yolk` / `shell` — a part whose calorie identity differs
sharply from the whole food (an egg white is ~55 kcal/100g against a whole egg's
~143) — that the query did **not** itself state now ranks **behind** any
whole-food row (`backend/app/estimator/fdc_ranking.py`, `PART_OF_FOOD_TOKENS`), so
`large eggs` selects a whole-egg row instead of `Eggs, Grade A, Large, egg white`
(the 2026-07-05 poisoned-cache incident). It is a **demotion**, not a rejection:
a part row stays compatible and still resolves when it is the only row, and a
query that states the part (`2 egg whites`) keeps it through the same
`_contains_token` stated-token exemption the rejected/demoted forms use — matched
singular/plural-safe like the other form vocabularies. The demotion is the
leading term of `fdc_preference_key` (a part is a larger identity error than an
unstated preparation form) and joins `is_fdc_description_rank_stable`, so a
**`products` cache row poisoned before the fix** (`large eggs` / `eggs` →
`usda_fdc:747997`) is no longer rank-stable: it re-fetches and self-heals to a
compatible whole-food row on read, with no operator `DELETE`. A bounded documented
tunable; no schema, DTO, or endpoint change.

24 (FTY-369): the Open Food Facts `product_database` source gains a **name-search**
path for barcode-less **branded** products. A branded candidate USDA/OFF-by-barcode
cannot resolve now consults OFF **by name** (`off.py` `OffClient.search_by_name` +
`OffNameResolver` in `food_resolvers.py`, wired into `official_step.py`) before the
chain falls to model prior, so a trivially findable packaged product (the 2026-07-16
`made good mornings … oat bars` incident) lands as `product_database` evidence instead
of a bare `user_text`/`model_prior` estimate. Name queries are built from the bounded
`identity_variants` machinery (item identity only — name + brand + product hint,
deduplicated, hard-capped), each passing the `sanitize_query` chokepoint and the OFF
host allowlist; each OFF hit passes the same `is_evidence_brand_compatible` gate FDC
branded routing applies, so a foreign product is rejected and the chain continues. The
tier sits at its hierarchy rank — **after** official source, **before** reference and
model prior — and never displaces an applicable `user_label`/`user_text`/
`official_source` result. Name hits cache and record through the existing `products`
(`(open_food_facts, <name query>)`, `barcode = NULL`) and `evidence_sources` shapes;
no schema, DTO, or endpoint change. Reuses the hardened OFF transport, schema
validation, plausibility gate, and serving math — a new query kind, not a new fetch
capability.

23 (FTY-370, contract only): pins the **budget/transience-degraded rough
estimate** — a candidate a run could not resolve before breaching the FTY-363
per-run ceiling (`run_wall_clock_deadline_exceeded` /
`run_provider_call_budget_exceeded`) or exhausting bounded transient retries
(`provider_transient_error`; `estimation-jobs.md` v7) is committed with rough
provenance (the `model_prior` / default-serving rough evidence shapes) plus an
explicit **content-free** degraded assumption, visibly distinct from
trusted/exact values and user-correctable — and the degrade producer must be
able to run **without further provider budget**. No schema, migration,
serving-math, or source-hierarchy change; FTY-371/FTY-372 implement. See
**Budget/transience-degraded rough estimates (FTY-370)**.

22 (FTY-368): composed-dish portions respect stated structure, and a
**resolved-value plausibility gate** bounds final dish totals. The FTY-254
common-portion table now declines any **composed/assembled dish** (closed
vocabulary — sandwich, wrap, burger, taco, …; snack idioms like `cracker
sandwich` excluded), so a table food named as one component (`… on white
bread`) can never supply the whole dish's grams (the 2026-07-16 live 65-kcal
tuna-salad-sandwich incident). After serving math produces a final total, a
deterministic gate (`backend/app/estimator/resolved_plausibility.py`) rejects a
dish-class item resolved outside a generous, cited dish-class band (100–3000
kcal per counted dish) or with resolved grams beneath a **stated component
amount** (`about 1/2 a can of tuna` bounds the sandwich from below). The
rejection is traced content-free (`rejected_implausible_resolved_total`, a
re-query trigger), the candidate refits through the existing
official/reference/model-prior tiers, and the refit item carries the
`resolved_plausibility_refit:<reason>` assumption so a rough re-estimate is
never presented as a cleanly-scaled trusted row. The terminal model-prior tier
stays ungated — the honest rough last resort, never a terminal failure. No
schema, DTO, or endpoint change.

21 (FTY-309): implements the **label** half of the exact-evidence upgrade propose
routing below. `POST .../exact-upgrade/label?save={bool}` validates the raw label
image bytes (the `label-upload.md` wire shape) as **data** fail-closed — size /
content-type allowlist / magic number, `413` / `415` **before any model call** —
then runs the existing schema-validated label extraction (`label-extraction.md`):
a confident read yields an `exact` `user_label` proposal (through the FTY-307
signed-`proposal_ref` foundation), an unreadable/not-a-label/unusable read a
clearly-labelled identity `fallback` through the existing reference-source →
model-prior tiers (`failure_reason` in the fixed `label_unreadable` / `not_a_label`
/ `no_usable_facts` set), else a `none` read. Loading and eligibility use the same
owner-scoped item loader as the barcode route (`not_upgradeable` `422` for an
already source-backed **or owned exercise** item). `save=true` writes exactly
**one** user-owned `log_attachments` row on the item's **owning log event**;
`save=false` and every `none`/provider-outage outcome retain nothing. A
vision-provider **error** surfaces a retryable `503`, never a disguised miss, and
propose never mutates the item — apply (FTY-307) does. No schema, migration, or
estimator change.

20 (FTY-308): implements the **barcode** half of the exact-evidence upgrade propose
routing below. `POST .../exact-upgrade/barcode` resolves the typed/scanned barcode
through the existing cache-first hardened OFF path (no second barcode mapper): a
confident match yields an `exact` `product_database` proposal (built through the
FTY-307 signed-`proposal_ref` foundation), a miss/disabled-source/plausibility-rejected
result yields a clearly-labelled `fallback` from the item's identity through the
existing reference-source → model-prior tiers when they can resolve, else a `none`
no-proposal read. The barcode `failure_reason` vocabulary is fixed here: `barcode_invalid`
(non-GTIN input), `barcode_no_match` (OFF has no product for the barcode), `no_usable_facts`
(OFF returned a product but its facts are unusable/plausibility-rejected), and
`source_unavailable` (OFF disabled by config). A transient/terminal OFF **error** surfaces a
retryable `503`, never a disguised miss. The route evaluates exact-upgrade eligibility
server-side (`not_upgradeable` `422` for an already source-backed item **or an owned exercise
item**) and never mutates the item — apply (FTY-307) does. No schema, migration, or estimator
change.

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

4 (FTY-062) adds the **official-source resolution step** (`official_step.py`): a
last-resort pipeline step that costs named restaurant / manufacturer / packaged
products USDA and OFF cannot resolve, orchestrating the FTY-079 search adapter and the
FTY-078 hardened fetch, and otherwise falling through to a **model-prior** estimate
with an explicit source status. It adds the additive `evidence_sources.assumptions`
column (`0012` migration) and an additive `brand` field on the parse candidate; it
does not change the FTY-044 USDA, FTY-060 OFF, or FTY-061 label paths. See
**Official-Source Resolution (FTY-062)** below.

3 (FTY-078) extends the shared `hardened_fetch` policy with an **official-source page
fetch** (`fetch_text` → inert text) and its egress configuration, without changing the
FTY-044 USDA path or the FTY-060 OFF path. This is the SSRF / egress prerequisite for
official-source resolution (FTY-062); it ships no search adapter or resolution pipeline
of its own. See **Official-Source Fetch Boundary (FTY-078)** below.

2 (FTY-060) adds the **Open Food Facts barcode source** *above* USDA generic in the
source hierarchy (a confident packaged-product match is preferred over a generic
estimate for the same input), without changing the FTY-044 USDA path or its math. The
source system id `open_food_facts` (source type `product_database`) is recorded on run
evidence and on each cached product / evidence row it produces. See **Barcode Source
(Open Food Facts)** below.

1 (FTY-044). The source system id `usda_fdc` is recorded on run evidence and on each
cached product / evidence row.
