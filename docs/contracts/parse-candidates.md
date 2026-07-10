# Contract: Parse Candidates & Clarification Questions

## Purpose

Define the structured **parse step** (FTY-042) of the estimation pipeline: how a
`pending` log event's raw text becomes schema-validated food/exercise
**candidates** (persisted unresolved), or **clarification questions** when the
input is ambiguous, or a terminal **failure** when it is empty/garbage/adversarial
or the model output is invalid.

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

9 (FTY-324, contract only): redefines the parsed candidate set as the
`InterpretationSession`'s **interpretation hypothesis**, not frozen upstream truth.
The model owns interpretation of the user's raw text plus accumulated clarification
answers for the lifetime of an estimation run; deterministic code owns schema
validation, calibrated confidence, plausibility gates, math, provenance, privacy,
and persistence. Hypotheses may be revised when later evidence contradicts or
clarifies the initial parse, and each revision is traced only with sanitized labels.
No schema, persistence, provider, prompt, settings, API, or estimator behavior changes
land in this documentation story; FTY-325/FTY-326 implement the target contract.

8 (FTY-304, wording clarification): names the concrete FTY-300 pre-validation
provider-output repair phases governed by
`FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS`, clarifies that the cap does not
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
semantics are `log-events.md` v6, `estimation-jobs.md` v3, and `daily-summary.md`.

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
`FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS`, parse disposition, question quality,
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

### Interpretation session and hypothesis revisions (FTY-324)

The natural-language estimation run has one logical **`InterpretationSession`**.
It begins with the raw log text and any accumulated `clarification_answers`, then
continues through parse, food resolution, exercise resolution, and evidence
lookup until the event reaches a terminal status. The session contract is:

> The model owns interpretation of the user's text end to end. Structured
> candidates are the model's working hypothesis — revisable whenever new evidence
> arrives — never a frozen upstream truth. Deterministic code owns math, bounds,
> provenance, privacy, and persistence. It never guesses intent, and it never
> discards or overrides user-stated detail because that detail did not fit an
> extracted field.

The raw log text and answered clarification text remain available **only inside
the configured LLM boundary** for every model interpretation call in the session.
They are not copied into search queries, fetch requests, run traces,
`assumptions`, `source_refs`, provider error strings, logs, or evidence rows.
Downstream search/fetch/model-prior tools receive the least-sensitive structured
inputs their contracts allow: sanitized item identity, bounded amount/unit fields,
source refs, fetched inert text, snippets, and content-free source-status labels.

An `InterpretationHypothesis` is a run-local working object. It is not a new public
HTTP DTO and is not persisted wholesale. It carries enough structure for
deterministic code to validate and calculate without interpreting intent:

| Field | Meaning |
| --- | --- |
| `session_id` | Run-local identifier used only inside the estimation run; never exposed as user data. |
| `raw_text` | The owning event's raw text, available to the configured LLM provider only. |
| `clarification_answers` | Prior answered question/answer pairs, fed to the model as bounded structured detail. |
| `items` | Ordered food/exercise hypothesis items. Each item has a run-local `hypothesis_item_id`, `type`, `name`, `quantity_text`, optional `unit`, `amount`, `barcode`, `brand`, and optional `stated_*` facts. |
| `item_links` | Run-local split/merge lineage between hypothesis items; used for traceability only, never as persisted user-visible data. |
| `evidence_view` | Bounded evidence gathered so far: source tier, lookup status, source refs, snippets/page extraction status, compatibility result, and content-free reject reason. It never carries raw fetched pages, raw snippets, provider output, or raw search queries. |
| `policy_view` | Active FTY-298 mode plus calibrated self-consistency/agreement signal metadata from ADR-0003. |
| `pending_questions` | Candidate clarification questions with item scope when an item-scoped question is allowed by FTY-278. |

The hypothesis may be revised during the same session. A revision may:

