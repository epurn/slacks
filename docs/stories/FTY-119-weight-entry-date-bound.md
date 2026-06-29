---
id: FTY-119
state: merged
primary_lane: backend-core
touched_lanes:
  - contracts
review_focus:
  - date-bound-validation
  - timezone-aware-today
  - charted-field-integrity
risk: medium
tags:
  - weight-entries
  - validation
  - timezone
  - api
approved_dependencies: []
requires_context:
  - docs/contracts/weight-entries.md
  - docs/standards/testing-standards.md
autonomous: true
---

# FTY-119: Bound the Weight-Entry Effective Date (backend)

## State

ready_with_notes

## Lane

backend-core

## Dependencies

- None to schedule. This **hardens one merged write path**: FTY-070 (the
  weight-entry create/list/delete API, `docs/contracts/weight-entries.md`),
  consumed by the merged FTY-074 weight-trend chart. Both are landed; this story
  tightens only the accepted range of an existing field — no schema, no migration,
  no request/response shape change.

## Outcome

A weight entry whose `effective_date` is an out-of-range typo — a far-future date
(`9999-01-01`) or an absurdly old one — is **rejected at create with `422`**
instead of being stored. Today the service validates only the canonical-kg
magnitude (`app/services/weight_entries.py` ~92–95); `effective_date` is accepted
as any syntactically valid date (`app/schemas/weight_entries.py` line 37), so a
single fat-fingered year lands a real row years off the axis and **silently skews
the FTY-074 weight-trend chart's date scale** — one bad point stretches the axis
and flattens the real trend. Bounding the date at the write boundary keeps the
charted series honest.

## Scope

