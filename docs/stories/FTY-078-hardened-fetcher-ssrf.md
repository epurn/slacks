---
id: FTY-078
state: merged
primary_lane: security-privacy
touched_lanes:
  - backend-core
risk: high
tags:
  - fetch
  - ssrf
  - security
  - evidence
approved_dependencies: []
requires_context:
  - docs/architecture/evidence-retrieval.md
  - docs/contracts/food-resolution.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
review_focus:
  - ssrf-egress-hardening
  - redirect-size-timeout-content-type-limits
  - active-content-stripping
  - content-free-errors
  - allowlist-fail-closed
autonomous: true
---

# FTY-078: Hardened Fetcher + SSRF Egress Policy for Official Sources

## State

ready

## Lane

security-privacy

## Dependencies

- FTY-044 (extends/reuses the existing `hardened_fetch` SSRF policy)

## Outcome

A hardened fetcher exists that retrieves an allowlisted public official-source
page and returns sanitized, active-content-stripped text for downstream
extraction — and refuses everything else fail-closed. This is the SSRF /
egress-boundary prerequisite for official-source resolution (FTY-062); it ships
no search adapter and no resolution pipeline of its own. It extends FTY-044's
`hardened_fetch` so official-source fetches and USDA fetches share one audited
egress boundary.

## Scope

- Extend / reuse FTY-044's `hardened_fetch` so it can fetch the small set of
  **allowlisted public official-source URLs** (HTTPS only). No crawling, no
  multi-page traversal, no open-ended browsing — only the explicit result URLs
  handed to it.
- Enforce, fail-closed, the full SSRF egress policy before and across the
  request:
  - **HTTPS + public-IP only.** Resolve the target and block loopback, private,
    link-local (incl. cloud metadata `169.254.169.254`), multicast, reserved,
    and unspecified addresses; non-HTTPS and `file:`/other schemes are refused.
  - **Allowlist.** Only configured official-source hosts are reachable; anything
    off-allowlist fails closed.
  - **Redirects** are refused or re-validated against the full policy (no
    redirect to a private/off-allowlist target).
  - **Size, timeout, and content-type limits** are bounded; non-allowed content
    types fail closed.
- **Strip scripts and active content** from the fetched body before returning
  it, so downstream extraction only ever sees inert text.
- **Content-free errors.** Fetch error messages never include the URL, request
  headers, request body, or response body.
- Expose the configured allowlist/limits through health/config diagnostics so
  operators can see the egress policy without reading code.

## Non-Goals

- The **search-provider adapter** and query sanitization (FTY-079).
- The **official-source resolution pipeline step**, evidence extraction,
  `derived_food_items`/`evidence_sources` writes, and model-prior fallback
  (FTY-062).
- Barcode/OFF fetch (FTY-060) and nutrition-label image extraction (FTY-061).
- Any change to FTY-044's USDA resolution behavior beyond the shared fetch
  boundary.

## Contracts

- The **hardened-fetch allowlist / SSRF policy** for official pages: HTTPS-only,
  public-IP-only, host allowlist, redirect re-validation, size/timeout/
  content-type limits, active-content stripping, content-free errors. Documented
  alongside FTY-044's fetch boundary in `food-resolution.md`.

## Security / Privacy

This is the egress trust boundary for official-source retrieval; it is the
system's largest SSRF surface.

- **SSRF defenses.** Targets must be HTTPS, on the configured allowlist, and
  resolve to public IPs only; loopback/private/link-local (incl. metadata
  `169.254.169.254`)/multicast/reserved/unspecified are blocked; redirects are
  refused or re-validated; time, size, and content type are bounded and fail
  closed.
- **Active-content stripping.** Scripts and active content are removed before the
  body is returned; the fetcher returns inert text only.
- **Content-free errors.** Error messages never include the URL, headers, request
  body, or response body.
- Rated **high**: a new external fetch egress path and the system's largest SSRF
  surface.

## Acceptance Criteria

- A fetch of an allowlisted HTTPS official-source URL returns sanitized,
  active-content-stripped text (stubbed network).
- The adversarial SSRF/allowlist negative suite is all blocked fail-closed:
  private / loopback / link-local / cloud-metadata (`169.254.169.254`) IPs,
  `file:` and non-HTTPS schemes, off-allowlist host, redirect-to-private,
  oversize body, and disallowed content type.
- Fetch error messages are **content-free** (no URL, headers, request body, or
  response body).
- FTY-044's existing USDA fetch behavior is unchanged (shared boundary, no
  regression).
- `make verify` passes with a stubbed fetcher / stubbed network.

## Verification

- `make verify` with a stubbed fetcher, including:
  - the allowlisted happy-path fetch → sanitized inert text;
  - the heaviest adversarial SSRF/allowlist negative suite (private/loopback/
    link-local/metadata IPs, `file:`/non-HTTPS schemes, off-allowlist host,
    redirect-to-private, oversize body, disallowed content type) — all
    fail-closed;
  - a content-free-error assertion;
  - a regression check that FTY-044 USDA fetch still passes.

## Readiness Sanity Pass

- **Product decision gaps:** none — extends an established `hardened_fetch`
  policy; allowlist + limits are config-driven.
- **Cross-lane impact:** security-privacy (egress policy) + backend-core (fetch
  implementation). One touched lane.
- **Security/privacy risk:** high — the largest SSRF surface; mitigated by
  HTTPS+public-IP allowlisting, redirect re-validation, bounded size/timeout/
  content-type, active-content stripping, and content-free errors.
- **Verification path:** `make verify` with a stubbed fetcher and the adversarial
  SSRF negative suite; FTY-044 fetch regression check.
- **Assumptions safe for autonomy:** yes — fetch-only boundary; the search
  adapter (FTY-079) and the resolution pipeline (FTY-062) are separate stories.
- **Sizing:** 1 touched lane, 5 review_focus, 5 requires_context — within the
  scope guardrail. Carved out of the former oversized FTY-062 as the SSRF/fetch
  big rock so the resolution pipeline depends on a hardened boundary.
