---
id: FTY-060
state: merged
primary_lane: estimator
touched_lanes:
  - contracts
  - backend-core
  - security-privacy
review_focus:
  - deterministic-serving-math
  - external-api-hardening
  - evidence-retention
  - migration-rollback
risk: high
tags:
  - estimator
  - food
  - barcode
  - open-food-facts
  - evidence
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/contracts/parse-candidates.md
  - docs/contracts/estimation-jobs.md
  - docs/contracts/log-events.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-060: Barcode Lookup (Open Food Facts)

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-040
- FTY-044
- FTY-045

## Outcome

A barcode (UPC/EAN) input resolves into a `derived_food_items` row carrying
calories and macros sourced from Open Food Facts (OFF), with deterministic
serving math and stored source evidence. The barcode source sits **above**
generic USDA lookup in the source hierarchy: a confident OFF product match is a
packaged-product fact and is preferred over a generic USDA estimate for the same
input. This is the backend/estimator slice only — no mobile UI (that is FTY-063).

## Scope

- Resolve a barcode-bearing food candidate into `derived_food_items` with
  calories and macros, reusing the FTY-044 resolution shape (canonical kcal +
  grams, stored evidence, cached product).
- Query **Open Food Facts** (open API; documented rate limits and data-quality
  caveats) through a hardened, allowlisted client built on FTY-044's
  `hardened_fetch` (HTTPS only, allowlisted host, SSRF protections, redirect/
  size/timeout/content-type limits, sanitized queries — no personal context
  sent). OFF is queried by barcode only.
- Map the OFF product response to canonical per-100g (or per-serving) facts:
  energy kcal (required), protein, carbohydrate, total fat; default serving
  grams when OFF supplies a gram/millilitre serving size.
- Store the retrieved facts as user-owned `evidence_sources` provenance and
  cache the product as a **global** `products` row keyed by barcode
  (`source = open_food_facts`, the normalized barcode as the cache key) so a
  repeat scan makes no external call. Store source reference, fetched timestamp,
  content hash, and the extracted per-100g/per-serving facts snapshot — never
  the raw OFF response or page.
- Compute calories/macros deterministically from canonical facts and the
  candidate quantity, reusing FTY-044's serving/quantity → grams rule where
  applicable (mass → grams; volume 1 ml ≈ 1 g → grams; count × default serving
  grams when OFF supplies one).
- Make OFF availability explicit in health/config diagnostics and in the
  estimation source status, and let a self-hoster disable the source.
- Migrate any additive schema this needs (e.g. a barcode key/index on
  `products`) with an apply/rollback path.

## Non-Goals

- Mobile barcode scanning / camera UI and the source-status display (FTY-063).
- Nutrition-label image extraction (FTY-061) and official restaurant/manufacturer
  source search (FTY-062).
- Recipe calculation, complex portion inference / `portion_memories`, and saved
  foods/aliases (Milestone 5).
- Changing the FTY-044 USDA path; this adds a higher-priority source above it,
  it does not redefine generic-food resolution math.

## Contracts

- The **barcode-resolution pipeline step** and the food-resolution output
  (calories/macros + source reference) it writes onto `derived_food_items`,
  plugged into FTY-040's pipeline-step interface and FTY-030/FTY-042 status
  transitions; documented as a versioned addition to
  `docs/contracts/food-resolution.md` (the source hierarchy: OFF barcode above
  USDA generic).
- The **Open Food Facts client** config (`FATTY_OFF_*` env var names: base URL,
  timeout, optional rate-limit/user-agent settings, and an enable/disable flag)
  and the hardened-fetch/allowlist policy it reuses.
- How `products` rows are **keyed by barcode** for the OFF source (cache key =
  normalized barcode under `source = open_food_facts`), and the additive
  migration that adds any new column/index this requires.
- The OFF product → canonical-facts mapping and the serving/quantity → grams
  reuse from FTY-044.

## Security / Privacy

- External calls go only to the allowlisted OFF endpoint through the hardened
  client (HTTPS only, host allowlist, every resolved IP required public —
  loopback/private/link-local incl. `169.254.169.254`, multicast, reserved,
  unspecified blocked — redirects refused, bounded time/size/content-type). A
  non-https or non-allowlisted target fails closed.
- A barcode carries no personal context, but enforce data minimization anyway:
  only the normalized barcode is sent; no profile, weight, history, or event
  metadata leaks to OFF. Queries are sanitized.
- No raw OFF response/page is retained: `evidence_sources` stores source
  reference (`open_food_facts:<barcode>`), content hash, fetched timestamp, and
  the extracted facts snapshot; `products` holds global source facts only (no
  user data). Per `docs/security/data-retention.md`.
