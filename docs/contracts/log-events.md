# Contract: Log Events

## Purpose

Define the log-event data model, its status state machine, and the create /
list-today / get-by-id API, so a user can turn natural-language input into a
pending raw log event and read their Today events back. This gives the mobile
timeline (FTY-031) and polling (FTY-032) a real backend, and gives the estimator
(Milestone 4) the row it later processes.

This contract covers three things:

1. the `log_events` persistence schema and its migration;
2. the **event status state machine** — the full v1 status vocabulary and the
   legal transitions between statuses, a named contract the estimator stories
   extend without redefining;
3. the create / list-today / get-by-id request/response shapes and their
   object-level authorization rule.

It deliberately excludes estimation, job enqueue, and worker processing
(FTY-040+); derived food/exercise items; and editing or deleting events (later
stories). Saved image attachments are owned by their own contract
(`log-attachments.md`, FTY-077): a `log_attachments` row references a log event but
is written only when the user explicitly saves an uploaded image.

## Owner

backend-core / contracts lane (`backend/app/models/log_events.py`,
`backend/app/schemas/log_events.py`, `backend/app/services/log_events.py`,
`backend/app/routers/log_events.py`, `backend/alembic/`).

## Version

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
  **nullable**), `created_at` (timestamptz, not null, indexed), `updated_at`
  (timestamptz, not null). `created_at` is indexed because the Today timeline
  queries events by day.
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
- `GET /api/users/{user_id}/log-events/{event_id}` — returns one of the user's
  events by id (for polling).

## Outputs

The event DTO (returned by create, each list element, and get-by-id):

```json
{
  "id": "UUID",
  "user_id": "UUID",
  "raw_text": "string",
  "status": "pending | processing | completed | failed | needs_clarification",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

- **Create (fresh)** → `201` with the event DTO at `status: "pending"`.
- **Create (idempotent replay)** → `200` with the **existing** event's DTO at its
  current status (see [Idempotent create](#idempotent-create-201-vs-200)).
- **List-today** → `200` with a JSON array of event DTOs, ordered oldest-first.
- **Get-by-id** → `200` with the event DTO.

The DTO does **not** echo `idempotency_key`: it is a write-only request token with
no consumer need in the response (a client already holds the key it sent).

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

## State machine

`status` is a `LogEventStatus`. The legal transitions are the named contract in
`app/services/log_events.py` (`LEGAL_TRANSITIONS`); the only mutation path
(`transition_event`) rejects any transition not in the map.

| From | To |
| --- | --- |
| `pending` | `processing`, `completed` |
| `processing` | `completed`, `failed`, `needs_clarification` |
| `needs_clarification` | `processing` |
| `completed` | _(terminal)_ |
| `failed` | _(terminal)_ |

FTY-030 implements creation at `pending` and the `pending → completed`
transition (exercised via the service contract before the estimator exists).
The estimator stories drive the `processing` / `failed` / `needs_clarification`
transitions by reusing this map.

## Validation

- `raw_text`: required; trimmed; non-empty after trimming; 1–2000 characters.
  Whitespace-only input is rejected.
- `idempotency_key`: optional; when present, a string, trimmed, non-empty after
  trimming, and at most 200 characters. An over-length, empty/whitespace, or
  wrong-type key is rejected (`422`). It is validated as opaque data only — the
  server never parses it.
- `day`: a valid `YYYY-MM-DD` date; otherwise `422`.
- Unknown request-body keys are rejected (`422`).
- Status is never client-settable on create; it is server-controlled and only
  changes through the state machine.

## Authorization

- Authentication: every endpoint requires a valid, unexpired bearer token;
  otherwise `401`.
- Object-level authorization: a user may create, list, and read **only their
  own** events. `{user_id}` must equal the authenticated user's id, and
  get-by-id is scoped to the owner so a cross-user id is indistinguishable from a
  missing one. A mismatch fails closed as `404` (no existence oracle). Negative
  tests prove create, list, and get-by-id all fail closed.
- The idempotency-key lookup is **scoped to the authenticated user**, so a key can
  only ever address that user's own events: the same key string from two users
  yields two distinct events and never crosses the boundary. Proven by a per-user
  namespacing test alongside the unchanged cross-user negative tests.

## Privacy and Retention

- `raw_text` is sensitive personal data: it is user-owned, never logged, and
  never returned to a non-owner.
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
| `404` | Creating, listing, or reading events for an account the caller does not own; a get-by-id whose event does not exist for the owner (fail closed). |
| `422` | Empty/whitespace/oversized `raw_text`, empty/whitespace/oversized/wrong-type `idempotency_key`, unknown body key, or malformed `day`. |

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

# Poll one event
curl -s :8000/api/users/<uid>/log-events/<event_id> -H 'authorization: Bearer <t>'
# → 200 { "id": "...", "status": "pending", ... }
```

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
```
