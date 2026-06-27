---
id: FTY-022
state: merged
primary_lane: estimator
touched_lanes:
  - contracts
  - backend-core
review_focus:
  - deterministic-math
  - documented-assumptions
  - boundary-values
  - migration-rollback
risk: high
tags:
  - calculator
  - rmr
  - tdee
  - goals
  - contracts
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/standards/testing-standards.md
  - docs/architecture/system-overview.md
autonomous: true
---

# FTY-022: Target Calculator Contract

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-020

## Outcome

A deterministic, well-tested target calculator turns a user's profile and weight goal into a daily calorie target, with documented assumptions, backed by `goals` and `daily_targets` contracts.

## Scope

- Define and migrate the `goals` and `daily_targets` tables/contracts (this story owns them).
- Implement RMR using **Mifflin-St Jeor**, taking the metabolic formula preference (FTY-021) as the sex-dependent constant.
- Compute TDEE as **RMR × a fixed baseline (sedentary) activity multiplier**. Logged exercise burn is added to the day's allowance separately by later logging stories and is explicitly NOT folded into this multiplier, to avoid double-counting MET-based active calories.
- Implement **NIDDK-style dynamic goal planning**: the goal input is a target weight plus a target date; the calculator derives the required daily calorie target along the trajectory, accounting for the dynamic change in energy expenditure as body mass changes.
- Make all math deterministic and fully unit-tested: exact worked examples, unit conversions, invalid inputs, and boundary values.
- Document every assumption (chosen baseline multiplier value, NIDDK model parameters, rounding, safety floors/ceilings on daily targets).

## Non-Goals

- Profile capture UI (FTY-021) and the profile/auth model (FTY-020).
- Logging exercise burn or adding it to the daily allowance (later logging/estimator stories).
- Adaptive calibration over time from observed weight trend (a later v1-polish concern).
- LLM involvement — this is pure deterministic backend math.
- Activity-level selection in the profile (deliberately excluded; baseline multiplier + logged exercise is the model).

## Contracts

- `goals` (target weight, target date, created/active state) and `daily_targets` (derived calorie target + the inputs/assumptions snapshot) table and DTO contracts.
- The calculator's input contract (profile fields + goal) and output contract (RMR, TDEE, daily calorie target, assumptions) become estimator contracts.
- The metabolic formula preference enum must match FTY-021's values.

## Security / Privacy

Operates on sensitive body data but produces derived numbers; it stores `goals` and `daily_targets` as user-owned records with object-level ownership at the persistence boundary. No external providers, no untrusted input, no LLM. Retention: derived targets follow profile/goal retention (until edited or account deletion). Rated high because it touches estimator contracts and migrations and underpins health-adjacent guidance, even though the math is deterministic.

## Acceptance Criteria

- RMR matches Mifflin-St Jeor worked examples for both formula-preference variants.
- TDEE = RMR × the documented baseline multiplier, with exercise explicitly excluded from the multiplier.
- Given a target weight + target date, the calculator returns a daily calorie target consistent with documented NIDDK-style dynamic assumptions.
- Deterministic tests cover exact examples, unit conversions, invalid inputs, and boundary values (including implausible goals and safety floors/ceilings).
- `goals` / `daily_targets` migrations apply and roll back; records carry user ownership.
- Assumptions are documented in the contract/story and referenced from code.
- `make verify` passes.

## Verification

- Run `make verify` (calculator unit tests + migration tests).
- Verify worked examples by hand against published Mifflin-St Jeor and NIDDK references.
- Apply/roll back the `goals` / `daily_targets` migration in a test database.

## Planning Notes

- The exact baseline activity multiplier and the specific NIDDK dynamic-model parameterization are implementation assumptions that must be documented and cited in the PR; defaults should be conservative and clearly labeled. These are non-blocking but warrant reviewer attention, hence ready_with_notes.
- Safety floors/ceilings on the daily calorie target (refusing dangerously low targets) should be included and documented as a safety guard.

## Readiness Sanity Pass

- Product decision gaps: none blocking — RMR formula, TDEE composition (baseline + separate exercise), and goal-input shape (target weight + date) are resolved.
- Cross-lane impact: owns `goals`/`daily_targets` contracts consumed by summaries and later targeting; depends on FTY-020 profile fields.
- Security/privacy risk: high (estimator + contracts + migrations), but deterministic, no external input, user-owned records.
- Verification path: `make verify` + hand-checked references + migration rollback.
- Assumptions safe for autonomy: yes; multiplier/NIDDK parameters must be documented and a safety floor enforced — captured as notes.
