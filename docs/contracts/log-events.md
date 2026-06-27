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
  (text, not null), `status` (string, not null), `created_at` (timestamptz, not
  null, indexed), `updated_at` (timestamptz, not null). `created_at` is indexed
  because the Today timeline queries events by day.

### HTTP requests

All requests carry `Authorization: Bearer <token>` and target the
authenticated user's own `{user_id}`.

- `POST /api/users/{user_id}/log-events` — `{ "raw_text": str }`. Creates a
  `pending` event. `raw_text` is trimmed; it must be non-empty after trimming
  and at most 2000 characters. Unknown body keys are rejected.
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

- **Create** → `201` with the event DTO at `status: "pending"`.
- **List-today** → `200` with a JSON array of event DTOs, ordered oldest-first.
- **Get-by-id** → `200` with the event DTO.

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

## Privacy and Retention

- `raw_text` is sensitive personal data: it is user-owned, never logged, and
  never returned to a non-owner.
- Retention (per `docs/security/data-retention.md`): food and exercise logs are
  retained until user deletion or account deletion. `ON DELETE CASCADE` on
  `user_id` removes a user's events when the account is deleted.

## Errors

| Status | When |
| --- | --- |
| `401` | Missing/invalid/expired bearer token. |
| `404` | Creating, listing, or reading events for an account the caller does not own; a get-by-id whose event does not exist for the owner (fail closed). |
| `422` | Empty/whitespace/oversized `raw_text`, unknown body key, or malformed `day`. |

## Examples

```sh
# Create a pending event
curl -sX POST :8000/api/users/<uid>/log-events \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"raw_text":"two eggs and toast"}'
# → 201 { "id": "...", "status": "pending", "raw_text": "two eggs and toast", ... }

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
- This is an additive migration; no prior table or column changes.
- Consumers (FTY-031 timeline, FTY-032 polling) depend on the event DTO and the
  endpoint shapes; the estimator (M4) depends on the table and extends the state
  machine map defined here.
```
