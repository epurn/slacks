---
id: FTY-074
state: ready
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - accessibility
  - sensitive-data-handling
  - charting-dependency
risk: medium
tags:
  - weight
  - trend
  - chart
  - mobile
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
autonomous: true
---

# FTY-074: Mobile Weight Logging + Trend Chart

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-070 (weight backend: create + list-range endpoints)
- FTY-013 (mobile app skeleton)
- FTY-021 (units preference)

## Outcome

On mobile, the user can log their body weight and view a simple weight trend
chart over a recent range, backed by FTY-070's weight endpoints. Two pieces:

1. A **weight-entry input** that respects the user's units preference (FTY-021)
   and persists the entry via FTY-070's create endpoint.
2. A **trend chart** that fetches the user's weight entries over a recent range
   via FTY-070's list-range endpoint and plots the actual logged points as a
   simple line.

## Scope

- Render a weight-entry input that accepts a body-weight value in the user's
  preferred units (FTY-021), converting to/from the canonical unit at the API
  boundary as the existing profile client does; do not alter stored canonical
  semantics.
- On submit, POST the entry to FTY-070's create endpoint; surface success and
  failure states. The newly logged point appears on the chart after a re-fetch.
- Render a trend chart over a recent range using FTY-070's list-range endpoint,
  plotting the actual logged points as a simple line (no smoothing for v1).
- Display the chart axis/values in the user's preferred units.
- Handle empty, sparse (single-point), loading, and error states gracefully so
  the chart never looks broken.
- Use an iOS-first, accessible, compact, nonjudgmental UI; provide accessible
  labels for the input and a text alternative/summary for the chart.
- Use a lightweight RN/Expo charting approach. If charting requires a new
  dependency, list it as an added/approved dependency in the implementation PR
  with a brief justification and update story metadata first per the FTY-013
  dependency rule.

## Non-Goals

- Target re-calibration from the trend (future, per target-calculator).
- A moving-average / smoothed trend line (nice-to-have only; explicitly out of
  v1 scope — keep it simple, plot raw points).
- Data export.
- Editing or deleting past weight entries (unless trivially supported by the
  existing surface; not required here).
- Any server-side logic, contract, or endpoint change — this slice is mobile UI
  consuming FTY-070 endpoints.

## Contracts

- None new. Consumes FTY-070's weight create and list-range DTOs and the
  canonical weight unit. Introduces no new server contract.

## Security / Privacy

- Body weight is sensitive. It is fetched and submitted only over the
  authenticated API (TLS), and shown only to the authenticated owner.
- Weight values are never written to logs, error messages, or analytics; errors
  carry only HTTP status and endpoint (mirroring the profile client).
- No on-device persistence of weight values beyond normal app state/cache needed
  to render the input and chart; no additional sensitive local storage.
- Medium risk: sensitive per-user data plus a likely charting dependency, but no
  server logic of its own.

## Acceptance Criteria

- Logging a weight persists it via FTY-070's create endpoint (verified through
  the endpoint), and the new point appears on the chart after re-fetch.
- The chart renders the user's logged points over a recent range as a simple
  line, sourced from FTY-070's list-range endpoint.
- Input and chart values display in the user's profile units preference
  (FTY-021); conversion happens only at the API boundary.
- Empty and sparse (single-point) states render gracefully; loading and error
  states render sensibly.
- No weight value is emitted to logs or error output.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Component tests for the weight-entry input (units-aware display + canonical
    conversion at submit; success/failure states).
  - Component tests for the trend chart: render of multiple points, sparse
    single-point state, empty state, loading, and error.
  - Integration tests against mocked FTY-070 create and list-range endpoints.
  - Accessibility checks (iOS-first, compact): accessible labels on the input and
    a text alternative/summary for the chart.
- Run mobile typecheck, lint, and tests via `make verify` where wired.
- On an iOS simulator, log a weight and confirm it appears on the trend chart in
  the user's preferred units.

## Planning Notes

- Mirrors the FTY-053 mobile-slice pattern: a mobile UI story consuming an
  already-specified backend (FTY-070) with no new contract.
- A smoothed/moving-average trend line is a possible follow-up but is
  deliberately excluded from v1 to keep the slice small.
- Any charting library beyond the minimal Expo set requires a planning PR
  updating story metadata first, per FTY-013's dependency rule.

## Readiness Sanity Pass

- Product decision gaps: none — log + plot raw points, units from FTY-021,
  no smoothing for v1, no edit/export/re-calibration. Settled with the product
  owner.
- Cross-lane impact: none beyond mobile-core; consumes FTY-070 DTOs and defines
  no new server contract.
- Security/privacy risk: medium — sensitive body-weight data over the
  authenticated API, no value logging, no extra on-device storage; plus a likely
  charting dependency to vet.
- Verification path: mobile component + integration tests against mocked FTY-070
  endpoints, accessibility checks, `make verify`, and a simulator smoke check.
- Assumptions safe for autonomy: yes. Dependency note: FTY-070 must be merged for
  live data; the slice builds against its published create + list-range surfaces.
  A new charting dependency, if needed, must be declared per FTY-013's rule.