- add an item the initial parse missed;
- split one item into several items;
- merge duplicate or over-split items;
- remove a spurious item;
- correct an item identity, brand/product identity, amount, unit, or exercise
  detail;
- attach, detach, or correct a user-stated nutrition fact;
- mark an item as genuinely indeterminate for an allowed clarification reason.

The following **model-consultable decision points** must be able to pass the raw
text, clarification answers, current hypothesis, and evidence view back to the
model for interpretation rather than relying only on frozen extracted fields:

| Decision point | Trigger |
| --- | --- |
| `initial_parse` | First structured interpretation of the raw log text. |
| `provider_clarification_adjudication` | A provider returns `needs_clarification`, samples disagree, or the hybrid score is conservative but a recognizable identity may be recoverable under FTY-298. |
| `source_selection` | Choosing which evidence tier(s) and query variants are applicable to an item. |
| `source_acceptance` | A source result, snippet, page extraction, barcode/OFF result, USDA row, official page, reference page, or model-prior estimate may or may not match the item the user meant. |
| `source_rejection_feedback` | A lookup misses, fetch fails, extraction is unresolved/low-confidence, compatibility rejects a result, or serving math rejects otherwise useful evidence. |
| `hypothesis_repair` | Evidence implies the initial item set was degenerate, over-split, under-split, brandless, amountless, or attached to the wrong item. |
| `clarification_boundary` | The session may ask only after the interpretation loop concludes the remaining item is genuinely indeterminate under the active FTY-298 mode, except deterministic gates that independently clarify/fail closed. |
| `answer_reestimate` | A clarification answer re-opens interpretation with the original raw text plus accumulated answers. |

Any current or future resolution decision that keys on a frozen extracted field
(`has_brand`, `amount_kind`, `name`, `unit`, `brand`, `quantity_text`, or a count
serving relation) must treat that field as a hypothesis feature, not authority.
It may be used by deterministic validators and as sanitized input to tools, but
if evidence suggests the feature is wrong or incomplete, the session revises the
hypothesis instead of forcing all later tiers to chase the stale value.

Confidence remains an engineered signal. The model may produce a verbalized
`confidence` because the existing schema carries it, but routing never trusts a
single self-reported score. Parse abstention uses the ADR-0003 hybrid
self-consistency/agreement signal and calibrated threshold, with FTY-298 mode
semantics layered on top; later interpretation calls that need uncertainty must
use the same cold-pass/agreement style or a stricter deterministic validator, not
a raw provider confidence claim.

#### Sanitized hypothesis-revision trace labels

Hypothesis revisions are traced with content-free labels. A trace entry for this
contract uses `decision = hypothesis_revision`; `candidate_index`, `tier`,
`amount_kind`, `has_brand`, and `result_count` may be included when useful, but
the entry must never include raw diary text, raw clarification answers, item
names, quantity phrases, prompts, provider output, fetched page/snippet text,
search queries, URLs with secrets, request/response bodies, or provider error
bodies.

Allowed `outcome` labels are:

- `initial_hypothesis`;
- `hypothesis_kept`;
- `item_added`;
- `item_removed`;
- `item_split`;
- `item_merged`;
- `identity_revised`;
- `brand_revised`;
- `quantity_revised`;
- `unit_revised`;
- `stated_nutrition_revised`;
- `exercise_detail_revised`;
- `evidence_attached`;
- `evidence_rejected`;
- `clarification_needed`;
- `deterministic_gate_failed`;
- `revision_truncated`.

The labels describe only the kind of revision. The revised values live in the
ordinary user-owned derived-item/evidence rows after validation and persistence,
not in the run trace.

### Pre-validation provider-output repair (FTY-300 / FTY-304)

`FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` caps deterministic, local
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
the most self-confident `parsed` sample's items. Under FTY-324 those routed
candidates are the `InterpretationSession`'s **initial hypothesis**, not an
immutable parse truth; later evidence may revise the item set or fields before
validated numbers are persisted.

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
| unanimously `unparseable`, or a trusted set with no items | `StepFailed` (terminal) | nothing | `processing → failed` |
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

