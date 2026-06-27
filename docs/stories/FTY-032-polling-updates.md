---
id: FTY-032
state: merged
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - polling-stop-condition
  - battery-network-efficiency
  - state-transitions
risk: low
tags:
  - polling
  - mobile
  - logging
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/architecture/system-overview.md
  - docs/adr/0002-product-architecture.md
autonomous: true
---

# FTY-032: Polling Updates

## State

ready

## Lane

mobile-core

## Dependencies

- FTY-031

## Outcome

The Today timeline refreshes pending entries automatically until they reach a terminal status, so a user sees an event move from pending to completed without manual refresh — the v1 update mechanism per ADR 0002.

## Scope

- Poll the FTY-030 endpoints while any visible event is non-terminal (`pending` / `processing`), updating the timeline as statuses change.
- Stop polling when no events are non-terminal; resume when a new event is created or the screen refocuses.
- Use a sensible fixed interval with a clear stop condition; avoid tight loops that drain battery or network.
- Reconcile fetched state into the timeline so completed/failed/needs_clarification entries render with their correct status and ordering.
- Pause polling when the screen is backgrounded/unfocused and resume on focus.

## Non-Goals

- Push notifications, websockets, or server-sent events (ADR: polling is sufficient for v1).
- Editing or correcting entries (Milestone 5).
- Rendering derived item detail (estimator stories).
- Configurable user-facing polling settings.

## Contracts

- Consumes the FTY-030 list-today and get-by-id DTOs and the event status enum; introduces no new contract. Terminal vs. non-terminal status classification must match the FTY-030 state machine.

## Security / Privacy

Polls the authenticated API for the user's own events only. Must not log event contents or spam requests. Low risk.

## Acceptance Criteria

- A pending event visibly transitions to its terminal status in the timeline without manual refresh.
- Polling stops once no events are non-terminal and resumes when a new event is created or the screen refocuses.
- Polling pauses while the screen is backgrounded/unfocused.
- The interval and stop condition are implemented to avoid excessive battery/network use.
- TypeScript strict passes; mobile state-transition tests cover start/stop/resume.

## Verification

- Run mobile typecheck, lint, and tests via `make verify` where wired; include tests for polling start/stop/resume logic.
- On an iOS simulator, drive a `pending → completed` transition (via the FTY-030 test/admin path until the estimator exists) and confirm the timeline updates automatically.

## Planning Notes

- Until the Milestone 4 estimator wires real processing, the only available transition is the FTY-030 `pending → completed` test/admin path; that is sufficient to verify the polling mechanism.
- The exact interval value is an implementation detail; pick a conservative default and document it.

## Readiness Sanity Pass

- Product decision gaps: none — interval polling with focus-aware start/stop, ADR-sanctioned mechanism.
- Cross-lane impact: builds on FTY-031; consumes FTY-030 contracts only.
- Security/privacy risk: low; own-user polling over authenticated API.
- Verification path: mobile state-transition tests + simulator transition check.
- Assumptions safe for autonomy: yes; interval value is the only soft detail, with a safe default.
