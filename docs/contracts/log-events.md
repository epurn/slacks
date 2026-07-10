# Contract: Log Events

## Purpose

Define the log-event data model, its status state machine, and the create /
list-today / get-by-id API, so a user can turn natural-language input into a
pending raw log event and read their Today events back. This gives the mobile
timeline (FTY-031) and polling (FTY-032) a real backend, and gives the estimator
(Milestone 4) the row it later processes.

This contract covers six things:

1. the `log_events` persistence schema and its migration;
2. the **event status state machine** — the full v1 status vocabulary and the
   legal transitions between statuses, a named contract the estimator stories
   extend without redefining;
3. the create / list-today / get-by-id request/response shapes and their
   object-level authorization rule;
4. a pointer to the **clarify-loop API** for a `needs_clarification` or
   `partially_resolved` event — the clarification read and answer (resolve)
   endpoints now live in their own contract, `clarification.md`, which this
   doc gates by owning the status state machine those endpoints drive;
5. the **day-listing read** (FTY-198) — an owner-scoped, Today-feed-shaped read
   for an arbitrary calendar day, returning each event plus the shared derived
   item read-model (`source` provenance + `is_edited`);
6. the **soft-void (delete) operation** (FTY-321) — `DELETE .../log-events/{id}`
   removes a mislogged entry from the day by setting a terminal `voided_at`
   marker, excluding the event and its derived items from every read model and
   the daily totals **without** hard-deleting any row (the append-only
   audit/provenance stance is preserved).