- **Reject a future `effective_date` at create.** The bound is **timezone-aware**:
  "future" means after **today in the user's profile timezone**, not UTC. The
  pure Pydantic schema cannot see the user's timezone, so the guard lives in the
  **service** (`create_entry`, `app/services/weight_entries.py` ~75–100) alongside
  the existing kg-range check — mirror the established `_user_timezone` resolver
  used by `app/services/targets.py` (~320–332, "today in the owner's profile
  timezone, falling back to UTC") and `app/services/daily_summary.py` (~95–105).
  Add a `_user_timezone` helper to the weight-entry service (or reuse the shared
  one if a single resolver is factored out) and compute `datetime.now(tz).date()`.
- **Apply a small future slack.** Accept `effective_date <= today_in_user_tz + 1
  day` (recommended default; see Planning Notes) so a client whose clock or tz is
  a few hours ahead of the server's resolved "today" is not spuriously rejected.
- **Apply a generous lower floor.** Reject `effective_date` before a sane fixed
  floor (recommended `1900-01-01`) so an absurd past typo is also caught while
  leaving any realistic backfill untouched.
- **Raise a typed error rendered as `422`.** Add an `InvalidWeightDate` exception
  to the service (sibling to `InvalidWeightValue`) and map it in
  `app/routers/weight_entries.py` to a `422` (mirror the existing `_INVALID_WEIGHT`
  `HTTPException`, ~38–41 and ~68–69) with a clear, non-sensitive `detail`.
- **Document the bound, minimally, in `docs/contracts/weight-entries.md`** — one
  line in the Validation section and the Errors table noting `effective_date` must
  be on or before today-in-user-tz (+1 day slack) and on or after the lower floor,
  rejected `422` otherwise. This tightens an existing field's accepted range; the
  request/response **shape is unchanged**.

## Non-Goals

- **No migration and no new table.** `weight_entries` is already correct; this only
  stops the boundary from accepting an out-of-range date.
- **No change to the kg validation.** The `(0, 1000]` canonical-kg check and the
  units-conversion path are untouched.
- **No backfill or cleanup** of existing bad rows. This is a forward-looking input
  guard only; remediating already-stored skewed entries is out of scope.
- **Touch no read path.** The list-by-range endpoint, its `from`/`to` params, the
  ordering, the DTO, and the FTY-074 chart are all unchanged.
- **No request/response shape change** and no new field — only the accepted *range*
  of `effective_date` narrows.

## Contracts

- **`docs/contracts/weight-entries.md` (minor doc update, version bump):** the
  Validation section and Errors table note the `effective_date` upper bound
  (today-in-user-tz, +1 day slack) and lower floor, both `422` on violation. No
  request/response shape changes; this records a tightened accepted range, not a
  new contract.
- **Consumed by FTY-074** (weight-trend chart): the charted series can no longer
  contain an out-of-range outlier date, so the axis scale stays honest.

## Security / Privacy

- **Input hardening only; no new surface.** This narrows the accepted range of an
  existing low-trust scalar field at the same write boundary that already validates
  `weight`. It is **not** a new untrusted-input trust boundary (no image, fetched
  page, OCR, or upload).
- **Object-level authorization is unchanged.** The guard runs after the existing
  fail-closed `_authorize` (cross-user create stays `404`, no existence oracle).
- **No new logging of sensitive data.** Body weight is still never logged; the
  `422` detail names only the date bound, never the weight value.
- **Rated medium:** a correctness fix on the user's weight write path with a
  timezone-correctness requirement (the bound must match the user's local "today",
  reusing the proven resolver), but no migration, no contract-shape change, and no
  new untrusted-input surface.

## Acceptance Criteria

- **Future date rejected:** a create with `effective_date` after today-in-user-tz
  by more than the slack (e.g. `9999-01-01`, or tomorrow+2) returns `422` and
  writes no row.
- **Absurd past rejected:** a create with `effective_date` before the lower floor
  (e.g. `1800-01-01`) returns `422` and writes no row.
- **Today / recent still succeeds:** a create with today-in-user-tz, and a normal
  recent past date, still returns `201` with the entry DTO — the existing happy
  path is unchanged.
- **Timezone boundary accepted:** an entry whose `effective_date` is "today" in a
  user whose profile timezone is ahead of UTC (so it is already "tomorrow" in UTC)
  is **accepted** — the bound resolves "today" in the user's tz, not UTC.
- **No kg regression:** the `(0, 1000]` post-conversion kg check and the
  metric/imperial conversion still behave exactly as before; the existing
  weight-validation tests stay green.
- `make verify` passes.

## Verification

- Run the backend verify hook: `cd backend && ./verify.sh` (ruff check + ruff
  format --check + mypy + pytest), i.e. root `make verify`.
- **Future-date test:** `POST .../weight-entries` with a far-future
  `effective_date` → `422`, no row created.
- **Lower-floor test:** a pre-floor `effective_date` → `422`, no row created.
- **Happy-path tests:** today-in-user-tz and a recent past date → `201`; keep the
  existing FTY-070 create tests green.
- **Timezone-boundary test:** set the user's profile timezone ahead of UTC so the
  local "today" is UTC "tomorrow"; assert that local-today create → `201` (not
  rejected by a UTC-based bound).

## Planning Notes

- **Why the service, not a schema `field_validator`:** the bound is timezone-aware
  and "today" depends on the user's profile, which the pure schema cannot read. The
  guard belongs in `create_entry`, reusing the same `_user_timezone` /
  `datetime.now(tz).date()` pattern already proven in `targets.py` and
  `daily_summary.py`. A schema-only validator would have to bound against UTC,
  which would wrongly reject legitimate local-today entries near the date line.
- **Upper-bound policy (the open call):** recommended **today-in-user-tz + 1 day
  slack**. Rejecting strictly at today-in-user-tz is the tightest, but a client a
  few hours ahead of the server's resolved "today" could be spuriously rejected; a
  +1 day slack absorbs clock/tz skew while still catching the multi-year typos this
  story targets. Reversible: the slack is a single constant. (A zero-slack variant
  is acceptable if the implementer prefers strictness, but +1 is recommended.)
- **Lower-bound policy:** recommended a **generous fixed floor (`1900-01-01`)** over
  an account-creation-date floor — it needs no extra lookup, never blocks a
  legitimate historical backfill, and still catches absurd past typos. An
  account-creation floor is stricter but couples the guard to registration data and
  risks rejecting intentional backfill; the fixed floor is the lower-stakes default.
- **Error shape:** add `InvalidWeightDate` and render `422` via a router
  `HTTPException` mirroring `_INVALID_WEIGHT`; the `detail` names only the bound,
  never the weight.

## Readiness Sanity Pass

- **Product decision gaps:** one small, reversible policy call — the exact cap
  policy (today-in-user-tz vs a +1 day slack) and whether/where to set a lower
  floor. Both defaults are pinned above (+1 day slack; `1900-01-01` floor) with the
  tradeoff noted, so the story is `ready_with_notes` rather than blocked. No
  health/nutrition/behavioural question is involved (this is input integrity, not
  guidance), so no evidence research is warranted.
- **Cross-lane impact:** primary backend-core; contracts rides along
  (non-serializing) for a one-line doc note. **Single boundary, zero big rocks:**
  no schema migration / new table, no contract-shape change, no new
  untrusted-input trust boundary. One serializing lane, so it stays one story.
- **Size:** `review_focus` = 3 (under the 5 ceiling); `requires_context` = 2
  (under 8). Comfortably one quick-win story.
- **Security/privacy risk:** medium — a write-path correctness fix with a
  timezone-correctness requirement; object-level authz unchanged; weight values
  still never logged; no new input surface.
- **Verification path:** `make verify` + future-date `422` + lower-floor `422` +
  today/recent `201` + timezone-boundary `201`, with the existing kg-validation
  tests staying green.
- **Assumptions safe for autonomy:** yes — a bounded guard in one service method
  plus one router error mapping and a one-line contract-doc note, reusing the
  proven `_user_timezone` pattern, with the policy defaults pinned above. No
  migration, no contract shape change, no UI, no external provider.
