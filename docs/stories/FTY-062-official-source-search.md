---
id: FTY-062
state: ready_with_notes
primary_lane: security-privacy
touched_lanes:
  - estimator
  - contracts
  - backend-core
review_focus:
  - ssrf-egress-hardening
  - query-sanitization-data-minimization
  - evidence-retention-no-raw-pages
  - untrusted-content-validation
  - migration-rollback
risk: high
tags:
  - evidence
  - estimator
  - search
  - fetch
  - ssrf
  - security
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/contracts/parse-candidates.md
  - docs/contracts/estimation-jobs.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-062: Official Source Search

## State

ready_with_notes

## Lane

security-privacy

## Dependencies

- FTY-040
- FTY-044
- FTY-045

## Outcome

Named restaurant, manufacturer, and packaged-food products that USDA (FTY-044)
and Open Food Facts (FTY-060) cannot resolve are costed from official sources:
the estimator runs a sanitized web search and a hardened fetcher against
allowlisted public pages, extracts nutrition facts, and stores those facts with
source provenance — never raw pages. When the search provider is disabled or
unavailable, named products fall through to a model-prior estimate that carries
an explicit source status and assumptions, never a silent guess.

## Scope

- Add an official-source resolution step that runs only for the
  evidence-retrieval Lookup Rule candidate types not already resolved upstream:
  named packaged products, named restaurant items, and manufacturer products.
  Generic foods stay on USDA (FTY-044); barcodes stay on Open Food Facts
  (FTY-060). Document the ordering so search is the **last resort before
  model-prior** in the pipeline.
- Introduce a **pluggable search-provider adapter** with **Brave Search** as the
  initial/default adapter, configured through `FATTY_SEARCH_*` env vars. The
  provider is **disabled by default** for self-host (no bundled key). Surface
  availability explicitly in health/config diagnostics and in estimation source
  status.
- Implement the **hardened fetcher** (extending / reusing the FTY-044
  `hardened_fetch` SSRF policy): sanitize queries before search; send **no**
  personal profile or food-history context to the search provider; fetch
  allowlisted public HTTP(S) URLs only; block private network, localhost, file,
  and cloud-metadata (`169.254.169.254`) targets; enforce redirect, size,
  timeout, and content-type limits; strip scripts and active content before
  extraction.
- Treat fetched pages, search results, extracted text, and LLM output as
  **untrusted** until validated by backend schemas and the deterministic
  calculators (reuse FTY-044 serving math for grams → calories/macros).
- Store extracted evidence in `evidence_sources`: source URL, fetched timestamp,
  content hash, and the extracted per-100g / per-serving facts snapshot — never
  raw pages (per `data-retention.md`). Record provider name, tool names, source
  references, assumptions, and sanitized traces on the estimation run.
- When the provider is disabled, unavailable, or returns no confident match,
  route to model-prior **with** explicit source status + assumptions so the
  entry stays user-editable (per the evidence-retrieval Lookup Rule).

## Non-Goals

- Barcode lookup (FTY-060) and nutrition-label image extraction (FTY-061).
- Generic-food USDA resolution (FTY-044, the upstream resolver this falls
  through from).
- Recipe / multi-ingredient calculation and complex portion inference.
- A hosted-service billing model for search providers (deferred; see notes).
- Crawling, multi-page traversal, or open-ended browsing — the fetcher retrieves
  only the small set of allowlisted result URLs.

## Contracts

- The **search-provider adapter** config (`FATTY_SEARCH_*` env var names),
  capability/availability surface, and the disabled/unavailable/rate-limited/
  failed/partial/success statuses (aligned with FTY-045).
- The **hardened-fetch allowlist / SSRF policy** for official pages (HTTPS-only,
  public-IP-only, redirect/size/timeout/content-type limits, active-content
  stripping).
- The **search + fetch pipeline step output** written onto
  `derived_food_items` (calories/macros + source reference), plugging into
  FTY-040's pipeline-step interface and status transitions
  (`estimation-jobs.md`) and consuming FTY-042 unresolved candidates
  (`parse-candidates.md`).
- The **source-status values** surfaced to clients for official-source resolved
  vs model-prior-fallback entries.
- `evidence_sources` reuse (and any additive migration if a new `source_type` /
  per-serving snapshot column is needed) per `food-resolution.md`.

## Security / Privacy

This is the security story for evidence retrieval. The estimator gets no
open-ended network access; all egress flows through backend tools.

- **SSRF defenses.** Search results and fetch targets must be HTTPS, on the
  configured allowlist, and resolve to public IPs only; loopback, private,
  link-local (incl. cloud metadata `169.254.169.254`), multicast, reserved, and
  unspecified addresses are blocked; redirects are refused or re-validated; time
  and size are bounded; non-allowed content types fail closed.
