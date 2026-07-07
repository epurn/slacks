# Contract: Estimation Jobs

## Purpose

Define the async estimation engine that turns a freshly created `pending` log
event into an estimated result. Creating a log event (FTY-030) enqueues a job; an
idempotent, retry-aware worker claims the event, records an auditable estimation
run, drives the event through the log-event status state machine, and runs a
**pluggable pipeline** whose parse/calculation steps are stubbed here and
implemented by FTY-042/043/044.

This contract covers four things:

1. the `estimation_jobs` and `estimation_runs` persistence schemas and their
   migration;
2. the **Celery job payload** published on event creation;
3. the **worker behaviour** — idempotency, ownership, the retry policy, and the
   status transitions it drives on the FTY-030 state machine;
4. the **pluggable pipeline step interface** the estimator step stories implement.

It deliberately excludes actual NL parsing (FTY-042), exercise math (FTY-043),
food resolution (FTY-044), LLM provider integration (FTY-041), and any
derived-item / evidence tables (owned by the step stories). The clarification
answer **endpoint and persistence** are `log-events.md`'s (v4); this contract
owns the job/run mechanics of the answer-triggered re-estimate (v2, below).

## Owner

estimator / backend-core / contracts lane:
`backend/app/models/estimation.py`, `backend/app/enums.py`,
`backend/app/schemas/estimation.py`, `backend/app/estimator/pipeline.py`,
`backend/app/estimator/processing.py`, `backend/app/estimator/enqueue.py`,
`backend/app/estimator/tasks.py`, `backend/app/worker.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`.

## Version

