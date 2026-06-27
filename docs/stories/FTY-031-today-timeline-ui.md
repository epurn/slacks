---
id: FTY-031
state: merged
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - accessibility
  - status-iconography
  - nonjudgmental-copy
risk: low
tags:
  - timeline
  - mobile
  - logging
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/standards/coding-standards.md
  - docs/architecture/system-overview.md
autonomous: true
---

# FTY-031: Today Timeline UI

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-013
- FTY-021
- FTY-030

## Outcome

The mobile Today shell renders the user's real log events from the API, showing pending and completed entries in a timeline, and lets the user submit natural-language input to create a new event.

## Scope

- Replace the FTY-013 mock state with real data from the FTY-030 list-today endpoint.
- Render events in a Today timeline, visually distinguishing `pending` from `completed` (and accommodating the other statuses defined in the contract).
- Provide a natural-language input that calls the FTY-030 create endpoint; on submit, the new event appears immediately as `pending`.
- Use status icons with accessibility labels; keep copy compact and nonjudgmental per the coding standards.
- Handle empty, loading, and error states gracefully.

## Non-Goals

- Polling/auto-refresh of pending entries (FTY-032 — a manual refresh is acceptable here).
- Editing entries or correcting estimates (Milestone 5).
- Displaying derived food/exercise item details (estimator stories) — event-level entries with status are sufficient for this slice.
- Attachments, barcode, or label capture (Milestone 6).

## Contracts

- Consumes the FTY-030 create / list-today DTOs and the event status enum; introduces no new contract. The mobile status-to-icon mapping must cover all statuses in the contract.

## Security / Privacy

Displays the authenticated user's own events only, fetched over the authenticated API. No new sensitive storage on-device beyond what is needed to render. Low risk.

## Acceptance Criteria

- The Today screen loads and renders the authenticated user's events for today from the API.
- Pending and completed events are visually distinct, with accessible status indicators.
- Submitting natural-language input creates an event that appears immediately as pending.
- Empty/loading/error states render sensibly.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Run mobile typecheck, lint, and tests via `make verify` where wired.
- On an iOS simulator, create an event and confirm it appears as pending in the timeline; confirm completed events render distinctly.

## Planning Notes

- Without polling (FTY-032), a pending event only updates on manual refresh/re-fetch; that is the expected boundary of this slice.
- Since the estimator is not yet wired (Milestone 4), events will remain pending in normal use; the UI must handle a persistently-pending state without looking broken.

## Readiness Sanity Pass

- Product decision gaps: none — event-level timeline over the FTY-030 API, manual refresh, status iconography.
- Cross-lane impact: consumes FTY-030 contracts; sets the timeline UI the polling story builds on.
- Security/privacy risk: low; own-user data over authenticated API.
- Verification path: mobile checks + simulator create/render check.
- Assumptions safe for autonomy: yes; scope excludes polling, editing, and derived-item display.