The estimate-vs-ask decision is a **measured operating point over a measured
signal**, not a hand-picked constant (the retired
`PARSE_CONFIDENCE_CLARIFY_THRESHOLD = 0.45` was an unprincipled guess; a fixed
uncalibrated threshold is fragile under distribution shift — Kamath, Jia &
Liang, ACL 2020, via `docs/adr/0003-estimator-confidence-clarification.md`,
which owns the architecture decision this implements):

- **Signal — the bake-off winner.** Over the labeled calibration sets (the
  FTY-157 synthetic band + the FTY-169 naturalistic band, scored `combined` by
  the FTY-157 harness), three signals were compared on risk-coverage curves:
  the verbalized confidence, the FTY-158 sampling-agreement score, and their
  hybrid (`0.6 × agreement + 0.4 × verbalized`). The **hybrid won** and is what
  the gate consumes: at the target precision the verbalized baseline reaches
  only 40% coverage and agreement-only never reaches it at all. A sample set
  with **no `parsed` sample** has no hybrid score to trust (its agreement can be
  a perfect 1.0 *about asking*), so the active FTY-298 policy owns routing:
  under `estimate_first`, clarification-only samples with a recognizable
  schema-validated identity are advisory and may be accepted as rough candidates;
  under `balanced`/`strict`, or when `estimate_first` has no recognizable
  identity or another allowed clarification reason applies, the set routes to
  clarification or failure.
- **Operating point — derived, with a margin.** The threshold is chosen on the
  winning signal's risk-coverage curve for a **target answered precision of
  0.99** (of the events the gate estimates, ≥ 99% must be gold-estimate —
  under-asking silently corrupts an honest count, so precision is the
  calibration target; maximizing coverage under it then minimizes over-asking),
  and committed as the midpoint of the empirical margin band around the
  selected point. Measured on the combined set: over-ask 12.4% → 6.5%,
  under-ask 19.4% → 1.9%, correct decisions 85.2% → 95.1% versus the retired
  gate. **Provenance caveat:** both calibration bands are author-constructed
  stand-ins, not recorded user traffic — the synthetic band is synthetic by
  construction, and the naturalistic band's "recorded" samples were authored
  alongside this calibration (`generate_naturalistic_seed.py`, provenance
  declared per record via `source_kind`; see the fixture README) — so the
  operating point and the improvement rates above quantify an authored
  simulation until a live-recorded band replaces the stand-ins. The constant
  lives in `app/estimator/clarify_policy.py`
  (`NL_PARSE_CLARIFY_POLICY`); the committed derivation is
  `backend/tests/fixtures/parse_calibration/calibration_summary.json`.
- **Regression gate.** `backend/tests/test_clarify_calibration.py` re-derives
  the bake-off on every verification run **from the committed static fixtures —
  no provider is invoked**: the production constant must equal the derived
  point, the committed artifact must match a fresh derivation, the calibrated
  decision must keep beating the verbalized-vs-0.45 baseline, and absolute
  floors (correct-decision rate, precision, over-/under-ask, coverage) must
  hold. The gate therefore catches fixture, signal-code, or selection-rule
  changes only; a prompt or model change leaves every fixture-derived number
  identical and CI green. Recalibrating after a prompt or model change is a
  **manual step**: re-run the harness bake-off over re-recorded or live
  provider outputs and recommit the derivation.
- **The label path shares the mechanism.** The nutrition-label gate
  (`label-extraction.md`) routes through the same `ClarifyPolicy` type
  (`LABEL_CLARIFY_POLICY`). Its operating point is a **documented tunable**
  (the conservative pre-FTY-159 value, 0.5, over the panel's verbalized
  confidence): the calibration sets are NL descriptions, not label-image scans,
  so a data-derived label point would be fabricated — a dedicated label-image
  eval slice is the recorded follow-up that earns one.