- **Query sanitization / data minimization.** Only a sanitized product/restaurant
  name is sent to the search provider — never profile, weight, history, event
  metadata, or any personal context.
- **Egress allowlisting.** Only the configured search endpoint and allowlisted
  official-source hosts are reachable.
- **No-raw-page retention.** `evidence_sources` stores URL, timestamp, content
  hash, and extracted facts only — never the raw page (per `data-retention.md`).
- **Secret handling.** The search API key is read from env only, never exposed
  to clients, never logged, and carried in a header (never the query string).
- **Content-free errors.** Fetch/search error messages never include the URL,
  headers, request body, or response body.
- **Untrusted-until-validated.** All fetched/searched/extracted/LLM content is
  validated against backend schemas and recomputed by deterministic calculators
  before persistence.

Rated **high**: a new external search + fetch egress path is the system's
largest SSRF / data-exfiltration surface, and it touches contracts, evidence
retention, and migrations.

## Acceptance Criteria

- A named restaurant/manufacturer/packaged product unresolved by USDA/OFF
  resolves to `derived_food_items` with calories/macros via stubbed search +
  fetch, with schema-validated facts and stored provenance
  (`evidence_sources`: URL, timestamp, content hash, extracted facts snapshot;
  no raw page).
- The official-source step runs **only** for the targeted candidate types and
  only after USDA/OFF miss, as the last resort before model-prior; ordering is
  documented.
- SSRF / private-IP / localhost / file / cloud-metadata / redirect-to-private /
  oversize / disallowed-content-type negative tests are all blocked and fail
  closed.
- A query-sanitization test proves no personal context (profile, weight,
  history, event metadata) egresses to the search provider.
- With the provider **disabled or unavailable**, named products fall through to
  model-prior **with** explicit source status + assumptions (never a silent
  guess); availability is reported in health/config diagnostics and source
  status.
- The search API key is env-only, never logged, never sent to clients; error
  messages are content-free.
- If `evidence_sources` schema changes, the migration applies and rolls back
  against a throwaway database.
- `make verify` passes with stubbed search + fetch.

## Verification

- Run `make verify` with a stubbed search provider and stubbed fetcher,
  including:
  - an end-to-end named-product resolution test (search → fetch → extract →
    schema-validate → serving math → `derived_food_items` + `evidence_sources`);
  - the adversarial SSRF/allowlist negative suite (private/loopback/link-local/
    metadata IPs, file/non-HTTPS schemes, redirect-to-private, oversize body,
    disallowed content type) — the heaviest negative suite in the estimator;
  - a query-sanitization test asserting no personal context leaves the system;
  - a disabled-provider test asserting model-prior-with-status fallback and
    diagnostics availability reporting;
  - a key-handling test asserting env-only, unlogged, content-free errors.
- Apply / roll back any `evidence_sources` migration against a throwaway
  database.

## Planning Notes

- **Brave Search is the default adapter but disabled by default** for self-host:
  no key is bundled, so out-of-the-box self-host resolves named products via
  model-prior-with-status. A self-hoster supplies a `FATTY_SEARCH_*` key to
  enable it.
- **Search-provider billing / hosted-service model is deferred** (consistent
  with FTY-045 non-goals); v1 only defines the pluggable adapter + config.
- The adapter is intentionally pluggable so a different search backend can be
  added later without re-deciding the SSRF/fetch boundary.
- This story is independent of FTY-060/061 and can be authored in parallel; it
  falls through from FTY-044's resolver and reuses its `hardened_fetch` and
  serving math.

## Readiness Sanity Pass

- Product decision gaps: none blocking — provider (Brave, pluggable, default
  disabled), trigger candidate types, ordering (last resort before model-prior),
  and fallback semantics are resolved; billing model is a documented deferral.
- Cross-lane impact: adds the official-source egress path to the estimator,
  extends the search/fetch + source-status contracts, and reuses FTY-044
  evidence storage; security-privacy is primary.
- Security/privacy risk: high — new external search + fetch egress is the
  largest SSRF/exfiltration surface; mitigated by HTTPS+public-IP allowlisting,
  query sanitization/data minimization, env-only key, content-free errors,
  untrusted-until-validated handling, and no-raw-page retention.
- Verification path: `make verify` with stubbed search + fetch, a heavy
  adversarial SSRF negative suite, sanitization + disabled-provider + key tests,
  and migration rollback.
- Assumptions safe for autonomy: yes — Brave-default-disabled, self-host
  fallback, and deferred search billing are documented non-blocking notes.
