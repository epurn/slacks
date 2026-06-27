---
id: FTY-050
state: merged
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - accessibility
  - optimistic-update-rollback
  - edited-vs-estimated-indicator
risk: medium
tags:
  - mobile
  - editing
  - timeline
  - estimates
approved_dependencies: []
requires_context:
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
autonomous: true
---

# FTY-050: Editable Food/Exercise Items (Mobile UI)

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- FTY-051
- FTY-031
- FTY-013

## Outcome

On the Today timeline, a user can correct a food or exercise item's values —
calories, macros (protein/fat/carbs), servings/quantity, and exercise burn —
directly from mobile. Edits call the FTY-051 edit endpoint (one PATCH per field)
and the UI renders the server's returned current values, with a clear indicator
when a value differs from the original estimate. Edits apply optimistically and
roll back on failure.

## Scope

- Add editable controls to the food/exercise item surface within the FTY-031
  Today timeline for: calories, macros (protein, fat, carbs), servings/quantity,
  and exercise burn.
- Each edit sends one PATCH per field to the FTY-051 edit endpoint and renders
  the **current** values from the server's response — including any
  server-rescaled values (a servings/quantity edit rescales calories and macros
  server-side per FTY-051's ratio rule; the UI does not compute the rescale).
- Render the corrected (current) value with an **edited** indicator that is
  visually distinct from the original/estimated value the backend preserves
  (per FTY-051). The user can tell at a glance which fields were corrected.
- Apply edits optimistically: show the new value immediately, then reconcile
  with the server response. On error, roll back to the prior value and surface a
  clear, nonjudgmental error.
- iOS-first, compact, accessible: edit controls have accessibility labels; the
  edited indicator is conveyed non-visually as well (not color alone).

## Non-Goals

- Saving a food, the "Save this food" button, and the typeahead suggestion bar
  (all FTY-053).
- Undo / edit-history UI.
- The edit endpoint, the ratio rescale rule, the estimated/original value
  preservation, and any authorization logic — all owned server-side by FTY-051.
- Editing event-level fields (raw text, status) — this story edits derived
  food/exercise item values only.
- Polling/auto-refresh (FTY-032).

## Contracts

- Consumes FTY-051's per-field edit DTO (the PATCH request/response shape and the
  current-vs-estimated value representation). Introduces no new server contract.

## Security / Privacy

Consumes a secured endpoint defined and authorized in FTY-051; this story adds
no migrations and no authorization logic of its own. It displays and edits the
authenticated user's own items over the authenticated API, storing nothing new
sensitive on-device beyond what is needed to render. No item values are written
to logs. Rated medium: a mobile UI mutating user data through a secured endpoint,
where the optimistic-update path must fail closed (roll back) on error.

## Acceptance Criteria

- The user can edit each of: calories, protein, fat, carbs, servings/quantity,
  and exercise burn on a Today food/exercise item.
- A servings/quantity edit displays the server-rescaled calories and macros
  returned by FTY-051 (the UI renders server values; it does not compute them).
- A corrected field renders with an "edited" indicator that is distinct from the
  original/estimated value, and the indicator is accessible (not color-only).
- Edits apply optimistically; a failed edit rolls back the optimistic update to
  the prior value and shows a clear error.
- TypeScript strict passes; mobile checks run via verification.

## Verification

Per `docs/standards/testing-standards.md` (mobile):

- Component tests for each edit control (calories, each macro, servings, burn),
  including rendering of the edited-vs-estimated indicator.
- An integration test of the edit flow against a **mocked FTY-051 endpoint**
  covering: a direct field override, a servings edit that returns rescaled
  calories/macros, and a failed PATCH that rolls back the optimistic update.
- Accessibility check: edit controls and the edited indicator expose accessible
  labels/state; iOS-first, compact per `docs/standards/coding-standards.md`.
- Run mobile typecheck, lint, and tests via `make verify` where wired.

## Planning Notes

- One PATCH per field is intentional and matches FTY-051's contract; the UI does
  not batch fields. A servings edit is still a single PATCH whose response may
  carry rescaled calories/macros that the UI re-renders.
- The UI is a thin consumer: all edit logic (ratio rescale, single-field
  override, estimated-value preservation) lives in FTY-051. If the response
  shape for current-vs-estimated values is still in flux when this is picked up,
  follow FTY-051 as the source of truth rather than re-deriving it here.

## Readiness Sanity Pass

- Product decision gaps: none — editable fields, per-field PATCH, server-rescale
  on servings, edited-vs-estimated indicator, and optimistic-with-rollback are
  all resolved with the product owner. Save-food, suggestion bar, and undo are
  explicitly out (FTY-053).
- Cross-lane impact: none beyond mobile-core; consumes FTY-051's edit DTO and
  builds on the FTY-031 timeline surface. Defines no new server contract.
- Security/privacy risk: medium; mutates own-user data over a secured endpoint
  (authz owned by FTY-051). Optimistic path must roll back on failure; no item
  values logged.
- Verification path: mobile component tests + integration test against a mocked
  FTY-051 endpoint (override, rescale, rollback) + accessibility/iOS checks.
- Assumptions safe for autonomy: yes. Note: this depends on the unmerged backend
  story **FTY-051** for the edit endpoint and DTO; the steward will not assign
  FTY-050 until FTY-051 merges. That is a dependency-ordering note, not a
  readiness blocker.
