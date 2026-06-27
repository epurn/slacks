---
id: FTY-061
state: ready_with_notes
primary_lane: estimator
touched_lanes:
  - contracts
  - backend-core
  - security-privacy
risk: high
tags:
  - estimator
  - evidence
  - nutrition-label
  - vision
  - llm-provider
  - attachments
approved_dependencies: []
requires_context:
  - docs/stories/README.md
  - docs/contracts/README.md
  - docs/contracts/llm-provider.md
  - docs/contracts/food-resolution.md
  - docs/contracts/parse-candidates.md
  - docs/contracts/estimation-jobs.md
  - docs/contracts/log-events.md
  - docs/architecture/evidence-retrieval.md
  - docs/security/security-baseline.md
  - docs/security/threat-model.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
review_focus:
  - llm-provider-contract-bump
  - untrusted-image-input
  - evidence-retention
  - attachment-retention-default
  - ssrf-egress
  - migration-rollback
autonomous: true
---

# FTY-061: Nutrition Label Image Extraction

## State

ready_with_notes

## Lane

estimator

## Dependencies

- FTY-040
- FTY-041
- FTY-044
- FTY-045

## Outcome

A user-provided nutrition-label image resolves into structured, schema-validated
nutrition facts (calories + macros) stored as source evidence on a derived food
item, with the source status surfaced. The label is read by a vision-capable LLM
behind the existing provider contract, the model output is trusted only after it
validates against a Pydantic nutrition-panel schema, calories/macros are computed
deterministically from the validated panel facts plus the serving/quantity, and
the raw image is discarded after extraction unless the user explicitly saved it.

## Scope

- Extend the **LLM provider contract to version 2**: add an **optional image
  input** to `structured_completion` (e.g.
  `structured_completion(prompt, schema, images=...)` or equivalent) so a
  vision-capable model can extract structured output from an image plus a prompt.
  The image + schema cross the **same validation trust boundary** as text: model
  output is untrusted until it validates against the supplied Pydantic schema.
  Requiring a vision-capable model when image input is used is part of the
  contract; per-provider multimodal mechanics (OpenAI image content parts vs.
  Anthropic image blocks) are implementation details behind the interface.
- Define the **nutrition-panel extraction schema** (a strict Pydantic model,
  `extra="forbid"`, bounded fields) capturing the panel facts needed for
  calories + macros (energy kcal, protein, carbs, fat, serving size + unit,
  servings-per-container as available) and a confidence/legibility signal.
- Implement the **label-resolution pipeline step** against FTY-040's step
  interface: it takes a user-provided label image, calls the extended provider
  with the nutrition-panel schema, validates the reply, and on success writes a
  resolved `derived_food_items` row with deterministic calories/macros.
- **Compute calories/macros deterministically** from the validated panel facts +
  the serving/quantity, reusing FTY-044's serving math (`food_serving.py`) where
  applicable; store canonical units (kcal, grams). The LLM never supplies the
  final calorie/macro math directly — it extracts panel facts that the backend
  calculators turn into the stored values.
- Store extracted facts as **`evidence_sources`** with a label source type
  (`user_provided_label`), high in the source hierarchy (a user-provided label
  outranks a generic database lookup). Store the source reference, content hash,
  fetch/extraction timestamp, and the immutable extracted-facts snapshot — never
  the raw model output beyond the schema-validated fields.
- Introduce the **`log_attachments`** table (the table slated for FTY-060/061 in
  `log-events.md`) and its DTO, used to hold an image **only when the user
  explicitly saves it**. By default no raw image is persisted: the label image is
  retained only while needed for extraction and discarded afterward.
- Route deterministically per FTY-042 + the `log-events` state machine: a label
  that cannot be read confidently routes to `needs_clarification` (or terminal
  `failed` for unusable/oversized/invalid input), never a guessed estimate.

## Non-Goals

