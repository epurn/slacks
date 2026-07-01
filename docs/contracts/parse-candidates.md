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
`estimation-jobs.md`). It excludes calorie/macro resolution (FTY-044), exercise
burn (FTY-043), and the clarification **answer** flow, `clarification_answers`,
and UI (a later story).

## Owner

estimator / contracts / backend-core lane:
`backend/app/schemas/parse.py`, `backend/app/estimator/parse.py`,
`backend/app/models/derived.py`, `backend/app/enums.py`
(`CandidateType`, `DerivedItemStatus`), `backend/alembic/`.

## Version

1 (FTY-042). Schema version string `parse/v1`, recorded on the estimation run.

## Inputs

### LLM output schema (`ParseResult`)

The strict schema the step enforces and validates (`extra="forbid"` on every
object — smuggled keys are rejected, not ignored):

| Field | Type | Notes |
| --- | --- | --- |
| `disposition` | `parsed` \| `needs_clarification` \| `unparseable` | Closed vocabulary; how the model classified the whole entry. |
| `confidence` | float `[0, 1]` | Gated against a documented threshold. |
| `items` | `ParsedCandidate[]` (≤ 32) | Extracted candidates. |
| `clarification_questions` | string[] (≤ 8, ≤ 300 chars) | Present on the ambiguous path. |
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
  `question_text`, `position` (int, stable order), `created_at`/`updated_at`.

## Outputs / Routing

The step validates the reply, then routes on the schema-validated disposition and
confidence (threshold `PARSE_CONFIDENCE_CLARIFY_THRESHOLD`, default `0.45`, a
documented tunable — below it the step clarifies even on a `parsed` reply):

| Validated reply | Pipeline signal | Persisted | Event transition |
| --- | --- | --- | --- |
| `parsed`, confident, ≥1 item, all food candidates plausible | _(completes)_ | candidates `unresolved` | `processing → completed` |
| `parsed`, confident, ≥1 item, but a food candidate is implausible | `NeedsClarification` (`implausible_candidate`) | clarification question | `processing → needs_clarification` |
| `needs_clarification`, or confidence below threshold | `NeedsClarification` | clarification questions | `processing → needs_clarification` |
| `unparseable`, or `parsed` with no items | `StepFailed` (terminal) | nothing | `processing → failed` |
| empty/whitespace input | `StepFailed` (terminal, no LLM call) | nothing | `processing → failed` |
| schema-invalid / non-retryable provider error | `StepFailed` (terminal) | nothing | `processing → failed` |
| transient provider error | `StepError` (retryable) | nothing | _(stays `processing`, retried)_ |

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

A `needs_clarification` reply with no questions persists one default question so
the event always has at least one for the later answer flow. Candidates and
questions are committed in the **same transaction** as the terminal status, so a
completed/clarification outcome and its rows are atomic.

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

When the model's reply would otherwise clarify (low confidence or a
`needs_clarification` disposition) **but every extracted item carries a detail signal**,
the step routes to `parsed` instead and lets the calculator layers estimate — a
detail-rich casual log should be estimated, not asked about. Clarification is *sharpened*,
not removed: an empty item list, or **any** item lacking a detail signal ("some crackers",
"played sports"), still routes the whole event to clarification, because that item's
portion is genuinely missing. A high-confidence `parsed` reply is unaffected (it never
entered the clarify branch), and the deterministic plausibility gate above still runs on
the accepted items.

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
  candidate names and questions are stored as data through parameterized inserts.
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
| `unparseable` / no-item `parsed` | Terminal `failed`; nothing persisted. |
| Schema-invalid model output | Rejected; terminal `failed` (`schema_validation_failed`); nothing persisted. |
| Non-retryable provider error (`LLMResponseError`/`LLMConfigurationError`) | Terminal `failed` (`provider_error`). |
| Transient provider error (`LLMTransientError`) | Retryable; worker retries within its bound. |
| Ambiguous / low confidence | `needs_clarification`; questions persisted (terminal for now). |

## Examples

```
event.raw_text = "two eggs and a 30 min run"
  → structured_completion(prompt, ParseResult)
  → { disposition: parsed, confidence: 0.95, items: [
        {type: food, name: "eggs", quantity_text: "two", amount: 2},
        {type: exercise, name: "run", quantity_text: "30 min"} ] }
  → derived_food_items += eggs (unresolved); derived_exercise_items += run (unresolved)
  → event: processing → completed
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
  The later clarification story consumes the persisted questions and adds the answer
  flow.
- FTY-060 (`barcode`) and FTY-062 (`brand`) add optional, length-bounded
  `ParsedCandidate` fields. Both are additive and backward-compatible: a reply that
  omits them validates unchanged (they default to `null`), and they are stored as data
  only. `brand` drives official-source routing (`food-resolution.md`); it adds no
  persistence column of its own (it is consumed at resolution time).
