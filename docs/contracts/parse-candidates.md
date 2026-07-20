# Contract: Parse Candidates & Clarification Questions

## Purpose

Define the structured **parse step** (FTY-042) of the estimation pipeline: how a
`pending` log event's raw text becomes schema-validated food/exercise
**candidates** (persisted unresolved), or **clarification questions** when the
input is ambiguous, or a terminal **failure** when it is empty or genuinely not
food/exercise at all, or the model output is invalid.

This covers three things:

1. the **LLM structured-output schema** (`ParseResult`) the step asks the
   provider to enforce and validates every reply against;
2. the **`derived_food_items` / `derived_exercise_items` / `clarification_questions`**
   persistence schemas and their migration;
3. the **routing and trust boundary** — how a validated reply maps to a pipeline
   outcome, and how invalid/adversarial output fails closed.

It consumes FTY-041's `structured_completion` (see `llm-provider.md`) and plugs
into FTY-040's pipeline-step interface and status transitions (see
`estimation-jobs.md`). It excludes calorie/macro resolution (FTY-044) and
exercise burn (FTY-043). The clarification **answer** flow — the resolve
endpoint, its semantics, and the `clarification_answers` persistence — is owned
by `clarification.md` (FTY-170 defines it; FTY-171 implements); the clarify sheet
UI is FTY-153.

## Owner

estimator / contracts / backend-core lane:
`backend/app/schemas/parse.py`, `backend/app/estimator/parse.py`,
`backend/app/estimator/parse_prompt.py`,
`backend/app/estimator/self_consistency.py`,
`backend/app/estimator/clarify_policy.py`,
`backend/app/models/derived.py`, `backend/app/enums.py`
(`CandidateType`, `DerivedItemStatus`), `backend/alembic/`.

## Version

14 (FTY-385, contract only): relocates the `### Calibrated clarify decision` and
`### Deterministic plausibility gate` sections — with their trailing gate-outcome,
question-quality, atomicity, and item-scoped partial clarification (FTY-278) rules —
to [clarify-gates.md](clarify-gates.md) with no normative change; the two headings
remain as compatibility anchors that link onward.

13 (FTY-370, contract only): narrows terminal `unparseable_input` to input the
samples **unanimously** judge genuinely not food/exercise/consumable at all
(e.g. "asdf", "how's the weather"); any informal, unbranded, homemade,
compositional, or borderline-consumable description (a homemade assembly of
ingredients; gum or supplements the user is logging) routes to an estimate or a
clarifying question — never `unparseable`. `empty_input` / `schema_validation_failed` unchanged; FTY-371 implements (`estimation-jobs.md` v7).

