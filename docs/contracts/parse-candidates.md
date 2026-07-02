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
by `log-events.md` (FTY-170 defines it; FTY-171 implements); the clarify sheet
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

3 (FTY-159): **pre-v1 breaking behaviour change** (no shim) — the clarify
decision becomes the **data-calibrated policy** (ADR 0003 Layer C). The step
draws N=3 parse samples through the FTY-158 self-consistency sampler (parallel,
unanimous-first-window early stop) and gates on the **hybrid**
agreement+verbalized score against a calibrated operating point
(`app/estimator/clarify_policy.py`), replacing the retired single-call
`confidence < 0.45` comparison. The `ParseResult` schema and persistence
schemas are unchanged (`parse/v1` stays recorded on runs until FTY-172 lands
`parse/v2`); the routing table below is what changed. See "Calibrated clarify
decision (FTY-159)".

2 (FTY-170): **pre-v1 breaking change** (no shim) — the `ParseResult`
clarification carrier becomes structured: `clarification_questions` changes
from `list[str]` to a list of `ClarificationQuestion` objects, each carrying
the specific question `text` plus candidate quick-pick `options` the clarify
sheet renders as tappable chips (audit finding A2). Schema version string
`parse/v2`. The `clarification_questions` table gains an `options` column
(shape specified here; the migration lands with the first producer, FTY-172),
and a fresh clarification round on a re-estimate **replaces** the event's
unanswered question rows. Consumers landing against the new shape: FTY-172
(produce), FTY-171 (serve via the clarification read and resolve via the
answer endpoint — `log-events.md` v4), FTY-153 (render).

1 (FTY-042). Schema version string `parse/v1`, recorded on the estimation run.

## Inputs

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
(≥ 0), optional `barcode` (digits, ≤ 14; FTY-060) and `brand` (≤ 120; FTY-062).
**No energy** — calories/macros are resolved downstream (FTY-043/044).

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
against; free text is always an allowed answer (see `log-events.md`,
Clarification read / Clarification answer). The estimator produces either no
options (the client then shows free-text only) or **2–5 meaningful
candidates** — an FTY-172 prompt requirement; the schema enforces only the
hard count/length caps, so a reply outside the 2–5 guidance is persisted
as-is rather than terminally failing the parse.

String length and list count bounds cap an adversarial or runaway reply.

### Persistence

The `0005` migration creates three user-owned tables (additive; no prior table is
altered):

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
  added by FTY-170, migration lands with FTY-172), `position` (int, stable
  order), `created_at`/`updated_at`. The stored `question_text` + `options`
  are what the clarification read serves (`log-events.md`), so the producer
  (this step) and the reader share one shape field-for-field. Questions the
  backend synthesises deterministically — the plausibility gate's targeted
  question and the persisted default question — carry `options: []`.

## Outputs / Routing

The step draws **N = 3 parse samples** of the entry through the FTY-158
self-consistency sampler (`app/estimator/self_consistency.py`; samples run in
parallel, and a unanimous first window of 2 stops early, so stable inputs pay
two calls and contested inputs pay three). Every sample is schema-validated
independently; the step then routes on the sample set and its **calibrated
clarify decision** (below). When the set is trusted, the routed candidates are
the most self-confident `parsed` sample's items.

| Validated sample set | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| calibrated-confident, ≥1 item, all food candidates plausible | _(completes)_ | candidates `unresolved` | `processing → completed` |
| calibrated-confident, ≥1 item, but a food candidate is implausible | `NeedsClarification` (`implausible_candidate`) | clarification question | `processing → needs_clarification` |
| no sample `parsed`, or the hybrid score is below the calibrated operating point (and no detail-signal override) | `NeedsClarification` | clarification questions (pooled across samples, deduplicated) | `processing → needs_clarification` |
| unanimously `unparseable`, or a trusted set with no items | `StepFailed` (terminal) | nothing | `processing → failed` |
| empty/whitespace input | `StepFailed` (terminal, no LLM call) | nothing | `processing → failed` |
| schema-invalid sample / non-retryable provider error | `StepFailed` (terminal) | nothing | `processing → failed` |
| transient provider error | `StepError` (retryable) | nothing | _(stays `processing`, retried)_ |