- **Cost.** Sampling costs ~N× the tokens of a single parse call; latency stays
  near-flat (parallel samples), and the early stop keeps stable inputs at 2
  calls (ADR 0003, Consequences).

### Deterministic plausibility gate (FTY-156)

After confidence/disposition routing, a model-free gate
(`app/estimator/plausibility.py`, `check_candidate`) checks each **food**
candidate's quantity against coarse physical/serving sanity ranges before the
parse is trusted. A single implausible food candidate makes the event's total
untrustworthy, so the step routes the whole event to `needs_clarification`
(`implausible_candidate`) with one targeted question naming the offending item,
and persists no candidates.

- **Bounds** (generous, documented tunables in `plausibility.py`): a generic
  discrete count above `MAX_PLAUSIBLE_COUNT` (`250`) fails, while clearly large
  counted foods use `MAX_PLAUSIBLE_LARGE_ITEM_COUNT` (`36`) so examples such as
  `50 eggs` still route to clarification without rejecting realistic small-food
  logs such as `50 blueberries` or food-specific units like `50 crackers`. A mass
  above `MAX_PLAUSIBLE_GRAMS` (`2000 g`) or a volume above `MAX_PLAUSIBLE_ML`
  (`2000 ml`) fails. A numeric amount on an unrecognised unit fails above
  `MAX_PLAUSIBLE_UNKNOWN_UNIT_AMOUNT` (`36`) unless the unit appears to be a
  food-specific count unit matching the candidate name, in which case the count
  cap applies. Every explicit `<number> <mass|volume unit>` measure in
  `quantity_text` is checked against the same mass/volume bounds even when
  structured fields are absent or describe a count/portion such as `1 serving`.
  A candidate with no structured `amount` and no explicit measured quantity in
  `quantity_text` passes (inference gaps are the confidence check's concern).
  Bounds are set just above any realistic single-entry portion so a false reject
  of a large-but-real meal is effectively impossible; the fail-safe is loose (an
  over-generous bound lets one absurd parse through rather than falsely asking).
- **Exercise candidates are excluded.** Their quantities are durations
  (minutes/hours), not mass/volume/count, so the food-portion bounds and unit
  vocabulary do not apply — exercise plausibility/duration parsing belongs to
  FTY-043 (`exercise-burn.md`). Running an exercise duration through this gate
  would falsely reject ordinary workouts (e.g. `walking, 60 minutes`).

Provider `needs_clarification` output is first checked against the shared advisory
provider rule ([estimator-policy.md](estimator-policy.md)). Only when backend policy
itself allows asking does provider clarification output have to be persisted; at that
point a missing specific question, a generic fallback question, or fewer than two
quick-pick options fails closed (`StepFailed("clarification_quality_failed")`) and
persists nothing. A
`needs_clarification` event therefore never reaches the answer flow with a
model-raised generic placeholder. If the active policy routes a low-confidence `parsed`
sample to clarification and no provider question was supplied, the parse step
synthesizes one targeted backend question naming the first item that still satisfies an
allowed clarification reason and persists 2–5 bounded quick-pick options.
Deterministic backend gates that synthesize their own targeted question without
meaningful quick-picks persist that question with `options: []`.
Candidates and questions are committed in the **same transaction** as the
terminal status, so a completed/clarification outcome and its rows are atomic.
When a **re-estimate** of an answered event (`clarification.md`, Clarification
answer) lands on `needs_clarification` again, the fresh round's questions
**replace** the event's unanswered question rows in that same transaction —
answered questions and their `clarification_answers` are preserved, since they
carry the accumulated details the re-estimate consumes — so the clarification
read (status-gated to `needs_clarification`; `clarification.md`) serves exactly
the fresh round's open questions.

**Item-scoped partial clarification (FTY-278, contract only).** Under the
item-scoped contract, a mixed entry is not all-or-nothing: the step commits the
entry's **costable** components as `resolved` items (via the downstream food
step, `food-resolution.md`) and raises a clarification only for the component(s)
that still have an allowed clarification reason after the active FTY-298 policy has
tried rough estimation, each question carrying its
`derived_food_item_id`. Such a `partially_resolved` event (`log-events.md` v6)
therefore carries committed `resolved` siblings alongside its open item-scoped
questions — the
event's derived-item set (resolved siblings + the `unresolved` component)
and its question rows are committed atomically in the terminal transaction. A
re-estimate re-costs **only the open component** and leaves the already-`resolved`
siblings untouched, so a resolved sibling is represented exactly once
and never duplicated or double-counted, and the fresh round's questions replace
only the **unanswered** ones (`estimation-jobs.md` v3, `daily-summary.md`). This
paragraph is the target contract; the estimator work to persist siblings and
populate `derived_food_item_id` is the FTY-278 implementation follow-up. The
historical **FTY-275 baseline** was whole-event, event-level clarification with
nothing committed; FTY-298 now makes recognizable amountless components rough
estimate first, and any remaining question stays item-scoped under this target.

