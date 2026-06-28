# Contract: Weight Entries

## Purpose

Define the weight-entry data model and the create / list-by-range / delete API,
so a user can record a dated body-weight time series and read those entries back
over a date range. This gives the mobile weight-trend chart (FTY-074) a real
backend to read from.

This contract covers three things:

1. the `weight_entries` persistence schema and its migration;
2. the canonical-units rule for storing and returning weight — input arrives in
   the user's `units_preference` and is converted deterministically to canonical
   kg on write; reads always return canonical kg;
3. the create / list-by-range / delete request/response shapes and their
   object-level authorization rule.

It deliberately excludes: the mobile weight-trend chart and capture UI (FTY-074);
adaptive calibration of the target calculator from observed weight trend (that
connection is explicitly excluded in `docs/contracts/target-calculator.md`);
updating or syncing the `user_profiles.weight_kg` current-weight snapshot from
entries; editing an existing entry; and any aggregation, smoothing, or trend math
over the series.

## Owner

backend-core / contracts lane (`backend/app/models/weight_entries.py`,
`backend/app/schemas/weight_entries.py`, `backend/app/services/weight_entries.py`,
`backend/app/routers/weight_entries.py`, `backend/alembic/`).

## Version

1 (FTY-070): introduces the `weight_entries` table and the create/list/delete API.
2 (FTY-119): tightens the accepted range of `effective_date` — see Validation below.

## Inputs

### Persistence

The `0013` migration creates:

- **`weight_entries`** — a user-owned dated body-weight observation. Columns:
  `id` (UUID, PK), `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`,
  indexed), `weight_kg` (float, canonical kilograms, not null),
  `effective_date` (date, the calendar day the weight was recorded for,
  indexed), `created_at` (timestamptz), `updated_at` (timestamptz).

This is a time series: multiple entries per user, one or more per effective
date, intentionally independent from the single `user_profiles.weight_kg`
current-weight snapshot.

### HTTP requests

All requests carry `Authorization: Bearer <token>` and target the authenticated
user's own `{user_id}`.

- `POST /api/users/{user_id}/weight-entries` — `{ "weight": float, "effective_date": "YYYY-MM-DD" }`.
  `weight` is in the user's `units_preference` (kg for metric, lb for
  imperial). Unknown body keys are rejected.
- `GET /api/users/{user_id}/weight-entries?from=YYYY-MM-DD&to=YYYY-MM-DD` — lists
  the user's entries whose effective date falls in the range `[from, to]`.
  Both bounds are optional (open-ended when omitted); when both are given,
  `from` must be on or before `to`.
- `DELETE /api/users/{user_id}/weight-entries/{entry_id}` — deletes one of the
  user's own entries.

## Outputs

The weight-entry DTO (returned by create and each list element):

```json
{
  "id": "UUID",
  "user_id": "UUID",
  "weight_kg": 70.5,
  "effective_date": "YYYY-MM-DD",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

- **Create** → `201` with the entry DTO. `weight_kg` is always canonical kg.
- **List-by-range** → `200` with a JSON array of entry DTOs, ordered oldest-first
  (by `effective_date` ascending, then `id` as a stable tiebreaker).
- **Delete** → `204` (no body).

## Canonical-Units Rule

`weight_kg` is always stored and returned in canonical kilograms regardless of
the user's `units_preference`.

- **Metric users** — the submitted `weight` value is already in kg and is stored
  unchanged.
- **Imperial users** — the submitted `weight` value is treated as pounds and
  converted to kg using the exact NIST factor:
  **1 international avoirdupois pound = 0.45359237 kg**.

The conversion is a pure, deterministic function (`lb_to_kg` /
`to_canonical_kg` in `app/services/weight_entries.py`) that lives in one place
so this path, the profile `weight_kg` field, and any future target-calculator
consumer all agree on the same factor.

`units_preference` is a display choice and never changes what is stored.

## Validation

- `weight`: required; must be strictly positive (validated at the schema
  boundary); after conversion to canonical kg must fall in `(0, 1000]` (the
  same bounds used by the profile `weight_kg` field); values outside the
  post-conversion range are rejected with `422`.
- `effective_date`: a valid `YYYY-MM-DD` calendar date; malformed strings are
  rejected with `422`. The accepted range is `[1900-01-01, today-in-user-tz + 1 day]`
  where "today" is resolved in the user's profile timezone (falling back to UTC).
  The +1 day slack absorbs clock/timezone skew between the client and the server's
  resolved "today". Dates before the floor or beyond the slack are rejected with `422`.
- Range params (`from` / `to`): valid `YYYY-MM-DD` dates; when both are
  provided, `from` must be on or before `to`; violation returns `422`.
- Unknown request-body keys are rejected with `422` (`extra="forbid"`).

## Authorization

- Authentication: every endpoint requires a valid, unexpired bearer token;
  otherwise `401`.
- Object-level authorization: a user may create, list, and delete **only their
  own** entries. `{user_id}` must equal the authenticated user's id, and a
  cross-user `entry_id` on the delete path is scoped to the owner so it is
  indistinguishable from a missing entry. A mismatch fails closed as `404`
  (no existence oracle). Negative tests prove create, list, and delete all fail
  closed, and that a cross-user `entry_id` on the owner's own path is also a
  `404`.

## Privacy and Retention

- Body weight is sensitive personal data: it is user-owned, never logged, and
  never returned to a non-owner.
- Retention (per `docs/security/data-retention.md`): body weight entries are
  retained until user deletion or account deletion. `ON DELETE CASCADE` on
  `user_id` removes all of a user's entries when the account is deleted (this
  is the primary deletion path for account deletion).
- The delete endpoint satisfies the data-retention requirement that users must
  be able to delete individual weight entries.

## Errors

| Status | When |
| --- | --- |
| `401` | Missing/invalid/expired bearer token. |
| `404` | Creating, listing, or deleting entries for an account the caller does not own; a delete whose entry does not exist or belongs to another user (fail closed). |
| `422` | Non-positive weight, post-conversion weight outside `(0, 1000]` kg, malformed date, `effective_date` before `1900-01-01` or after today-in-user-tz + 1 day, inverted range (`from > to`), unknown body key. |

## Examples

```sh
# Create a metric weight entry
curl -sX POST :8000/api/users/<uid>/weight-entries \
  -H 'authorization: Bearer <t>' -H 'content-type: application/json' \
  -d '{"weight": 70.5, "effective_date": "2026-06-27"}'
# → 201 { "id": "...", "user_id": "...", "weight_kg": 70.5, "effective_date": "2026-06-27", ... }

# List entries for June 2026
curl -s ':8000/api/users/<uid>/weight-entries?from=2026-06-01&to=2026-06-30' \
  -H 'authorization: Bearer <t>'
# → 200 [ { "id": "...", "weight_kg": 70.5, "effective_date": "2026-06-27", ... } ]

# Delete an entry
curl -sX DELETE :8000/api/users/<uid>/weight-entries/<entry_id> \
  -H 'authorization: Bearer <t>'
# → 204
```

## Migration / Compatibility

- The `0013` migration applies cleanly (`alembic upgrade head`) on top of the
  evidence-assumptions schema (`0012`) and is fully reversible (`alembic
  downgrade 0012`), verified by a migration apply/rollback test against a
  throwaway database.
- This is an additive migration: a new table only; no prior table or column is
  altered.
- `weight_entries` is independent from `user_profiles.weight_kg`; FTY-074
  reads this series, and any calibration consumer (target calculator) is a
  later, separate story.
- Consumers (FTY-074 weight-trend chart) depend on the entry DTO and the
  endpoint shapes defined here.
