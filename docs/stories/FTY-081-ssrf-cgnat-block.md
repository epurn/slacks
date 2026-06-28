---
id: FTY-081
state: merged
primary_lane: security-privacy
touched_lanes:
  - backend-core
risk: high
tags:
  - fetch
  - ssrf
  - security
  - egress
approved_dependencies:
  - FTY-078
requires_context:
  - docs/contracts/food-resolution.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/standards/testing-standards.md
review_focus:
  - is-global-public-address-check
  - cgnat-rfc6598-blocked-fail-closed
  - no-regression-existing-ssrf-suite
autonomous: true
---

# FTY-081: Block RFC 6598 CGNAT Space in the SSRF Public-Address Check

## State

ready

## Lane

security-privacy

## Dependencies

- FTY-078 (hardens the `hardened_fetch` SSRF egress policy this corrects)

## Outcome

The hardened fetcher's public-address check is allowlist-by-property rather than
denylist-by-category, so carrier-grade-NAT space (RFC 6598, `100.64.0.0/10`) and
any other non-global range can no longer slip through as "public." This closes a
release-audit SSRF finding on the system's largest egress surface.

## Scope

- In `app/estimator/hardened_fetch.py`, change `_is_public_address()` to **accept
  an address only when it is globally routable** (`ip_address(...).is_global`),
  instead of rejecting an enumerated set of categories (`is_private`,
  `is_loopback`, `is_link_local`, `is_reserved`, `is_multicast`, `is_unspecified`).
  Requiring `is_global` is fail-closed by construction: any range not globally
  routable — including RFC 6598 CGNAT (`100.64.0.0/10`) — is rejected.
- Keep the existing behavior intact: the check still runs on **every** resolved
  IP (all A/AAAA records), still runs **before any socket opens**, still applies
  across all transport verbs, and still produces content-free errors.
- Promote the existing `xfail` regression test
  (`test_cgnat_shared_space_should_be_blocked_finding` in
  `backend/tests/security/test_ssrf_egress.py`) to a passing assertion that CGNAT
  resolution is blocked fail-closed. Remove the `xfail` marker.

## Non-Goals

- Any change to the allowlist mechanism, redirect handling, size/timeout/
  content-type limits, or active-content stripping (all FTY-078, unchanged).
- The search adapter (FTY-079) or resolution pipeline (FTY-062).
- New egress paths or new providers.

## Contracts

- None changed. The SSRF/egress policy documented in `food-resolution.md`
  (HTTPS-only, public-IP-only, allowlist, bounded limits) is unchanged in intent;
  "public IP" is simply tightened to mean "globally routable." If that doc
  enumerates blocked categories, add CGNAT/non-global to the description.

## Security / Privacy

This is the system's largest SSRF surface. The current check denylists known-bad
categories and so admits any range it forgot to name; RFC 6598 CGNAT
(`100.64.0.0/10`) is the concrete gap — an attacker controlling a DNS record could
resolve a target into carrier-internal space. Switching to a positive
`is_global` requirement is the standard fail-closed posture: unknown/new
non-global ranges are denied by default rather than admitted.

Rated **high**: it is a direct hardening of the primary SSRF boundary.

## Acceptance Criteria

- `_is_public_address()` returns true only for globally routable addresses;
  RFC 6598 CGNAT (`100.64.0.0/10`, e.g. `100.64.0.1`) is rejected fail-closed.
- The previously-`xfail` CGNAT test now passes as a positive assertion (marker
  removed), and the full existing SSRF adversarial suite (loopback, private,
  link-local/metadata, multicast, reserved, broadcast, IPv6 variants, mixed
  public/private resolution, DNS failure, all transport verbs) still passes
  unchanged.
- A genuinely public address (e.g. a normal global IP) still resolves and fetches
  as before — no false-positive regression on the allowlisted happy path.
- Error messages remain content-free.
- `make verify` passes (stubbed network).

## Verification

- `make verify` with the security suite, asserting:
  - CGNAT (`100.64.0.0/10`) blocked fail-closed before any socket opens;
  - the full pre-existing SSRF negative suite still all-blocked (no regression);
  - an allowlisted global-IP happy-path fetch still succeeds;
  - content-free-error assertion intact.

## Readiness Sanity Pass

- **Product decision gaps:** none — a one-line policy tightening with a test
  already written (currently `xfail`).
- **Cross-lane impact:** security-privacy (policy) + backend-core (implementation).
  One touched lane.
- **Security/privacy risk:** high — hardens the primary SSRF boundary; fail-closed
  by switching denylist→allowlist-by-property.
- **Verification path:** `make verify` + the existing adversarial SSRF suite with
  the CGNAT test flipped to passing.
- **Assumptions safe for autonomy:** yes — the fix shape and the regression test
  are both already present in the repo.
- **Sizing:** 1 touched lane, 3 review_focus, 4 requires_context — within the
  scope guardrail. Single-file change plus a test marker flip.