3 (FTY-278, contract only): the answer-triggered re-estimate under **item-scoped
partial resolution**. The new first-class `partially_resolved` event status
(`log-events.md` v6) carries committed `resolved` derived items (the costable
siblings of a mixed log — `food-resolution.md` v9); answering an **item-scoped**
question re-estimates the same event (`partially_resolved → processing`) and must
**preserve those siblings** without re-costing, duplicating, or double-counting
them. The v2 job/run mechanics (re-open the terminal job, cumulative attempts,
commit-first enqueue, redelivery idempotency) are **unchanged** — the pipeline's
"needs clarification" outcome keeps its `needs_clarification` run/job status and
just drives the event to `partially_resolved` instead of `needs_clarification`
when it commits costable siblings; this version adds one rule on the pipeline's
terminal write — the answer-triggered re-estimate re-costs **only the open
component** and **leaves the already-`resolved` siblings untouched**, so each
component is represented exactly once and no sibling is re-created or
double-counted. No
schema change (`estimation_jobs` / `estimation_runs` untouched). This settles the
mechanics only; the estimator implementation is the **downstream FTY-278
follow-up**, and until it lands a mixed log routes to an event-level
`needs_clarification` with no committed siblings (the FTY-275 baseline) so the
re-estimate is the v2 event-level round-trip unchanged. See
[Answer-triggered re-estimate](#answer-triggered-re-estimate-fty-171).

2 (FTY-171): the **answer-triggered re-estimate**. The clarification answer
(`log-events.md` v4) re-opens a job terminal in `needs_clarification` so the
same event can be estimated again with the user's accumulated answers as
structured input. v1's "one job per event" anchor is unchanged; its "a job
terminal in `needs_clarification` is never reprocessed" rule is **amended**:
the *resolve* — never the worker — re-opens such a job (`needs_clarification →
queued`, in the same transaction that persists the answer and drives the event
`needs_clarification → processing`) and enqueues a fresh task with the same
payload. Redelivery idempotency for queue-delivered tasks is preserved: the
worker still treats a terminal job as a no-op, so only a first-write-wins
answer (unique per question) can re-open it. See
[Answer-triggered re-estimate](#answer-triggered-re-estimate-fty-171).

1 (FTY-040): introduces `estimation_jobs` / `estimation_runs`, the enqueue
trigger, the worker, the retry policy, and the stub pipeline. The pipeline's
parse/calc steps are stubs; FTY-042/043/044 replace them without changing the
worker contract.

## Inputs

### Persistence

The `0004` migration creates two user-owned tables (additive; no prior table is
altered):

- **`estimation_jobs`** — at most one job per log event. Columns: `id` (UUID,
  PK), `log_event_id` (UUID, FK → `log_events.id`, `ON DELETE CASCADE`, **unique**,
  indexed — the idempotency anchor), `user_id` (UUID, FK → `users.id`,
  `ON DELETE CASCADE`, indexed), `status` (string, `EstimationJobStatus`),
  `attempts` (int), `max_attempts` (int), `idempotency_key` (string, unique),
  `created_at` / `updated_at` (timestamptz).
- **`estimation_runs`** — one auditable record per attempt. Columns: `id` (UUID,
  PK), `job_id` (UUID, FK → `estimation_jobs.id`, `ON DELETE CASCADE`, indexed),
  `log_event_id` (UUID, FK → `log_events.id`, `ON DELETE CASCADE`, indexed),
  `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, indexed), `attempt`
  (int), `status` (string, `EstimationRunStatus`), `provider` / `model` /
  `schema_version` (nullable strings), `tool_names` / `source_refs` /
  `assumptions` / `validation_errors` (JSON arrays), `trace` (JSON, sanitized),
  `error` (nullable text, sanitized), `created_at` / `updated_at` (timestamptz).

### Job payload (`EstimationJobPayload`)

Published when a log event is created and consumed by the worker. Ids only — no
sensitive text — so queue logs cannot leak personal data. Re-validated at the
worker trust boundary (`extra="forbid"`).

```json
{ "log_event_id": "UUID", "user_id": "UUID" }
```

### Pipeline step interface

A step carries a stable `name` and a `run(context)` that mutates an
`EstimationContext` (appending sanitized `tool_names`, `source_refs`,
`assumptions`, `validation_errors`, and `trace` entries; setting
`provider` / `model` / `schema_version`; and, for the parse step, accumulating
`food_candidates` / `exercise_candidates` / `clarification_questions` the worker
persists). As input the context carries the event's untrusted `raw_text` and —
on an answer-triggered re-estimate (v2) — `answered_clarifications`, every
answered (question, answer) pair the parse step folds in as delimited,
untrusted structured detail (never copied into `trace`/`error`). A step signals
a non-success outcome by raising:

- `NeedsClarification(reason)` — terminal, **not** retried (only the user can
  resolve ambiguous input);
- `StepFailed(reason)` — terminal, **not** retried: a deterministic failure
  (empty/garbage/unparseable input, or model output that failed schema validation)
  where retrying the same input cannot help. The worker fails the event
  immediately rather than burning retries (added in FTY-042);
- `StepError(message)` — a *retryable* transient failure.

`default_pipeline(provider)` wires the real FTY-042 parse step ahead of the real
FTY-043 `exercise_calculate` step. (FTY-040 shipped two stub steps; FTY-042 replaced
`stub_parse` with the provider-driven parse step — see `parse-candidates.md` — and
FTY-043 replaced `stub_calculate` with the deterministic MET exercise-burn step —
see `exercise-burn.md`. Food resolution, FTY-044, is still to come.)

A log event carrying a user-provided **nutrition-label image** (FTY-061) runs a
separate `label_pipeline(provider)` instead — a single `label_resolve` step that
reads the image through the v2 vision provider and costs it deterministically,
because a label event has an image rather than NL text. It uses the same step-signal
vocabulary and status transitions; see `label-extraction.md`.

## Outputs / State machine

The worker reuses the FTY-030 `LEGAL_TRANSITIONS` map (it does not redefine it):

| Pipeline outcome | Run status | Job status | Log-event transition |
| --- | --- | --- | --- |
| (claimed) | `running` | `running` | `pending → processing` |
| completed | `completed` | `succeeded` | `processing → completed` |
| needs clarification, **no** component costed | `needs_clarification` | `needs_clarification` | `processing → needs_clarification` |
| needs clarification, **≥1 sibling committed** (item-scoped, FTY-278) | `needs_clarification` | `needs_clarification` | `processing → partially_resolved` |
| failed (retryable), retries remain | `failed` | `running` | _(stays `processing`)_ |
| failed (retryable), bound reached | `failed` | `failed` | `processing → failed` |
| failed (deterministic, `StepFailed`) | `failed` | `failed` | `processing → failed` (immediate, no retry) |

The **run/job status is `needs_clarification` for both clarification outcomes** —
it is the worker-terminal, awaiting-answer status, re-opened only by the
clarification resolve. FTY-278 adds no run/job status: whether the event lands
`needs_clarification` (nothing costed) or `partially_resolved` (costable siblings
committed) is decided at the **event** transition, and the resolve re-opens the
`needs_clarification` job identically in either case.

### Answer-triggered re-estimate (FTY-171)

A valid, fresh clarification answer (`log-events.md` v4) re-estimates the
**same** event. The resolve endpoint — not the worker — prepares the job, all
in the one transaction that persists the `clarification_answers` row:

- **Re-open:** the job goes `needs_clarification → queued`, and `max_attempts`
  is extended to `attempts + DEFAULT_MAX_ATTEMPTS`, granting the re-estimate a
  fresh bounded retry budget. `attempts` stays **cumulative** — run `attempt`
  numbers keep increasing monotonically, so the run history remains one honest,
  ordered audit trail across rounds.
- **Event transition:** the resolve drives the event to `processing`
  (`needs_clarification → processing` for an event-level question,
  `partially_resolved → processing` for an item-scoped one — both legal in the
  FTY-030 map) *before* publishing, so the worker finds an already-`processing`
  event with a non-terminal job and simply runs the pipeline — the claim rule is
  unchanged.
- **Enqueue:** a fresh task is published with the same `EstimationJobPayload`
  (ids only), commit-first like create.
- **Structured answers in the pipeline:** the worker loads every answered
  (question, answer) pair for the event onto the `EstimationContext`
  (`answered_clarifications`), and the parse step folds them into the prompt as
  delimited, untrusted structured detail. `raw_text` is passed through
  unchanged — the answer never rewrites the phrase. If the enriched input is
  still genuinely indeterminate, the fresh clarification round **replaces** the
  event's unanswered question rows in the terminal transaction
  (`parse-candidates.md`); answered questions and their answers are kept.
- **Redelivery idempotency preserved:** the worker never re-opens a terminal
  job, so a redelivered task for a job that has gone terminal (again) is still
  a no-op. The re-open itself is idempotent per question — the unique
  `question_id` on `clarification_answers` is the anchor; a replayed answer
  neither re-opens nor re-enqueues.
- **Resolved siblings preserved untouched, never double-counted (FTY-278, contract only):**
  when the event carries committed `resolved` siblings from an earlier round
  (the `partially_resolved` item-scoped partial state — `log-events.md` v6,
  `food-resolution.md` v9),
  the re-estimate re-costs **only the open (newly-answered) component** and
  **leaves the already-`resolved` siblings untouched** — it neither re-costs,
  re-creates, nor replaces them. The answered component's own row is advanced
  **in place** from `unresolved` to `resolved`; each component is therefore
  represented exactly once, so a sibling is never re-costed into a duplicate row
  or counted twice. During the
  `processing` window a `processing` event is excluded from every finalized read
  (`daily-summary.md`), so intake never flickers; when the round commits, the
  siblings are still their original `resolved` rows and the answered component is
  now `resolved` (or, if still indeterminate, the event stays `partially_resolved`
  with a fresh item-scoped question while the siblings stay resolved). When
  the last unresolved component resolves the event reaches `completed` with the
  full costed set. Because an item-scoped question's `derived_food_item_id` is
  `ON DELETE SET NULL` (`parse-candidates.md` v5), not `CASCADE`, an answered
  question is never cascade-deleted with its unique `question_id` answer anchor:
  the answered component's row is updated in place (not deleted), and were a
  referenced derived-item row ever removed the link is simply nulled — detaching
  the question and preserving the accumulated detail. This is the target contract;
  the sibling-preserving estimator
  work is the downstream FTY-278 follow-up. Under the FTY-275 baseline the event
  carries no committed siblings, so this reduces to the v2 event-level re-estimate.

## Retry policy

- **Bounded retries.** `DEFAULT_MAX_ATTEMPTS = 3` (the initial attempt plus two
  retries). Each attempt increments `estimation_jobs.attempts`; once it reaches
  `max_attempts`, the job and event are marked `failed`.
- **Exponential backoff.** `retry_countdown(retries)` = `10s × 2^retries`, capped
  at `600s` → 10s, 20s, 40s. Celery schedules the retry; the worker core only
  reports whether a retry is due.
- **Idempotency key.** Derived from the log event id (`estimation_jobs` has a
  unique `log_event_id`), so there is exactly one job per event and a redelivered
  task is recognised rather than duplicated.
- These values are conservative documented defaults and may be tuned (story
  planning notes).

## Validation

- The job payload is schema-validated at the worker boundary; unknown keys are
  rejected.
- The event is claimed only from `pending`; a re-entry mid-retry finds it
  `processing` and leaves it — the same path an answer-triggered re-estimate
  takes, since the resolve drives the event to `processing` before enqueueing.
  A job in a terminal status (`succeeded` / `failed` / `needs_clarification`)
  is never reprocessed **by the worker** — that is what makes re-delivery a
  no-op. The only way out of terminal `needs_clarification` is the user-driven
  clarification resolve, which re-opens the job to `queued` at answer time
  (v2; see [Answer-triggered re-estimate](#answer-triggered-re-estimate-fty-171)).
- All step output written to a run is sanitized; raw user text is never copied
  into `trace` or `error`.

## Authorization

- The worker loads the event **scoped to the job's `user_id`**; a missing or
  cross-user event fails closed with `EstimationEventNotFound` and nothing is
  processed. Both tables carry `user_id` at the persistence boundary.
- The enqueue trigger runs only after the FTY-030 create path's own object-level
  authorization succeeds, so a failed cross-user create publishes no job.

## Privacy and Retention

- `estimation_runs` stores only sanitized reproducibility metadata
  (model/provider, schema version, tool names, source references, assumptions,
  validation errors) plus a sanitized trace and error — **no raw prompts, no
  secrets, no raw user text** (security baseline + `docs/security/data-retention.md`,
  "Estimation runs").
- Jobs carry event/user ids; logs use ids, never raw text.
- Retention follows the owning log event: `ON DELETE CASCADE` on `log_event_id`
  (and `user_id`) removes a user's jobs and runs when the event or account is
  deleted.

## Errors

| Condition | Result |
| --- | --- |
| Redelivered task for a terminal job | No-op; no new run, no re-advance. |
| Event missing or owned by another user | `EstimationEventNotFound` (fail closed); event untouched. |
| Transient step failure (`StepError`), retries remain | Run `failed`; job stays `running`; task retried with backoff. |
| Transient step failure (`StepError`), bound reached | Run + job + event `failed`. |
| Deterministic step failure (`StepFailed`) | Run + job + event `failed` immediately (no retry). |
| Ambiguous input (`NeedsClarification`) | Run + job `needs_clarification`; event `needs_clarification` (nothing costed) or `partially_resolved` (costable siblings committed — FTY-278). Terminal for the worker; only the clarification resolve re-opens it — v2/v3. |

## Examples

```
POST /api/users/{uid}/log-events  →  201 pending event
  └─ enqueue EstimationJobPayload{ log_event_id, user_id }
       └─ worker: get-or-create job → claim event (pending→processing)
            → create estimation_run (attempt N) → run pipeline
            → completed: run=completed, job=succeeded, event=completed
```

## Migration / Compatibility

- The `0004` migration applies cleanly (`alembic upgrade head`) on top of the
  log-events schema and is fully reversible (`alembic downgrade 0003`), verified
  by an apply/rollback test against a throwaway database.
- Additive: no prior table or column is changed. It extends the FTY-030 create
  path (enqueue) and reuses the FTY-030 state-machine map.
- FTY-042/043/044 implement real pipeline steps against the step interface. The
  worker's claim → run → transition and idempotency/ownership contracts are
  unchanged; FTY-042 additively extended the step-signal vocabulary with the
  terminal `StepFailed` (deterministic, non-retryable) outcome and persists its
  candidates/questions to their own tables (see `parse-candidates.md`).
- **v2 (FTY-171, no migration).** The answer-triggered re-estimate lands the
  amendment FTY-170 recorded here: the clarification resolve re-opens a job
  terminal in `needs_clarification` (`→ queued`, `max_attempts` extended to
  `attempts + DEFAULT_MAX_ATTEMPTS`) in the same transaction as the answer and
  the `needs_clarification → processing` transition, then enqueues a fresh
  task. No schema change: `estimation_jobs` / `estimation_runs` are untouched
  (the additive `clarification_answers` table is `log-events.md`'s, migration
  `0016`). The unique `log_event_id` (one job per event) still holds — a
  re-estimate is a new attempt/run on the *same* job, not a second job — and
  redelivery idempotency for queue-delivered tasks is preserved because the
  worker itself never re-opens a terminal job. See
  [Answer-triggered re-estimate](#answer-triggered-re-estimate-fty-171).
- **v3 (FTY-278, contract only; no migration).** Adds the sibling-preserving
  rule for the answer-triggered re-estimate — it re-costs only the open component
  and leaves the already-`resolved` siblings untouched — so a mixed log's costable
  components can be committed on a `partially_resolved` event and preserved
  untouched across clarification rounds without duplication or double-counting. The v1/v2 claim →
  run → transition, idempotency, ownership, and retry contracts are unchanged, and
  `estimation_jobs` / `estimation_runs` are untouched (the item↔question link is
  `clarification_questions.derived_food_item_id`, `parse-candidates.md` v5's
  additive column). The estimator implementation is the downstream FTY-278
  follow-up; the FTY-275 baseline ships until then.
