---
id: FTY-013
state: merged
primary_lane: mobile-core
touched_lanes:
  - contracts
risk: low
tags:
  - skeleton
  - mobile
  - expo
  - tooling
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
review_focus:
  - scope-control
  - accessibility
  - verify-command
autonomous: true
---

# FTY-013: Mobile App Skeleton

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-010

## Outcome

An Expo / React Native iOS-first app opens to a Today shell rendered from local mock state, with file-based routing set up so further screens can be added without rework.

## Scope

- Scaffold an Expo / React Native app with **Expo Router** (file-based routing) configured, but only a single Today screen present.
- Enable TypeScript strict mode per the coding standards.
- Render the Today screen from in-memory/local mock state — pending and completed entries may be represented in the mock per the system overview, but with no networking.
- Use an iOS-first, accessible, compact, nonjudgmental UI; where status/evidence indicators appear, use icons with accessibility labels (minimal is acceptable at this stage).
- Add mobile typecheck, lint, and a basic test into root verification where feasible.

## Non-Goals

- Backend integration or any networking.
- Auth or onboarding screens.
- Real log creation, editing flows, or polling (polling is FTY-032).
- Android-specific work or platform parity.
- A committed mock-state schema — the Today shell's mock shape is an internal placeholder only.

## Contracts

- None external. The Today shell's local mock-state shape is an internal placeholder and is explicitly not a committed contract; the real DTOs arrive with the logging-spine stories.

## Security / Privacy

No real user data. Only synthetic/mock data is used. Low risk.

## Acceptance Criteria

- The Expo app builds and opens to the Today screen on iOS.
- The Today screen renders mock pending/completed entries.
- TypeScript strict mode passes.
- Mobile checks (typecheck, lint, basic test) run via root verification.
- The routing structure supports adding additional screens without restructuring.

## Verification

- Run the mobile package's typecheck, lint, and test (via `make verify` where wired).
- Launch the Expo app on an iOS simulator and confirm the Today screen renders mock entries.

## Planning Notes

- Exact Expo SDK version and minor project-structure choices may be finalized in the implementation PR as long as Expo Router, TS strict, and the single-screen scope hold.
- New third-party UI/state libraries beyond the minimal Expo Router set require a planning PR updating story metadata first.

## Readiness Sanity Pass

- Product decision gaps: none — Expo Router + single Today screen + mock state are resolved.
- Cross-lane impact: establishes the mobile app foundation and routing convention for later mobile stories; no committed contract yet.
- Security/privacy risk: low; synthetic data only, no networking.
- Verification path: mobile checks via `make verify` plus a simulator smoke check.
- Assumptions safe for autonomy: yes; scope is bounded to a single screen on mock state with no networking.