- **No mobile capture UI** — camera/upload flow is separate story **FTY-064**.
  This is the backend/estimator slice only.
- Barcode lookup (FTY-060) and official-source web search/fetch (FTY-062).
- Manual hand-entry of label facts as a UI (this story covers the
  extraction-from-image path and its evidence/storage contracts).
- Recipe calculation, complex portion inference / `portion_memories`, and saved
  foods/aliases (Milestone 5).
- Changing the existing text-only parse step (FTY-042) behavior; the provider
  text-only path stays backward-compatible.

## Contracts

- **`llm-provider` contract → version 2**: `structured_completion` gains an
  **optional** image argument (defaults to none). The text-only signature stays
  backward-compatible; image input requires a vision-capable configured model.
  The privacy rules (no prompts, no images, no raw responses in logs) extend to
  cover image inputs. Per-provider multimodal mechanics stay behind the contract.
- **Nutrition-panel extraction schema**: a new strict Pydantic model expressing
  both the JSON schema sent to the provider and the validator for the reply.
- **`log_attachments` table + DTO**: new user-owned table for an explicitly-saved
  image; default behavior persists no raw image. (Resolves the
  `log-events.md` "excluded: `log_attachments` (FTY-060/061)" placeholder.)
- **Label-resolution pipeline step output**: resolved `derived_food_items`
  (canonical calories/macros + grams) plus a `evidence_sources` row with the
  `user_provided_label` source type, written in the same transaction as the
  terminal status, consistent with FTY-044's persistence/routing pattern.

## Security / Privacy

- **Untrusted image input.** The label image is untrusted user-supplied content.
  Extracted facts are trusted only after they validate against the Pydantic
  nutrition-panel schema and pass the deterministic calculators; prompt-injection
  text embedded in a label image is never executed or followed (data, not
  instructions).
- **No raw image / prompt / response logging.** Per the provider privacy rules
  (extended to v2), keys, prompts, images, and raw responses are never logged;
  logs carry only provider label, attempt, outcome, and error counts. Estimation
  runs store sanitized metadata only.
- **Attachment retention default = discard.** Per `data-retention.md`, the label
  image is retained only while needed for extraction and discarded afterward
  unless the user explicitly saves the attachment. `log_attachments` holds an
  image only on an explicit save; default flow persists no raw image. Avoid
  long-term raw OCR/vision-text retention — store extracted facts + source
  metadata (content hash, timestamp), not raw model output beyond the
  schema-validated fields.
- **Upload constraints.** Enforce image size and content-type limits; reject
  oversized or non-image input deterministically (terminal `failed`) before any
  provider call.
- **Egress / SSRF.** The image is sent only to the configured LLM provider; no
  other network egress. If the image is ever referenced by URL rather than
  inline bytes, the existing hardened-fetch/SSRF policy applies; the default path
  takes uploaded bytes and performs no outbound fetch beyond the provider.
- **Evidence, not pages.** `evidence_sources` stores source reference, content
  hash, timestamp, and the extracted facts snapshot — never raw model output or a
  raw stored image (unless the user explicitly saved the attachment).
- Rated **high**: a public provider-contract change, untrusted image input, new
  evidence/attachment retention, and a migration introducing `log_attachments`.

## Acceptance Criteria

- A nutrition-label image yields **schema-validated** panel facts and produces a
  resolved `derived_food_items` row with deterministic calories/macros via the
  **extended (v2) provider**, with an `evidence_sources` row carrying the
  `user_provided_label` source type and source status surfaced.
- The provider **text-only path is unchanged** — a backward-compatibility test
  proves `structured_completion(prompt, schema)` still works without an image.
- By default the **raw image is discarded** after extraction; it is persisted in
  `log_attachments` **only** when the user explicitly saves it (retention test).
- An **unreadable / low-confidence** label routes deterministically to
  `needs_clarification` (and unusable/oversized/invalid input to terminal
  `failed`) — never a guessed estimate.
