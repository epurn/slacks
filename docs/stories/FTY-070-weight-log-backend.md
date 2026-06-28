---
id: FTY-070
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
  - security-privacy
review_focus:
  - object-level-authz
  - migration-rollback
  - units-conversion
  - input-validation
risk: medium
tags:
  - weight
  - api
  - contracts
  - time-series
approved_dependencies: []
requires_context:
  - docs/contracts/identity-and-profile.md
  - docs/contracts/log-events.md
  - docs/contracts/target-calculator.md
  - docs/security/security-baseline.md
  - docs/security/data-retention.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-070: Weight Log Backend

## State

ready

## Lane

backend-core

## Dependencies

- FTY-020
- FTY-021

## Outcome

A user can record dated body-weight entries — a time series, distinct from the single current `weight_kg` on their profile — and list those entries over a date range through the API. This gives the mobile weight-trend chart (FTY-074) a real backend to read, and explains why a weight time series exists separate from the profile snapshot (the target calculator references calibration from observed weight trend; that calibration is out of scope here).

## Scope

- Add a new additive migration creating a user-owned `weight_entries` table: `id` (UUID, PK), `user_id` (UUID, FK → `users.id`, `ON DELETE CASCADE`, indexed), `weight_kg` (float, canonical kilograms), an effective date/timestamp (the day the weight was recorded for, indexed because the chart queries by date range), `created_at`, `updated_at`. This is a time series: multiple entries per user, one (or more) per effective date, distinct from the single `user_profiles.weight_kg` current-weight snapshot.
- Store weight in **canonical kg**. Accept input in the user's `units_preference` (`metric` → kg, `imperial` → lb) and convert deterministically to kg on write, the same canonical-units discipline used by the profile (`weight_kg`) and the exercise-burn calculator. `units_preference` is a display choice and never changes what is stored.
- Implement endpoints, mirroring the log-events shapes and object-level authorization:
  - `POST /api/users/{user_id}/weight-entries` — create one weight entry from a weight value (in the user's units) plus an effective date; returns the typed entry DTO with weight in canonical kg.
  - `GET /api/users/{user_id}/weight-entries?from=YYYY-MM-DD&to=YYYY-MM-DD` — list the user's entries whose effective date falls in the range, resolved in the user's profile timezone; ordered oldest-first.
  - `DELETE /api/users/{user_id}/weight-entries/{entry_id}` — delete one of the user's own entries (the data-retention deletion requirement for weight entries). If a trivial owner-scoped delete is not clean to land in this slice, it may be deferred to a follow-up and the story promoted as `ready_with_notes`; the create + list round-trip is the load-bearing contract.
- Enforce object-level authorization on every access path: `{user_id}` must equal the authenticated user's id; cross-user create/list/delete and a cross-user `entry_id` fail closed as `404` (no existence oracle), same discipline as log-events and the profile.
- Validate input: `weight` within plausible bounds (reuse the profile / exercise-burn `(0, 1000]` kg style, applied after conversion to canonical kg); effective date a valid `YYYY-MM-DD`; range params valid dates with `from <= to`; unknown request-body keys rejected (`422`).

## Non-Goals

- The mobile weight-trend chart and any weight-entry capture UI (FTY-074).
- Adaptive calibration of the target calculator from observed weight trend (referenced by `docs/contracts/target-calculator.md`, explicitly excluded there too).
- Updating the profile's current `weight_kg` snapshot from entries, or any sync between the two — they remain independent in this slice.
- Editing an existing entry (only create / list / delete are in scope).
- Aggregation, smoothing, moving averages, or trend math over the series.

## Contracts

- `weight_entries` table + entry DTO contract (canonical `weight_kg`, effective date, timestamps, `user_id` ownership key). The DTO returns weight in canonical kg.
- The create and list-by-range request/response shapes, consumed by FTY-074.
- The units-conversion rule: input arrives in the user's `units_preference` and is converted deterministically to canonical kg on write; reads return canonical kg. This is the same canonical-units discipline established by the profile and exercise-burn contracts.
- Retention behavior is documented per the data-retention PR requirement (new stored field): body weight entries are retained until user/account deletion, removed by `ON DELETE CASCADE`, and the deletion requirement is satisfied by the delete endpoint.

## Security / Privacy

Body weight is sensitive personal data. It must be user-owned with object-level authorization on every access path, proven by negative tests that fail closed (`404`, no existence oracle). Weight values must never be logged and never returned to a non-owner. `ON DELETE CASCADE` on `user_id` removes a user's entries on account deletion, and the delete endpoint satisfies the data-retention deletion requirement that users be able to delete weight entries. Rated medium: a new table and migration plus new endpoints, handling sensitive but simple, self-contained data with no external providers or LLM input.

## Acceptance Criteria

- `POST` creates a `weight_entries` row at the given effective date with weight stored in canonical kg, and returns the typed entry DTO.
- Unit conversion is correct and deterministic: a value submitted in lb by an `imperial`-preference user is stored as the equivalent kg; a `metric`-preference user's kg value is stored unchanged. Conversion is unit-tested at exact and boundary values.
- `GET` list-by-range returns only the authenticated user's entries whose effective date falls in `[from, to]`, resolved in the user's profile timezone, ordered oldest-first — a create + list round-trip returns the written entry in canonical kg.
- Cross-user create, list, and delete (and a cross-user `entry_id`) fail closed as `404`, proven by negative authorization tests.
- `DELETE` removes one of the owner's entries (or, if deferred, the story is promoted `ready_with_notes` documenting the deferral and the `ON DELETE CASCADE` path still covers account deletion).
- Validation rejects out-of-bounds weight (outside `(0, 1000]` kg after conversion), malformed dates, an inverted range, and unknown body keys with a clear error shape (`422`).
- The migration applies (`alembic upgrade head`) and rolls back cleanly; entries carry `user_id` ownership and `ON DELETE CASCADE`.
- `make verify` passes.

## Verification

- Run `make verify` (API + migration + authz tests).
- Apply and roll back the new `weight_entries` migration against a throwaway database (migration apply/rollback test).
- Unit-test the kg/lb canonical conversion at exact values, boundary values, and invalid inputs.
- Run negative authorization tests for create, list, and delete proving each fails closed as `404`.
- Exercise a create + list-by-range round-trip and confirm the returned weight is canonical kg.

## Planning Notes

- The effective date is what the chart plots against; `created_at` is the audit timestamp. Range queries resolve the effective date in the user's profile timezone, mirroring how log-events resolves `day`.
- The weight time series is intentionally independent from `user_profiles.weight_kg`; FTY-074 reads the series, and any calibration consumer (target calculator) is a later, separate story.
- Conversion uses a single canonical factor (1 lb = 0.45359237 kg); keep it deterministic and in one place so the calculator/profile path and this path agree.

## Readiness Sanity Pass

- Product decision gaps: none — table shape, canonical-kg storage with input-units conversion, endpoint surface (create/list-by-range/delete), and bounds are resolved. The only open caveat is whether the trivial delete lands in this slice or is deferred; both paths are specified and the deletion requirement is otherwise covered by `ON DELETE CASCADE`.
- Cross-lane impact: defines the weight-entry contract (table, DTO, request/response shapes, units rule) consumed by FTY-074; touches contracts and security-privacy lanes; depends only on the existing identity/profile contracts (FTY-020/021).
- Security/privacy risk: medium; sensitive body weight, user-owned, object-level authz with fail-closed negative tests, never logged, `ON DELETE CASCADE`, retention documented per the data-retention PR requirement.
- Verification path: `make verify` + migration apply/rollback + conversion unit tests + negative authz tests + create/list round-trip.
- Assumptions safe for autonomy: yes; scope is a self-contained additive table and endpoints with no external providers or LLM, and explicitly excludes calibration and UI.
