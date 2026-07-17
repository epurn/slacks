# Contract: Nutrition Label Extraction

## Purpose

Define the **nutrition-label extraction step** (FTY-061) of the estimation
pipeline: how a user-provided nutrition-**label image** becomes a costed
`derived_food_items` row carrying canonical **calories and macros**, with the
extracted facts stored as user-owned `evidence_sources` at the top of the source
hierarchy (`user_label`), the calories/macros computed **deterministically** by
the backend, and the raw image discarded after extraction unless the user
explicitly saved it.

This covers four things:

1. the **nutrition-panel extraction schema** (`schemas/nutrition_panel.py`) — the
   strict Pydantic model sent to the v2 vision provider and the validator every
   reply must pass before any of it is trusted;
2. the **label-resolution pipeline step** (`estimator/label_step.py`) — image
   validation, the vision-provider call, disposition routing, and the deterministic
   calc;
3. the **deterministic serving math** added to `food_serving.py` — printed
   per-serving facts + serving/quantity → canonical per-100g facts → stored
   calories/macros (reusing FTY-044's rule);
4. the **persistence + retention** — a resolved `derived_food_items` row plus a
   `user_label` `evidence_sources` row written in the same transaction as the
   terminal status, and discard-by-default raw-image retention via FTY-077.

It consumes the **v2 LLM provider** (`llm-provider.md`, FTY-076 — optional image
input), the **`log_attachments`** table + retention (`log-attachments.md`,
FTY-077), the **evidence source hierarchy** (`evidence-retrieval.md`, FTY-045 —
`user_label` is rank 1), and plugs into FTY-040's pipeline-step interface and
status transitions (`estimation-jobs.md`). It excludes the provider contract change
and the `log_attachments` table/retention rules (consumed, not defined here), the
mobile capture/upload UI (FTY-064), barcode (FTY-060), official-source search
(FTY-062), manual hand-entry of label facts, and recipe calculation.

## Owner

estimator / backend-core lane: `backend/app/schemas/nutrition_panel.py`,
`backend/app/estimator/label_step.py`, `backend/app/estimator/food_serving.py`
(`serving_size_grams`, `per_serving_to_per_100g`), and the label wiring in
`backend/app/estimator/pipeline.py` (`label_pipeline`),
`backend/app/estimator/processing.py` (label pipeline selection), and
`backend/app/estimator/persist.py` (label persistence, retention). No new table
or migration: it reuses `derived_food_items`,
`evidence_sources` (FTY-044), and `log_attachments` (FTY-077).

## Version

2 (FTY-370, contract only). Reconciles the async-worker retry/terminal wording
below with `estimation-jobs.md` v7's never-fail semantics: a `provider_transient_error`
(`StepError`) that exhausts the bounded retries no longer lands terminal `failed`
— the worker **degrades** (a rough, honestly-labelled estimate when ≥1 candidate
was interpreted, otherwise the honest still-working `processing` state). Terminal
`failed` stays reserved for the deterministic non-food/unusable/schema-invalid
gates. The synchronous single-attempt label seam (`label-upload.md`) is unchanged.
No schema, provider, or validation change.

1 (FTY-061). The source-hierarchy classification `user_label` (rank 1, above any
database lookup) is recorded on the estimation run `source_refs` and on each
`evidence_sources` row this step produces.

## Inputs

### The label image + consumed quantity (`LabelInput`)

A user-provided label image is `(data: bytes, content_type: str)` plus the consumed
quantity (`unit` / `amount` / `quantity_text`, defaulting to **one serving**:
`amount = 1`, count unit) and an explicit `save` flag (the FTY-077 retention
choice). The image is untrusted user content; it is validated as **data** before
anything else (size + content-type allowlist + magic-number signature, reusing
`services/attachments.validate_upload`) and an invalid image fails closed without
any model call. The HTTP upload path that supplies this (mobile capture) is FTY-064
(`label-upload.md`); this contract is the backend pipeline that consumes a validated
upload.

### Nutrition-panel extraction schema (`NutritionPanel`)

The strict schema the step asks `Provider.structured_completion` to enforce and the
validator every reply must pass. Defence-in-depth mirrors `parse-candidates.md`:
`extra="forbid"` on every model, every numeric field bounded (`ge`/`le`/`gt`),
string fields length-bounded, and a closed `disposition` vocabulary.

| Field | Type | Notes |
| --- | --- | --- |
| `disposition` | enum | `extracted` \| `unreadable` \| `not_a_label`. |
| `confidence` | float [0,1] | Extraction confidence; gated by the shared FTY-159 clarify-policy mechanism (`app/estimator/clarify_policy.py`, `LABEL_CLARIFY_POLICY`). The label operating point (0.5) is a **documented tunable**, not data-derived — no label-image eval set exists yet; a dedicated label-image eval slice is the recorded follow-up (see `clarify-gates.md`, "Calibrated clarify decision"). |
| `facts` | `PanelFacts \| null` | Required when `extracted`; ignored otherwise. |
| `reason` | string? | Short sanitized label for `not_a_label`; never echoed image text. |

`PanelFacts` carries the transcribed **per-serving** values: `product_name?`,
`serving_size_amount` (>0), `serving_size_unit`, `servings_per_container?`,
`energy_kcal_per_serving`, `protein_g_per_serving`, `carbs_g_per_serving`,
`fat_g_per_serving`. The model transcribes only; it never computes totals, per-100g
values, or the amount consumed.

## Outputs

### Deterministic serving math

The backend — never the model — turns the validated panel into stored numbers:

1. `serving_size_grams(amount, unit)` resolves the printed serving size to grams
   (mass/volume only, 1 ml ≈ 1 g; a count-only serving size like "1 bar" fails
   closed → `needs_clarification`).
2. `per_serving_to_per_100g(per_serving, serving_g)` canonicalises the per-serving
   facts to per-100g (`× 100 / serving_g`).
3. `resolve_grams(unit, amount, quantity_text, default_serving_g=serving_g)`
   (FTY-044, unchanged) resolves the **consumed** quantity to grams; the label's
   serving size is the default for a count quantity.
4. `scale_facts(per_100g, grams)` (FTY-044) scales to the consumed portion, rounded
   to 0.1. Storage is canonical (kcal, grams).

### Persistence

On a legible, confident panel the worker writes, in the **same transaction** as the
terminal `completed` status:

- a **`proposed`** (uncounted, FTY-196) **`derived_food_items`** row (canonical
  `calories`/macros + `grams`, with the original snapshot captured for FTY-051
  corrections). The deterministic serving math is unchanged; only the item's
  committed/counted status changes — a label parse is held as an uncounted proposal
  until the user confirms it (`label-upload.md` → Confirmation gate), because "OCR
  is fallible — Slacks never silently trusts a fallible parse"
  (`docs/design-philosophy.md`). It was `resolved` (immediately counted) before
  FTY-196;
- a user-owned **`evidence_sources`** row with `source_type = user_label`,
  `source_ref = user_label:<content_hash>`, the image `content_hash`, the extraction
  timestamp, and the immutable per-100g facts snapshot. `product_id` is **null** —
  a label is user-provided evidence, not a global cache row.

The run records `user_label` in `source_refs`.

### Worked example

```
label image (image/png) + consumed quantity default (1 serving)
panel facts: serving 40 g, 200 kcal / 10 P / 20 C / 8 F per serving
  → serving_g = 40; per-100g = 500 kcal / 25 P / 50 C / 20 F
  → consumed grams = 1 × 40 = 40
  → calories = 200.0; protein 10.0; carbs 20.0; fat 8.0
  → derived_food_items += Trail Mix (proposed/uncounted, calories 200.0, grams 40)
  → evidence_sources += user_label:<sha256> (hash, extracted_at, per-100g snapshot)
  → run.source_refs += "user_label"; event: processing → completed
  → raw image discarded (no log_attachments row) unless save=true
```

## Validation

- **Image is data.** Validated fail-closed (size, content-type allowlist, signature)
  before any model call. Prompt-injection text printed on the label is data, never
  instructions.
- **Untrusted analyst.** The reply is trusted only after it validates against
  `NutritionPanel`; a schema-invalid reply is rejected (`StepFailed`), never
  persisted.
- **Legibility.** `unreadable`, confidence below the clarify policy's operating
  point (`LABEL_CLARIFY_POLICY`), or missing facts → `needs_clarification`
  (never a guessed estimate).
- **Serving / quantity.** A serving size or consumed quantity that does not resolve
  to grams → `needs_clarification`.

## Outputs / Routing

| Condition | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| Legible, confident panel + resolvable serving/quantity | _(completes)_ | food **`proposed`** (uncounted, `user_label`) + `evidence_sources` — confirm to count (FTY-196) | `processing → completed` |
| Unreadable / low-confidence / missing facts | `NeedsClarification` (`label_unreadable`) | clarification question | `processing → needs_clarification` |
| Unresolvable serving size or quantity | `NeedsClarification` | clarification question | `processing → needs_clarification` |
| Not a nutrition label (unusable input) | `StepFailed` (`unusable_label`) | nothing | `processing → failed` |
| Invalid/mistyped image bytes | `StepFailed` (`invalid_label_image`) | nothing | `processing → failed` |
| Schema-invalid reply | `StepFailed` (`schema_validation_failed`) | nothing | `processing → failed` |
| Transient provider failure | `StepError` (retryable) | rough estimate on degrade (`food-resolution.md` v22) | retries within bound, then **degrades** (FTY-370, `estimation-jobs.md` v7): `processing → completed` / `partially_resolved` with ≥1 interpreted candidate, else honest still-working `processing`; never terminal `failed` |

## Authorization

Every `derived_food_items` and `evidence_sources` row carries `user_id` at the
persistence boundary, written scoped to the owning event's user (the worker loaded
the event scoped to the job's `user_id`; see `estimation-jobs.md`). A saved
`log_attachments` row is authorized the same way (`AttachmentForbidden` on a
cross-user save). `ON DELETE CASCADE` from `users` and `log_events` enforces
object-level ownership and retention.

## Privacy and Retention

- **Untrusted image input → trusted only after validation.** Extracted facts are
  trusted only after they pass the Pydantic schema and the deterministic
  calculators. Prompt injection embedded in the image is never followed.
- **Evidence, not raw output.** `evidence_sources` stores the source reference,
  content hash, extraction timestamp, and the extracted-facts snapshot — **never**
  raw model output or the raw image.
- **Discard by default.** The raw image is discarded after extraction; it is
  persisted in `log_attachments` only on an explicit user save (FTY-077), and never
  on a failed extraction. A saved image shares its evidence's `content_hash`, so the
  two correlate without a foreign key.
- **No image / prompt / raw-response logging** (inherited from the FTY-076 v2
  privacy rules). The run records only sanitized metadata.

## Errors

| Condition | Result |
| --- | --- |
| Invalid / mistyped / oversized image | Terminal `failed` (`invalid_label_image`); no model call, nothing persisted. |
| Image is not a nutrition label | Terminal `failed` (`unusable_label`); nothing guessed. |
| Schema-invalid provider reply | Terminal `failed` (`schema_validation_failed`); rejected, never persisted. |
| Unreadable / low-confidence label | `needs_clarification` (`label_unreadable`). |
| Unresolvable serving size / quantity | `needs_clarification`. |
| Transient provider error | `StepError`; retried within the bound, then **degrades** (FTY-370) per `estimation-jobs.md` v7 — a rough, honestly-labelled estimate when ≥1 candidate was interpreted, else the honest still-working `processing` state; never terminal `failed`. (The synchronous single-attempt label seam is `label-upload.md`; this row is the async worker path.) |

## Examples

The schema bounds, the deterministic serving math, and the end-to-end extraction
(with a stubbed vision provider — happy path, unreadable, not-a-label, injection,
schema-invalid, retention default vs. save) are covered by
`backend/tests/test_nutrition_panel_schema.py`,
`backend/tests/test_label_serving.py`, and
`backend/tests/test_label_resolution.py`.

## Migration / Compatibility

- **No new table or migration.** Reuses `derived_food_items` and `evidence_sources`
  (FTY-044, `0007`) and `log_attachments` (FTY-077, `0011`). `evidence_sources`
  already permits a null `product_id` (`ON DELETE SET NULL`), which the label path
  uses.
- Additive to the pipeline: `label_pipeline` is a separate composition from
  `default_pipeline`; the text parse/exercise/food path is unchanged.
- **FTY-196 (no migration).** The persisted label item's status changes from
  `resolved` to `proposed` (the uncounted confirmation-gate state); `status` is a
  `VARCHAR`, so the new value needs no schema migration. Only the label path writes
  `proposed`; the text food/exercise resolution still commits `resolved`. The
  read/confirm API for the proposal lives in `label-upload.md`.
