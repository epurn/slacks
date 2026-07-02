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
food resolution (FTY-044), LLM provider integration (FTY-041), the clarification
answer flow, and any derived-item / evidence tables (owned by the step stories).

## Owner

estimator / backend-core / contracts lane:
`backend/app/models/estimation.py`, `backend/app/enums.py`,
`backend/app/schemas/estimation.py`, `backend/app/estimator/pipeline.py`,
`backend/app/estimator/processing.py`, `backend/app/estimator/enqueue.py`,
`backend/app/estimator/tasks.py`, `backend/app/worker.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`.

## Version

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
persists). A step signals a non-success outcome by raising:

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
| needs clarification | `needs_clarification` | `needs_clarification` | `processing → needs_clarification` |
| failed (retryable), retries remain | `failed` | `running` | _(stays `processing`)_ |
| failed (retryable), bound reached | `failed` | `failed` | `processing → failed` |
| failed (deterministic, `StepFailed`) | `failed` | `failed` | `processing → failed` (immediate, no retry) |

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
  `processing` and leaves it. A job already in a terminal status
  (`succeeded` / `failed` / `needs_clarification`) is never reprocessed — that is
  what makes re-delivery a no-op. (FTY-171 amends the `needs_clarification`
  arm of this rule for the user-driven clarification resolve — see
  Migration / Compatibility.)
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
| Ambiguous input (`NeedsClarification`) | Run + job + event `needs_clarification` (terminal). |

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
- **Pending amendment (FTY-170 → FTY-171).** `log-events.md` v4 defines a
  first-class clarification answer that drives
  `needs_clarification → processing` on the same event and mandates a
  **re-estimate** with the accumulated (question, answer) pairs as structured
  input. This contract as written (v1) cannot express that re-estimate: the
  unique `log_event_id` on `estimation_jobs` allows exactly one job per
  event, and a job terminal in `needs_clarification` is never reprocessed —
  both rules predate a user-driven resolve and treat `needs_clarification` as
  the end of the job's life. FTY-171 (which implements the answer round-trip)
  must evolve this contract with a version bump defining the re-estimate's
  job/run mechanics — e.g. re-opening the event's job for a fresh
  answer-triggered attempt/run — while preserving redelivery idempotency for
  queue-delivered tasks. Until FTY-171 lands, the answer endpoint does not
  exist, so no running behaviour contradicts v1.
