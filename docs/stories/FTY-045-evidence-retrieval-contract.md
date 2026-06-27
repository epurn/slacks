---
id: FTY-045
state: merged
primary_lane: contracts
touched_lanes:
  - estimator
  - backend-core
  - security-privacy
risk: medium
tags:
  - evidence
  - estimator
  - providers
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/architecture/system-overview.md
  - docs/architecture/evidence-retrieval.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
review_focus:
  - source-backed-estimates
  - privacy-boundaries
  - fetch-safety
autonomous: true
---

# FTY-045: Evidence Retrieval Contract

## State

ready_with_notes

## Lane

contracts

## Dependencies

- FTY-010

## Outcome

Fatty has explicit public contracts for source-backed estimation: provider capabilities, evidence records, lookup statuses, and fallback behavior.

## Scope

- Define evidence source records for USDA, Open Food Facts, official web pages, user-provided labels, and model-prior fallback.
- Define provider capability/status contracts for unavailable, disabled, rate-limited, failed, partial, and successful lookups.
- Define normalized nutrition fact fields needed for calories and macros.
- Define official-source search and hardened fetch boundaries at the contract level.
- Document that the estimator must not finalize named products, restaurant items, barcodes, nutrition labels, or generic food lookups from model prior alone when source lookup is available.

## Non-Goals

- Implement provider adapters.
- Implement web fetch or parsing.
- Implement nutrition math.
- Choose a hosted-service billing model for search providers.

## Contracts

- Evidence source schema.
- Provider capability/status schema.
- Normalized nutrition fact schema.
- Search/fetch request and response boundaries.
- Fallback/source status values surfaced to clients.

## Security / Privacy

Contracts must minimize personal context sent to providers. Search queries must avoid body/profile/history details. Fetch contracts must include SSRF, redirect, timeout, size, content-type, and raw-content retention limits.

## Acceptance Criteria

- Evidence retrieval contracts are documented under `docs/contracts/`.
- Contracts cover USDA FoodData Central, Open Food Facts, official web pages, nutrition labels, and model-prior fallback.
- Privacy and fetch-safety constraints are explicit.
- Follow-up implementation stories can build provider adapters without re-deciding source hierarchy or fallback semantics.

## Verification

- Run `make verify`.

## Planning Notes

- USDA FoodData Central requires a data.gov API key.
- Open Food Facts is open data but has rate limits and data-quality caveats.
- Search provider configuration should be pluggable; Brave Search is the initial hosted/default candidate.

## Readiness Sanity Pass

- Product decision gaps: none; source-backed evidence retrieval is now required for v1 when available.
- Cross-lane impact: informs backend provider config, estimator adapters, security tests, and mobile source display.
- Security/privacy risk: medium because this defines web/provider boundaries; reviewers should focus on data minimization and fetch safety.
- Verification path: `make verify`.
- Assumptions safe for autonomy: yes; this is a contract/documentation slice only.
