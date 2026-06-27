---
id: FTY-043
state: merged
primary_lane: estimator
touched_lanes:
  - contracts
  - backend-core
review_focus:
  - deterministic-math
  - met-table-versioning
  - boundary-values
  - double-count-avoidance
risk: high
tags:
  - estimator
  - exercise
  - met
  - calculator
approved_dependencies: []
requires_context:
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-043: MET Exercise Calculator

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-042

## Outcome

Exercise candidates resolve into derived exercise items with deterministic, tested active-calorie burn, using MET values from a curated, versioned table and the user's body weight.

## Scope

- Implement a deterministic MET-based active-calorie calculator that resolves `derived_exercise_items` from FTY-042 candidates.
- Compute **net active calories** using the (MET − 1) adjustment so resting energy already counted in TDEE (via the FTY-022 baseline multiplier) is not double-counted.
- The LLM-extracted candidate provides the activity description and duration; the **backend** maps the activity to a MET value from a curated, versioned MET table (Compendium of Physical Activities-based) and validates it. The LLM never supplies the MET number directly.
- Use the user's stored body weight (canonical kg) from the profile.
- Persist the computed active calories onto the derived exercise item and record the MET-table version/source in the estimation run/evidence.

## Non-Goals

- Food calorie/macro resolution (FTY-044).
- Heart-rate or device-based burn estimation.
- Editable corrections to burn (Milestone 5).
- Expanding the MET table beyond a curated v1 subset.

## Contracts

- The MET table (curated subset + version) and the exercise-burn formula become estimator contracts.
- The activity → MET lookup and validation rule (reject/needs_clarification when no confident MET match) is a contract.
- Writes the `active_calories` field on `derived_exercise_items` (table from FTY-042).

## Security / Privacy

Deterministic backend math on user-owned data; no external calls, no untrusted numbers trusted (MET comes from the curated table, not the LLM). Uses body weight, which is sensitive — kept user-owned and not logged. Rated high: estimator contract + health-adjacent math, though deterministic.

## Acceptance Criteria

- Active calories match worked examples for representative activities using the (MET − 1) net convention and the user's weight.
- The activity is mapped to a MET value only from the curated table; an activity with no confident match is handled deterministically (failed or needs_clarification), not guessed by the LLM.
- Tests cover exact examples, unit handling, invalid inputs, and boundary values (zero/extreme duration, missing weight).
- The MET-table version/source is recorded for the run.
- `make verify` passes.

## Verification

- Run `make verify` (calculator unit tests).
- Hand-verify worked examples against the published Compendium MET values and the net-active formula.

## Planning Notes

- The exact curated MET subset and the net-active constant form are documented assumptions to cite in the PR; (MET − 1) net burn is the chosen convention to align with the FTY-022 TDEE model.
- The no-confident-match behavior (fail vs needs_clarification) should follow FTY-042's routing conventions.

## Readiness Sanity Pass

- Product decision gaps: none blocking — net-active convention and LLM→curated-table mapping resolved.
- Cross-lane impact: completes exercise burn feeding daily summaries; consistent with FTY-022 to avoid double-counting.
- Security/privacy risk: high (estimator + body data), mitigated by deterministic math and curated MET values.
- Verification path: `make verify` + hand-checked Compendium examples.
- Assumptions safe for autonomy: yes; curated table + constants are documented assumptions (notes).