It deliberately excludes estimation, job enqueue, and worker processing
(FTY-040+); editing an event's derived items (`corrections.md`); and new
derived-item persistence. **Deleting** an event is now in scope as the
soft-void operation (FTY-321, item 6 above): a void is a status marker, not a
hard row deletion, so no derived-item, correction, or evidence row is ever
removed by application code. The day-listing read composes the existing derived
food/exercise item read-model without changing its storage contract. Saved image attachments are owned by their own contract
(`log-attachments.md`, FTY-077): a `log_attachments` row references a log event but
is written only when the user explicitly saves an uploaded image.

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/schemas/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`).

## Version

8 (FTY-321): adds the **soft-void (delete) operation** — `DELETE
/api/users/{user_id}/log-events/{event_id}` — and a nullable `voided_at`
timestamptz on `log_events` (migration `0019`). Voiding is the user removing a
mislogged entry: it sets `voided_at` **once** (a terminal status; there is no
un-void), which excludes the event **and every derived item hanging off it**
from the list / by-date / single GET, the clarification read/answer, the
day-listing items, and the daily-summary intake/exercise/`uncounted_entries`
totals — so the entry disappears from the day. The **keyed create-replay** and
the **single-item mutation endpoints** (correction edit, re-match
candidate-list / re-resolve) **fail closed (`404`)** against a voided event via
backend-core boundary prechecks, since they return/mutate their target row
directly and bypass the read-time join. **No row is hard-deleted**: the
event, its derived items, corrections, and evidence are all retained, preserving
the append-only audit/provenance stance (`corrections.md` reconciled). The
delete is **idempotent** (repeating it returns `204` identically) and works from
any status (`completed` / `needs_clarification` / `failed` / …); a cross-user or
unknown id fails closed as `404` (no existence oracle), matching every other
log-event route. `voided_at` is an orthogonal marker, **not** a new
`LogEventStatus` value, so the event keeps its pre-void estimation status for
audit and the state-machine map is unchanged. Void does **not** cancel an
in-flight or queued estimation (the estimator is void-agnostic;
`estimation-jobs.md` unchanged): derived rows a late estimation writes onto a
voided event are retained-and-excluded by the read-time parent-`voided_at`
join.

7 (FTY-282): relocates the clarify-loop **endpoint contract** — the
clarification read and the clarification answer (resolve), and their
examples — out of this doc into a new `clarification.md` page. **Structural
relocation only, no semantic change**: the read/answer shapes, status gating,
idempotency, and privacy rules are preserved verbatim. This doc keeps
everything else it owns — persistence, create/list/get, the full event status
state machine (including `needs_clarification` and `partially_resolved`),
validation, authorization, privacy/retention, and errors — since the clarify
endpoints are still gated by the statuses defined here.

6 (FTY-278): defines the **item-scoped partial clarification** contract for a
mixed food log by adding a first-class **`partially_resolved`** event status — a
**pre-v1 additive extension** of the status vocabulary and state machine, with no
back-compat shim. Before FTY-278 a mixed log with any un-costable component routed
the *whole* entry to a terminal-with-nothing-committed `needs_clarification` event:
no item was persisted while a question waited. FTY-278 makes clarification
**item-scoped**: the costable components of the entry are committed as `resolved`
derived items (and counted — see `daily-summary.md`) on a new `partially_resolved`
event while a **specific unresolved component** owns the open question.
`needs_clarification` keeps its pre-FTY-278 meaning — event-level clarification
with *nothing* committed (no component individually costed). Concretely this story
settles four contract points and cross-links the affected contracts:

1. **Event status and transitions** — a new **`partially_resolved`** status is the
   item-scoped partial state: it carries committed `resolved` items alongside an
   open item-scoped question. The state machine gains two transitions —
   `processing → partially_resolved` (the estimator commits the costable siblings
   and raises the item-scoped question in one terminal transaction) and
   `partially_resolved → processing` (answering re-estimates the same event).
   `needs_clarification` and its transitions are unchanged and still mean the
   event-level, nothing-committed case.
2. **Question → component reference** — each item-scoped clarification question
   names the specific unresolved component by a stable `derived_food_item_id`
   reference (see `parse-candidates.md`), never by echoing the raw diary phrase.
   That reference is an **internal** producer→estimator link (which component the
   answer-triggered re-estimate re-costs); it is **not** surfaced in the API. The
   **FTY-170 clarification read/answer shape is unchanged** — the read still
   serves `{ id, text, options }`, and the human context is the question `text`,
   which names the component by its sanitized food `name`.
3. **Partial read exposure** — the day-listing read returns a partial event's
   committed `resolved` items (its event-status gate relaxes from `completed`-only
   to `completed` **or** `partially_resolved`); the open question remains
   discoverable through the status-gated clarification read.
4. **Answer flow** — answering an item-scoped question re-estimates **only that
   open component** on the **same** event (`partially_resolved → processing`),
   leaves the already-resolved siblings **untouched** (never re-costing,
   re-creating, or replacing them), and completes the entry when the last
   component resolves, with no double-counting or duplicate item rows (the
   job/run mechanics are `estimation-jobs.md` v3).

**This version is a contract decision only; it edits no product code.** The
downstream estimator/backend implementation is a required follow-up split (called
out under Migration / Compatibility). FTY-301 changes the default amountless case:
recognizable components now rough-estimate under `estimate_first`. Until the
item-scoped follow-up lands, any **remaining** allowed clarification (strict mode,
unsafe input, or every rough path unavailable) is still event-level
`needs_clarification` with no committed siblings.

5 (FTY-198): adds the **day-listing read** —
`GET /api/users/{user_id}/log-events/by-date?day=YYYY-MM-DD` — which returns an
oldest-first list of entries for one profile-timezone calendar day. Each entry
carries the log event envelope plus the same derived item DTOs the Today timeline
renders, including per-item `source` provenance and `is_edited` from the shared
item read-model (`daily-summary.md` / `corrections.md`). Existing create,
list-events, get-by-id, clarification, and label endpoints are unchanged.

4 (FTY-170): a **pre-v1 breaking change** to the clarify loop (no back-compat
shim). The clarification read's per-question shape grows from `{ text }` to
`{ id, text, options }` — each question now carries a stable id and candidate
quick-pick options — and a first-class **clarification answer (resolve)**
endpoint is added:
`POST /api/users/{user_id}/log-events/{event_id}/clarification/answers`. A
valid answer applies a structured detail to the **same** event, drives
`needs_clarification → processing`, and re-estimates the event; the raw phrase
is never mutated and no second event is created. This **retires** the interim
v3 resolve mechanism — re-submitting the combined phrase via the create path
(FTY-149) — which is the documented cause of the raw-phrase-mutation and
duplicate-entry audit findings (A3/A5); the missing question/options in the
read were finding A2. Consumers landing against the new shapes: FTY-172
(estimator produces question + options — see `parse-candidates.md` v2),
FTY-171 (backend serves the new read shape and implements the answer
round-trip — evolving `estimation-jobs.md` beyond its v1 one-job-per-event /
never-reprocessed rules to express the answer-triggered re-estimate; that
amendment landed as `estimation-jobs.md` v2), FTY-153 (mobile clarify sheet).

3 (FTY-152): adds an **owner-scoped clarification read** —
`GET /api/users/{user_id}/log-events/{event_id}/clarification` — that returns the
clarification questions the estimator already persisted for a
`needs_clarification` event (see [Clarification read](clarification.md#clarification-read)). This
is additive: no existing DTO field, endpoint, or status code changes, and no
schema migration is involved (the `clarification_questions` table already exists).
It is the backend half of the "Add a detail" clarify flow; the mobile sheet
(FTY-153) consumes it.

2 (FTY-096): the create request gains an optional, opaque `idempotency_key`, and
create becomes a safe-to-retry **first-write-wins** operation — a fresh create
returns `201`, an idempotent replay of an already-submitted key returns `200`
with the existing event. The key namespace is per-user. This is the backend half
of offline logging (see [Offline submit](#offline-submit-and-the-pending-unparsed-state)).

1 (FTY-030): introduces the `log_events` table, the status state machine, and
the create/list/get API. Creation at `pending` and the `pending → completed`
transition are implemented; the `processing`, `failed`, and
`needs_clarification` transitions are defined in the state machine and
implemented by the estimator stories (Milestone 4).

## Inputs

### Persistence

The `0003` migration creates:

- **`log_events`** — a user-owned raw log entry. Columns: `id` (UUID, PK),
  `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, indexed), `raw_text`
  (text, not null), `status` (string, not null), `idempotency_key` (string,
  **nullable**), `voided_at` (timestamptz, **nullable**, added by the `0019`
  migration), `created_at` (timestamptz, not null, indexed), `updated_at`
  (timestamptz, not null). `created_at` is indexed because the Today timeline
  queries events by day.