- The `log_attachments` migration **applies and rolls back** cleanly against a
  throwaway database; it is additive (no destructive change to prior tables).
- Negative tests prove the **egress/SSRF** boundary (image goes only to the
  configured provider) and **oversize/invalid-image** rejection fail closed.
- `make verify` passes with a **fake/stubbed vision provider** (no real provider
  calls in tests).

## Verification

- Run `make verify` with a stubbed vision provider, including:
  - a happy-path test: label image → validated panel facts → resolved
    `derived_food_items` + `evidence_sources` (`user_provided_label`);
  - a provider **backward-compat** test: text-only `structured_completion` is
    unchanged;
  - a **retention** test: default flow persists no raw image; explicit-save flow
    writes one `log_attachments` row;
  - an **adversarial / unreadable label** test: routes to
    `needs_clarification`/`failed`, nothing guessed, prompt-injection in the
    image is not followed;
  - **security negatives**: oversize/invalid content-type rejected before any
    provider call; no network egress beyond the configured provider; no image /
    prompt / raw response in logs;
  - deterministic **serving-math** unit tests for calories/macros from validated
    panel facts (reusing/extending FTY-044's serving math).
- Apply/roll back the `log_attachments` migration against a throwaway database.

## Planning Notes

- **Provider contract bump (v2).** This story changes a public contract:
  `structured_completion` gains an optional image argument. Keep the text-only
  signature backward-compatible (image arg optional, defaults to none) and bump
  `docs/contracts/llm-provider.md` to version 2. Image input requires a
  vision-capable configured model; document this requirement and the
  per-provider multimodal mechanics as implementation details behind the
  interface.
- **Vision model required.** When image input is used, the configured
  `FATTY_LLM_MODEL` must be vision-capable; surface a clear configuration/
  capability error when it is not, consistent with the contract's fail-fast
  config validation.
- The exact migration number follows the latest applied migration at
  implementation time (FTY-044 introduced `0007`; Milestone 5 stories add later
  migrations); the `log_attachments` migration must be additive and reversible.
- Source-hierarchy ordering (user-provided label outranks generic database
  lookup) follows `evidence-retrieval.md`; reuse FTY-044/FTY-045 evidence
  conventions rather than re-deciding them.
- If FTY-060 (barcode) lands first and introduces `log_attachments`, this story
  reuses that table rather than re-creating it; both stories are scoped to own
  the table per `log-events.md` — coordinate so only one migration creates it.

## Readiness Sanity Pass

- **Product decision gaps:** none blocking — extraction approach (extend provider
  to v2 with optional image input), evidence storage (`evidence_sources`,
  `user_provided_label`), deterministic calories/macros, attachment retention
  default (discard unless saved via `log_attachments`), and deterministic routing
  for unreadable labels are all resolved.
- **Cross-lane impact:** changes the public `llm-provider` contract (v2), adds the
  nutrition-panel schema, introduces the `log_attachments` table/DTO and the
  label-resolution pipeline step, and writes `evidence_sources` — touching
  contracts, backend-core, and security-privacy. Mobile capture is deferred to
  FTY-064.
- **Security/privacy risk:** high — untrusted image input, a provider-contract
  change, evidence + attachment retention, and a new migration. Mitigated by
  schema validation as the trust boundary, deterministic calculators, no
  image/prompt/response logging, discard-by-default attachment retention,
  upload size/content-type limits, provider-only egress, and fail-closed
  negative tests.
- **Verification path:** `make verify` with a fake/stubbed vision provider
  (happy path, provider backward-compat, retention, adversarial/unreadable,
  SSRF/egress + oversize negatives, serving-math units) plus migration
  apply/rollback.
- **Assumptions safe for autonomy:** yes — carries non-blocking notes (the
  provider v2 contract bump and the vision-model-required requirement); mobile
  capture and barcode/`log_attachments` ownership coordination are documented.
