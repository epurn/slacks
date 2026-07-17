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
answer **endpoint and persistence** are `clarification.md`'s; this contract
owns the job/run mechanics of the answer-triggered re-estimate (v2, below).

## Owner

estimator / backend-core / contracts lane:
`backend/app/models/estimation.py`, `backend/app/enums.py`,
`backend/app/schemas/estimation.py`, `backend/app/estimator/pipeline.py`,
`backend/app/estimator/processing.py`, `backend/app/estimator/enqueue.py`,
`backend/app/estimator/tasks.py`, `backend/app/worker.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`.

## Version

6 (FTY-374, contract only; no schema change to these tables): the worker learns
to feed a **unified text+image submission** (`log-events.md` v9) to the
estimator. The `EstimationJobPayload` is **unchanged — ids only, reaffirmed**:
no image bytes, paths, or hashes ever ride the queue or logs. Instead, the
worker **loads the event's transient image attachments by `log_event_id` at
claim time** (`log-attachments.md` v3) and passes them to the pipeline as
`ImageInput`s (`llm-provider.md` v2 `images=`). An image-bearing NL event runs
the **text-parse / interpretation pipeline augmented with the images as vision
evidence surfaces** (`parse-candidates.md` v12) — *not* the label-only
`label_pipeline` — and the worker **purges the event's transient rows in the
same transaction as the terminal status write** (`completed`/`failed`) unless
they were saved. Implementation is the downstream **FTY-375/FTY-376** split.
See [Image-bearing events](#image-bearing-events-fty-374).

5 (FTY-363, descriptive; no schema change): the retry/terminal state machine gains
a **per-run provider-call / wall-clock ceiling** — a run-scoped bound on total
sequential provider work *within one attempt*, distinct from the attempt-level
retries. A run that breaches it terminates `processing → failed` immediately as a
`StepFailed`-class (deterministic, non-retryable) failure with a content-free
reason, so a pathological input can no longer keep an event `processing` past the
live smoke's poll window. No schema change; the attempt-level bounds are unchanged.
See [Retry policy](#retry-policy).

4 (FTY-255, additive): estimation runs record a **sanitized structured decision
trace**. Alongside the coarse step labels, the food-resolution steps append
bounded, sanitized decision entries to `estimation_runs.trace` — which source
tier saw each candidate, which non-secret source reference was considered, and
why the resolver accepted, rejected, deferred, or clarified — so a source-routing
audit no longer needs product-cache queries or ad hoc search/fetch probes. The
run `provider`/`model` now record the **configured provider selector and model
string** (`openai` vs `openai_compatible`/OpenRouter, and e.g.
`deepseek/deepseek-chat-v3`) rather than a shared adapter label with a blank
model. No schema change (`trace` is already JSON). See
[Decision trace](#decision-trace-fty-255).

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
follow-up**. FTY-301 rough-estimates recognizable amountless components under the
default policy; until item-scoped partials land, any remaining allowed
clarification still routes to an event-level `needs_clarification` with no
committed siblings, so the re-estimate is the v2 event-level round-trip unchanged. See
[Answer-triggered re-estimate](#answer-triggered-re-estimate-fty-171).

2 (FTY-171): the **answer-triggered re-estimate**. The clarification answer
(`clarification.md`) re-opens a job terminal in `needs_clarification` so the
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

**FTY-374 reaffirms this shape unchanged for image-bearing events**: no image
bytes, storage paths, content hashes, or any other image-derived value is ever
placed on the queue, in task arguments, or in logs. The worker reaches the
images through the database, by the event id it already carries (see
[Image-bearing events](#image-bearing-events-fty-374)).

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

A log event created by the standalone synchronous **nutrition-label upload**
(FTY-061/FTY-064, `label-upload.md`) runs a separate `label_pipeline(provider)`
instead — a single `label_resolve` step that reads the image through the v2
vision provider and costs it deterministically, because a label event has an
image rather than NL text. It uses the same step-signal vocabulary and status
transitions; see `label-extraction.md`.

**Pipeline selection for image-bearing events (FTY-374):** an event created by
the unified text+image submission (`log-events.md` v9) is an **NL event with
image evidence**, not a label event — it runs `default_pipeline` (the
parse/interpretation path) **augmented with the event's images as vision
evidence surfaces**, never `label_pipeline`. Text supplies identity, count, and
context; an image supplies label facts as `user_label`-tier evidence
(`parse-candidates.md` v12, `label-extraction.md`, `evidence-retrieval.md`).
The `label_pipeline` remains reserved for the synchronous label endpoint's
"photograph a label, nothing typed" flow and is unchanged, as is its FTY-196
confirmation gate.

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

A valid, fresh clarification answer (`clarification.md`) re-estimates the
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
  `processing` window the event's already-committed `resolved` siblings **stay
  counted** in every finalized read — the scoped re-estimate is admitted by the
  two-clause discriminator (a committed `resolved` sibling **and** an open
  item-scoped question on a still-`unresolved` component; FTY-349,
  `daily-summary.md`), not
  excluded — so the day total never dips and reappears; only the still-open
  component stays uncounted until it resolves. When the round commits, the
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
  the sibling-preserving estimator work is the downstream FTY-278 follow-up. Until
  that lands, only remaining allowed clarifications after FTY-301's rough-estimate
  fallback carry no committed siblings, so this reduces to the v2 event-level
  re-estimate.

### Image-bearing events (FTY-374)

An event created with images (`log-events.md` v9) runs the same claim → run →
transition machinery with four additional rules, implemented by the downstream
FTY-375/FTY-376 split:

- **Worker-side image load, by event id.** At claim time the worker loads the
  event's `log_attachments` rows by `log_event_id`, scoped to the job's
  `user_id` like the event itself (a cross-user row is unreachable by
  construction), and places them on the `EstimationContext` as `ImageInput`s
  (`llm-provider.md` v2). The queue payload stays ids-only; the database is the
  only channel image bytes travel from create to worker.
- **Vision gating — an image never reaches a non-vision model.** Images are
  supplied to the provider only when the configured model is vision-capable
  (`SLACKS_LLM_SUPPORTS_VISION=true`; `llm-provider.md` fails fast otherwise).
  On a non-vision deployment the worker does **not** pass the images: the run
  proceeds on the text surface alone as a visibly rough estimate (the
  *estimate-first / never-reject* clause — a configuration limit is
  infrastructure trouble, never grounds for a terminal `failed`). An
  image-only event (marker `raw_text`, no usable text surface) on a non-vision
  deployment routes to a clarifying question rather than terminal failure.
- **Same run bounds, same re-estimate.** The attempt-level retry policy and
  the per-run provider-call / wall-clock ceiling (FTY-363) apply unchanged. An
  answer-triggered re-estimate reloads the event's still-retained transient
  images the same way (they are retained across the awaiting-answer window —
  `log-attachments.md` v3), so a clarify round never loses the image evidence.
- **Terminal purge.** When the run drives the event to a terminal status
  (`completed` / `failed`), the worker **hard-deletes the event's
  `transient = true` attachment rows in the same transaction as the terminal
  status write** — atomic with the outcome, so no purge job, no orphaned
  window. Saved rows (`transient = false`) are never touched. Worker-terminal
  clarification outcomes (`needs_clarification` / `partially_resolved`) purge
  nothing.

**Image egress and privacy.** Images are untrusted input sent to the
**LLM/vision provider only** (`llm-provider.md` — data, never instructions).
They are never sent to search, fetch, OCR-web, or any other egress; never
logged; never placed on the queue; and never copied — as bytes, paths, or
hashes — into `estimation_runs` `trace` or `error` (the evidence row's
`content_hash` provenance lives in `evidence_sources`, not the run). Errors
stay content-free. Prompt-injection printed on an image is data, never
instructions: image-derived output crosses the same schema-validation trust
boundary as any text output before anything is persisted.

## Decision trace (FTY-255)

`estimation_runs.trace` is a JSON array of two entry shapes:

- **Step entries** (`{"step", "status"}`) — the FTY-040 coarse per-step record,
  unchanged.
- **Decision entries** (`{"step", "decision", …}`) — bounded structured records
  the food-resolution steps (`food_resolve`, `official_source_resolve`) and the
  parse/interpretation step (`parse`, FTY-325) append so a failed or
  fallen-through estimate — or a degenerate interpretation hypothesis — is
  auditable from the run alone. Owned by
  `backend/app/estimator/decision_trace.py`, which sanitizes every value.

A decision entry carries `step`, `decision`, and a **closed** optional field set
(unknown fields are a programming error, not an extension channel):

| Field | Type | Meaning |
| --- | --- | --- |
| `decision` | label | What kind of decision: `candidate` (per-candidate intro), `source` (a source tier saw the candidate), `search` (one identity-query variant executed), `fetch` (one result-URL fetch), `extract` (one untrusted-text transcription), `serving` (serving-math routing), `outcome` (the candidate's terminal route), `hypothesis_revision` (an interpretation-hypothesis event on the parse step — FTY-324/FTY-325; its `outcome` labels are the sanitized hypothesis-revision vocabulary pinned in `parse-candidates.md`, e.g. `initial_hypothesis`, `item_split`, `item_added`, `brand_revised`, `hypothesis_kept`, `revision_truncated`, `deterministic_gate_failed`, `clarification_needed`), `trace_truncated` (bound marker). |
| `candidate_index` | int | Position in the parsed food-candidate list — never the candidate's name or text. |
| `has_brand` | bool | Whether the candidate names a branded product. |
| `amount_kind` | label | `mass` / `volume` / `count` / `missing` / `unknown` — the parsed quantity's shape without its text. |
| `tier` | label | Source tier consulted: `usda_fdc`, `open_food_facts`, `official_source`, `reference_source`, `model_prior`, or the bounded re-query tool `interpretation_session`. |
| `query_variant` | int | Which bounded FTY-253 identity-query variant produced this decision. |
| `search_status` | label | The FTY-079 lookup status (`success`, `partial`, `failed`, …). |
| `result_count` | int | Candidate URLs the search returned (clamped); on a `hypothesis_revision` entry, the hypothesis candidate count. |
| `source_ref` | ref | Non-secret source reference (`usda_fdc:<fdcId>`, `official_source:<url>`); an embedded URL keeps **scheme/host/path only** — query string, fragment, and userinfo are dropped, and each remaining hostname label and path segment is redacted of secret-looking material (`key=…` pairs, provider-key prefixes, long opaque token blobs), so a token embedded in an untrusted result URL's subdomain or path never persists. |
| `source_desc` | label | Bounded description of a **global** source row (e.g. the rejected FDC description) — global source data, never user text. |
| `surface` | label | For `extract`: `page` (fetched body) or `snippet` (FTY-314 title+snippet fallback). |
| `outcome` | label | Sanitized outcome, e.g. `accepted`, `accepted_snippet`, `miss`, `rejected_brand_mismatch`, `rejected_incompatible_row`, `rejected_unresolvable_quantity`, `rejected_incompatible_serving`, `deferred_to_web_evidence`, `clarified_quantity`, `clarified_unknown_food`, `clarified_barcode_unknown`, `unresolved_no_source`, `source_unavailable`, `search_disabled`, `search_unavailable`, `fetch_unconfigured`, `not_applicable_by_session`, `skipped_long_source_ref`, `fetch_ok`, `fetch_empty_text`, `fetch_<status>` (HTTP status, e.g. `fetch_403`), `fetch_policy_blocked`, `fetch_transient_error`, `fetch_response_error`, `extract_error`, `extract_unresolved`, `extract_low_confidence`, `extract_rejected_facts`, `snippet_unavailable`, `count_serving_scaled`, `default_serving_estimated`, `as_logged_total`, `requery_revised_identity`, `requery_identity_unchanged`, `requery_truncated`, `requery_<sanitized_step_reason>`, `model_prior_unavailable`, `model_prior_unusable`, and model-prior detail labels `provider_error`, `low_confidence`, `non_resolved_disposition`, `unusable_facts`. |

Sanitization and bounds (enforced at entry construction, defence in depth over
the steps' own fixed vocabularies): labels are length-bounded,
control-character-stripped, and redacted of secret-looking material (`key=…`
pairs, bearer tokens, long opaque blobs); counts are clamped non-negative; the
trace is capped per run — once the bound is reached a single
`trace_truncated` marker is appended and further decisions are dropped. The
hard FTY-040 rule is unchanged and tested: **no raw event text, prompts,
provider output, API keys/tokens, fetched pages, snippets, or source payload
bodies** ever enter `trace`, `error`, or logs. Food identity is deliberately
excluded from decision entries — candidate drafts are product data persisted to
their own tables, and the trace carries booleans, refs, and reason labels
instead. Needs-clarification runs keep their full decision context (the trace is
written before the terminal status), so the route to a question is explainable
even though no derived food rows are persisted.

**Provider/model identity.** `estimation_runs.provider` records the configured
provider **selector** (`openai`, `openai_compatible`, `anthropic`,
`claude_code`, `codex`, `fake`) — not the shared wire-format adapter label — and
`estimation_runs.model` records the configured model string
(`SLACKS_LLM_MODEL`; empty only for CLI-session providers using their session
default). Both are operator configuration, never secrets.

Retention is unchanged: the trace lives on `estimation_runs`, cascades with the
owning log event / user (see **Privacy and Retention**), and adds no new stored
surface (`docs/security/data-retention.md`, "Estimation runs").

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
- **Per-run provider-call / wall-clock ceiling (FTY-363).** A *distinct*,
  **run-scoped** bound on the total sequential provider work **within one
  attempt**, separate from the attempt-level retries above. The worker wraps the
  run's provider so every LLM/provider call across all pipeline steps is counted
  and time-checked; a run exceeding a total provider-call budget
  (`DEFAULT_MAX_PROVIDER_CALLS`) or a wall-clock deadline
  (`DEFAULT_RUN_DEADLINE_SECONDS`, an injectable-clock elapsed check, below the
  live smoke's 90s poll window) terminates as a **`StepFailed`-class**
  (deterministic, non-retryable) failure — `processing → failed` immediately, **no
  additional attempt consumed** on the same input (a re-run would hit the same
  bound). The failure reason is a fixed, content-free label
  (`run_provider_call_budget_exceeded` / `run_wall_clock_deadline_exceeded`) — no
  raw prompt, provider output, user text, or credential. This is a runaway-cost /
  denial-of-service guard on the untrusted-input path, so failing closed on breach
  is the security-preferred behaviour. The ceiling terminates the run identically on
  **both** run shapes: the first-pass worker path and the answer-triggered **scoped
  re-estimate** — a breach there fails the run closed (`processing → failed`) rather
  than reopening a component question. Defaults live next to the retry constants
  (`backend/app/estimator/run_budget.py`) and may be tuned like them. The
  attempt-level retry bound, backoff schedule, and per-call rate-limit retry above
  are unchanged.
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
- Jobs carry event/user ids; logs use ids, never raw text. Image-bearing events
  (FTY-374) add nothing to this surface: image bytes/paths/hashes never appear
  on the queue, in logs, or in `trace`/`error` — the worker reads images from
  the database and sends them to the vision provider only.
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
| Per-run ceiling breached (`StepFailed`-class, FTY-363: provider-call budget or wall-clock deadline) | Run + job + event `failed` immediately (no retry); content-free reason. |
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
  (the additive `clarification_answers` table is `clarification.md`'s, migration
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
  follow-up; until then, FTY-301 rough-estimates recognizable amountless items by
  default and any remaining allowed clarification stays event-level.
- **v6 (FTY-374, contract only; no code, no migration in this story).** Adds
  the image-bearing-event rules: worker-side image load by `log_event_id` at
  claim time onto the context as `ImageInput`s, pipeline selection
  (`default_pipeline` augmented with images, never `label_pipeline`), vision
  gating with the never-reject degrade path, the terminal-transaction purge of
  transient attachment rows, and provider-only image egress. The
  `EstimationJobPayload`, both tables, the claim/idempotency/ownership rules,
  the retry policy, and the FTY-363 ceiling are all unchanged. Implementation:
  **FTY-375** (ingestion/retention + the `log-attachments.md` v3 migration) and
  **FTY-376** (worker/pipeline consumption).
- **FTY-334 (brand cutover, mechanical rename).** The LLM model reference for
  `estimation_runs.model` documented here now uses the `SLACKS_LLM_MODEL`
  environment key, renamed from the legacy prefix as part of the repo-wide brand
  cutover to Slacks. This is not a contract version bump — the field meaning,
  its operator-configuration (non-secret) nature, and worker/retention semantics
  are unchanged.