- **`voided_at`** (FTY-321) is the **soft-void marker**: `NULL` for a live
  event, set **once** to the void instant when the user deletes the entry. It is
  orthogonal to `status` (the event keeps its pre-void estimation status), and
  every read model filters `voided_at IS NULL` so a voided event and its derived
  rows are retained but never surfaced or counted. Void is terminal — there is
  no un-void, no un-set.
- A composite **unique index** `(user_id, idempotency_key)`
  (`uq_log_events_user_idempotency_key`, added by the `0015` migration) makes the
  key namespace per-user and the database the dedup authority. NULL keys are
  distinct in Postgres (and SQLite), so the online/no-key path and the
  label-upload path keep inserting freely.

### HTTP requests

All requests carry `Authorization: Bearer <token>` and target the
authenticated user's own `{user_id}`.

- `POST /api/users/{user_id}/log-events` —
  `{ "raw_text": str, "idempotency_key"?: str }`. Creates a `pending` event.
  `raw_text` is trimmed; it must be non-empty after trimming and at most 2000
  characters. The optional `idempotency_key` is an **opaque** client token (a
  UUID/ULID by convention — the server never parses or interprets it): trimmed,
  non-empty after trimming when present, and at most 200 characters. Unknown body
  keys are rejected. See [Idempotent create](#idempotent-create-201-vs-200).
- `GET /api/users/{user_id}/log-events?day=YYYY-MM-DD` — lists the user's events
  whose `created_at` falls on `day`, resolved in the user's profile timezone.
  `day` is optional and defaults to the current day in that timezone.
- `GET /api/users/{user_id}/log-events/by-date?day=YYYY-MM-DD` — lists the user's
  day entries in the Today-feed shape: each row has `event` (the event DTO) and
  `items` (derived food/exercise item DTOs with `source` and `is_edited`). The
  same profile-timezone day bounds and oldest-first event ordering as
  `GET .../log-events?day=` apply. `day` is optional and defaults to the current
  day in that timezone.
- `GET /api/users/{user_id}/log-events/{event_id}` — returns one of the user's
  events by id (for polling). A **voided** event is treated as not-found (`404`).
- `DELETE /api/users/{user_id}/log-events/{event_id}` — **soft-voids** the event
  (FTY-321). Sets `voided_at` once and returns `204 No Content` with an empty
  body. Voids the event **regardless of its status** (`pending` / `processing` /
  `completed` / `failed` / `needs_clarification`). **Idempotent**: repeating the
  delete on an already-voided event returns `204` identically (the marker is not
  re-stamped). No request body. Ownership-scoped like every other route — a
  cross-user or unknown id returns `404` (no existence oracle) and mutates
  nothing. See [Soft-void (delete)](#soft-void-delete-fty-321).
- `GET /api/users/{user_id}/log-events/{event_id}/clarification` and
  `POST /api/users/{user_id}/log-events/{event_id}/clarification/answers` — the
  clarify-loop read and answer (resolve) endpoints for a `needs_clarification`
  or `partially_resolved` event. Defined in full, including request/response
  shapes and status gating, in `clarification.md`.

## Outputs

The event DTO (returned by create, each list element, get-by-id, and the
clarification answer):

```json
{
  "id": "UUID",
  "user_id": "UUID",
  "raw_text": "string",
  "status": "pending | processing | completed | failed | needs_clarification | partially_resolved",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

- **Create (fresh)** → `201` with the event DTO at `status: "pending"`.
- **Create (idempotent replay)** → `200` with the **existing** event's DTO at its
  current status; a replay whose stored event has been **voided** (FTY-321) fails
  closed with `404` instead (see
  [Idempotent create](#idempotent-create-201-vs-200)).
- **List-today** → `200` with a JSON array of event DTOs, ordered oldest-first.
- **Day-listing read** → `200` with a JSON array of entry DTOs, ordered
  oldest-first by the owning event:

```json
[
  {
    "event": {
      "id": "UUID",
      "user_id": "UUID",
      "raw_text": "rice and a walk",
      "status": "completed",
      "created_at": "datetime",
      "updated_at": "datetime"
    },
    "items": [
      {
        "item_type": "food",
        "id": "UUID",
        "user_id": "UUID",
        "log_event_id": "UUID",
        "name": "white rice",
        "quantity_text": "1 serving",
        "unit": null,
        "amount": 1.0,
        "status": "resolved",
        "grams": 150.0,
        "calories": 205.0,
        "protein_g": 4.3,
        "carbs_g": 44.5,
        "fat_g": 0.4,
        "calories_estimated": 205.0,
        "protein_g_estimated": 4.3,
        "carbs_g_estimated": 44.5,
        "fat_g_estimated": 0.4,
        "source": {
          "source_type": "trusted_nutrition_database",
          "label": "USDA",
          "ref": "usda_fdc:168880"
        },
        "is_edited": false,
        "created_at": "datetime",
        "updated_at": "datetime"
      }
    ]
  }
]
```

`items` uses the shared `DerivedFoodItemDTO | DerivedExerciseItemDTO` shape from
`corrections.md` / `daily-summary.md`, but only for finalized item detail: the
owning event must be `completed` **or** `partially_resolved` (the FTY-278 partial
state), the item must be `resolved`, and its costed value must be present
(`calories` for food, `active_calories` for exercise). This mirrors the
`daily-summary.md` finalized-state filter exactly — a `resolved`, costed item is
surfaced whether it is the whole of a `completed` entry or a **costable sibling of
a `partially_resolved` entry**, so a mixed log's resolved components appear in
place while its unresolved component's question stays open. A pending, processing,
failed, `needs_clarification`, or completed/partial-with-no-finalized-item event is
still returned with `items: []`, matching the Today timeline's status-row
fallback. Non-finalized item rows — including the **unresolved component** that
owns an item-scoped question — remain persisted with their own `status`
(`unresolved` / `proposed`) and nullable values but are **not** included in this
read; that component is instead discoverable through the status-gated
clarification read (its open question names the component in the question
`text`), so the
`items` array stays "finalized costed detail only" and never surfaces an
uncosted placeholder row. (After FTY-301, recognizable amountless components
usually rough-estimate and complete; if a remaining allowed clarification occurs
before the FTY-278 follow-up, it is still event-level and returns `items: []`.)
- **Get-by-id** → `200` with the event DTO. A voided event is not-found (`404`).
- **Delete (void)** → `204 No Content` with an empty body, on both the first
  void and every idempotent repeat.

The DTO does **not** echo `idempotency_key`: it is a write-only request token with
no consumer need in the response (a client already holds the key it sent).

**Timestamps are UTC, serialized timezone-aware.** `created_at` and `updated_at`
are stored as UTC (`timestamptz`) and serialized as **timezone-aware ISO-8601 with
an explicit UTC offset** (e.g. `2026-06-16T01:00:00Z`) — never a naive datetime a
client would misread as its own local time. This is what lets the client convert an
instant to the device zone unambiguously, so an entry logged the previous local
evening renders — and buckets — under the correct day. The backend enforces this at
the ORM boundary (a UTC-normalizing `timestamptz` type), so the guarantee holds on
every backend regardless of whether the driver preserves the offset on read.

### Idempotent create (`201` vs `200`)

`POST .../log-events` is safe to retry when an `idempotency_key` is supplied —
**first-write-wins**, scoped per user:

- **No key** → behaves exactly as v1: create a `pending` event and enqueue its
  estimation job. Returns `201`. Back-compatible.
- **Key supplied, no event yet for `(user_id, key)`** → create the `pending`
  event, store the key, enqueue the job. Returns `201`.
- **Key supplied, an event already exists for `(user_id, key)`** → return that
  **existing** event's current DTO, create **no** new row, enqueue **no** second
  job. Returns `200`. The `201`/`200` distinction lets the client tell a fresh
  create from a replay.
- **Key supplied, the stored event is voided** (FTY-321) → **fail closed with
  `404`**. The replay is a **read** of the stored event, so it obeys the same
  "excluded from every read" rule as every other read path: a voided event is
  never resurfaced as a live DTO. The key stays **consumed**
  (first-write-wins) — the stored row keeps the key, so no replacement row is
  created and no second job is enqueued. A client that voids an entry and later
  flushes a stale outbox replay of it treats the `404` as expected, exactly as
  it does for get-by-id.

Replay reflects the event's **current** status: if the original has advanced to
`processing` or `completed` before the retry arrives, the replay returns that
status so the client reconciles rather than resetting it.

The create path is **race-safe**: two concurrent same-key submits (a double outbox
flush, parallel retries) converge to one event. The `(user_id, idempotency_key)`
unique index is the guard — the insert that loses the race catches the integrity
violation, re-reads the now-committed sibling, and returns it as the `200` replay.
No `500`, no duplicate, no orphaned second enqueue.

**Body mismatch is not an error.** A replay carrying a different `raw_text` under
the same key still returns the **originally stored** event (no new row, no
re-enqueue); the divergent body is ignored. The offline outbox sends a
byte-identical body by construction, so a mismatch only arises from a client
key-reuse bug, and the client owns key generation.

### Offline submit and the pending-unparsed state

An offline-queued entry is a **client-only** state (the FTY-104 outbox) with **no
server row** until it is submitted. There is no server status for "queued offline":
on submit the entry becomes a server `pending` event — the pending-unparsed,
uncounted state (a raw event exists but no derived items yet, so it does not count
in the day's totals) — and runs the unchanged `pending → processing → completed`
transitions the estimator drives (see `estimation-jobs.md`). A keyed create
enqueues exactly as the no-key path does; the replay path enqueues nothing.

### Clarification read and Clarification answer (resolve)

The clarify-loop read (`GET .../log-events/{event_id}/clarification`) and
answer/resolve (`POST .../log-events/{event_id}/clarification/answers`)
endpoints — their request/response shapes, status gating, idempotency, and the
same-event re-estimate rules — are defined in full in
[`clarification.md`](clarification.md). This doc keeps ownership of the
`needs_clarification` and `partially_resolved` statuses those endpoints read
and drive (see [State machine](#state-machine), below), plus the shared
validation, authorization, privacy, and error rules those endpoints follow
alongside every other endpoint on this resource.

### Soft-void (delete) (FTY-321)

`DELETE /api/users/{user_id}/log-events/{event_id}` lets a user remove a
mistaken or unwanted logged entry. It is a **soft void**, not a hard delete:

- **Marker, not deletion.** The event's `voided_at` is set once (a terminal
  status; there is no un-void). The event row, its derived food/exercise items,
  its corrections, and its evidence rows are all **retained** — nothing is
  hard-deleted — so the append-only audit/provenance stance holds
  (`corrections.md`).
- **Full read-model exclusion.** A voided event disappears from the day: it is
  omitted from list-today, the day-listing (`by-date`) read, and the single
  get-by-id (which returns `404`); its derived items are omitted from the
  day-listing item rows; and its kcal/macros/burn no longer count toward the
  daily summary `intake` / `exercise`, nor does it count toward
  `uncounted_entries` (`daily-summary.md`). The clarification read and answer
  fail closed (`404`) for a voided event.
- **Single-item surfaces fail closed (`404`).** The endpoints that return or
  mutate a specific stored row **directly** — and so never pass through the
  read-time exclusion join above — each refuse a voided target with `404`,
  making the exclusion exhaustive across the surface:
  - the **keyed create-replay** (`POST .../log-events` with an
    `idempotency_key` whose stored event is voided) — see
    [Idempotent create](#idempotent-create-201-vs-200); the key stays consumed
    and no replacement row is created;
  - the **clarification read and answer** (`clarification.md`), as above;
  - the **correction edit**
    (`PATCH .../derived-items/{item_type}/{item_id}`, `corrections.md`) on an
    item whose parent event is voided;
  - the **re-match candidate-list and re-resolve**
    (`POST .../derived-items/food/{item_id}/source-candidates` and
    `.../re-resolve`, `corrections.md`) on an item whose parent event is voided.

  These are backend-core route/service boundary prechecks (each loads the
  target's parent event and rejects when `voided_at` is set); the estimator
  re-match capability and the worker stay void-agnostic. The `404` matches the
  unknown-item/unknown-event shape, so there is no void oracle.
- **Any status.** Voiding works whatever the event's estimation status
  (`pending`, `processing`, `completed`, `failed`, `needs_clarification`) —
  `voided_at` is orthogonal to `status`, and the event keeps its pre-void status
  for audit.
- **Idempotent.** Repeating the delete on an already-voided event returns `204`
  identically and does **not** move `voided_at`; the marker is write-once,
  **first-write-wins** — enforced database-side (the void is a conditional
  `UPDATE … WHERE voided_at IS NULL`), so even concurrent deletes cannot
  re-stamp an already-set marker.
- **Void does not cancel estimation.** A void is a read-model concern, not a
  pipeline stop: it does **not** cancel an in-flight or queued estimation job,
  and the estimator is void-agnostic (`estimation-jobs.md` is unchanged). A
  late estimation that completes after the void is expected and is not an
  error: any derived rows it writes onto the voided event are
  **retained-and-excluded** — persisted like any other derived rows, but never
  surfaced or counted, because every derived-item and daily-summary read joins
  each row to its parent event and drops rows whose parent has `voided_at`
  set. Exclusion happens at read time, so it holds regardless of when the rows
  were written.
- **Ownership fails closed.** The event is loaded scoped to the authenticated
  owner. A cross-user or unknown `event_id` is indistinguishable as `404` (no
  existence oracle) and mutates nothing — the same convention as get-by-id.

The delete adds no un-void/undo endpoint, no bulk delete, and no retention/purge
job (those are out of scope). Because a voided event is excluded from get-by-id,
a client that voids an entry treats a subsequent `404` on that id as expected.

## State machine

`status` is a `LogEventStatus`. The legal transitions are the named contract in
`app/services/log_events.py` (`LEGAL_TRANSITIONS`); the only mutation path
(`transition_event`) rejects any transition not in the map.

| From | To |
| --- | --- |
| `pending` | `processing`, `completed` |
| `processing` | `completed`, `failed`, `needs_clarification`, `partially_resolved` |
| `needs_clarification` | `processing` |
| `partially_resolved` | `processing` |
| `completed` | _(terminal)_ |
| `failed` | _(terminal)_ |

FTY-030 implements creation at `pending` and the `pending → completed`
transition (exercised via the service contract before the estimator exists).
The estimator stories drive the `processing` / `failed` / `needs_clarification`
transitions by reusing this map. The clarification answer (FTY-170;
`clarification.md`) is the user-driven trigger for the already-legal
`needs_clarification → processing` transition; it adds no new status and no
new transition.

**FTY-278 adds the `partially_resolved` status and two transitions** —
`processing → partially_resolved` and `partially_resolved → processing`.
`partially_resolved` is the item-scoped partial state: the event carries committed
`resolved` derived items (the costable siblings of a mixed log) alongside its open
item-scoped question, whereas `needs_clarification` keeps its meaning of
event-level clarification with **nothing** committed. The costable siblings are
committed in the same terminal transaction as the `processing →
partially_resolved` transition — the same atomicity the `processing → completed`
path already uses (`food-resolution.md`). Answering the item-scoped question drives
`partially_resolved → processing` and re-estimates the same event (the FTY-170
answer round-trip, generalized to the new source status). The `needs_clarification`
transitions are unchanged.

**FTY-321 does not add a status value.** The soft-void (delete) operation is an
orthogonal `voided_at` marker on the row, not a member of `LogEventStatus`, so
this transition map is unchanged: a voided event keeps its pre-void status for
audit, and read models simply filter `voided_at IS NULL` on top of the
finalized-state predicate. Void is terminal at the marker level (write-once, no
un-void).

This is the **event** status vocabulary. The separate **derived-item** status
vocabulary (`DerivedItemStatus`: `unresolved` / `resolved`, plus `proposed` added
by FTY-196 for an uncounted, confirmation-required nutrition-label parse) is owned
by the estimator/label contracts (`label-upload.md`, `label-extraction.md`,
`daily-summary.md`), not here — this contract deliberately excludes derived
food/exercise items. FTY-196 adds no event status and does not change this map: a
label event still reaches terminal `completed`; only its food item is held
`proposed` until confirmed.

## Validation

- `raw_text`: required; trimmed; non-empty after trimming; 1–2000 characters.
  Whitespace-only input is rejected.
- `idempotency_key`: optional; when present, a string, trimmed, non-empty after
  trimming, and at most 200 characters. An over-length, empty/whitespace, or
  wrong-type key is rejected (`422`). It is validated as opaque data only — the
  server never parses it.
- `day`: a valid `YYYY-MM-DD` date; otherwise `422`.
- `question_id` (answer submission): required; a UUID. Missing or malformed →
  `422`. Well-formed but not one of the owned event's questions → `404` (fail
  closed, no existence oracle).
- `answer` (answer submission): required; a string, trimmed, non-empty after
  trimming, at most 300 characters. Empty/whitespace-only, oversized, or
  wrong-type → `422` — an empty answer is never submitted.
- Unknown request-body keys are rejected (`422`).
- Status is never client-settable on create; it is server-controlled and only
  changes through the state machine.

## Authorization

- Authentication: every endpoint requires a valid, unexpired bearer token;
  otherwise `401`.
- Object-level authorization: a user may create, list, read, and **void** (delete)
  **only their own** events. `{user_id}` must equal the authenticated user's id, and
  get-by-id and delete are scoped to the owner so a cross-user id is
  indistinguishable from a missing one. A mismatch fails closed as `404` (no
  existence oracle). Negative tests prove create, list, get-by-id, the
  day-listing read, and delete all fail closed. Voiding another user's event is a
  `404` that mutates nothing, so a user can never delete data they do not own.
- The clarification read reuses the same object-level scoping: a cross-user or
  nonexistent `event_id` returns `404` with no existence oracle, proven by a
  cross-user negative test.
- The clarification answer fails closed the same way: the event is loaded
  scoped to the authenticated owner, and `question_id` is resolved **scoped to
  that event** — a cross-user or nonexistent event, or a `question_id` that is
  not one of that event's questions, returns `404` with no existence oracle
  and mutates nothing. Proven by cross-user and cross-event negative tests.
- The idempotency-key lookup is **scoped to the authenticated user**, so a key can
  only ever address that user's own events: the same key string from two users
  yields two distinct events and never crosses the boundary. Proven by a per-user
  namespacing test alongside the unchanged cross-user negative tests.

## Privacy and Retention

- `raw_text` is sensitive personal data: it is user-owned, never logged, and
  never returned to a non-owner.
- Day-listing item names, calories/macros/burn values, and provenance are
  sensitive nutrition data: they are returned only to the owner through the
  scoped read, are not logged, and are derived server-side so the client never
  joins `evidence_sources` / `corrections`.
- `clarification_questions.question_text`, its quick-pick `options`, and
  `clarification_answers.answer_text` are likewise tied to the user's
  sensitive log: they are returned only to the owning client, never logged,
  never copied into estimation-run `trace`/`error` (the `parse-candidates.md`
  no-raw-text rule), and never returned to a non-owner.
- `idempotency_key` is treated as potentially sensitive (a client may derive it
  from content): it is never logged, never returned in the DTO, and never surfaced
  to a non-owner.
- Retention (per `docs/security/data-retention.md`): food and exercise logs are
  retained until user deletion or account deletion. `ON DELETE CASCADE` on
  `user_id` removes a user's events — including the `idempotency_key` column,
  which lives on `log_events` and adds no new retention surface — when the account
  is deleted.

## Errors

| Status | When |
| --- | --- |
| `401` | Missing/invalid/expired bearer token. |
| `404` | Creating, listing, day-listing, or reading events for an account the caller does not own; a get-by-id, **delete (void)**, clarification read, or clarification answer whose event does not exist for the owner (a voided event is not-found for get-by-id and the clarify endpoints); an answer whose `question_id` is not one of the owned event's questions (all fail closed). |
| `409` | A fresh (non-replay) answer for an event not in `needs_clarification` or `partially_resolved` — `{"error": "not_awaiting_clarification"}`; nothing persisted or mutated. |
| `422` | Empty/whitespace/oversized `raw_text`, empty/whitespace/oversized/wrong-type `idempotency_key`, unknown body key, malformed `day`, missing/malformed `question_id`, or empty/whitespace/oversized/wrong-type `answer`. |

## Examples

```sh
# Create a pending event
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast"}'
# → 201 { "id": "...", "status": "pending", "raw_text": "two eggs and toast", ... }

# Offline submit with an idempotency key, then a safe retry of the same key
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast","idempotency_key":"01J...ULID"}'
# → 201 { "id": "abc", "status": "pending", ... }
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast","idempotency_key":"01J...ULID"}'
# → 200 { "id": "abc", "status": "pending", ... }   # same id, no new row, no re-enqueue

# List today's events
curl -s ':8000/api/users/<uid>/log-events?day=2026-06-26' -H 'authorization: Bearer <t>'
# → 200 [ { "id": "...", "status": "pending", ... } ]

# List a day's Today-feed-shaped entries with derived item provenance
curl -s ':8000/api/users/<uid>/log-events/by-date?day=2026-06-26' \
  -H 'authorization: Bearer <t>'
# → 200 [ { "event": { "id": "...", "status": "completed", ... },
#           "items": [ { "item_type": "food", "source": { ... },
#                        "is_edited": false, ... } ] } ]

# Poll one event
curl -s :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 200 { "id": "...", "status": "pending", ... }

# Void (soft-delete) a mislogged entry, then a safe idempotent retry
curl -sX DELETE :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 204 (no body); the event and its items vanish from every read and the day's totals
curl -sX DELETE :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 204   # idempotent: already voided, voided_at unchanged
curl -s :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 404   # a voided event is not-found for get-by-id
```

Clarify-loop examples (reading and answering an event's clarification
questions) live in `clarification.md`.

## Migration / Compatibility

- The `0003` migration applies cleanly (`alembic upgrade head`) on top of the
  goals/targets schema and is fully reversible (`alembic downgrade 0002`),
  verified by a migration apply/rollback test against a throwaway database.
- The `0015` migration (FTY-096) is additive: it adds the nullable
  `idempotency_key` column and the `(user_id, idempotency_key)` unique index to
  `log_events`, with no backfill (existing rows keep a NULL key and are
  unaffected). It applies on top of `0014` and rolls back cleanly
  (`alembic downgrade 0014`), verified by a migration apply/rollback test.
- These are additive migrations; no prior table or column is altered.
- Consumers (FTY-031 timeline, FTY-032 polling) depend on the event DTO and the
  endpoint shapes; the estimator (M4) depends on the table and extends the state
  machine map defined here. The offline outbox (FTY-104) depends on the
  safe-to-retry submit semantics and the `201`/`200` distinction.
- The FTY-152 clarification read is additive and needs no migration: the
  `clarification_questions` table already exists (migration `0005`, FTY-042).
- The `0016` migration (FTY-171) is **additive**: it creates the
  `clarification_answers` table (see **Answer persistence**,
  `clarification.md`) with its
  unique `question_id` idempotency anchor and cascading ownership FKs; no prior
  table or column is altered and no backfill is needed. It applies on top of
  `0015` and rolls back cleanly (`alembic downgrade 0015`), verified by an
  apply/rollback test and exercised against Postgres by the FTY-143 migration
  guard.
- The `0017` migration (FTY-172) is **additive**: it adds the not-null
  `options` JSON column to `clarification_questions`, backfilled/defaulted to
  `[]` for existing deterministic questions. It applies on top of `0016` and
  rolls back cleanly (`alembic downgrade 0016`), verified by an
  apply/rollback test.
- The `0019` migration (FTY-321) is **additive**: it adds the nullable
  `voided_at` timestamptz column to `log_events` with no backfill (existing rows
  keep `voided_at = NULL` and stay live). It applies on top of `0018` and rolls
  back cleanly (`alembic downgrade 0018`), verified by an apply/rollback test
  and exercised against Postgres by the FTY-143 migration guard. Retention is
  unchanged — the column lives on `log_events` and is removed by the existing
  `ON DELETE CASCADE` on account deletion.
- **FTY-170 (breaking, pre-v1, no shim).** The clarification read's
  per-question shape changes from `{ text }` to `{ id, text, options }`, the
  read is scoped to unanswered questions, and the clarification answer
  (resolve) endpoint is added. The interim resolve — re-submitting the
  combined phrase via the create path (FTY-149) — is **retired**; it mutated
  the raw phrase and duplicated entries (audit findings A3/A5). No back-compat
  shim is kept: pre-v1, the old shape has no consumers to preserve. Landing
  order for implementers: the `options` persistence and produce side is the
  parse contract's (`parse-candidates.md` v2, `0017` with FTY-172); the
  `clarification_answers` table, the new read shape, and the answer round-trip
  are FTY-171; the mobile clarify sheet (FTY-153) consumes both new shapes.
- **FTY-278 (contract only; additive, pre-v1, no shim).** Adds the first-class
  `partially_resolved` event status and its two transitions
  (`processing → partially_resolved`, `partially_resolved → processing`) as the
  item-scoped partial state, keeps the **FTY-170 clarification read/answer shape
  unchanged** (the item↔question link stays the internal, producer-side
  `clarification_questions.derived_food_item_id`, `parse-candidates.md` v5 — never
  surfaced in the read), relaxes the day-listing read's event-status gate to
  include `partially_resolved`, and specifies the sibling-preserving answer
  re-estimate. The new status is a value in the existing string `status` column,
  so it needs **no schema migration**. **No code, no migration, and no read/DTO
  change land in this story** — it settles the semantics only. The downstream
  **implementation is a required follow-up split** (planner-decomposed into
  properly-laned stories): (a) a parse/estimator story to persist an entry's
  costable siblings on a `partially_resolved` event and link each item-scoped
  question to its `unresolved` component via the additive, nullable
  `derived_food_items.id` reference on `clarification_questions`
  (`parse-candidates.md` v5 — an additive, reversible migration owned by that
  story); (b) the backend read/answer story that relaxes the day-listing and
  daily-summary reads and implements the sibling-preserving re-estimate
  (`estimation-jobs.md` v3, `daily-summary.md`), leaving the FTY-170
  clarification read/answer shape unchanged; and, once the reads
  expose partial state, an optional mobile presentation story (no visual redesign
  is specified here). Until that split lands, FTY-301's default rough-estimate path
  handles recognizable amountless components; any remaining allowed clarification
  still routes the whole event to event-level `needs_clarification` with nothing
  committed.