- No secret/PII logging: fetch error messages never include URL, headers,
  request body, or response body; the OFF response is untrusted until it
  validates against the response schema. (OFF needs no secret key; if a
  user-agent/contact string is configured it is non-secret config.)
- Rated **high**: external API trust boundary, evidence retention, contracts,
  and migrations.

## Acceptance Criteria

- A barcode-bearing food candidate resolves to `derived_food_items` with
  calories and macros computed deterministically from canonical OFF facts and
  the candidate quantity.
- OFF is queried by barcode through the hardened, allowlisted client; no
  personal context leaves the system; the source is configurable and can be
  disabled by a self-hoster, with availability surfaced in health/config and
  estimation source status.
- A confident OFF product match is preferred over generic USDA lookup for the
  same input (source hierarchy: barcode above generic).
- Retrieved facts are stored as `evidence_sources` (source reference + content
  hash + fetched timestamp + facts snapshot) and cached as a `products` row
  keyed by barcode; a repeat scan makes no external call; raw responses/pages
  are not stored.
- A barcode OFF cannot resolve (no match, or insufficient/low-quality facts —
  e.g. no energy value) routes deterministically to `needs_clarification` or
  `failed` per the FTY-042/log-events state machine; it is **never** finalized
  from a guessed model-prior value while the source is available. Model-prior is
  allowed only when the source is unavailable/disabled, and then the entry
  retains source status + assumptions so the user can edit it.
- An unresolvable quantity routes deterministically (not guessed), per FTY-044.
- The additive migration applies and rolls back; global `products` vs user-owned
  `evidence_sources` ownership is correctly separated.
- `make verify` passes, including the tests below.

## Verification

- Run `make verify` with a stubbed OFF client, including:
  - deterministic serving-math / macro-scaling unit tests (mass, volume, count ×
    default serving, and an unresolvable quantity → `needs_clarification`);
  - a stubbed-OFF integration test for the resolve + cache + evidence-write path
    (including a cache hit that makes no external call, and a no-match/no-energy
    case routing to `needs_clarification`/`failed`);
  - an SSRF / allowlist negative test proving a non-https or non-allowlisted OFF
    target fails closed;
  - a source-hierarchy test proving a confident OFF match wins over generic USDA
    for the same input;
  - a privacy test proving only the normalized barcode is sent (no personal
    context) and that no raw response is persisted.
- Apply and roll back the additive migration (barcode key/index on `products`)
  against a throwaway database.
- Hand-verify the computed calories/macros against a known barcode's published
  OFF facts (public data, cite/store source metadata per testing standards).

## Planning Notes

- OFF data quality is uneven: products may lack energy or macros, or carry
  per-serving-only facts. The step treats missing/low-quality facts as a
  non-match and routes deterministically rather than guessing. The exact
  data-quality threshold (e.g. require energy kcal; macros default to 0 when
  absent, mirroring FTY-044) is a documented tunable.
- OFF rate limits and etiquette (identifying user-agent) are honored via config;
  the cache-first lookup keeps external calls minimal.
- per-serving vs per-100g handling: prefer per-100g canonical storage; when OFF
  supplies only per-serving facts plus a gram serving size, convert to per-100g
  for canonical storage. If neither a per-100g basis nor a gram serving size is
  derivable, treat as a non-match (route deterministically).
- Whether to add a dedicated `barcode` column on `products` or reuse the
  existing `query_key` slot for the normalized barcode is an implementation
  choice; either way it must stay additive and reversible.

## Readiness Sanity Pass

- Product decision gaps: none blocking — OFF as the barcode source, source
  hierarchy above USDA generic, cache-by-barcode, deterministic fallback, and
  self-host disable are all resolved.
- Cross-lane impact: extends the FTY-044 evidence/product contracts with a
  higher-priority barcode source; backend/estimator only — mobile scanning/UI is
  FTY-063; depends on FTY-040 (pipeline step), FTY-044 (products/evidence tables
  + hardened-client pattern), FTY-045 (evidence retrieval contract).
- Security/privacy risk: high; external API trust boundary + evidence retention,
  mitigated by the allowlisted hardened client, barcode-only sanitized queries,
  no-raw-response retention, and no secret/PII logging.
- Verification path: `make verify` with stubbed OFF + SSRF/allowlist negative
  test + source-hierarchy test + migration apply/rollback + hand-verify against
  a known barcode.
- Assumptions safe for autonomy: yes; OFF availability and data-quality handling
  are documented non-blocking notes (hence `ready_with_notes`).
