# Contracts

Contracts define boundaries before implementation details leak across systems.

Use contracts for:

- HTTP APIs,
- mobile/backend DTOs,
- database tables and migrations,
- Celery job payloads,
- estimator tool inputs and outputs,
- LLM structured outputs,
- provider adapters,
- source evidence records,
- user-approved saved foods, aliases, and preference memory writes,
- event status state machines.

## Contract Template

```md
# Contract: <Name>

## Purpose

## Owner

## Version

## Inputs

## Outputs

## Validation

## Authorization

## Privacy and Retention

## Errors

## Examples

## Migration / Compatibility
```

## Contracts Index

| Contract | Purpose |
|----------|---------|
| [clarification.md](clarification.md) | Clarify-loop read/answer sub-API for a `needs_clarification` or `partially_resolved` log event |
| [corrections.md](corrections.md) | User-initiated corrections and edits to derived food and exercise items |
| [daily-summary.md](daily-summary.md) | Read-only daily-summary endpoint for fetching a user's daily totals and entries |
| [estimate-first-routing.md](estimate-first-routing.md) | Parse step's estimate-first routing override, deterministic detail signal, amount fills, and user-stated-nutrition extraction |
| [estimation-jobs.md](estimation-jobs.md) | Async estimation engine that turns pending log events into resolved food and exercise items |
| [estimator-policy.md](estimator-policy.md) | Shared estimator clarification modes, last-resort ask policy, and rough-provenance requirements |
| [evidence-retrieval.md](evidence-retrieval.md) | Source-backed estimation contracts defining the evidence hierarchy and lookup rules |
| [exercise-burn.md](exercise-burn.md) | Deterministic MET-based exercise burn calculation |
| [food-resolution.md](food-resolution.md) | Deterministic generic-food resolution step using USDA and external sources |
| [food-suggestions.md](food-suggestions.md) | Read-only contextual quick-add food suggestions ranked by deterministic time-aware frecency |
| [goals-target-reveal.md](goals-target-reveal.md) | Goal direction input and target-calculation step turning user goals into calorie targets |
| [identity-and-profile.md](identity-and-profile.md) | User identity, profile data model, and minimal local-mode profile defaults |
| [interpretation-session.md](interpretation-session.md) | LLM-owned interpretation session: the revisable hypothesis, evidence-tiers-as-tools, and deterministic-code authority across an estimation run |
| [label-extraction.md](label-extraction.md) | Nutrition label extraction step from uploaded photos |
| [label-upload.md](label-upload.md) | HTTP upload boundary for capturing and transmitting nutrition label photos |
| [llm-provider.md](llm-provider.md) | Provider-agnostic LLM adapter configuration supporting OpenAI, Anthropic, Claude Code, and local models |
| [log-attachments.md](log-attachments.md) | Log attachments table, retention policy, and discard-by-default behavior |
| [log-events.md](log-events.md) | Log-event data model, status state machine, and create/list/edit API |
| [parse-candidates.md](parse-candidates.md) | Structured parse step producing candidate food and exercise items with clarification questions |
| [saved-foods.md](saved-foods.md) | Saved foods, aliases, and typeahead data model and API |
| [target-calculator.md](target-calculator.md) | Deterministic daily calorie target calculation from profile and weight goal |
| [weight-entries.md](weight-entries.md) | Weight-entry data model and create/list-by-range/delete API |

## Current Contract Principles

- Store canonical units: kcal, grams, milliliters, seconds, meters, kilograms.
- Display units are user preferences, not storage units.
- LLM output is never trusted until schema-validated.
- User-owned data must carry user ownership at the persistence boundary.
- Global source facts must not contain user-specific habits.
- Evidence retrieval contracts must separate source facts from user-specific log
  events, corrections, and preferences.
