---
id: FTY-061
state: ready
primary_lane: estimator
touched_lanes:
  - backend-core
risk: high
tags:
  - estimator
  - evidence
  - nutrition-label
  - vision
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/food-resolution.md
  - docs/contracts/parse-candidates.md
  - docs/contracts/estimation-jobs.md
  - docs/architecture/evidence-retrieval.md
  - docs/standards/testing-standards.md
review_focus:
  - untrusted-image-input
  - evidence-retention
  - deterministic-calorie-macro-calc
  - unreadable-label-routing
autonomous: true
---

# FTY-061: Nutrition Label Extraction Pipeline (Backend)

## State

ready

> 2026-06-27: split. This story was over-scoped (it bundled a public provider
> contract change, a new table + migration, and the extraction pipeline into one
> run) and churned through several failed author runs. The two "big rocks" were
> carved out as prerequisites — **FTY-076** (provider v2 image input) and
> **FTY-077** (`log_attachments` table + discard-by-default retention) — and this
> story is now just the extraction pipeline that depends on them. The steward
> will not assign it until FTY-076 and FTY-077 merge.

## Lane

estimator

## Dependencies

- FTY-040
- FTY-041
- FTY-044
- FTY-045
- FTY-076 (provider v2 — optional image input)
- FTY-077 (log_attachments table + discard-by-default retention)

## Outcome

A user-provided nutrition-label image resolves into structured, schema-validated
nutrition facts (calories + macros) stored as source evidence on a derived food
item, with the source status surfaced. The label is read by the **v2 vision
provider (FTY-076)**, model output is trusted only after it validates against a
Pydantic nutrition-panel schema, calories/macros are computed **deterministically**
from the validated facts plus serving/quantity, and the raw image is discarded
after extraction unless the user explicitly saved it via **`log_attachments`
(FTY-077)**.

## Scope

- Define the **nutrition-panel extraction schema** (a strict Pydantic model,
  `extra="forbid"`, bounded fields): energy kcal, protein, carbs, fat, serving
  size + unit, servings-per-container as available, plus a confidence/legibility
  signal.
- Implement the **label-resolution pipeline step** against FTY-040's step
  interface: take a user-provided label image, call the **v2 provider (FTY-076)**
  with the nutrition-panel schema, validate the reply, and on success write a
  resolved `derived_food_items` row.
- **Compute calories/macros deterministically** from the validated panel facts +
  serving/quantity, reusing FTY-044's serving math (`food_serving.py`); store
  canonical units (kcal, grams). The LLM never supplies the final math — it
  extracts panel facts the backend calculators turn into stored values.
- Store extracted facts as **`evidence_sources`** with a `user_provided_label`
  source type, high in the source hierarchy (a user-provided label outranks a
  generic database lookup). Store source reference, content hash, extraction
  timestamp, and the immutable extracted-facts snapshot — never raw model output
  beyond the schema-validated fields.
- Persist the raw image only via **`log_attachments` (FTY-077)** and only on an
  explicit user save; the default path discards it after extraction.
- Route deterministically per FTY-042 + the `log-events` state machine: a label
  that cannot be read confidently routes to `needs_clarification` (terminal
  `failed` for unusable input), never a guessed estimate.

## Non-Goals

- The **provider contract change** (FTY-076) and the **`log_attachments` table /
  retention rules** (FTY-077) — this story consumes both, it does not define them.
- **Mobile capture UI** (FTY-064); barcode (FTY-060); official-source search
  (FTY-062).
- Manual hand-entry of label facts; recipe calculation; portion memories; saved
  foods/aliases.
- Changing the existing text-only parse step (FTY-042) behavior.

## Contracts

- **Nutrition-panel extraction schema**: a new strict Pydantic model expressing
  both the JSON schema sent to the provider and the validator for the reply.
- **Label-resolution pipeline step output**: resolved `derived_food_items`
  (canonical calories/macros + grams) plus an `evidence_sources` row with the
  `user_provided_label` source type, written in the same transaction as the
  terminal status, consistent with FTY-044's persistence/routing pattern.

## Security / Privacy

- **Untrusted image input.** The label image is untrusted user content; extracted
  facts are trusted only after they validate against the Pydantic schema and pass
  the deterministic calculators. Prompt-injection text embedded in a label image
  is data, never instructions.
- **Evidence, not raw output.** `evidence_sources` stores source reference,
  content hash, timestamp, and the extracted-facts snapshot — never raw model
  output. Raw image retention is governed entirely by FTY-077 (discard by
  default).
- **No image / prompt / raw-response logging** (inherited from the FTY-076 v2
  privacy rules).
- Rated **high**: untrusted image input feeding stored evidence on the estimator
  path. (The contract change and the migration/retention surface now live in
  FTY-076 / FTY-077.)

## Acceptance Criteria

- A nutrition-label image yields **schema-validated** panel facts and produces a
  resolved `derived_food_items` row with **deterministic** calories/macros via
  the v2 provider, with an `evidence_sources` row carrying `user_provided_label`
  and the source status surfaced.
- An **unreadable / low-confidence** label routes deterministically to
  `needs_clarification` (unusable input → terminal `failed`) — never a guessed
  estimate; prompt-injection in the image is not followed.
- By default the **raw image is discarded** after extraction; it is persisted in
  `log_attachments` only on an explicit save (consuming FTY-077).
- Deterministic **serving-math** unit tests cover calories/macros from validated
  panel facts (reusing/extending FTY-044's serving math).
- `make verify` passes with a **fake/stubbed vision provider** (no real provider
  calls).

## Verification

- `make verify` with a stubbed vision provider, including:
  - happy path: label image → validated panel facts → resolved
    `derived_food_items` + `evidence_sources` (`user_provided_label`);
  - adversarial / unreadable label: routes to `needs_clarification`/`failed`,
    nothing guessed, prompt-injection in the image not followed;
  - retention: default flow stores no image; explicit-save writes one
    `log_attachments` row (via FTY-077);
  - deterministic serving-math units for calories/macros.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — extraction approach, evidence
  storage, deterministic calc, and unreadable-label routing are resolved; the
  contract and retention decisions are settled in FTY-076/FTY-077.
- **Cross-lane impact:** estimator (pipeline + evidence) + backend-core
  (calculators, persistence). One touched lane; the contracts and
  security-privacy big rocks moved to FTY-076/FTY-077.
- **Security/privacy risk:** high — untrusted image input feeding stored
  evidence; mitigated by schema-validation trust boundary, deterministic
  calculators, evidence-not-raw-output storage, and inherited no-logging +
  discard-by-default rules.
- **Verification path:** `make verify` with a stubbed vision provider (happy,
  adversarial, retention, serving-math).
- **Assumptions safe for autonomy:** yes — gated behind FTY-076 + FTY-077, which
  the steward enforces via dependencies before assigning this story.
- **Sizing:** 1 touched lane, 4 review_focus, 6 requires_context — within the
  scope guardrail after the split.
