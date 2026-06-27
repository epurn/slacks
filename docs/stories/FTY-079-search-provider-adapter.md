---
id: FTY-079
state: merged
primary_lane: contracts
touched_lanes:
  - backend-core
risk: high
tags:
  - search
  - provider
  - contracts
  - data-minimization
approved_dependencies: []
requires_context:
  - docs/contracts/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
review_focus:
  - search-provider-contract
  - config-env-key-handling
  - capability-availability-surface
  - status-values-alignment
  - query-sanitization-data-minimization
autonomous: true
---

# FTY-079: Pluggable Search-Provider Adapter (Brave Default, Disabled by Default)

## State

ready

## Lane

contracts

## Dependencies

- FTY-045 (evidence-retrieval contract: provider/status/fallback vocabulary)

## Outcome

A pluggable search-provider adapter contract exists, with **Brave Search** as the
default adapter and **disabled by default** for self-host (no bundled key). It
takes a sanitized query and returns candidate result URLs plus an explicit
availability/status, sending **no personal context** to the provider. This is the
search-boundary prerequisite for official-source resolution (FTY-062); it ships
no fetcher and no resolution pipeline of its own.

## Scope

- Define a **pluggable search-provider adapter** interface with **Brave Search**
  as the initial/default adapter, configured through **`FATTY_SEARCH_*`** env
  vars. A different search backend can be added later without re-deciding the
  boundary.
- **Disabled by default** for self-host: no key is bundled, so out of the box the
  adapter reports unavailable and callers (FTY-062) fall through to
  model-prior-with-status. A self-hoster supplies a `FATTY_SEARCH_*` key to
  enable it.
- Surface a **capability/availability** signal and the explicit status values —
  `disabled`, `unavailable`, `rate-limited`, `failed`, `partial`, `success` —
  aligned with the FTY-045 evidence-retrieval status/fallback vocabulary, and
  reflected in health/config diagnostics.
- **Query sanitization / data minimization.** Only a sanitized product /
  restaurant / manufacturer name is sent to the provider — never profile, weight,
  food history, event metadata, or any personal context. The sanitizer is the
  single chokepoint the query passes through before egress.
- **Secret handling.** The search API key is read from env only, never exposed to
  clients, never logged, and carried in a request header (never in the query
  string).
- **Content-free errors.** Search error messages never include the query, key,
  headers, or response body.

## Non-Goals

- The **hardened fetcher / SSRF egress policy** for the result URLs (FTY-078) —
  this adapter returns candidate URLs; it does not fetch them.
- The **official-source resolution pipeline step**, evidence extraction,
  `derived_food_items`/`evidence_sources` writes, and model-prior fallback
  (FTY-062).
- A hosted-service billing model for search providers (deferred, consistent with
  FTY-045 non-goals); v1 defines only the pluggable adapter + config.
- Barcode/OFF (FTY-060) and label image extraction (FTY-061).

## Contracts

- The **search-provider adapter** contract: `FATTY_SEARCH_*` config (incl. the
  default-disabled posture), the capability/availability surface, the
  `disabled/unavailable/rate-limited/failed/partial/success` status values
  (aligned with FTY-045), the sanitized-query input, and env-only key handling.
  Documented against the evidence-retrieval contract.

## Security / Privacy

- **Query sanitization / data minimization.** Only a sanitized name egresses;
  profile, weight, history, and event metadata never reach the provider. A test
  proves no personal context leaves the system.
- **Egress allowlisting.** Only the configured search endpoint is reachable from
  the adapter.
- **Secret handling.** Key is env-only, never logged, never sent to clients,
  carried in a header (never the query string).
- **Content-free errors.** No query, key, headers, or response body in error
  messages.
- Rated **high**: a public provider/contract surface plus a new external egress
  channel and a data-minimization boundary.

## Acceptance Criteria

- A stubbed adapter returns candidate result URLs plus a `success`/`partial`
  status for a sanitized query (no real provider calls).
- With **no `FATTY_SEARCH_*` key configured**, the adapter reports `disabled` /
  unavailable, and availability is reflected in health/config diagnostics.
- A **query-sanitization test** proves no personal context (profile, weight,
  history, event metadata) egresses to the provider; only the sanitized name is
  sent.
- The status values map cleanly onto the FTY-045 vocabulary
  (`disabled/unavailable/rate-limited/failed/partial/success`).
- A **key-handling test** proves the key is env-only, never logged, never sent to
  clients, and carried in a header (not the query string); error messages are
  content-free.
- `make verify` passes with a stubbed search provider.

## Verification

- `make verify` with a stubbed search provider, including:
  - the stubbed happy-path returning candidate URLs + status;
  - a disabled/unavailable test (no key) asserting diagnostics availability
    reporting;
  - a query-sanitization test asserting no personal context egresses;
  - a key-handling test (env-only, unlogged, not client-exposed, header-carried,
    content-free errors).

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — Brave default, pluggable, disabled by
  default; status vocabulary aligned with FTY-045; billing is a documented
  deferral.
- **Cross-lane impact:** contracts (adapter surface, status values, config) +
  backend-core (adapter implementation). One touched lane.
- **Security/privacy risk:** high — a public adapter surface + a new search egress
  channel; mitigated by query sanitization/data minimization, env-only key,
  content-free errors, and explicit availability statuses.
- **Verification path:** `make verify` with a stubbed search provider; no real
  provider calls in tests.
- **Assumptions safe for autonomy:** yes — adapter-only; the fetcher (FTY-078) and
  the resolution pipeline (FTY-062) are separate stories.
- **Sizing:** 1 touched lane, 5 review_focus, 5 requires_context — within the
  scope guardrail. Carved out of the former oversized FTY-062 as the
  search-provider contract big rock.
