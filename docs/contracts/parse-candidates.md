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

7 (FTY-298, contract only): defines the versioned **rare clarification policy** for
natural-language text logs. The default operator mode is now
`FATTY_ESTIMATOR_CLARIFY_MODE=estimate_first`: a recognizable food or exercise
identity is enough to attempt a rough, editable estimate even when the user did not
state a count, serving, duration, distance, or other amount. Counts, portions, brands,
product identities, explicit nutrition facts, exercise durations/distances/steps/games,
and standard-serving cues still make an estimate stronger, but they are no longer the
only route to estimation. Provider-raised `needs_clarification` output is advisory,
not authoritative, whenever recognized candidates or a recoverable identity can be
validated under the active policy. Clarification under `estimate_first` is reserved for
missing recognizable identity, non-log/gibberish input, deterministic unsafe
contradictions or implausibilities, an unavailable/disabled estimator path after its
bounded recovery attempts, or an operator-selected stricter mode. This version changes
the public contract only; the settings and estimator implementation are downstream
FTY-299/FTY-300/FTY-301 follow-ups.

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

The text-log clarify gate is policy-driven. Downstream implementation stories expose
the mode through:

| Variable | Default | Values | Meaning |
| --- | --- | --- | --- |
| `FATTY_ESTIMATOR_CLARIFY_MODE` | `estimate_first` | `estimate_first`, `balanced`, `strict` | Operator-selected abstention posture for natural-language parse/resolution. Unknown values fail closed at config load. |

Mode semantics:

- **`estimate_first` (default).** Ask only when the estimator cannot identify a
  recognizable food/exercise identity, the input is non-log/gibberish, deterministic
  validators find an impossible/unsafe contradiction, every enabled estimator/provider
  path is unavailable after bounded retries/repair attempts, or the relevant estimator
  path is explicitly disabled. Missing quantity alone is not enough to ask: `milk`,
  `some crackers`, `crackers and hummus`, and a bare recognizable exercise identity
  are accepted as rough candidates and resolved downstream with visible rough
  provenance.
- **`balanced`.** Preserve the calibrated abstention threshold from ADR 0003 / FTY-159
  for deployments that prefer the measured ask/estimate tradeoff, but never re-ask for
  a detail the user already stated: counts, portions (including approximate wording),
  brands/product identities, explicit nutrition facts, exercise durations/distances/
  steps/games, or standard-serving cues.
- **`strict`.** Maximize precision for deployments that prefer fewer rough estimates;
  older-style amount clarifications for recognizable-but-amountless items are allowed.
  Deterministic plausibility and schema validation still fail closed.

Optional numeric tunables are contract names for downstream code stories; this docs-only
story does not require every runtime setting to exist yet:

| Variable | Applies to | Meaning |
| --- | --- | --- |
| `FATTY_ESTIMATOR_PARSE_CLARIFY_THRESHOLD` | `balanced`, `strict` | Overrides the calibrated parse abstention threshold. It must never make the gate re-ask for a user-stated detail in `balanced`. |
| `FATTY_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR` | rough nutrition facts | Minimum calibrated/cold-pass agreement for accepting a model/default-prior rough nutrition estimate; disagreement leaves a rough/unknown field or asks only for an allowed reason. |
| `FATTY_ESTIMATOR_MAX_PARSE_REPAIR_ATTEMPTS` | all modes | Maximum bounded recovery/repair attempts when provider output is schema-valid but conflicts with the active policy, such as returning a clarification for a recoverable identity. |

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
the most self-confident `parsed` sample's items.

Under FTY-298 the routing table is interpreted through the active
`FATTY_ESTIMATOR_CLARIFY_MODE`. In the default `estimate_first` mode, a
schema-valid provider `needs_clarification` disposition, a low hybrid score, or a
source/quantity gap is not a terminal parse decision when the sample set contains a
recognizable food/exercise candidate or a bounded repair pass can recover one. The
backend treats such provider-raised questions as **advisory**, discards them unless
the policy itself allows asking, and accepts the recognizable candidate for downstream
rough resolution with content-free assumptions. The calibrated abstention threshold
still governs `balanced`, and `strict` may choose the older amount-clarification path.

| Validated sample set | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| calibrated-confident, ≥1 item, all food candidates plausible | _(completes)_ | candidates `unresolved` | `processing → completed` |
| calibrated-confident, ≥1 item, but a food candidate is implausible | `NeedsClarification` (`implausible_candidate`) | clarification question | `processing → needs_clarification` |
| provider asks / no sample `parsed`, but a recognizable identity is present or recoverable and `estimate_first` is active | _(completes)_ | rough candidates `unresolved` + content-free assumptions; provider questions discarded | `processing → completed` |
| no sample `parsed`, or the hybrid score is below the calibrated operating point, and the active policy allows asking | `NeedsClarification` | clarification questions (pooled across samples or synthesized by backend policy) | `processing → needs_clarification` |
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
  with **no `parsed` sample** is a direct clarify decision, never scored (its
  agreement can be a perfect 1.0 *about asking*).
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

