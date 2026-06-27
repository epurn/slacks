---
id: FTY-062
state: ready
primary_lane: estimator
touched_lanes:
  - backend-core
review_focus:
  - pipeline-ordering-last-resort
  - untrusted-content-validation
  - evidence-retention-no-raw-pages
  - model-prior-fallback-with-status
  - migration-rollback
risk: high
tags:
  - evidence
  - estimator
  - search
  - fetch
approved_dependencies: []
requires_context:
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/contracts/parse-candidates.md
  - docs/contracts/estimation-jobs.md
  - docs/contracts/evidence-retrieval.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-062: Official-Source Resolution Pipeline Step

## State

ready

> 2026-06-27: split. This story was over-scoped (it bundled a hardened SSRF
> fetcher, a pluggable search-provider adapter, and the resolution pipeline step
> across three lanes) and tripped the circuit breaker after three implement
> attempts produced no merged PR. The two "big rocks" were carved out as
> prerequisites — **FTY-078** (hardened fetcher + SSRF egress policy) and
> **FTY-079** (pluggable search-provider adapter) — and this story is now just
> the official-source resolution pipeline step that depends on them. The steward
> will not assign it until FTY-078 and FTY-079 merge.

## Lane

estimator

## Dependencies

- FTY-040
- FTY-044
- FTY-045
- FTY-078 (hardened fetcher + SSRF egress policy)
- FTY-079 (pluggable search-provider adapter)

## Outcome

Named restaurant, manufacturer, and packaged-food products that USDA (FTY-044)
and Open Food Facts (FTY-060) cannot resolve are costed from official sources:
the estimator runs the sanitized search adapter (FTY-079), fetches the candidate
pages through the hardened fetcher (FTY-078), validates the extracted facts with
backend schemas and deterministic calculators, and writes those facts with source
provenance — never raw pages. When the search provider is disabled or
unavailable, named products fall through to a model-prior estimate that carries an
explicit source status and assumptions, never a silent guess.

## Scope

- Add an **official-source resolution step** against FTY-040's pipeline-step
  interface that runs **only** for the evidence-retrieval Lookup Rule candidate
  types not already resolved upstream: named packaged products, named restaurant
  items, and manufacturer products. Generic foods stay on USDA (FTY-044);
  barcodes stay on Open Food Facts (FTY-060). Document the ordering so this step
  is the **last resort before model-prior** in the pipeline.
- **Orchestrate FTY-079 search + FTY-078 fetch:** call the search adapter for the
  targeted candidate, hand its result URLs to the hardened fetcher, and take the
  sanitized inert text back for extraction. This story owns the orchestration and
  evidence write — the SSRF/egress boundary lives in FTY-078 and the search
  boundary in FTY-079.
- Treat fetched/searched/extracted/LLM content as **untrusted** until validated
  by backend schemas and recomputed by the deterministic calculators (reuse
  FTY-044 serving math for grams → calories/macros).
- On a confident match, write a resolved **`derived_food_items`** row
  (calories/macros + source reference) and an **`evidence_sources`** row: source
  URL, fetched timestamp, content hash, and the extracted per-100g / per-serving
  facts snapshot — **never raw pages** (per `data-retention.md`). Record provider
  name, tool names, source references, assumptions, and sanitized traces on the
  estimation run.
- When the provider is **disabled, unavailable, or returns no confident match**,
  route to model-prior **with** explicit source status + assumptions so the entry
  stays user-editable (per the evidence-retrieval Lookup Rule).

## Non-Goals

- The **hardened fetcher / SSRF egress policy** (FTY-078) and the **search-provider
  adapter** (FTY-079) — this story consumes both, it does not define them.
- Barcode lookup (FTY-060) and nutrition-label image extraction (FTY-061).
- Generic-food USDA resolution (FTY-044, the upstream resolver this falls through
  from).
- Recipe / multi-ingredient calculation and complex portion inference.
- Crawling or multi-page traversal (the fetcher retrieves only the allowlisted
  result URLs, per FTY-078).

## Contracts

- The **search + fetch pipeline step output** written onto `derived_food_items`
  (calories/macros + source reference), plugging into FTY-040's pipeline-step
  interface and status transitions (`estimation-jobs.md`) and consuming FTY-042
  unresolved candidates (`parse-candidates.md`).