### Estimate-first routing override (FTY-167, FTY-298)

A casual entry is often returned by the model with a conservative confidence (or
even a `needs_clarification` disposition) even though it already carries enough
real-world structure to estimate — "Had a handful (5-10) of deep fried onion rings",
"Had 3 cracker sandwiches", "ran 5 km", "played 3 games of badminton". Before routing
such a reply to clarification, the step checks each extracted item against the active
shared clarification policy ([estimator-policy.md](estimator-policy.md)). The older **deterministic detail signal**
(`app/estimator/detail_signals.py`) remains a strengthening signal:

- **food** — a positive structured `amount` (a count or a measured quantity), a
  numeric **range** in `quantity_text` (`5-10`), a **stated worded portion**
  (FTY-275) in `quantity_text`: a household / cooking measure (`cup`, `tsp`, `tbsp`,
  `fl oz`, `pint`, `quart`, `gallon` and their spellings), a colloquial / approximate
  measure word (`splash`, `drizzle`, `dash`, `pinch`, `handful`, `glug`), or an
  indefinite-article measure (`a`/`an` = one); **or a stated nutrition fact**
  (FTY-279 — a `stated_calories` total or a `stated_*` macro the user wrote). Each
  means the user *stated* a usable detail, so a generic source-miss defers to
  estimation (or, for a stated nutrition fact, resolves directly from that
  `user_text` evidence) rather than re-asking — see `food-resolution.md`
  (**User-Stated Resolution (FTY-279)** (its no-second-follow-up rule), and **Official-Source
  Resolution**, v8). Under the default `estimate_first` policy, a bare recognizable
  identity with **no** stated portion and no stated nutrition fact (`milk`, `some
  crackers`, `crackers and hummus`) is still enough to attempt a rough estimate; under
  `balanced`/`strict` it may still lack the stronger detail signal used by the
  calibrated abstention path;
- **exercise** — an explicit duration, a **distance**, a **step count**, or a **game
  count**.

When the sample set would otherwise clarify (a hybrid score below the calibrated
operating point or a provider `needs_clarification` disposition), the parse step
applies the shared mode semantics and allowed clarification reasons from
[estimator-policy.md](estimator-policy.md). Successful bounded schema-shape repair
is not an independent clarification branch: after pre-validation repair yields a
trusted `ParseResult`, routing uses the same disposition, sample
confidence/agreement, recognizable-identity, plausibility, stated-nutrition
safety, and active-policy gates as any other validated sample. Missing amounts
become downstream rough assumptions, not parse questions, under the default policy.
A calibrated-confident sample set is unaffected (it never entered the clarify
branch), and the deterministic plausibility gate above still runs on the accepted
items.

