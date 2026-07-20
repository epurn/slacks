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
food/exercise item read-model without changing its storage contract. Image attachments are owned by their own contract
(`log-attachments.md`): a `log_attachments` row references a log event and is
written either when the user explicitly saves an uploaded image (FTY-077) or
transiently — purged at estimation-terminal — for a unified text+image
submission (FTY-374, `log-event-images.md`).

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/schemas/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`).

## Version

The version history has moved to
[log-events-history.md](log-events-history.md#version) — every prior
`### Version N (FTY-###)` entry lives there, and new version entries are
recorded there.

## Inputs

### Persistence

The `0003` migration creates:

- **`log_events`** — a user-owned raw log entry. Columns: `id` (UUID, PK),
  `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, indexed), `raw_text`
  (text, not null), `name` (string, **nullable**, added by the `0023`
  migration), `status` (string, not null), `idempotency_key` (string,
  **nullable**), `voided_at` (timestamptz, **nullable**, added by the `0019`
  migration), `created_at` (timestamptz, not null, indexed), `updated_at`
  (timestamptz, not null). `created_at` is indexed because the Today timeline
  queries events by day.
- **`name`** (FTY-421) is the **model-generated meal label** — a short,
  human-readable name (e.g. `"Turkey sandwich"`) the estimator (FTY-422) writes.
  It is **never user-authored** in v1 (no rename UI yet): `NULL` on every
  existing row and on every freshly-created event until estimation names it, so
  it is always safe to be `null`. It is derived user data (a label over what the
  user logged) — not sensitive in the way `raw_text` is, but still user content,
  so it is returned only to the owner and kept out of logs/errors alongside
  `raw_text`.
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

- `POST /api/users/{user_id}/log-events` — creates a `pending` event. Accepts
  **either** of two content types (FTY-374):
  - `application/json` — `{ "raw_text": str, "idempotency_key"?: str }`,
    **byte-for-byte unchanged** from v1/v2. `raw_text` is trimmed; it must be
    non-empty after trimming and at most 2000 characters. The optional
    `idempotency_key` is an **opaque** client token (a UUID/ULID by convention —
    the server never parses or interprets it): trimmed, non-empty after trimming
    when present, and at most 200 characters. Unknown body keys are rejected.
    See [Idempotent create](#idempotent-create-201-vs-200).
  - `multipart/form-data` — one JSON `payload` part (same field rules as the
    JSON body) plus 0..N binary `image` parts, with an optional `save` query
    flag. Wire shape, validation, and limits:
    [log-event-images.md](log-event-images.md).
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
  "name": "string | null",
  "status": "pending | processing | completed | failed | needs_clarification | partially_resolved",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

`name` (FTY-421) is the nullable, model-generated meal label. It is **always
present** in the response shape and `null` until the estimator (FTY-422) names
the event — every event create/get/list here returns `name: null`.

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
      "name": null,
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
owning event must be `completed`, `partially_resolved` (the FTY-278 partial
state), **or** `processing` as an answer-triggered scoped re-estimate of a
previously-partial event (FTY-349) — discriminated by **two** facts on the event: a
committed `resolved` item **and** an open item-scoped clarification question on a
still-`unresolved` component; the item must be `resolved`, and its costed value must
be present (`calories` for food, `active_calories` for exercise). This mirrors the
`daily-summary.md` finalized-state filter exactly — a `resolved`, costed item is
surfaced whether it is the whole of a `completed` entry or a **costable sibling of
a `partially_resolved` entry**, so a mixed log's resolved components appear in
place while its unresolved component's question stays open. The same committed
siblings stay surfaced while the event momentarily flips `partially_resolved →
processing` to re-cost the still-open component, so the by-date read never drops a
committed sibling during the re-estimate window (no dip, matching the
`daily-summary.md` no-dip guarantee). A pending, **first-pass** processing (owns no
open item-scoped question, so it surfaces nothing early — excluded even inside the
worker's two-commit completion window, where committed `resolved` rows briefly
coexist with the `processing` status), failed, `needs_clarification`, or
completed/partial-with-no-finalized-item event is still returned with `items: []`,
matching the Today timeline's status-row fallback. Non-finalized item rows — including the **unresolved component** that
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

### Images on create (FTY-374)

Specified in [log-event-images.md](log-event-images.md): the multipart wire
shape (`payload` part + 0..N `image` parts + `save` query flag), the
at-least-one-surface rule and the `"Photo log"` marker for image-only
submissions, the fail-closed per-image validation (`MAX_SUBMISSION_IMAGES = 4`,
10 MiB, allowlist + signature), the async never-reject routing rationale, and
the transient-then-purge retention (`log-attachments.md` v3). On this page's
surfaces nothing changes: both content types create exactly one `pending`
event and enqueue exactly one job; first-write-wins idempotency holds and a
keyed replay **re-ingests nothing** (the "body mismatch is not an error" rule
extends to image parts, which a replay ignores entirely); the status state
machine, `daily-summary.md` counting, and soft-void (FTY-321) are unchanged.

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
mistaken or unwanted logged entry as a **soft void**, not a hard delete: it sets
a write-once terminal `voided_at` marker, and the event plus every row hanging
off it are **retained** (nothing hard-deleted, no `ON DELETE CASCADE`) while
being excluded from every read model and the day's totals. The full normative
semantics live in **[log-event-soft-void.md](log-event-soft-void.md)**:
marker-not-deletion, full read-model exclusion, the fail-closed
single-item-surface enumeration (keyed create-replay, clarification read/answer,
correction edit, re-match candidate-list/re-resolve, label-proposal
read/confirm), any-status voiding, database-enforced idempotent
first-write-wins, void-does-not-cancel-estimation with retained-and-excluded
late derived rows, and owner-scoped no-oracle `404`s.

This page keeps the entries that page's semantics point back to: the `voided_at`
persistence column ([Persistence](#persistence)), the `DELETE` endpoint listing
([HTTP requests](#http-requests)) and its `204` response
([Outputs](#outputs)), the voided-replay `404` on idempotent create
([Idempotent create](#idempotent-create-201-vs-200)), and the state-machine note
that void adds no `LogEventStatus` value ([State machine](#state-machine)).

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

- `raw_text`: required on the `application/json` create; trimmed; non-empty
  after trimming; 1–2000 characters. Whitespace-only input is rejected. On a
  `multipart/form-data` create it is optional **only when at least one `image`
  part is present**, and obeys the same rules when present (FTY-374).
- Multipart `payload` / `image` parts and the `save` query flag: validated
  fail-closed **before** any event, attachment, enqueue, or model call —
  limits, ordering, and rejection statuses in
  [log-event-images.md](log-event-images.md).
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
- `name` (FTY-421) is derived user data — a model-generated label over what the
  user logged. It is not sensitive in the way `raw_text` is, but it is still user
  content: returned only to the owner through the event DTO and kept out of
  logs/errors alongside `raw_text` where those already redact event content.
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
| `413` / `415` | A multipart create `image` part failing size / content-type+signature validation; the whole submission is rejected — no event, no attachment, no enqueue, no model call (`log-event-images.md`). |
| `422` | Empty/whitespace/oversized `raw_text`, empty/whitespace/oversized/wrong-type `idempotency_key`, unknown body key, malformed `day`, missing/malformed `question_id`, empty/whitespace/oversized/wrong-type `answer`, or a malformed/over-limit/empty multipart submission (`log-event-images.md`). |

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

The migration / compatibility history has moved to
[log-events-history.md](log-events-history.md#migration--compatibility) —
every prior migration and compatibility note lives there, and new notes are
recorded there.
