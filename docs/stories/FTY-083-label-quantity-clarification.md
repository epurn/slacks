---
id: FTY-083
state: merged
primary_lane: estimator
touched_lanes: []
risk: low
tags:
  - estimator
  - label
  - clarification
  - ux
approved_dependencies:
  - FTY-061
requires_context:
  - docs/contracts/label-extraction.md
  - docs/contracts/label-upload.md
  - docs/standards/testing-standards.md
review_focus:
  - quantity-question-distinct-from-serving-question
  - unresolvable-consumed-quantity-routes-correct-question
autonomous: true
---

# FTY-083: Ask for Consumed Quantity (Not Serving Size) When the Label Quantity Is Unresolvable

## State

ready

## Lane

estimator

## Dependencies

- FTY-061 (the label extraction pipeline whose clarification path this corrects)

## Outcome

When the label pipeline can read the panel but cannot resolve **how much the user
consumed**, the clarification it asks the user matches what it actually needs —
the consumed amount — instead of mistakenly asking for the serving size printed
on the label. This removes a user-facing confusion in the label-capture flow.

## Scope

- In `app/estimator/label_step.py` (around line 258), the branch that handles an
  unresolvable **consumed quantity** currently sets
  `context.clarification_questions = [SERVING_QUESTION]` ("What is the serving
  size on the label…?"). That question is for a different gap (an unreadable
  printed serving size), not for "how much did you eat."
- Introduce a distinct constant, e.g.
  `QUANTITY_QUESTION = "How much did you consume (for example, in grams or
  servings)?"`, and use it on the unresolvable-consumed-quantity branch.
- Leave `SERVING_QUESTION` and any branch that genuinely needs the printed
  serving size unchanged.

## Non-Goals

- Any change to extraction, validation, the panel schema, per-serving→per-100g
  math, or the fail-closed disposition handling.
- The per-100g evidence-precision rounding nit (separate, non-blocking; not in
  scope).
- Mobile copy/UX beyond surfacing the question text already returned by the API.

## Contracts

- `label-extraction.md` / `label-upload.md`: if the clarification question text or
  the set of clarification reasons is enumerated there, update it to reflect the
  distinct consumed-quantity question. No request/response shape change — the
  field already carries free-text clarification questions.

## Security / Privacy

- None. This only changes which human-readable clarification string is returned;
  no new data is read, stored, logged, or egressed. Rated **low**.

## Acceptance Criteria

- When the panel is legible but the consumed quantity cannot be resolved, the
  returned clarification question asks for the **consumed amount** (grams/
  servings), not the label's serving size.
- A branch that legitimately needs the printed serving size (if one exists) still
  returns `SERVING_QUESTION`.
- A test asserts the unresolvable-consumed-quantity path returns the new
  `QUANTITY_QUESTION` (update the existing label-resolution clarification test
  rather than duplicating it).
- `make verify` passes.

## Verification

- `make verify`, including an updated/added assertion in the label resolution
  tests that the unresolvable-consumed-quantity branch yields the consumed-amount
  question and the serving-size branch (if present) is unaffected.

## Readiness Sanity Pass

- **Product decision gaps:** none — the correct question wording is given; any
  reasonable equivalent phrasing is acceptable.
- **Cross-lane impact:** estimator only. Zero touched lanes.
- **Security/privacy risk:** low — string-only change on an existing
  clarification path.
- **Verification path:** `make verify` + a focused label-resolution test
  assertion.
- **Assumptions safe for autonomy:** yes — single file, single branch, with the
  exact line and intended wording specified.
- **Sizing:** 0 touched lanes, 2 review_focus, 3 requires_context — comfortably
  within the scope guardrail. Smallest of the audit fixes.
