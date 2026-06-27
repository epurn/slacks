---
id: FTY-076
state: merged
primary_lane: contracts
touched_lanes:
  - backend-core
risk: high
tags:
  - llm-provider
  - vision
  - contracts
approved_dependencies: []
requires_context:
  - docs/contracts/llm-provider.md
  - docs/security/security-baseline.md
  - docs/standards/testing-standards.md
review_focus:
  - llm-provider-contract-bump
  - vision-model-required-config
  - image-input-privacy-logging
  - text-only-backward-compat
autonomous: true
---

# FTY-076: LLM Provider Contract v2 — Optional Image Input

## State

ready

## Lane

contracts

## Dependencies

(none — extends the existing `llm-provider` contract)

## Outcome

The `llm-provider` contract gains a backward-compatible way to send an image
alongside the prompt + schema, so a vision-capable model can extract structured
output from an image. Text-only callers are completely unaffected. This is the
contract-only prerequisite for nutrition-label extraction (FTY-061); it ships no
extraction pipeline of its own.

## Scope

- Bump the **`llm-provider` contract to version 2**: add an **optional image
  argument** to `structured_completion` (e.g. `structured_completion(prompt,
  schema, images=...)` or equivalent), defaulting to none. The text-only
  signature stays byte-for-byte backward-compatible.
- The image + schema cross the **same validation trust boundary** as text: model
  output is untrusted until it validates against the supplied Pydantic schema.
- **Vision-capable model required when an image is supplied.** Surface a clear,
  fail-fast configuration/capability error when image input is used with a
  non-vision model, consistent with the contract's existing config validation.
- Per-provider multimodal mechanics (OpenAI image content parts vs. Anthropic
  image blocks) are **implementation details behind the interface**.
- **Privacy rules extend to images:** keys, prompts, **images**, and raw
  responses are never logged; logs carry only provider label, attempt, outcome,
  and error counts.
- Update `docs/contracts/llm-provider.md` to v2 documenting all of the above.

## Non-Goals

- The nutrition-panel extraction schema, the label-resolution pipeline step, and
  evidence/calorie computation — those are **FTY-061**.
- The `log_attachments` table and attachment retention — those are **FTY-077**.
- Any change to text-only `structured_completion` behavior.

## Contracts

- **`llm-provider` → version 2.** `structured_completion` gains an optional image
  argument (defaults to none); text-only signature unchanged; image input
  requires a vision-capable configured model; privacy rules cover image inputs.

## Security / Privacy

- **Untrusted image input** is data, not instructions: extracted output is
  trusted only after it validates against the caller's Pydantic schema. (The
  schema itself is defined by the caller — here, FTY-061.)
- **No image / prompt / raw-response logging** under the v2 privacy rules.
- Rated **high**: a public provider-contract change.

## Acceptance Criteria

- A **backward-compat** test proves `structured_completion(prompt, schema)` still
  works unchanged with no image argument.
- A test with a **stubbed vision provider** proves an image + schema returns
  schema-validated structured output (no real provider calls).
- Using image input with a **non-vision** configured model raises a clear
  fail-fast configuration error before any provider call.
- A logging test proves no image, prompt, or raw response is written to logs.
- `docs/contracts/llm-provider.md` reads version 2 and documents the optional
  image argument + vision-model requirement.

## Verification

- `make verify` with a fake/stubbed vision provider, including the backward-compat
  test, the stubbed vision happy-path, the non-vision config-error test, and the
  no-image-logging test.

## Readiness Sanity Pass

- **Product decision gaps:** none — optional argument, default none, vision model
  required when used; mechanics are per-provider implementation details.
- **Cross-lane impact:** changes the public `llm-provider` contract (contracts)
  and its backend implementation (backend-core). One touched lane.
- **Security/privacy risk:** high — a public contract change and a new (image)
  input channel; mitigated by schema-validation trust boundary and extended
  no-logging rules.
- **Verification path:** `make verify` with a stubbed vision provider; no real
  provider calls in tests.
- **Assumptions safe for autonomy:** yes — scoped to the contract + provider
  implementation; consumers (FTY-061) are separate stories.
- **Sizing:** 1 touched lane, 4 review_focus, 4 requires_context — well within
  the scope guardrail. Deliberately carved out of the former oversized FTY-061 as
  the standalone contract slice.
