---
id: FTY-044
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
  - usda
  - calculator
approved_dependencies: []
requires_context:
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-044: Generic Food Calculator

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-042

## Outcome

Simple generic food candidates resolve into derived food items with calories and macros, sourced from USDA FoodData Central, with deterministic serving math and stored source evidence.

## Scope

- Implement resolution of generic food candidates (from FTY-042) into `derived_food_items` with calories and macros.
- Query **USDA FoodData Central** (configurable API key) for generic foods through a hardened, allowlisted client (timeouts, SSRF protections, sanitized queries — no personal context sent).
- Store retrieved facts as source evidence (`evidence_sources`) and cache generic foods (`products`) to avoid repeat lookups; migrate these tables here.
- Compute calories/macros deterministically from canonical per-100g facts and the candidate's quantity; store canonical units (kcal, grams).
- Record the source (per the source hierarchy: trusted nutrition database) and a content reference/hash; do not store raw pages.
- For quantities that can't be resolved to grams/servings confidently, route deterministically (failed or needs_clarification) per FTY-042 conventions.

## Non-Goals

- User nutrition-label or barcode evidence (Milestone 6, higher in the source hierarchy).
- Restaurant/manufacturer official-source lookups and recipe calculation (later).
- Complex portion inference / `portion_memories` (later).
- Saved foods/aliases (Milestone 5).

## Contracts

- `evidence_sources` and `products` table + DTO contracts; the food-resolution output (calories/macros + source reference) written onto `derived_food_items`.
- The USDA FDC client config (env var names) and the hardened-fetch/allowlist policy.
- The serving/quantity → grams resolution rule.

## Security / Privacy

External calls go only to the allowlisted USDA FDC endpoint through a hardened client with timeouts and SSRF protections; queries are sanitized so no personal context leaves the system. The FDC key is read from env, never exposed to clients or logged. Evidence storage follows data-retention: store source reference, timestamp, content hash, and extracted facts — not raw pages. Global source facts (`products`) carry no user-specific data, kept separate from user habits. Rated high: external API trust boundary, evidence retention, contracts, and migrations.

## Acceptance Criteria

- A generic food candidate resolves to `derived_food_items` with calories and macros computed deterministically from canonical per-100g facts.
- USDA FDC is queried through the hardened, allowlisted client; the key is env-configured and never logged; queries carry no personal context.
- Retrieved facts are stored as `evidence_sources` (with source reference/hash) and cached as `products`; raw pages are not stored.
- Unresolvable quantities route deterministically (failed/needs_clarification), not guessed.
- Migrations apply and roll back; user-owned vs global records are correctly separated.
- `make verify` passes (deterministic serving-math tests, a stubbed-FDC integration test, and an SSRF/allowlist negative test).

## Verification

- Run `make verify` with a stubbed FDC client, including serving-math unit tests and an SSRF/allowlist negative test.
- Hand-verify serving math against known USDA per-100g facts.
- Apply/roll back the `evidence_sources` / `products` migrations.

## Planning Notes

- Whether to ship a small bundled fallback dataset for offline self-host is deferred; v1 assumes a self-hoster supplies a free FDC key.
- The quantity → grams resolution scope is intentionally simple in v1 (grams, milliliters, or count × default serving); richer portion inference is later.

## Readiness Sanity Pass

- Product decision gaps: none blocking — USDA FDC API + cached evidence + deterministic serving math resolved.
- Cross-lane impact: completes generic-food calories/macros feeding daily summaries; establishes evidence/product contracts reused by Milestone 6.
- Security/privacy risk: high; external API + evidence retention, mitigated by allowlisted hardened client, sanitized queries, env-only key, and no-raw-page retention.
- Verification path: `make verify` with stubbed FDC + SSRF negative test + migration rollback.
- Assumptions safe for autonomy: yes; offline-fallback and portion scope are documented deferrals (notes).
