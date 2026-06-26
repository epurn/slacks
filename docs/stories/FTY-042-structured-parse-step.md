---
id: FTY-042
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - contracts
  - backend-core
  - security-privacy
review_focus:
  - prompt-injection
  - schema-validation
  - adversarial-input
  - migration-rollback
risk: high
tags:
  - estimator
  - parsing
  - llm
  - candidates
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/architecture/system-overview.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-042: Structured Parse Step

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-040
- FTY-041

## Outcome

The estimator pipeline parses a log event's natural-language text into schema-validated food and exercise candidates, or marks the event as needing clarification, persisting candidates for the calculation steps.

## Scope

- Implement the parse pipeline step (plugging into the FTY-040 pipeline) that sends the event's raw text through FTY-041's `structured_completion` with a strict candidate schema.
- Candidate schema (minimal, validated): per item a `type` (food | exercise), `name`, a raw `quantity`/`portion` string, and optional parsed unit/amount. Downstream calculators (FTY-043/044) resolve specifics.
- Persist candidates as `derived_food_items` and `derived_exercise_items` rows in an unresolved state (no calories yet); migrate these tables here.
- Produce `needs_clarification` when input is ambiguous or low-confidence: store one or more `clarification_questions` (migrate this table) and transition the event to `needs_clarification`. The clarification **answer** flow and UI are a later story; questions persist unanswered for now.
- On unparseable/empty/garbage input, mark the event `failed` with a reason.
- Treat all model output as untrusted: schema-validate before persisting; never execute or trust embedded instructions (prompt-injection resistant).

## Non-Goals

- Calorie/macro resolution (FTY-044) and exercise burn (FTY-043).
- The clarification answer flow, `clarification_answers`, and UI (later story).
- Source lookup, search, or fetching (Milestone 6).
- Saved foods, aliases, or memory (Milestone 5).

## Contracts

- The candidate schema and the `derived_food_items` / `derived_exercise_items` (unresolved) and `clarification_questions` table contracts.
- Consumes FTY-041's `structured_completion` and FTY-040's pipeline-step interface and status transitions.

## Security / Privacy

The LLM is untrusted: output is schema-validated and any embedded instructions are ignored (prompt-injection tests required, failing closed). Raw text and model output are not logged beyond sanitized form. Candidates and clarification questions are user-owned with object-level authorization. Retention follows derived-data rules. Rated high: LLM trust boundary, adversarial input, contracts, and migrations.

## Acceptance Criteria

- Valid NL input yields schema-validated food/exercise candidates persisted in an unresolved state.
- Schema-invalid model output is rejected and never persisted; the step fails closed.
- Ambiguous/low-confidence input creates `clarification_questions` and sets the event to `needs_clarification`.
- Empty/garbage/adversarial input marks the event `failed` with a reason and never executes embedded instructions (prompt-injection tests pass).
- Migrations apply and roll back; records carry user ownership.
- `make verify` passes (schema-validation, adversarial-input, and prompt-injection tests with the fake provider).

## Verification

- Run `make verify` using the fake provider, including adversarial-input and prompt-injection negative tests.
- Apply/roll back the `derived_food_items` / `derived_exercise_items` / `clarification_questions` migrations.

## Planning Notes

- Confidence thresholds for routing to `needs_clarification` are documented tunables; start conservative.
- Because the clarification answer flow is later, `needs_clarification` events are terminal-for-now in the UI; this is an accepted interim state.

## Readiness Sanity Pass

- Product decision gaps: none blocking — minimal candidate schema and "produce needs_clarification now" are resolved.
- Cross-lane impact: defines candidate + clarification contracts consumed by FTY-043/044 and the later clarification story.
- Security/privacy risk: high; untrusted LLM output, prompt injection, sensitive text, mitigated by schema validation failing closed.
- Verification path: `make verify` with adversarial + prompt-injection tests + migration rollback.
- Assumptions safe for autonomy: yes; confidence thresholds are documented tunables (notes).
