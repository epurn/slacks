---
id: FTY-030
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - object-level-authz
  - state-machine-contract
  - migration-rollback
  - input-validation
risk: high
tags:
  - logging
  - api
  - contracts
  - state-machine
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-030: Log Event API

## State

ready

## Lane

backend-core

## Dependencies

- FTY-020

## Outcome

A user can create a pending raw log event from natural-language input through the API, and read their Today events back, so the mobile timeline and polling have a real backend to talk to.

## Scope

- Add a `log_events` migration: user-owned records holding the raw natural-language text, a status, and timestamps.
- Define the **event status state machine** contract covering all v1 statuses — `pending`, `processing`, `completed`, `failed`, `needs_clarification` — and document the legal transitions. This story implements creation at `pending` and the `pending → completed` transition only; the estimator stories (M4) implement `processing`, `failed`, and `needs_clarification`.
- Implement endpoints: `POST` to create a pending event from raw text; `GET` to list the authenticated user's events for a given day (Today); `GET` one event by id (for polling).
- Enforce object-level authorization: a user can only create, list, and read their own events.
- Validate input (non-empty raw text, length bounds) with a clear error shape.

## Non-Goals

- Estimation, job enqueue, or any worker processing (FTY-040+ in Milestone 4).
- Derived food/exercise items (estimator stories).
- `log_attachments` — label images and barcodes are deferred to Milestone 6 (FTY-060/061).
- Editing or deleting events (later stories).
- The mobile timeline UI (FTY-031) and polling (FTY-032).

## Contracts

- `log_events` table + DTO contract (raw text, status, timestamps, user ownership).
- The event status state machine (statuses + legal transitions) is a named contract other stories extend without redefining.
- The create / list-today / get-by-id request/response shapes are contracts consumed by FTY-031 and FTY-032.

## Security / Privacy

`log_events` raw text is sensitive personal data and must be user-owned with object-level authorization on every access path, proven by negative tests that fail closed. Raw text must not be logged. Retention follows the data-retention doc (logs retained until user/account deletion). Rated high: touches contracts, migrations, a state-machine contract, and privacy.

## Acceptance Criteria

- `POST` creates a `log_events` row at status `pending` with the raw text and returns the typed event.
- `GET` list-today returns only the authenticated user's events for the requested day.
- `GET` by id returns the event only to its owner; cross-user access fails closed (negative test).
- The status enum and legal transitions are defined and documented; an illegal transition is rejected.
- Input validation rejects empty/oversized text with a clear error shape.
- Migration applies and rolls back; records carry user ownership.
- `make verify` passes.

## Verification

- Run `make verify` (API + migration + authz tests).
- Apply/roll back the `log_events` migration in a test database.
- Run negative authorization tests for list and get-by-id.

## Planning Notes

- Events created here remain `pending` until the Milestone 4 estimator wires processing; that is expected and FTY-032 will visibly show them pending until then.
- The `pending → completed` transition is implemented so the state machine is exercisable end-to-end before the estimator exists (e.g. via a test/admin path), without implementing real estimation.

## Readiness Sanity Pass

- Product decision gaps: none — status model (full enum, pending→completed now) and endpoint surface (create/list/get) are resolved.
- Cross-lane impact: defines the logging contract consumed by mobile (FTY-031/032) and extended by the estimator (M4).
- Security/privacy risk: high; sensitive raw text, user-owned, object-level authz with negative tests.
- Verification path: `make verify` + migration rollback + negative authz tests.
- Assumptions safe for autonomy: yes; scope explicitly excludes estimation and attachments.