12 (FTY-374, contract only): the parse/interpretation step gains **images as
evidence surfaces** (see
[Images as parse evidence surfaces](#images-as-parse-evidence-surfaces-fty-374))
— an event created by the unified text+image submission (`log-event-images.md`)
reaches this step with 0..N validated images alongside its `raw_text`: text
supplies identity/count/context, an image supplies label facts as
`user_label`-tier evidence, and each derived number records which surface
backed it. No `ParseResult`/persistence/routing change; FTY-376 implements.

11 (FTY-364, contract only): relocates the `### Estimate-first routing override`
and `### User-stated nutrition facts` sections to
[estimate-first-routing.md](estimate-first-routing.md) with no normative change;
the two headings remain as compatibility anchors that link onward.

10 (FTY-348, contract only): relocates the FTY-324 (v9) interpretation-session and
hypothesis-revision semantics to [interpretation-session.md](interpretation-session.md)
with no normative change; this page keeps the parse schema, sampling, routing, and
persistence rules.

8 (FTY-304, wording clarification): names the concrete FTY-300 pre-validation
provider-output repair phases governed by
`SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS`, clarifies that the cap does not
retry provider calls or repair schema-valid policy conflicts, and records the
fail-closed label when bounded repair is exhausted or unsafe. No schema,
persistence, prompt, provider, settings, or estimator behavior changes.

7 (FTY-298, contract only): adopts the shared **rare clarification /
estimate-first** policy for natural-language text logs. The parse step consumes the
mode semantics, advisory-provider-clarification rule, allowed last-resort
clarification reasons, and rough-provenance requirements now owned by
[estimator-policy.md](estimator-policy.md). This version changes the public contract
only; the settings and estimator implementation are downstream FTY-299/FTY-300/FTY-301
follow-ups.

6 (FTY-279, contract only): the parser may **extract explicit nutrition facts the
user stated** in the entry text into new optional, bounded `ParsedCandidate` fields
— `stated_calories`, `stated_protein_g`, `stated_carbs_g`, `stated_fat_g`. A
recognizable item carrying a user-stated calorie total ("… 580 cals …") or a macro
("30g protein") therefore resolves as user-provided (`user_text`) evidence instead
of being sent back for a quantity clarification. The parser still **invents
nothing**: an unstated field is `null`, the fields are **untrusted evidence** the
resolution step validates, bounds, and owns (`evidence-retrieval.md` →
**User-Stated Nutrition Evidence — FTY-279**; `food-resolution.md`), and a stated
nutrition fact is a **detail signal** that — like a stated portion (FTY-275) —
defers a source-miss to estimation rather than clarification. This version settles
the **schema/routing contract only**; the estimator/parser code (and any additive
persistence) are the **downstream FTY-280 implementation follow-up**, and the
historical FTY-278/FTY-275 runtime baseline shipped until that implementation landed.
The stated fields need **no new parse persistence column** — like `brand`, they are
consumed at resolution time, and the `derived_food_items` energy/macro columns are
already nullable (FTY-044/FTY-051).
FTY-280 implementation note: because a stated calorie total becomes rank-1
`user_text` evidence, the FTY-158 self-consistency concordance also **compares the
`stated_*` fields** across samples, and the parse step fails a stated total **closed**
to a targeted calorie question when the samples materially disagree on it (a
contradictory duplicate total, or a strict majority of the samples that recognised
the item not extracting a total) — an unstable extraction is never persisted as a
trusted user-stated fact.

5 (FTY-278, contract only): defines the **item-scoped** clarification carrier for
a mixed food log. A clarification question may now name the **specific unresolved
component** it is about via a nullable `derived_food_item_id` reference on
`clarification_questions` (→ `derived_food_items.id`, `ON DELETE SET NULL`), so the
estimator can commit an entry's costable components as `resolved` items while a
single amountless component keeps its own question — the parse/food step no longer
has to discard the whole entry's costing to ask one question. An **event-level**
question (parse-time ambiguity not tied to one component) leaves the reference
`NULL`, so the existing shape is a strict superset and every current question is
representable unchanged. This version **settles the schema/routing contract only**;
the additive, reversible migration that adds the column and the estimator changes
that populate it and persist resolved siblings are a **downstream implementation
follow-up** (see Migration / Compatibility). Under the historical **FTY-275
baseline**, a genuinely amountless component routed the whole event to an event-level
`needs_clarification` and persisted no candidates; FTY-298 supersedes that default for
recognizable identities by falling forward to rough estimation before any question. The
answer flow and read shape are `clarification.md`; the item-scoped status and counting
semantics are `log-events-history.md` v6, `estimation-jobs.md` v3, and `daily-summary.md`.

4 (FTY-172): the estimator now **produces** the FTY-170 clarification-with-options
shape and records schema version `parse/v2`. Model-raised clarification output is
treated as low-quality and fails closed unless each question has specific
question text plus 2–5 bounded, display-only candidate options. The old generic
default-question fallback is retired for provider output; backend-routed
low-confidence `parsed` samples and deterministic parse plausibility questions
synthesize targeted amount/duration/unit questions with 2–5 fixed quick-pick
options. Other non-parse deterministic backend questions (for example
food/exercise/label gates) still carry targeted text with `options: []` when no
meaningful quick-pick set exists. The `0017` migration adds the persisted
`options` column.

3 (FTY-159): **pre-v1 breaking behaviour change** (no shim) — the clarify
decision becomes the **data-calibrated policy** (ADR 0003 Layer C). The step
draws N=3 parse samples through the FTY-158 self-consistency sampler (parallel,
unanimous-first-window early stop) and gates on the **hybrid**
agreement+verbalized score against a calibrated operating point
(`app/estimator/clarify_policy.py`), replacing the retired single-call
`confidence < 0.45` comparison. FTY-159 did not change the `ParseResult` schema
or persistence schemas; the routing table below is what changed. See
"Calibrated clarify decision (FTY-159)".

2 (FTY-170): **pre-v1 breaking change** (no shim) — the `ParseResult`
clarification carrier becomes structured: `clarification_questions` changes
from `list[str]` to a list of `ClarificationQuestion` objects, each carrying
the specific question `text` plus candidate quick-pick `options` the clarify
sheet renders as tappable chips (audit finding A2). Schema version string
`parse/v2`. The `clarification_questions` table gains an `options` column
(shape specified here; the migration landed with the first producer, FTY-172),
and a fresh clarification round on a re-estimate **replaces** the event's
unanswered question rows. Consumers landing against the new shape: FTY-172
(produce), FTY-171 (serve via the clarification read and resolve via the
answer endpoint — `clarification.md`), FTY-153 (render).

1 (FTY-042). Schema version string `parse/v1`, recorded on the estimation run.

## Inputs

### Clarify policy config (FTY-298)

The text-log clarify gate is policy-driven. Mode names, defaults, optional tunables,
invalid-config fail-closed behavior, allowed last-resort clarification reasons, and
rough-provenance requirements are defined once in [estimator-policy.md](estimator-policy.md). This parse
contract owns how that active policy is applied to schema-validated samples, the
bounded pre-validation provider-output repair phases governed by
`SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS`, parse disposition, question quality,
and persistence.

### LLM output schema (`ParseResult`)

The strict schema the step enforces and validates (`extra="forbid"` on every
object — smuggled keys are rejected, not ignored):

| Field | Type | Notes |
| --- | --- | --- |
| `disposition` | `parsed` \| `needs_clarification` \| `unparseable` | Closed vocabulary; how the model classified the whole entry. |
| `confidence` | float `[0, 1]` | The verbalized component of the calibrated clarify decision (see Outputs / Routing) — never gated alone. |
| `items` | `ParsedCandidate[]` (≤ 32) | Extracted candidates. |
| `clarification_questions` | `ClarificationQuestion[]` (≤ 8) | Present on the ambiguous path; each question carries its quick-pick options. |
| `reason` | string \| null (≤ 120) | Short label when `unparseable`. |

`ParsedCandidate`: `type` (`food` \| `exercise`), `name` (1–200 chars),
`quantity_text` (raw portion phrase, ≤ 120), optional `unit` (≤ 32) and `amount`
(≥ 0), optional `barcode` (digits, ≤ 14; FTY-060) and `brand` (≤ 120; FTY-062), and
the optional **user-stated nutrition** fields `stated_calories`, `stated_protein_g`,
`stated_carbs_g`, `stated_fat_g` (FTY-279). The parser **does not invent** energy —
calories/macros are resolved downstream (FTY-043/044) — but it **may extract a
nutrition fact the user explicitly wrote** into these fields (see **User-stated
nutrition facts** below); an unstated field is `null`.

The `stated_*` fields (FTY-279, `extra="forbid"` unchanged) each hold a finite number
`≥ 0` or `null`, bounded by the schema's abuse cap (a value above the cap, negative,
or non-finite is a schema-invalid reply and fails closed). They are **as-logged
totals for that item** (not per-100g/per-serving), captured verbatim from the user's
wording — the parser is still untrusted and invents nothing; the food step validates
plausibility, applies the as-logged abuse cap and internal-consistency (Atwater)
check, and **owns every persisted number** (`evidence-retrieval.md`). They add no
`derived_*` persistence column of their own (consumed at resolution time, like
`brand`).

`brand` (additive, FTY-062) names a **specific** restaurant / manufacturer /
packaged-product brand when the item is a *named* product (`"Big Mac"` →
`"McDonald's"`), and is left empty for a generic food (`"white rice"`). It is the
signal the food step uses to route an item USDA/OFF cannot resolve to the
official-source resolver (search + hardened fetch, then a model-prior fallback)
instead of stopping at `needs_clarification` — see `food-resolution.md`
(**Official-Source Resolution**). The model never invents a brand the user did not
name; like every field it is stored as data, never interpreted.

`ClarificationQuestion` (`extra="forbid"`, FTY-170): `text` (1–300 chars — the
specific question the clarify sheet shows, e.g. "How many cracker
sandwiches?") and `options` (candidate quick-pick answer strings; ≤ 5 per
question, each 1–80 chars). Options are **display candidates** the client
renders as one-tap chips — never an enum the server validates an answer
against; free text is always an allowed answer (see `clarification.md`,
Clarification read / Clarification answer). The parse estimator produces **2–5
meaningful candidates** for model-raised parse clarifications,
backend-routed low-confidence parsed clarifications, and deterministic parse
plausibility clarifications. Other backend steps may still produce no options
for deterministic questions without meaningful quick-pick choices. The schema
enforces the hard count/length caps; FTY-172's parse producer adds a stricter
quality gate for provider output, rejecting missing, generic, or under-optioned
clarification questions before persistence.

String length and list count bounds cap an adversarial or runaway reply.

### Pre-validation provider-output repair (FTY-300 / FTY-304)

`SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` caps deterministic, local
schema-shape repair for each provider sample before the parse step has a trusted
`ParseResult`. The cap applies to every sampled provider reply, including the
first early-stop window and any remaining self-consistency samples. It does not
issue another provider call, change the prompt, reinterpret content, invent
fields, or repair a schema-valid `needs_clarification` / `parsed` /
`unparseable` output that conflicts with the active clarification policy. Those
schema-valid outputs are routed by the policy gates described below.

Each repair pass consumes one attempt. One pass may either unwrap one harmless
top-level object wrapper or normalize the enumerated field shapes in the current
object before strict `ParseResult` validation runs again. The repairable phases
are:

- unwrap a single top-level wrapper named `parse_result`, `result`, `response`,
  or `output` when that wrapper is the only key and its value is an object;
- normalize closed-vocabulary tokens for top-level `disposition` and candidate
  `type` by trimming, case-folding, and replacing spaces/hyphens with
  underscores;
- replace `null` top-level `items` or `clarification_questions` with empty
  arrays;
- coerce finite numeric strings for top-level `confidence`, candidate `amount`,
  and candidate `stated_calories` / `stated_protein_g` / `stated_carbs_g` /
  `stated_fat_g`.

Repairable examples include `{ "result": { ...ParseResult... } }`,
`"Parsed"` / `"Food"` tokens, `"0.82"` confidence, `"6"` amounts, and
`clarification_questions: null`. Unsafe or unenumerated shapes remain
schema-invalid: unknown dispositions or candidate types, extra smuggled keys,
missing required candidate names, non-finite or out-of-bounds numbers,
non-object wrappers, multi-key wrappers, and any shape that still fails strict
validation after the cap is exhausted.

If the payload validates after bounded repair, the repaired value is treated as
ordinary schema-validated provider output and continues through the same
calibration, advisory-provider-clarification, plausibility, question-quality,
and persistence gates as any other sample. If repair is disabled (`0`),
exhausted, unsafe, or still schema-invalid, the sample fails closed as
`StepFailed("schema_validation_failed")`; no candidates, questions, raw provider
output, raw diary text, or repair transcript are persisted.

### Persistence

The `0005` migration creates three user-owned tables, and `0017` adds
clarification quick-pick options (additive; no prior user data is required):

- **`derived_food_items`** / **`derived_exercise_items`** — one row per parsed
  candidate. Columns: `id` (UUID PK), `log_event_id` (FK → `log_events.id`,
  `ON DELETE CASCADE`, indexed), `user_id` (FK → `users.id`, `ON DELETE CASCADE`,
  indexed), `name`, `quantity_text`, `unit` (nullable), `amount` (nullable float),
  `status` (`DerivedItemStatus`, written `unresolved`), `created_at`/`updated_at`.
  FTY-043 later adds `active_calories` (nullable) to `derived_exercise_items` and
  advances costed rows to `resolved` (see `exercise-burn.md`).
- **`clarification_questions`** — one row per question. Columns: `id` (UUID PK),
  `log_event_id` (FK, cascade, indexed), `user_id` (FK, cascade, indexed),
  `question_text`, `options` (JSON array of strings, not null, default `[]` —
  the question's quick-pick candidates, stored exactly as schema-validated;
  added by FTY-172's `0017` migration), `derived_food_item_id` (**nullable** FK →
  `derived_food_items.id`, `ON DELETE SET NULL`, indexed — the specific unresolved
  component an item-scoped question is about; `NULL` for an event-level question;
  added by the FTY-278 implementation follow-up's additive migration), `position`
  (int, stable order), `created_at`/`updated_at`. The reference is an **internal**
  producer→estimator link — **never surfaced in the clarification read** — and is
  `SET NULL` (not `CASCADE`) on purpose: the answer-triggered re-estimate re-costs
  **only the open component** and leaves the already-`resolved` siblings untouched
  (`estimation-jobs.md` v3, `clarification.md`). The answered component's own row is
  advanced **in place** from `unresolved` to `resolved` rather than deleted, so the
  link is not exercised in the normal flow; but were a referenced
  `derived_food_items` row ever removed (e.g. an event-level re-estimate or
  correction), `SET NULL` **detaches** the answered question rather than
  cascade-deleting it — preserving the answered question and its
  `clarification_answers` anchor (which `ON DELETE CASCADE` on `question_id` would
  otherwise cascade away) as the accumulated detail the next round consumes. The
  link is component identity **for the estimator only**; the reader never sees it,
  and the question stays component-identified to the user by its sanitized `name` in
  `question_text`. Question
  ownership/retention still cascades from the owning event and user (`log_event_id`,
  `user_id`). The stored `question_text` +
  `options` are what the clarification read serves (`clarification.md`) — the
  **unchanged FTY-170 read shape**; `derived_food_item_id` is **not** part of that
  read shape (it stays internal to the producer/estimator), so the producer (this
  step) and the reader continue to share the FTY-170 `question_text` + `options`
  fields field-for-field. Questions
  the backend synthesises deterministically — the plausibility gate's targeted
  question — carry 2–5 quick-pick options. An item-scoped question names its
  component through `derived_food_item_id` and the component's own sanitized
  `name`, **never** by copying the raw diary phrase into `question_text`.

## Outputs / Routing

The step draws **N = 3 parse samples** of the entry through the FTY-158
self-consistency sampler (`app/estimator/self_consistency.py`; samples run in
parallel, and a unanimous first window of 2 stops early, so stable inputs pay
two calls and contested inputs pay three). Every sample is schema-validated
independently; the step then routes on the sample set and its **calibrated
clarify decision** (below). When the set is trusted, the routed candidates are
the most self-confident `parsed` sample's items — the `InterpretationSession`'s
revisable **initial hypothesis** ([interpretation-session.md](interpretation-session.md)).

Under FTY-298 the routing table is interpreted through the active shared policy
([estimator-policy.md](estimator-policy.md)). In the default `estimate_first` mode, a
schema-valid provider `needs_clarification` disposition, a low hybrid score, or a
source/quantity gap is not a terminal parse decision when the schema-validated sample
set contains a recognizable food/exercise candidate. The parse step discards advisory
provider questions unless backend policy itself allows asking, and accepts the
recognizable candidate for downstream rough resolution with content-free assumptions.

| Validated sample set | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| calibrated-confident, ≥1 item, all food candidates plausible | _(completes)_ | candidates `unresolved` | `processing → completed` |
| calibrated-confident, ≥1 item, but a food candidate is implausible | `NeedsClarification` (`implausible_candidate`) | clarification question | `processing → needs_clarification` |
| provider asks / no sample `parsed`, but a recognizable schema-validated identity is present and `estimate_first` is active | _(completes)_ | rough candidates `unresolved` + content-free assumptions; provider questions discarded | `processing → completed` |
| active policy allows asking, and either no recognizable schema-validated candidate remains or the hybrid score is below the calibrated operating point | `NeedsClarification` | clarification questions (pooled across samples or synthesized by backend policy) | `processing → needs_clarification` |
| unanimously `unparseable` **and** the input is genuinely not food/exercise/consumable at all (FTY-370 — e.g. "asdf", "how's the weather"; never an informal/homemade/compositional/borderline-consumable food description), or a trusted set with no items | `StepFailed` (terminal) | nothing | `processing → failed` |
| empty/whitespace input | `StepFailed` (terminal, no LLM call) | nothing | `processing → failed` |
| schema-invalid sample / non-retryable provider error | `StepFailed` (terminal) | nothing | `processing → failed` |
| transient provider error | `StepError` (retryable) | nothing | _(stays `processing`, retried)_ |

A **mixed** set (e.g. one `unparseable` sample alongside `parsed` ones) is
genuine uncertainty, not a terminal failure. Under `balanced`/`strict`, the
disagreement can drag the hybrid score down and route to clarification. Under the
default `estimate_first` policy, the same disagreement routes to a rough estimate when
the recognized identity survives validation, and to clarification only for the allowed
rare reasons above. In every mode the pipeline fails closed on impossible quantities,
unsafe contradictions, schema-invalid output, or missing identity; it never commits a
silent trusted guess.

### Calibrated clarify decision (FTY-159, ADR 0003 Layer C)

The estimate-vs-ask decision — the **measured operating point over the FTY-158
hybrid signal**, the no-`parsed`-sample routing under the active FTY-298 policy,
the 0.99 answered-precision operating point with its provenance caveat and
committed derivation artifact, the fixture-only regression gate and
manual-recalibration rule, the shared-`ClarifyPolicy` label path
(`label-extraction.md`), and the sampling-cost note — is specified in
[clarify-gates.md](clarify-gates.md#calibrated-clarify-decision-fty-159-adr-0003-layer-c).
This heading remains as a compatibility anchor.

### Deterministic plausibility gate (FTY-156)

The model-free `check_candidate` bounds (count / large-item count / grams / ml /
unknown-unit caps, quantity-text measure checks, no-quantity pass), the loose
fail-safe stance, and the exercise-candidate exclusion are specified in
[clarify-gates.md](clarify-gates.md#deterministic-plausibility-gate-fty-156).
That page also owns the section's trailing gate-outcome rules: the
advisory-provider precedence hand-off to
[estimator-policy.md](estimator-policy.md), the clarification-quality fail-closed
rule (`clarification_quality_failed`), backend question synthesis with bounded
quick-picks, same-transaction atomicity of candidates + questions, the
re-estimate question-replacement rule, and the item-scoped partial clarification
paragraph (FTY-278). This heading remains as a compatibility anchor.

### Estimate-first routing override (FTY-167, FTY-298)

The estimate-first routing override — the deterministic **detail signal**
(`app/estimator/detail_signals.py`), the per-item food/exercise detail-signal
enumeration, the `estimate_first` vs `balanced`/`strict` policy interaction,
the "bounded schema-shape repair is not an independent clarify branch" rule,
and the **deterministic amount fills** (range midpoint / stranded count) — is
specified in
[estimate-first-routing.md](estimate-first-routing.md#estimate-first-routing-override-fty-167-fty-298).
That page owns how a recognizable-but-underspecified entry is estimated rather
than re-asked; this step applies it after the calibrated clarify decision and
before the deterministic plausibility gate above, interpreting the shared mode
semantics from [estimator-policy.md](estimator-policy.md).

### Images as parse evidence surfaces (FTY-374)

An event created by the unified text+image submission (`log-event-images.md`)
arrives here carrying 0..N already-validated images, loaded by the worker and
supplied to the provider through `structured_completion(..., images=)`
(`llm-provider.md` v2; vision gating and the non-vision degrade path are
`estimation-jobs.md` v6). This runs the **normal parse/interpretation path** —
not the label-only `label_pipeline` — with images as evidence surfaces:

- **Division of surfaces.** The text is the primary identity/count/context
  surface ("2 of these bars" states a count of 2 and that the images depict
  the bars); an image is a facts surface — a photographed nutrition label
  yields label facts as **`user_label`-tier (rank 1) evidence**, extracted and
  validated under the same normalized fact schema and plausibility validators
  as the label pipeline (`label-extraction.md`, `evidence-retrieval.md`). A
  non-label food photo is hypothesis context, never invented numbers.
- **Per-surface provenance — every number shows where it came from.** Each
  derived number records the surface that backed it: a count/quantity stated
  in text, facts extracted from an image label (`user_label`), or a
  database/reference/model-prior tier as usual. The worked case — `"2 of these
  bars"` + a label photo — resolves as: `amount = 2` (text-stated), per-100g /
  per-serving facts from the label (`user_label` evidence row carrying the
  source image's `content_hash`), scaled **deterministically** by classical
  code — provenance `user_label` with the text-supplied count. Image-derived
  facts pass the same schema/validator trust boundary as any untrusted input;
  prompt-injection printed on an image is data, never instructions.
- **Interpretation, not a schema change.** The images join the
  `InterpretationSession` as evidence at the model-consultable decision points
  (`interpretation-session.md` v2). `ParseResult`, persistence, N=3 sampling /
  the calibrated clarify decision, the FTY-298 policy gates, and the routing
  table are unchanged — an image strengthens the hypothesis, so it can only
  make clarification *rarer*, never introduce a new ask.
- **Egress.** Images go to the configured LLM/vision provider only — never to
  search/fetch/tools, never logged, never in `trace`/`error` (the raw-diary-
  text boundary, extended to the image surface).

### User-stated nutrition facts (FTY-279)

When the user writes an explicit nutrition fact, the parser extracts it into
the optional `stated_*` fields on that item's candidate (see **Inputs** and
`## Validation`) rather than dropping it. The extract-don't-invent / as-logged
/ bounded-untrusted / prompt-injection-safe rules are specified in
[estimate-first-routing.md](estimate-first-routing.md#user-stated-nutrition-facts-fty-279).

## Validation

- Every provider reply is validated against `ParseResult` before any of it is
  used. Explicitly enumerated schema-shape mistakes may consume bounded repair
  attempts first; repair exhaustion, unsafe shapes, and still-invalid output are
  rejected (`StepFailed("schema_validation_failed")`) and **never persisted** —
  the step fails closed.
- **User-stated nutrition fields (FTY-279)** validate as finite, non-negative, and
  within the schema abuse cap; an out-of-range/negative/non-finite `stated_*` value
  is schema-invalid and fails closed. Extraction is trusted only as **untrusted
  evidence**: the food step applies the as-logged abuse cap and internal-consistency
  check before any of it backs a persisted number (`evidence-retrieval.md`).
- Closed vocabularies (`disposition`, `CandidateType`) and `extra="forbid"` mean a
  reply cannot smuggle fields or free-form instructions.
- Provider-raised clarification output is advisory under the shared
  `estimate_first` policy ([estimator-policy.md](estimator-policy.md)). If the backend
  policy accepts a clarification outcome, the persisted question must carry specific
  question text and 2–5 options per question; a missing/generic/under-optioned accepted
  question fails closed as `clarification_quality_failed` before persistence.
- A `parsed` reply with zero items fails closed rather than completing empty.

## Authorization

Every derived row and question carries `user_id` at the persistence boundary and
is written scoped to the owning event's user (the worker already loaded the event
scoped to the job's `user_id`; see `estimation-jobs.md`). `ON DELETE CASCADE` from
both `users` and `log_events` enforces object-level ownership.

## Privacy and Retention

- **Untrusted LLM, fail closed.** Model output is schema-validated before trust;
  embedded instructions in the user text are never executed or followed —
  candidate names, questions, and quick-pick options are stored as data through
  parameterized inserts and never interpreted.
- **No raw text in logs or runs.** The prompt and raw model output are never
  logged (provider contract) and never copied into the estimation run's `trace`
  or `error`; only sanitized labels (`empty_input`, `unparseable_input`,
  `schema_validation_failed`, `clarification_quality_failed`, `provider_error`,
  `provider_transient_error`) are persisted on the run.
- **Rough-estimate diagnostics are content-free.** Schema-shape repair attempts,
  provider-raised questions that were overridden by `estimate_first`,
  default-serving/model-prior assumptions, source-miss reasons, and calibration
  artifacts follow the shared privacy invariant in
  [estimator-policy.md](estimator-policy.md): they record only sanitized labels
  and source ids, not raw diary text, prompts, provider/fetched output, error
  bodies, or secrets.
- **Retention** follows the owning log event: derived items and clarification
  questions live until the event, user, or account is deleted (`ON DELETE CASCADE`),
  matching the food/exercise-log retention rule in
  `docs/security/data-retention.md`.

## Errors

| Condition | Result |
| --- | --- |
| Empty/whitespace text | Terminal `failed` (`empty_input`); no LLM call, nothing persisted. |
| Unanimously `unparseable` genuinely-non-food input (FTY-370) / no-item trusted set | Terminal `failed` (`unparseable_input`); nothing persisted. An informal/homemade/compositional/borderline-consumable description is never `unparseable` — it routes to estimate/clarify. |
| Schema-invalid model output, unsafe/unrecoverable shape, or exhausted bounded repair cap (any sample) | Rejected; terminal `failed` (`schema_validation_failed`); nothing persisted. |
| Accepted provider clarification output missing a specific question or 2–5 options | Rejected; terminal `failed` (`clarification_quality_failed`); nothing persisted. Provider questions overridden by `estimate_first` are discarded instead. |
| Non-retryable provider error (`LLMResponseError`/`LLMConfigurationError`) | Terminal `failed` (`provider_error`). |
| Transient provider error (`LLMTransientError`) | Retryable; worker retries within its bound. |
| Ambiguous / below the calibrated operating point | Under `estimate_first`, rough-estimate a recognizable identity unless an allowed clarification reason applies; under `balanced`/`strict`, `needs_clarification` with questions (text + options) persisted when the active policy asks. |

## Examples

```
event.raw_text = "two eggs and a 30 min run"
  → 2 parallel structured_completion samples (first window; unanimous → early stop)
  → both: { disposition: parsed, confidence: 0.95, items: [
        {type: food, name: "eggs", quantity_text: "two", amount: 2},
        {type: exercise, name: "run", quantity_text: "30 min"} ] }
  → agreement 1.0, hybrid 0.98 ≥ calibrated operating point → trusted
  → derived_food_items += eggs (unresolved); derived_exercise_items += run (unresolved)
  → event: processing → completed
```

```
event.raw_text = "crackers and peanut butter"        # recognizable, amountless food
  → samples disagree or one provider asks "How much?"
  → estimate_first policy sees recognizable identities and no unsafe contradiction
  → provider question is advisory; schema-validated candidates continue:
      {type: food, name: "crackers", quantity_text: "", amount: null}
      {type: food, name: "peanut butter", quantity_text: "", amount: null}
  → derived_food_items += rough unresolved candidates
  → event: processing → completed
  # downstream food resolution records rough default/reference/model-prior provenance
  # and keeps the estimate editable; no clarification is asked solely for quantity.
```

```
event.raw_text = "stuff"
  → no recognizable identity survives validation/bounded repair, but the input
     is not clearly non-food: genuinely indeterminate, never `unparseable_input`
  → backend synthesizes a targeted clarification (FTY-370)
```

## Migration / Compatibility

- The `0005` migration applies (`alembic upgrade head`) on top of the estimation
  schema and is fully reversible (`alembic downgrade 0004`), verified by an
  apply/rollback test against a throwaway database. The `0017` migration adds
  `clarification_questions.options` and is reversible to `0016`.
- Additive: existing rows backfill `options: []`; no existing column semantics
  change.
- FTY-042 replaces FTY-040's stub parse step with this real step and adds a
  terminal `StepFailed` signal to the pipeline interface (see `estimation-jobs.md`);
  the worker's claim → run → transition contract is unchanged.
- FTY-043/044 consume the `unresolved` candidates and advance them to `resolved`
  with energy/macros; FTY-043 (exercise burn) is specified in `exercise-burn.md`.
- **FTY-170 (breaking, pre-v1, no shim).** The `clarification_questions`
  carrier in `ParseResult` changes from `list[str]` to structured
  `ClarificationQuestion` objects (`parse/v2`), and the
  `clarification_questions` table gains the `options` column. The v1
  string-list shape is retired with no back-compat shim — pre-v1, it has no
  consumers to preserve. The `options` migration landed with FTY-172 (`0017`,
  the first producer); FTY-171 serves the options through the clarification
  read and implements the answer resolve (`clarification.md`); FTY-153 renders
  the chips and free-text fallback.
- **FTY-159 (breaking behaviour, pre-v1, no shim).** The clarify decision
  becomes the calibrated policy over the FTY-158 hybrid self-consistency
  signal, and the parse step samples the provider N=3 times (early-stopped)
  instead of once. `PARSE_CONFIDENCE_CLARIFY_THRESHOLD` (0.45) and
  `LABEL_CONFIDENCE_CLARIFY_THRESHOLD` (0.5) are retired as bare constants;
  both gates route through `app/estimator/clarify_policy.py`. No schema,
  persistence, or API change; token cost is ~N× per parse with near-flat
  latency. Recalibration (re-running the harness bake-off) is required after
  any parse-prompt or model change.
- FTY-060 (`barcode`) and FTY-062 (`brand`) add optional, length-bounded
  `ParsedCandidate` fields. Both are additive and backward-compatible: a reply that
  omits them validates unchanged (they default to `null`), and they are stored as data
  only. `brand` drives official-source routing (`food-resolution.md`); it adds no
  persistence column of its own (it is consumed at resolution time).
- **FTY-279 (contract only; no code, no migration in this story).** Adds the optional,
  bounded `stated_calories` / `stated_protein_g` / `stated_carbs_g` / `stated_fat_g`
  `ParsedCandidate` fields (a **deliberate pre-v1 refinement** of "No energy": the
  parser may now extract a nutrition fact the user explicitly stated, as untrusted
  evidence). Additive and backward-compatible: a reply that omits them validates
  unchanged (default `null`), they are stored as data only and never interpreted, and
  they add **no** `derived_*` persistence column (consumed at resolution time, like
  `brand`). They drive `user_text` resolution and the no-second-follow-up rule
  (`food-resolution.md`), back user-provided evidence (`evidence-retrieval.md` →
  **User-Stated Nutrition Evidence**), and let a calorie-only item count in
  `daily-summary.md`. The estimator/parser implementation is the downstream FTY-280
  follow-up; the historical FTY-278/FTY-275 runtime baseline shipped until it landed.
- **FTY-280 (implements FTY-279).** The parser now extracts the `stated_*` fields
  (bounded by `MAX_STATED_ENERGY_KCAL` / `MAX_STATED_MACRO_G`, `allow_inf_nan=False`
  so a non-finite value is schema-invalid), a stated nutrition fact is a
  `has_stated_nutrition` detail signal, and the food step resolves a stated calorie
  total from the `user_text` tier (`backend/app/estimator/user_text_step.py`). Still
  **no** `derived_*` parse-persistence column (consumed at resolution time, like
  `brand`); the additive evidence-layer migration is `evidence-retrieval.md` /
  `food-resolution.md`'s `0018`.
- **FTY-278 (contract only; no code, no migration in this story).** Adds the
  nullable `clarification_questions.derived_food_item_id` reference — an
  **internal** producer→estimator link, **not** surfaced in the clarification read
  (the FTY-170 read/answer shape is unchanged) — so a question can be item-scoped.
  The
  column and its migration are **additive and reversible** (existing questions
  default it to `NULL` and remain valid event-level questions; no backfill), but
  they are **owned by the downstream FTY-278 implementation follow-up**, not this
  spec — this version fixes the shape and routing so that story and the backend
  read/answer story (`clarification.md`, `log-events-history.md` v6, `estimation-jobs.md` v3,
  `daily-summary.md`) build to one agreed contract. No existing `ParseResult`
  field, `ClarificationQuestion` shape, or column semantics change; the FTY-275
  baseline (whole-event event-level clarification, nothing committed) ships until
  the follow-up lands.
- **FTY-298 / FTY-303 (contract only; no code, no migration in this story).** FTY-298
  bumps the parse contract to the rare clarification policy, and FTY-303 extracts the
  global mode semantics, advisory-provider rule, allowed last-resort clarification
  reasons, and rough-provenance requirements to [estimator-policy.md](estimator-policy.md).
  This parse contract keeps the schema, sampling, recovery, parse-disposition,
  question-quality, and persistence rules. No `ParseResult`, persistence, DTO, or
  migration changes are made here; FTY-299/FTY-300/FTY-301 implement the runtime
  behavior.
- **FTY-304 (documentation-only wording clarification).** The shared
  `SLACKS_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` setting already existed from FTY-300.
  This contract now names the concrete pre-validation provider-output repair phases
  and the `schema_validation_failed` fail-closed result when repair is disabled,
  exhausted, unsafe, or still invalid. No `ParseResult`, persistence, DTO, migration,
  provider, prompt, settings, or estimator behavior changes are made here.
- **FTY-324 / FTY-348 (contract only; no code or migration).** FTY-324 named the
  `InterpretationSession` contract; FTY-348 relocates it to
  [interpretation-session.md](interpretation-session.md) with no normative change.
  FTY-325/FTY-326 implement the interpreter core.
- **FTY-374 (contract only; no code, no migration in this story).** Adds the
  images-as-evidence-surfaces rules above (`log-event-images.md`): validated
  images alongside `raw_text`, label facts as `user_label` (rank 1) evidence,
  per-surface provenance, provider-only image egress. No `ParseResult`,
  persistence, sampling, policy, or routing change. FTY-376 implements
  (ingestion/retention is FTY-375).
- **FTY-370 (contract only; no code, no migration).** Narrows terminal
  `unparseable_input` to unanimous genuinely-non-food input; no `ParseResult`,
  persistence, sampling, or policy change. FTY-371 implements (`estimation-jobs.md` v7).