**Range midpoint.** When a food item has no structured `amount` but its `quantity_text`
states a numeric range, the step fills the arithmetic **midpoint** as the count
(`5-10 → 7.5`) so the serving math can estimate a single portion, and records a
content-free `range_midpoint: <low>-<high> → <mid>` assumption on the run. The midpoint
is filled **before** the FTY-156 plausibility gate, so it is bounded by the same count
caps as an explicit amount (`500-1000 → 750` clarifies rather than bypassing the gate),
and the assumption is recorded only when the event is accepted. This changes routing
and the count only — the parse step still carries **no** energy/macro value;
calories/macros remain the calculator layers' responsibility (FTY-043/044/062).

### User-stated nutrition facts (FTY-279)

When the user writes an explicit nutrition fact — a calorie total (`580 cals`,
`580 calories`, e.g. "Sobeys buffalo chicken lime wrap (580 cals idk the
breakdown)"), a macro (`30g protein`), or both — the parser extracts it into the
`stated_*` fields on that item's candidate rather than dropping it. Common calorie
and macro phrasings (`cal`/`cals`/`calories`/`kcal`; `30g protein`, `30 g protein`)
all resolve to the same `stated_*` field. The rule refines "No energy": the parser still **invents no
number**, but it is allowed to **read what the user stated** and carry it as
untrusted evidence.

- **Extract, don't invent.** A `stated_*` field is filled **only** from a value the
  user actually wrote for that item; an unstated field is `null`. The model must not
  synthesize a calorie/macro number the user did not give (that is the resolution
  layers' job, with their own provenance), and it never copies a value from one item
  onto another.
- **As-logged.** `stated_*` values are the totals for the exact item as logged, not
  per-100g/per-serving. The honest basis and per-field provenance are fixed in
  `evidence-retrieval.md` (`as_logged`, `field_provenance`); the parser only carries
  the raw stated numbers.
- **Bounded & untrusted.** Each field is finite, `≥ 0`, and schema-capped; an
  out-of-range/negative/non-finite value makes the reply schema-invalid and fails
  closed. Extracted facts back a persisted number only after the food step's
  plausibility validation (as-logged abuse cap + Atwater internal-consistency);
  a self-contradictory claim clarifies rather than committing (`food-resolution.md`).
- **Prompt-injection safe.** The stated numbers are stored as data through
  parameterized inserts and never interpreted; an instruction embedded in the entry
  text is never executed (as for every `ParsedCandidate` field).

A stated nutrition fact is a **detail signal** (above): a recognizable item that
carries one is estimated/resolved, **not** re-asked for an amount — see the
no-second-follow-up rule in `food-resolution.md`.

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
- **Raw text stays inside the model boundary.** The raw log text and accumulated
  clarification answers may be sent to the configured LLM provider for
  interpretation throughout the `InterpretationSession`, as the parse step already
  does today. They must not be sent to search/fetch providers or copied into run
  traces, source refs, assumptions, diagnostics, error strings, or logs; those
  surfaces keep the sanitized label/source-id vocabulary described above.
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
| Unanimously `unparseable` / no-item trusted set | Terminal `failed`; nothing persisted. |
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
  → no recognizable food or exercise identity survives validation and any
     bounded schema-shape repair
  → estimate_first has no safe object to estimate
  → backend synthesizes a targeted clarification if one can help, otherwise the
     parse fails closed as unparseable
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
  read/answer story (`clarification.md`, `log-events.md` v6, `estimation-jobs.md` v3,
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
  `FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` setting already existed from FTY-300.
  This contract now names the concrete pre-validation provider-output repair phases
  and the `schema_validation_failed` fail-closed result when repair is disabled,
  exhausted, unsafe, or still invalid. No `ParseResult`, persistence, DTO, migration,
  provider, prompt, settings, or estimator behavior changes are made here.
- **FTY-324 (contract only; no code or migration in this story).** The parse
  contract now names the `InterpretationSession`, the `InterpretationHypothesis`
  fields, model-consultable decision points, and sanitized hypothesis-revision
  trace labels. It deliberately does not add a public API, parse persistence column,
  provider, prompt, settings, migration, or compatibility shim. FTY-325/FTY-326
  implement the interpreter core and evidence-tier tool loop against this target.