- The **source-status values** surfaced to clients for official-source-resolved vs
  model-prior-fallback entries (consuming the FTY-079 / FTY-045 status vocabulary;
  this story does not redefine it).
- `evidence_sources` reuse (and any **additive** migration if a new `source_type`
  / per-serving snapshot column is needed) per `food-resolution.md`.

## Security / Privacy

The estimator gets no open-ended network access; all egress flows through the
backend tools defined in FTY-078 (fetch) and FTY-079 (search). This story keeps
those guarantees intact at the orchestration + persistence layer.

- **No-raw-page retention.** `evidence_sources` stores URL, timestamp, content
  hash, and extracted facts only — never the raw page (per `data-retention.md`).
- **Untrusted-until-validated.** All fetched/searched/extracted/LLM content is
  validated against backend schemas and recomputed by deterministic calculators
  before persistence.
- **Egress only via FTY-078/FTY-079.** This step issues no network calls of its
  own; it cannot bypass the hardened fetcher's SSRF policy or the adapter's query
  sanitization.
- **Model-prior fallback carries status, never a silent guess.**
- Rated **high**: it drives the official-source egress path and persists evidence;
  the SSRF and data-minimization surfaces are mitigated upstream in FTY-078/079
  but the orchestration must not reintroduce them.

## Acceptance Criteria

- A named restaurant/manufacturer/packaged product unresolved by USDA/OFF resolves
  to `derived_food_items` with calories/macros via the stubbed FTY-079 search +
  FTY-078 fetch, with schema-validated facts and stored provenance
  (`evidence_sources`: URL, timestamp, content hash, extracted-facts snapshot; no
  raw page).
- The official-source step runs **only** for the targeted candidate types and only
  after USDA/OFF miss, as the last resort before model-prior; ordering is
  documented.
- With the provider **disabled or unavailable** (FTY-079 reports it), named
  products fall through to model-prior **with** explicit source status +
  assumptions — never a silent guess.
- A test proves this step issues no direct network egress: search goes through the
  FTY-079 adapter and fetch through the FTY-078 hardened fetcher.
- If `evidence_sources` schema changes, the **additive** migration applies and
  rolls back against a throwaway database.
- `make verify` passes with the stubbed search + fetch.

## Verification

- `make verify` with a stubbed FTY-079 search provider and stubbed FTY-078
  fetcher, including:
  - an end-to-end named-product resolution test (search → fetch → extract →
    schema-validate → serving math → `derived_food_items` + `evidence_sources`);
  - an ordering test (runs only for targeted types, only after USDA/OFF miss, last
    before model-prior);
  - a disabled-provider test asserting model-prior-with-status fallback;
  - a no-direct-egress test asserting all network goes through FTY-078/FTY-079.
- Apply / roll back any additive `evidence_sources` migration against a throwaway
  database.

## Planning Notes

- The adversarial SSRF negative suite and the query-sanitization/data-minimization
  proofs now live in **FTY-078** and **FTY-079** respectively; this story relies on
  those boundaries rather than re-testing them, and only proves it does not bypass
  them.
- Search-provider billing / hosted-service model remains **deferred** (consistent
  with FTY-045 / FTY-079 non-goals).
- This story is independent of FTY-060/061 and falls through from FTY-044's
  resolver, reusing its serving math.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — trigger candidate types, ordering
  (last resort before model-prior), and fallback semantics are resolved; the
  fetcher and adapter decisions are settled in FTY-078/FTY-079.
- **Cross-lane impact:** estimator (pipeline + evidence orchestration) +
  backend-core (calculators, persistence, additive migration). One touched lane;
  the SSRF/fetch and search-adapter big rocks moved to FTY-078/FTY-079.
- **Security/privacy risk:** high — it drives the official-source egress path and
  persists evidence; mitigated by routing all egress through FTY-078/FTY-079,
  untrusted-until-validated handling, no-raw-page retention, and
  model-prior-with-status fallback.
- **Verification path:** `make verify` with stubbed search + fetch (end-to-end
  resolution, ordering, disabled-provider fallback, no-direct-egress) + additive
  migration rollback.
- **Assumptions safe for autonomy:** yes — gated behind FTY-078 + FTY-079, which
  the steward enforces via dependencies before assigning this story.
- **Sizing:** 1 touched lane, 5 review_focus, 7 requires_context — within the
  scope guardrail after the split. Deliberately narrowed from the former
  three-lane, three-big-rock story that tripped the circuit breaker.
