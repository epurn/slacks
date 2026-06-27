---
id: FTY-053
state: ready_with_notes
primary_lane: mobile-core
touched_lanes: []
review_focus:
  - accessibility
  - debounce-correctness
  - source-attribution
risk: medium
tags:
  - saved-foods
  - typeahead
  - mobile
  - editing
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/standards/coding-standards.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
autonomous: true
---

# FTY-053: Saved-Food Save Action + Typeahead Suggestion Bar (Mobile)

## State

ready_with_notes

## Lane

mobile-core

## Dependencies

- FTY-050 (the item-editing UI surface the Save action attaches to)
- FTY-052 (the saved-food save + typeahead search endpoints)

## Outcome

On mobile, the user can save a corrected food for reuse and have their saved
foods surface as tap-to-apply suggestions while logging. Two pieces:

1. A **"Save this food"** action in the FTY-050 item-editing surface that calls
   FTY-052's save endpoint to persist a corrected food, recording the user's
   typed phrase as an alias.
2. A **typeahead suggestion bar** rendered directly below the log-entry text
   input (a mobile keyboard-style suggestion strip). As the user types, it
   debounced-queries FTY-052's typeahead search endpoint and shows the user's
   matching saved foods. Tapping a suggestion applies that saved food's stored
   values to the item, marks the item `source='saved_food'`, and skips the
   estimator for that item. If the user picks nothing, the normal estimator
   path runs on submit.

## Scope

- Add a "Save this food" action to the FTY-050 editing surface that POSTs the
  corrected food (plus the typed phrase as an alias) to FTY-052's save endpoint;
  surface success and failure states.
- Render a suggestion bar below the log-entry input that debounced-queries
  FTY-052's typeahead search endpoint as the user types.
- Show the user's prefix-matching saved foods/aliases as tappable suggestions;
  render an empty/no-match state without occupying space unnecessarily.
- On tap, apply the saved food's stored values to the item, mark it
  `source='saved_food'`, and skip the estimator for that item on submit.
- When no suggestion is tapped, leave the normal estimator path unchanged.
- The user always chooses explicitly: there is no silent auto-apply.
- Keep the suggestion bar accessible (iOS-first, compact), with accessible
  labels on suggestion items and the Save action.

## Non-Goals

- Fuzzy or semantic suggestions — the backend returns only normalized prefix
  matches, and the UI consumes exactly those.
- A manage/edit/delete-saved-foods screen.
- Auto-save of corrected foods (saving is always an explicit user action).
- Any server-side logic, contract, or estimator behavior change — this slice is
  mobile UI consuming FTY-052 endpoints.

## Contracts

- Consumes FTY-052's saved-food save and typeahead search DTOs and the item
  `source` field (`saved_food`). Introduces no new server contract.

## Security / Privacy

- Operates only on the authenticated user's own saved foods over the
  authenticated API; the typeahead endpoint must return only that user's data.
- The typed log phrase is sent to the search and save endpoints as the user
  types (debounced); no additional on-device sensitive storage beyond what is
  needed to render suggestions and apply a selection.
- Medium risk: consumes secured endpoints and attributes item source, but holds
  no server logic of its own.

## Acceptance Criteria

- After correcting an item, "Save this food" persists it via FTY-052's save
  endpoint (verified through the endpoint), recording the typed phrase as an
  alias.
- Typing text that prefix-matches a saved food/alias surfaces it in the
  suggestion bar, with the query debounced rather than firing per keystroke.
- Tapping a suggestion applies its stored values to the item, marks the item
  `source='saved_food'`, and skips the estimator for that item on submit.
- Choosing no suggestion leaves the normal estimator path intact.
- Empty input and no-match results render a sensible, non-intrusive state.
- TypeScript strict passes; mobile checks run via verification.

## Verification

- Per `docs/standards/testing-standards.md` (mobile):
  - Component tests for the suggestion bar: debounce behavior, render of
    matches, empty/no-match state, and apply-on-tap (values applied + item
    marked `source='saved_food'` + estimator skipped).
  - Component test for the "Save this food" action (calls save endpoint with the
    corrected food + typed-phrase alias; success/failure states).
  - Integration tests against mocked FTY-052 save and search endpoints.
  - Accessibility checks (iOS-first, compact): accessible labels on suggestion
    items and the Save action.
- Run mobile typecheck, lint, and tests via `make verify` where wired.

## Planning Notes

- Splits Milestone 5's saved-food mobile work from the FTY-052 backend. FTY-052
  owns the save + typeahead search endpoints and the prefix-match semantics;
  this story is the mobile consumer.
- The "no fuzzy matching" boundary is enforced server-side; the UI must not add
  its own client-side fuzzy/semantic ranking.

## Readiness Sanity Pass

- Product decision gaps: none — settled with the product owner. Save is an
  explicit action; suggestions are tap-to-apply with no silent auto-apply;
  prefix-only matching owned by the backend; non-goals exclude a manage screen,
  fuzzy/semantic suggestions, and auto-save.
- Cross-lane impact: none beyond mobile-core; consumes FTY-052 DTOs and defines
  no new server contract.
- Security/privacy risk: medium — consumes secured per-user endpoints and
  attributes item source; no server logic of its own.
- Verification path: mobile component + integration tests against mocked FTY-052
  endpoints, plus accessibility checks and `make verify`.
- Assumptions safe for autonomy: yes. Dependency note: FTY-050 (editing surface)
  and FTY-052 (save + search endpoints) are not yet merged — this is a
  dependency note, not a blocker; the slice builds against their published
  surfaces.
