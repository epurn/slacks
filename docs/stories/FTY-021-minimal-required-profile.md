---
id: FTY-021
state: ready
primary_lane: mobile-core
touched_lanes:
  - security-privacy
review_focus:
  - accessibility
  - nonjudgmental-copy
  - input-validation
risk: medium
tags:
  - profile
  - mobile
  - onboarding
  - privacy
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/standards/coding-standards.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
autonomous: true
---

# FTY-021: Minimal Required Profile

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-013
- FTY-020

## Outcome

The mobile app captures the minimal required profile and persists it through the profile API, so the target calculator has everything it needs.

## Scope

- Build an iOS-first, accessible, compact, nonjudgmental profile capture flow on the mobile app that collects: height, weight, age or birth year, metabolic formula preference, units preference, and timezone.
- The **metabolic formula preference** is the input Mifflin-St Jeor requires for its sex-dependent constant. Present it to the user as a calculation/formula preference (e.g. "metabolic formula" or similar non-clinical wording), **not** as a "biological sex" question. It is required, because RMR cannot be computed without it; offer the two MSJ variants as clearly labeled choices. (This is the roadmap's existing "formula setting" field.)
- Capture units preference (metric/imperial) and timezone; convert user-entered values to canonical units (kg, m) before sending to the API.
- Validate inputs client-side (plausible ranges, required fields) and surface clear, nonjudgmental errors.
- Persist via the FTY-020 profile read/write API for the authenticated user.

## Non-Goals

- The profile persistence model and API (owned by FTY-020).
- The RMR/TDEE/goal calculator (FTY-022).
- Goal entry (target weight/date) — that belongs with the target calculator story.
- Editable history of profile changes, body-fat %, or optional advanced fields.
- Android-specific layout work.

## Contracts

- Consumes the FTY-020 profile DTO and profile read/write API; introduces no new persistence contract.
- The metabolic formula preference enum values must match what FTY-022's calculator maps to the Mifflin-St Jeor constant.

## Security / Privacy

Collects sensitive body data. Only the minimal required fields are captured (data minimization). Values are sent over the authenticated profile API; nothing sensitive is logged on-device beyond what is necessary. Wording for the formula preference must avoid clinical "biological sex" framing per the product decision while remaining accurate enough to drive the calculation. Medium risk (sensitive data, but UI over an already-secured API).

## Acceptance Criteria

- A user can enter height, weight, age/birth year, metabolic formula preference, units preference, and timezone, and save them.
- Entered values are converted to canonical units before persistence.
- The metabolic formula preference is presented as a calculation preference (non-clinical wording), is required, and offers the two MSJ variants.
- Client-side validation rejects implausible/missing values with clear, nonjudgmental messages.
- Saved profile round-trips correctly via the FTY-020 API for the authenticated user.
- TypeScript strict passes and mobile checks run via verification.

## Verification

- Run mobile typecheck, lint, and tests via `make verify` where wired.
- On an iOS simulator, complete the profile flow and confirm values persist and reload via the API.

## Planning Notes

- Exact copy/labels for the formula preference are a product-polish detail; the constraint is non-clinical wording that still maps unambiguously to the two MSJ variants. Final strings can be refined in the PR.
- If onboarding placement (first-run vs. settings) needs a product call, default to a first-run required step with later edit access.

## Readiness Sanity Pass

- Product decision gaps: none blocking — field set, formula-preference framing, and canonical-unit conversion are resolved.
- Cross-lane impact: depends on FTY-020 API; produces the profile data FTY-022 consumes.
- Security/privacy risk: medium; minimal sensitive body data over an authenticated API, careful non-clinical framing.
- Verification path: mobile checks + simulator round-trip against the profile API.
- Assumptions safe for autonomy: yes; only copy refinement and onboarding placement are soft, both with safe defaults.