A **mixed** set (e.g. one `unparseable` sample alongside `parsed` ones) is
genuine ambiguity, not a terminal failure: the disagreement drags the hybrid
score down and the event clarifies — fail closed toward asking, never toward a
silent guess.

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

A `needs_clarification` reply with no questions persists one default question
(`options: []`) so the event always has at least one for the answer flow.
Candidates and questions are committed in the **same transaction** as the
terminal status, so a completed/clarification outcome and its rows are atomic.
When a **re-estimate** of an answered event (`log-events.md`, Clarification
answer) lands on `needs_clarification` again, the fresh round's questions
**replace** the event's unanswered question rows in that same transaction —
answered questions and their `clarification_answers` are preserved, since they
carry the accumulated details the re-estimate consumes — so the clarification
read (status-gated to `needs_clarification`; `log-events.md`) serves exactly
the fresh round's open questions.

### Detail-signal routing override (FTY-167)

A casual entry is often returned by the model with a conservative confidence (or
even a `needs_clarification` disposition) even though it already carries enough
real-world structure to estimate — "Had a handful (5-10) of deep fried onion rings",
"Had 3 cracker sandwiches", "ran 5 km", "played 3 games of badminton". Before routing
such a reply to clarification, the step checks each extracted item for a **deterministic
detail signal** (`app/estimator/detail_signals.py`):

- **food** — a positive structured `amount` (a count or a measured quantity), or a
  numeric **range** in `quantity_text` (`5-10`);
- **exercise** — an explicit duration, a **distance**, a **step count**, or a **game
  count**.

When the sample set would otherwise clarify (a hybrid score below the calibrated
operating point, or a set that never parsed) **but every extracted item carries a
detail signal**, the step routes to `parsed` instead and lets the calculator layers
estimate — a detail-rich casual log should be estimated, not asked about.
Clarification is *sharpened*, not removed: an empty item list, or **any** item
lacking a detail signal ("some crackers", "played sports"), still routes the whole
event to clarification, because that item's portion is genuinely missing. A
calibrated-confident sample set is unaffected (it never entered the clarify
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

## Validation

- Every provider reply is validated against `ParseResult` before any of it is
  used; schema-invalid output is rejected (`StepFailed("schema_validation_failed")`)
  and **never persisted** — the step fails closed.
- Closed vocabularies (`disposition`, `CandidateType`) and `extra="forbid"` mean a
  reply cannot smuggle fields or free-form instructions.
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
  `schema_validation_failed`, `provider_error`, `provider_transient_error`) are
  persisted on the run.
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
| Non-retryable provider error (`LLMResponseError`/`LLMConfigurationError`) | Terminal `failed` (`provider_error`). |
| Transient provider error (`LLMTransientError`) | Retryable; worker retries within its bound. |
| Ambiguous / below the calibrated operating point | `needs_clarification`; questions (text + options) persisted; the user resolves via the clarification answer (`log-events.md`). |

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
event.raw_text = "crackers and peanut butter"        # count genuinely indeterminate
  → samples disagree (window not unanimous → full N drawn; guessed portions
    diverge / dispositions flip) → hybrid below the calibrated operating point
  → { disposition: needs_clarification, confidence: 0.3, items: [ … ],
      clarification_questions: [
        { text: "How many cracker sandwiches?", options: ["2", "4", "6"] } ] }
  → clarification_questions += one row (question_text, options, position 0)
  → event: processing → needs_clarification
  # the user resolves via POST .../clarification/answers (log-events.md);
  # the re-estimate receives the (question, answer) pair as structured input
```

## Migration / Compatibility

- The `0005` migration applies (`alembic upgrade head`) on top of the estimation
  schema and is fully reversible (`alembic downgrade 0004`), verified by an
  apply/rollback test against a throwaway database.
- Additive: no prior table or column is changed.
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
  consumers to preserve. The `options` migration lands with FTY-172 (the
  first producer); FTY-171 serves the options through the clarification read
  and implements the answer resolve (`log-events.md` v4); FTY-153 renders the
  chips and free-text fallback.
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