Provider `needs_clarification` output is first checked against the active rare
clarification policy. In `estimate_first`, a provider question that conflicts with a
recognized/recoverable identity is discarded as advisory and the candidate is accepted
for rough downstream resolution. Only when the backend policy itself allows asking does
provider clarification output have to be persisted; at that point a missing specific
question, a generic fallback question, or fewer than two quick-pick options fails closed
(`StepFailed("clarification_quality_failed")`) and persists nothing. A
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
rare clarification policy. The older **deterministic detail signal**
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
operating point, a provider `needs_clarification` disposition, or a set that needs a
bounded repair pass), the default `estimate_first` policy routes to `parsed` if each
component has a recognizable food/exercise identity and no deterministic validator
finds an unsafe contradiction. Missing amounts become downstream rough assumptions,
not parse questions. `balanced` keeps the FTY-159 calibrated abstention behavior except
that a stated detail is never re-asked; `strict` may still ask for amount precision.
Clarification is *sharpened*, not removed: an empty item list, gibberish/non-log text,
a component with no recognizable identity, an impossible quantity, contradictory
stated nutrition, or exhausted/disabled estimator paths can still ask or fail closed.
A calibrated-confident sample set is unaffected (it never entered the clarify branch),
and the deterministic plausibility gate above still runs on the accepted items.

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
  used; schema-invalid output is rejected (`StepFailed("schema_validation_failed")`)
  and **never persisted** — the step fails closed.
- **User-stated nutrition fields (FTY-279)** validate as finite, non-negative, and
  within the schema abuse cap; an out-of-range/negative/non-finite `stated_*` value
  is schema-invalid and fails closed. Extraction is trusted only as **untrusted
  evidence**: the food step applies the as-logged abuse cap and internal-consistency
  check before any of it backs a persisted number (`evidence-retrieval.md`).
- Closed vocabularies (`disposition`, `CandidateType`) and `extra="forbid"` mean a
  reply cannot smuggle fields or free-form instructions.
- Provider-raised clarification output is advisory under `estimate_first`. If the
  backend policy accepts a clarification outcome, the persisted question must carry
  specific question text and 2–5 options per question; a missing/generic/under-optioned
  accepted question fails closed as `clarification_quality_failed` before persistence.
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
- **Rough-estimate diagnostics are content-free.** Repair attempts, provider-raised
  questions that were overridden by `estimate_first`, default-serving/model-prior
  assumptions, source-miss reasons, and calibration artifacts record only sanitized
  labels and source ids. They never copy raw diary text, raw prompts, raw provider
  output, raw fetched text, or provider error bodies into `trace`, `error`,
  `assumptions`, `source_refs`, logs, or calibration artifacts beyond explicit public
  fixture inputs.
- **Retention** follows the owning log event: derived items and clarification
  questions live until the event, user, or account is deleted (`ON DELETE CASCADE`),
  matching the food/exercise-log retention rule in
  `docs/security/data-retention.md`.

## Errors

| Condition | Result |
| --- | --- |
| Empty/whitespace text | Terminal `failed` (`empty_input`); no LLM call, nothing persisted. |
| Unanimously `unparseable` / no-item trusted set | Terminal `failed`; nothing persisted. |
| Schema-invalid model output (any sample) | Rejected; terminal `failed` (`schema_validation_failed`); nothing persisted. |
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
  → provider question is advisory; bounded repair/selection keeps candidates:
      {type: food, name: "crackers", quantity_text: "", amount: null}
      {type: food, name: "peanut butter", quantity_text: "", amount: null}
  → derived_food_items += rough unresolved candidates
  → event: processing → completed
  # downstream food resolution records rough default/reference/model-prior provenance
  # and keeps the estimate editable; no clarification is asked solely for quantity.
```

```
event.raw_text = "stuff"
  → no recognizable food or exercise identity survives validation/repair
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
- **FTY-298 (contract only; no code, no migration in this story).** Bumps the parse
  contract to the rare clarification policy and reserves
  `FATTY_ESTIMATOR_CLARIFY_MODE` plus optional numeric tunables for downstream
  settings/code stories. `estimate_first` is the new default target: recognized bare
  food/exercise identities are accepted as rough candidates, provider-raised
  clarification is advisory when it conflicts with the policy, and clarification is
  reserved for missing identity, non-log/gibberish input, unsafe contradictions or
  implausibilities, unavailable/disabled estimator paths after bounded recovery, or a
  stricter operator mode. No `ParseResult`, persistence, DTO, or migration changes are
  made here; FTY-299/FTY-300/FTY-301 implement the runtime behavior.
